from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx

from app.errors import AppError
from app.models import MediaResult, PlaylistResult
from app.services.proxy.restream import RestreamManager
from app.services.proxy.tokens import TokenRegistry
from app.services.resolver.service import Resolver, needs_header_proxy
from tests.fakes import LIVE_MEDIA, MASTER, VOD_MEDIA, FakeProvider, Resource, ytdlp_info
from tests.test_m3u import IPTV

BASE = "http://cast.test:8000"


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as c:
        yield c


def make(http: httpx.AsyncClient, tmp_path: Path, media_root: Path | None = None, force_proxy: bool = False,
         browser: FakeProvider | None = None) -> Resolver:
    return Resolver(
        http,
        TokenRegistry(),
        RestreamManager(tmp_path / "rs"),
        media_root=media_root,
        browser=browser,
        enable_playwright=browser is not None,
        webpage_timeout=1.0,
        ytdlp_extractor=ytdlp_info,
        base_url=lambda: BASE,
        force_proxy=lambda: force_proxy,
    )


@respx.mock
async def test_detect_kinds(http, tmp_path, media_root):
    r = make(http, tmp_path, media_root)
    respx.get("https://site.example.com/watch").respond(200, html="<html><body>hi</body></html>")
    respx.get("https://site.example.com/getstream").respond(200, text=LIVE_MEDIA, headers={"content-type": "text/plain"})
    respx.get("https://site.example.com/list").respond(200, text=IPTV)
    assert await r.detect_kind("Movies/film.mp4") == "local"
    assert await r.detect_kind(str(media_root / "Movies" / "film.mp4")) == "local"
    assert await r.detect_kind("https://cdn.example.com/live.m3u8") == "direct"
    assert await r.detect_kind("https://cdn.example.com/list.m3u") == "m3u"
    assert await r.detect_kind("https://www.youtube.com/watch?v=abc") == "ytdlp"
    assert await r.detect_kind("https://youtu.be/abc") == "ytdlp"
    assert await r.detect_kind("https://cdn.example.com/movie.mp4") == "direct"
    assert await r.detect_kind("rtmp://live.example.com/app/key") == "direct"
    assert await r.detect_kind("https://site.example.com/watch") == "webpage"
    assert await r.detect_kind("https://site.example.com/getstream") == "direct"
    assert await r.detect_kind("https://site.example.com/list") == "m3u"
    with pytest.raises(AppError) as e:
        await r.detect_kind("not a url")
    assert e.value.code == "unsupported_source"


ACAO = {"access-control-allow-origin": "*"}


@respx.mock
async def test_direct_hls_live_with_cors_not_proxied(http, tmp_path):
    master = respx.get("https://cdn.example.com/live/master.m3u8").respond(200, text=MASTER, headers=ACAO)
    respx.get("https://cdn.example.com/live/low/index.m3u8").respond(200, text=LIVE_MEDIA, headers=ACAO)
    seg = respx.get("https://cdn.example.com/live/low/seg100.ts").respond(200, content=b"TS", headers=ACAO)
    res = await make(http, tmp_path).resolve("https://cdn.example.com/live/master.m3u8")
    # probed like the receiver: with an Origin (many CDNs only send ACAO then), segments included
    assert master.calls.last.request.headers["origin"] == "https://www.gstatic.com"
    assert seg.called
    assert isinstance(res, MediaResult)
    m = res.media
    assert m.mime_type == "application/x-mpegURL"
    assert m.stream_type == "LIVE"
    assert m.proxied is False
    assert m.cast_url == "https://cdn.example.com/live/master.m3u8"
    assert m.preview_url.startswith("/proxy/")  # browser preview needs same-origin
    assert m.source_kind == "direct"
    assert m.title == "master"


@respx.mock
async def test_hls_with_cors_on_playlist_but_not_segments_is_proxied(http, tmp_path):
    respx.get("https://cdn.example.com/live/master.m3u8").respond(200, text=MASTER, headers=ACAO)
    respx.get("https://cdn.example.com/live/low/index.m3u8").respond(200, text=LIVE_MEDIA, headers=ACAO)
    respx.get("https://cdn.example.com/live/low/seg100.ts").respond(200, content=b"TS")
    m = (await make(http, tmp_path).resolve("https://cdn.example.com/live/master.m3u8")).media
    assert m.proxied and m.cast_url.startswith(BASE + "/proxy/")


