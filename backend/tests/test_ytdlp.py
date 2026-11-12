"""yt-dlp format selection + parsing against info dicts shaped like real extractor output."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.resolver import ytdlp

MASTER = "https://manifest.googlevideo.com/api/manifest/hls_variant/expire/1/id/abc/file/index.m3u8"
HEADERS = {"User-Agent": "Mozilla/5.0 yt", "Accept": "*/*"}


def _fmt(fid: str, *, protocol: str, vcodec: str, acodec: str, ext: str = "mp4", height: int | None = None,
         tbr: float = 100.0, manifest: bool = False) -> dict[str, Any]:
    f: dict[str, Any] = {
        "format_id": fid,
        "url": f"https://rr1.googlevideo.com/videoplayback?itag={fid}" if protocol == "https"
        else f"https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/{fid}/index.m3u8",
        "protocol": protocol,
        "ext": ext,
        "vcodec": vcodec,
        "acodec": acodec,
        "tbr": tbr,
        "http_headers": HEADERS,
    }
    if height:
        f |= {"height": height, "width": height * 16 // 9}
    if manifest:
        f["manifest_url"] = MASTER
    return f


def youtube_2026_info() -> dict[str, Any]:
    """Current YouTube without a JS runtime: no muxed format (no itag 18), only split
    video-only m3u8/DASH and audio-only DASH; every m3u8 format points at the same master."""
    formats = [
        _fmt("140", protocol="https", vcodec="none", acodec="mp4a.40.2", ext="m4a", tbr=129),
        _fmt("251", protocol="https", vcodec="none", acodec="opus", ext="webm", tbr=130),
        _fmt("229", protocol="m3u8_native", vcodec="avc1.4D4015", acodec="none", height=240, tbr=311, manifest=True),
        _fmt("135", protocol="https", vcodec="avc1.4D401F", acodec="none", height=480, tbr=356),
        _fmt("232", protocol="m3u8_native", vcodec="avc1.4D401F", acodec="none", height=720, tbr=2500,
             manifest=True),
        _fmt("299", protocol="https", vcodec="avc1.64002A", acodec="none", height=1080, tbr=3248),
        _fmt("617", protocol="m3u8_native", vcodec="vp09.00.41.08", acodec="none", height=1080, tbr=5022,
             manifest=True),
    ]
    return {
        "id": "aqz-KE-bpKQ",
        "title": "Big Buck Bunny",
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "webpage_url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        "thumbnail": "https://i.ytimg.com/vi/aqz-KE-bpKQ/hq.jpg",
        "duration": 635,
        "is_live": False,
        "formats": formats,
    }


def select(info: dict[str, Any]) -> dict[str, Any]:
    """Run yt-dlp's real format selection with our FORMAT, offline."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "format": ytdlp.FORMAT}
    with YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        return ydl.sanitize_info(ydl.process_ie_result(info, download=False))  # type: ignore[return-value]


def test_youtube_split_formats_cast_the_hls_master():
    picked = select(youtube_2026_info())  # used to fail: "Requested format is not available"
    r = ytdlp.parse_info(picked)
    assert r.url == MASTER and r.protocol.startswith("m3u8") and r.title == "Big Buck Bunny"
    assert r.headers["User-Agent"] == HEADERS["User-Agent"] and not r.is_live


def test_muxed_hls_is_still_preferred():
    info = youtube_2026_info()
    info["formats"].append(_fmt("96", protocol="m3u8_native", vcodec="avc1.640028", acodec="mp4a.40.2",
                                height=1080, tbr=4000, manifest=True))
    info["formats"].append(_fmt("18", protocol="https", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360))
    r = ytdlp.parse_info(select(info))
    assert r.url.endswith("/itag/96/index.m3u8")  # the muxed variant itself


def test_muxed_mp4_when_there_is_no_hls():
    info = youtube_2026_info()
    info["formats"] = [f for f in info["formats"] if f["protocol"] == "https"]
    info["formats"].append(_fmt("18", protocol="https", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360))
    r = ytdlp.parse_info(select(info))
    assert r.url.endswith("itag=18")


def test_split_dash_only_falls_back_to_video_stream():
    info = youtube_2026_info()
    info["formats"] = [f for f in info["formats"] if f["protocol"] == "https"]
    r = ytdlp.parse_info(select(info))
    assert "itag=299" in r.url  # no HLS master anywhere: best video (documented: no audio)


def test_video_only_single_pick_uses_master():
    info = {"id": "x", "title": "t", "url": "https://h/itag/617.m3u8", "protocol": "m3u8_native", "ext": "mp4",
            "vcodec": "vp9", "acodec": "none", "manifest_url": MASTER}
    assert ytdlp.parse_info(info).url == MASTER


def test_audio_only_site():
    info = {"id": "s", "title": "Song", "extractor": "x", "extractor_key": "X", "webpage_url": "https://s/1",
            "formats": [_fmt("mp3", protocol="https", vcodec="none", acodec="mp3", ext="mp3")]}
    r = ytdlp.parse_info(select(info))
    assert r.url.endswith("itag=mp3")


@pytest.mark.parametrize("info", [{"id": "x"}, {"_type": "playlist", "entries": []}])
def test_no_url_is_an_error(info):
    with pytest.raises(ValueError):
        ytdlp.parse_info(info)
