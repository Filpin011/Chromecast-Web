"""Segments disguised as .html / images: the Cast receiver HEADs them and fails the LOAD
unless the proxy gives them a media name and a media Content-Type (hls.js doesn't care)."""

from app.services.proxy.hls import encode_url, media_filename, rewrite_playlist
from app.services.proxy.stream import sniff_media, upstream_url
from app.services.proxy.tokens import ProxyTarget

TS = (b"\x47" + b"\x00" * 187) * 8  # 8 MPEG-TS packets
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120  # fake image in front of the TS data

DISGUISED_MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.example.com/storage/enc.key"
#EXTINF:4.0,
https://cdn.example.com/hls/v/720p/0000-0179.html?token=abc
#EXTINF:4.0,
0001-0179.jpg
#EXT-X-ENDLIST
"""


def register(client, url, headers=None):
    return client.app.state.services.tokens.register(url, headers)


def test_rewrite_gives_disguised_segments_a_media_extension():
    out = rewrite_playlist(DISGUISED_MEDIA, "https://cdn.example.com/hls/v/720p/index", "tok")
    segs = [ln for ln in out.splitlines() if ln and not ln.startswith("#")]
    assert segs[0].endswith("/0000-0179.ts") and segs[1].endswith("/0001-0179.ts")
    assert 'enc.key"' in out  # keys keep their name
    fmp4 = DISGUISED_MEDIA.replace("#EXT-X-TARGETDURATION:4", '#EXT-X-TARGETDURATION:4\n#EXT-X-MAP:URI="init.png"')
    out = rewrite_playlist(fmp4, "https://cdn.example.com/hls/v/720p/index", "tok")
    assert "/init.mp4" in out and out.count(".m4s") == 2


def test_rewrite_keeps_real_media_names_and_master_variants():
    media = "#EXTM3U\n#EXTINF:4,\nseg1.ts\n#EXTINF:4,\nseg2.aac\n"
    out = rewrite_playlist(media, "https://c/x/index.m3u8", "tok")
    assert out.splitlines()[2].endswith("/seg1.ts") and out.splitlines()[4].endswith("/seg2.aac")
    master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nplaylist/799812?type=video\n'
    out = rewrite_playlist(master, "https://c/x/master", "tok")
    assert out.splitlines()[2].endswith("/799812")  # variant playlists are not renamed


def test_upstream_url_maps_renamed_segment_back_to_original():
    original = "https://cdn.example.com/hls/v/720p/0000-0179.html?token=abc"
    t = ProxyTarget(token="t", url="https://cdn.example.com/master")
    for ext in (".ts", ".m4s", ".mp4"):
        assert upstream_url(t, f"u/{encode_url(original)}/{media_filename(original, ext)}") == original


def test_sniff_media_detects_types_and_fake_image_headers():
    assert sniff_media(TS) == ("video/mp2t", 0)
    assert sniff_media(PNG_HEADER + TS) == ("video/mp2t", len(PNG_HEADER))
    assert sniff_media(b"\x00\x00\x00\x18ftypiso6" + b"\x00" * 16) == ("video/mp4", 0)
    assert sniff_media(b"\xff\xd8\xff\xe0" + b"\x00" * 60 + b"\x00\x00\x00\x18styp") == ("video/mp4", 64)
    assert sniff_media(b"\xff\xf1\x50\x80" + b"\x00" * 10)[0] == "audio/aac"
    assert sniff_media(b"ID3\x04\x00")[0] == "audio/aac"
    assert sniff_media(b"WEBVTT\n\n")[0] == "text/vtt"
    assert sniff_media(b"<html>not media</html>") == (None, 0)


def test_proxy_serves_html_disguised_segment_as_video(client, mock_http):
    seg_url = "https://cdn.example.com/hls/v/720p/0000-0179.html?token=abc"
    mock_http.get("https://cdn.example.com/hls/v/720p/index").respond(200, text=DISGUISED_MEDIA)
    mock_http.get(seg_url).respond(200, content=TS, headers={"content-type": "text/html"})
    mock_http.head(seg_url).respond(200, headers={"content-type": "text/html", "content-length": str(len(TS))})
    t = register(client, "https://cdn.example.com/hls/v/720p/index")

    playlist = client.get(f"/proxy/{t.token}/index").text
    seg_path = next(ln for ln in playlist.splitlines() if ln and not ln.startswith("#"))
    assert seg_path.endswith(".ts")

    head = client.head(seg_path)
    assert head.status_code == 200 and head.headers["content-type"] == "video/mp2t"
    r = client.get(seg_path)
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp2t" and r.content == TS


def test_proxy_strips_fake_png_header_in_front_of_ts(client, mock_http):
    seg_url = "https://cdn.example.com/hls/v/720p/0000-0179.html?token=abc"
    mock_http.get(seg_url).respond(200, content=PNG_HEADER + TS, headers={"content-type": "image/png"})
    t = register(client, "https://cdn.example.com/hls/v/720p/index")
    r = client.get(f"/proxy/{t.token}/u/{encode_url(seg_url)}/{media_filename(seg_url, '.ts')}")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp2t"
    assert r.content == TS  # fake header gone, no stale Content-Length truncating it


def test_proxy_leaves_real_media_types_and_ranges_alone(client, mock_http):
    seg_url = "https://cdn.example.com/v/seg1.ts"
    mock_http.get(seg_url).respond(206, content=TS[:188], headers={"content-type": "video/mp2t", "content-range": f"bytes 0-187/{len(TS)}"})
    t = register(client, "https://cdn.example.com/v/index.m3u8")
    r = client.get(f"/proxy/{t.token}/u/{encode_url(seg_url)}/seg1.ts", headers={"Range": "bytes=0-187"})
    assert r.status_code == 206 and r.headers["content-type"] == "video/mp2t" and r.content == TS[:188]
    assert r.headers["content-range"] == f"bytes 0-187/{len(TS)}"