@respx.mock
async def test_hls_cors_check_honours_specific_origin(http, tmp_path):
    gst = {"access-control-allow-origin": "https://www.gstatic.com"}
    respx.get("https://cdn.example.com/v/index.m3u8").respond(200, text=LIVE_MEDIA, headers=gst)
    respx.get("https://cdn.example.com/v/seg100.ts").respond(200, content=b"TS", headers=gst)
    assert not (await make(http, tmp_path).resolve("https://cdn.example.com/v/index.m3u8")).media.proxied
    respx.get("https://cdn.example.com/w/index.m3u8").respond(
        200, text=LIVE_MEDIA, headers={"access-control-allow-origin": "https://other.example"})
    assert (await make(http, tmp_path).resolve("https://cdn.example.com/w/index.m3u8")).media.proxied


@respx.mock
async def test_direct_hls_vod_without_cors_is_proxied(http, tmp_path):
    respx.get("https://cdn.example.com/vod/index.m3u8").respond(200, text=VOD_MEDIA)
    m = (await make(http, tmp_path).resolve("https://cdn.example.com/vod/index.m3u8")).media
    assert m.stream_type == "BUFFERED"
    assert m.proxied is True
    assert m.cast_url.startswith(BASE + "/proxy/")
    assert m.cast_url.endswith("/index.m3u8")


@respx.mock
async def test_force_proxy_mp4(http, tmp_path):
    m = (await make(http, tmp_path, force_proxy=True).resolve("https://cdn.example.com/a/movie.mp4")).media
    assert m.proxied and m.cast_url.startswith(BASE + "/proxy/")
    assert m.mime_type == "video/mp4" and m.stream_type == "BUFFERED"
    m2 = (await make(http, tmp_path).resolve("https://cdn.example.com/a/movie.mp4")).media
    assert not m2.proxied and m2.cast_url == m2.preview_url == "https://cdn.example.com/a/movie.mp4"


@respx.mock
async def test_raw_ts_and_rtmp_are_restreamed(http, tmp_path):
    r = make(http, tmp_path)
    m = (await r.resolve("http://iptv.example.com/live/123.ts")).media
    assert m.cast_url.startswith(BASE + "/restream/") and m.cast_url.endswith("/index.m3u8")
    assert m.mime_type == "application/x-mpegURL" and m.stream_type == "LIVE" and m.proxied
    m = (await r.resolve("rtmp://live.example.com/app/key")).media
    assert "/restream/" in m.cast_url
    assert len(r.restream.jobs) == 2
    assert all(j.live for j in r.restream.jobs.values())


@respx.mock
async def test_raw_ts_file_over_http_is_restreamed_as_vod(http, tmp_path):
    respx.get("http://files.example.com/movie.ts").respond(
        200, content=b"\x47" * 188, headers={"content-type": "video/mp2t", "content-length": "188"})
    r = make(http, tmp_path)
    m = (await r.resolve("http://files.example.com/movie.ts")).media
    assert "/restream/" in m.cast_url and m.stream_type == "BUFFERED"
    (job,) = r.restream.jobs.values()
    assert not job.live  # event playlist, full file, -re


@respx.mock
async def test_input_with_kodi_headers(http, tmp_path):
    route = respx.get("https://cdn.example.com/ch/index.m3u8").respond(200, text=LIVE_MEDIA)
    value = "https://cdn.example.com/ch/index.m3u8|Referer=https%3A%2F%2Fsite.example%2F&User-Agent=VLC%2F3"
    r = make(http, tmp_path)
    m = (await r.resolve(value)).media
    assert m.url == "https://cdn.example.com/ch/index.m3u8" and m.original_input == value
    assert m.title == "index" and m.proxied
    assert route.calls.last.request.headers["referer"] == "https://site.example/"
    assert route.calls.last.request.headers["user-agent"] == "VLC/3"
    tok = m.cast_url.split("/proxy/")[1].split("/")[0]
    assert r.tokens.get(tok).headers == {"Referer": "https://site.example/", "User-Agent": "VLC/3"}


@respx.mock
async def test_m3u_returns_playlist_preview(http, tmp_path):
    respx.get("https://lists.example.com/it.m3u").respond(200, text=IPTV)
    res = await make(http, tmp_path).resolve("https://lists.example.com/it.m3u")
    assert isinstance(res, PlaylistResult)
    assert res.name == "it"
    assert len(res.channels) == 5


@respx.mock
async def test_m3u_extension_with_hls_content_is_direct(http, tmp_path):
    respx.get("https://lists.example.com/stream.m3u").respond(200, text=LIVE_MEDIA)
    res = await make(http, tmp_path).resolve("https://lists.example.com/stream.m3u")
    assert isinstance(res, MediaResult)
    assert res.media.mime_type == "application/x-mpegURL"


async def test_resolve_media_rejects_playlists(http, tmp_path):
    r = make(http, tmp_path)
    with respx.mock:
        respx.get("https://lists.example.com/it.m3u").respond(200, text=IPTV)
        with pytest.raises(AppError) as e:
            await r.resolve_media("https://lists.example.com/it.m3u")
    assert e.value.code == "unsupported_source"


async def test_ytdlp_vod_and_subtitles(http, tmp_path):
    r = make(http, tmp_path)
    m = (await r.resolve("https://www.youtube.com/watch?v=abc")).media
    assert m.source_kind == "ytdlp"
    assert m.title == "Some Video"
    assert m.mime_type == "video/mp4"
    assert m.stream_type == "BUFFERED"
    assert not m.proxied  # only a User-Agent: no need to proxy
    assert len(m.subtitles) == 1 and m.subtitles[0].lang == "it"
    assert m.subtitles[0].url.startswith(BASE + "/proxy/")  # receivers need CORS on tracks


@respx.mock
async def test_ytdlp_live_hls(http, tmp_path):
    respx.get("https://cdn.example.com/live/master.m3u8").respond(200, text=MASTER,
                                                                  headers={"access-control-allow-origin": "*"})
    m = (await make(http, tmp_path).resolve("https://www.twitch.tv/live_channel")).media
    assert m.stream_type == "LIVE"
    assert m.mime_type == "application/x-mpegURL"


async def test_ytdlp_failure_is_resolve_failed(http, tmp_path):
    with pytest.raises(AppError) as e:
        await make(http, tmp_path).resolve("https://www.youtube.com/watch?v=fail", "ytdlp")
    assert e.value.code == "resolve_failed"


async def test_local_files(http, tmp_path, media_root):
    r = make(http, tmp_path, media_root)
    m = (await r.resolve("Movies/film.mp4")).media
    assert m.source_kind == "local"
    assert m.cast_url == BASE + "/local/Movies/film.mp4"
    assert m.preview_url == "/local/Movies/film.mp4"
    assert m.mime_type == "video/mp4"
    avi = (await r.resolve("Movies/old.avi")).media
    assert "/restream/" in avi.cast_url
    assert not r.restream.jobs[avi.cast_url.split("/restream/")[1].split("/")[0]].live
    with pytest.raises(AppError):
        await r.resolve("../../etc/passwd", "local")


@respx.mock
async def test_webpage_uses_browser_and_proxies_with_headers(http, tmp_path):
    page = "https://sport.example.com/match"
    provider = FakeProvider(
        site={page: [
            Resource("https://ads.doubleclick.net/vast/preroll.mp4", "video/mp4"),
            Resource("https://cdn.stream.example/hls/master.m3u8?token=1", "application/vnd.apple.mpegurl", MASTER,
                     frame_url="https://player.embed.example/iframe.html"),
        ]},
        titles={page: "Big Match"},
    )
    respx.get("https://cdn.stream.example/hls/master.m3u8?token=1").respond(200, text=MASTER)
    respx.get("https://cdn.stream.example/hls/low/index.m3u8").respond(200, text=LIVE_MEDIA)
    r = make(http, tmp_path, browser=provider)
    m = (await r.resolve(page, "webpage")).media
    assert m.url == "https://cdn.stream.example/hls/master.m3u8?token=1"
    assert m.source_kind == "webpage"
    assert m.proxied is True  # Referer captured from the iframe → must replay it
    target = r.tokens.get(m.cast_url.split("/proxy/")[1].split("/")[0])
    assert target is not None
    assert target.headers["Referer"] == "https://player.embed.example/iframe.html"
    assert target.headers["Cookie"] == "sess=abc"
    assert provider.contexts[0].closed


async def test_webpage_nothing_found_hints_interactive_browser(http, tmp_path):
    provider = FakeProvider(site={})
    r = make(http, tmp_path, browser=provider)
    with pytest.raises(AppError) as e:
        await r.resolve("https://www.example.org/empty-fail", "webpage")
    assert e.value.code == "resolve_failed"
    assert "interattivo" in e.value.detail


def test_needs_header_proxy():
    assert needs_header_proxy({"Referer": "https://x"})
    assert needs_header_proxy({"Cookie": "a=b"})
    assert not needs_header_proxy({"User-Agent": "x"})


FMP4_MEDIA = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:4
#EXT-X-MAP:URI="init.mp4"
#EXTINF:4.0,
seg-1.m4s
"""


@respx.mock
async def test_iptv_list_named_m3u8_is_a_playlist(http, tmp_path):
    respx.get("https://iptv.example.com/tv_channels.m3u8").respond(
        200, text=IPTV, headers={"content-type": "application/x-mpegURL"})
    respx.get("https://cdn.example.com/live.m3u8").respond(200, text=LIVE_MEDIA)
    r = make(http, tmp_path)
    assert await r.detect_kind("https://iptv.example.com/tv_channels.m3u8") == "m3u"
    assert await r.detect_kind("https://cdn.example.com/live.m3u8") == "direct"
    # broken .m3u8 (server error, slow body): still cast it, the receiver reports
    respx.get("https://broken.example.com/x.m3u8").respond(500)
    assert await r.detect_kind("https://broken.example.com/x.m3u8") == "direct"
    respx.get("https://slow.example.com/x.m3u8").mock(side_effect=httpx.ReadTimeout("slow"))
    assert await r.detect_kind("https://slow.example.com/x.m3u8") == "direct"
    # unreachable host: nothing can play it → 502 resolve_failed (see below)
    respx.get("https://down.example.com/x.m3u8").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AppError) as e:
        await r.detect_kind("https://down.example.com/x.m3u8")
    assert e.value.code == "resolve_failed"
    res = await r.resolve("https://iptv.example.com/tv_channels.m3u8")
    assert isinstance(res, PlaylistResult) and res.channels


@respx.mock
async def test_fmp4_hls_carries_segment_format(http, tmp_path):
    respx.get("https://cdn.example.com/cmaf/master.m3u8").respond(200, text=MASTER, headers=ACAO)
    respx.get("https://cdn.example.com/cmaf/low/index.m3u8").respond(200, text=FMP4_MEDIA, headers=ACAO)
    respx.get("https://cdn.example.com/cmaf/low/seg-1.m4s").respond(200, content=b"x", headers=ACAO)
    respx.get("https://cdn.example.com/ts/live.m3u8").respond(200, text=LIVE_MEDIA, headers=ACAO)
    respx.get("https://cdn.example.com/ts/seg100.ts").respond(200, content=b"x", headers=ACAO)
    r = make(http, tmp_path)
    media = (await r.resolve("https://cdn.example.com/cmaf/master.m3u8")).media
    assert media.hls_segment_format == "fmp4" and not media.proxied
    assert (await r.resolve("https://cdn.example.com/ts/live.m3u8")).media.hls_segment_format is None


MPD_LIVE = '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic"><Period/></MPD>'
MPD_VOD = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"><Period/></MPD>'


@respx.mock
async def test_dash_without_cors_is_proxied_and_live_detected(http, tmp_path):
    respx.get("https://cdn.example.com/live/manifest.mpd").respond(200, text=MPD_LIVE)
    respx.get("https://cdn.example.com/vod/manifest.mpd").respond(200, text=MPD_VOD, headers=ACAO)
    r = make(http, tmp_path)
    live = (await r.resolve("https://cdn.example.com/live/manifest.mpd")).media
    assert live.proxied and live.cast_url.startswith(f"{BASE}/proxy/") and live.stream_type == "LIVE"
    assert live.mime_type == "application/dash+xml"
    vod = (await r.resolve("https://cdn.example.com/vod/manifest.mpd")).media
    assert not vod.proxied and vod.cast_url == "https://cdn.example.com/vod/manifest.mpd"
    assert vod.stream_type == "BUFFERED" and vod.preview_url.startswith("/proxy/")


@respx.mock
async def test_malformed_and_unreachable_urls_are_clean_errors(http, tmp_path):
    r = make(http, tmp_path)
    for bad in ("http://[bad/x", "https:///nohost"):
        with pytest.raises(AppError) as e:
            await r.resolve(bad)
        assert e.value.status_code == 400 and e.value.code == "unsupported_source"
    with pytest.raises(AppError) as e:
        await r.resolve("http://[bad/x", kind="direct")  # explicit kind skips detection
    assert e.value.code == "unsupported_source"
    respx.get("https://127.0.0.1:1/x").mock(side_effect=httpx.ConnectError("Connection refused"))
    with pytest.raises(AppError) as e:
        await r.resolve("https://127.0.0.1:1/x")
    assert e.value.status_code == 502 and e.value.code == "resolve_failed"
    assert "Could not connect to 127.0.0.1" in e.value.detail and "browser" not in e.value.detail


@respx.mock
@pytest.mark.parametrize("url", ["http://127.0.0.1:1/x.m3u8", "http://127.0.0.1:1/x.mp4", "http://127.0.0.1:1/x.mpd",
                                 "http://127.0.0.1:1/live/1.ts"])
@pytest.mark.parametrize("error", [httpx.ConnectError("Connection refused"), httpx.ConnectTimeout("timed out")])
async def test_unreachable_media_urls_are_resolve_failed(http, tmp_path, url, error):
    respx.get(url).mock(side_effect=error)
    r = make(http, tmp_path)
    for kind in (None, "direct"):  # detected, or kind given explicitly (e.g. M3U channel)
        with pytest.raises(AppError) as e:
            await r.resolve(url, kind)
        assert e.value.status_code == 502 and e.value.code == "resolve_failed"
        assert "Could not connect to 127.0.0.1" in e.value.detail
    assert not r.restream.jobs and not len(r.tokens)


@respx.mock
async def test_reachable_media_with_http_error_is_still_cast(http, tmp_path):
    # 403 on a plain GET (e.g. needs the receiver's headers): not a connect error, keep casting
    respx.get("https://cdn.example.com/a/movie.mp4").respond(403)
    m = (await make(http, tmp_path).resolve("https://cdn.example.com/a/movie.mp4")).media
    assert m.cast_url == "https://cdn.example.com/a/movie.mp4" and m.mime_type == "video/mp4"


def _ts_bytes(packets: int = 8) -> bytes:
    return b"".join(b"\x47" + bytes([i % 256]) * 187 for i in range(packets))


def _endless(body: bytes, content_type: str = "application/octet-stream"):
    """A live feed: chunked body, no Content-Length."""
    async def chunks():
        for i in range(0, len(body), 100):
            yield body[i:i + 100]

    return lambda request: httpx.Response(200, headers={"content-type": content_type}, content=chunks())


@respx.mock
async def test_extensionless_octet_stream_mpegts_is_restreamed_live(http, tmp_path):
    # Xtream-style channel: no extension, application/octet-stream, no Content-Length
    url = "http://panel.example.com:8080/user/pass/12345"
    route = respx.get(url).mock(side_effect=_endless(_ts_bytes()))
    r = make(http, tmp_path)
    assert await r.detect_kind(url) == "direct"
    m = (await r.resolve(url)).media
    assert m.cast_url.startswith(BASE + "/restream/") and m.mime_type == "application/x-mpegURL"
    assert m.stream_type == "LIVE" and m.proxied
    (job,) = r.restream.jobs.values()
    assert job.live
    assert route.calls.last.request.headers["user-agent"].startswith("Mozilla/")


@respx.mock
async def test_extensionless_octet_stream_flv_and_ts_file(http, tmp_path):
    respx.get("http://panel.example.com/flv/1").mock(side_effect=_endless(b"FLV\x01\x05" + b"\0" * 600))
    respx.get("http://panel.example.com/file/2").respond(
        200, content=_ts_bytes(), headers={"content-type": "binary/octet-stream", "content-length": "1504"})
    r = make(http, tmp_path)
    flv = (await r.resolve("http://panel.example.com/flv/1")).media
    assert "/restream/" in flv.cast_url and flv.stream_type == "LIVE"
    vod = (await r.resolve("http://panel.example.com/file/2")).media
    assert "/restream/" in vod.cast_url and vod.stream_type == "BUFFERED"


@respx.mock
async def test_mkv_is_announced_as_mp4(http, tmp_path, media_root):
    (media_root / "Movies" / "film.mkv").write_bytes(b"\x1a\x45\xdf\xa3")
    respx.get("https://cdn.example.com/a/movie.mkv").respond(200, headers={"content-type": "video/x-matroska"})
    r = make(http, tmp_path, media_root)
    local = (await r.resolve("Movies/film.mkv")).media
    assert local.mime_type == "video/mp4" and local.cast_url == BASE + "/local/Movies/film.mkv"
    direct = (await r.resolve("https://cdn.example.com/a/movie.mkv")).media
    assert direct.mime_type == "video/mp4" and not direct.proxied
