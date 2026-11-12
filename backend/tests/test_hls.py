from app.services.proxy.hls import (
    best_resolution,
    decode_url,
    encode_url,
    filter_variants,
    first_variant_url,
    is_hls_playlist,
    is_live_media_playlist,
    is_master_playlist,
    proxy_path,
    quality_label,
    rewrite_playlist,
)
from tests.fakes import LIVE_MEDIA, MASTER, MIXED_MASTER, VOD_MEDIA

BASE = "https://cdn.example.com/live/stream/master.m3u8?token=abc"
T = "tok123"


def p(url: str) -> str:
    return proxy_path(T, url)


def test_encode_roundtrip():
    url = "https://a.example.com/x y/ü.m3u8?q=1&r=/2"
    assert decode_url(encode_url(url)) == url
    assert "=" not in encode_url(url)


def test_rewrite_master_golden():
    src = """#EXTM3U
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Italiano",LANGUAGE="it",URI="audio/it.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="EN",URI="https://subs.example.com/en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,AUDIO="aud",SUBTITLES="subs"
720p/index.m3u8?token=abc
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,AUDIO="aud"
/abs/360p.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=90000,URI="iframes.m3u8"
"""
    expected = f"""#EXTM3U
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Italiano",LANGUAGE="it",URI="{p('https://cdn.example.com/live/stream/audio/it.m3u8')}"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="EN",URI="{p('https://subs.example.com/en.m3u8')}"
#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,AUDIO="aud",SUBTITLES="subs"
{p('https://cdn.example.com/live/stream/720p/index.m3u8?token=abc')}
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,AUDIO="aud"
{p('https://cdn.example.com/abs/360p.m3u8')}
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=90000,URI="{p('https://cdn.example.com/live/stream/iframes.m3u8')}"
"""
    assert rewrite_playlist(src, BASE, T) == expected


def test_rewrite_media_with_key_map_and_data_uri():
    src = """#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-MAP:URI="init.mp4"
#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example.com/k?id=1",IV=0x1234
#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="skd://fairplay-key"
#EXTINF:4.0,
seg_001.m4s
#EXT-X-KEY:METHOD=AES-128,URI="data:text/plain;base64,AAAA"
#EXTINF:4.0,title
http://other.example.com/seg_002.m4s
"""
    out = rewrite_playlist(src, "https://cdn.example.com/v/media.m3u8", T).splitlines()
    assert out[2] == f'#EXT-X-MAP:URI="{p("https://cdn.example.com/v/init.mp4")}"'
    assert out[3] == f'#EXT-X-KEY:METHOD=AES-128,URI="{p("https://keys.example.com/k?id=1")}",IV=0x1234'
    assert out[4] == '#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="skd://fairplay-key"'
    assert out[6] == p("https://cdn.example.com/v/seg_001.m4s")
    assert out[7].endswith('URI="data:text/plain;base64,AAAA"')
    assert out[9] == p("http://other.example.com/seg_002.m4s")


def test_proxy_path_has_filename_hint():
    path = p("https://cdn.example.com/a/b/index.m3u8?x=1")
    assert path.startswith("/proxy/tok123/u/")
    assert path.endswith("/index.m3u8")


def test_playlist_detection_helpers():
    assert is_hls_playlist(MASTER) and is_master_playlist(MASTER)
    assert is_hls_playlist(LIVE_MEDIA) and not is_master_playlist(LIVE_MEDIA)
    assert not is_hls_playlist("#EXTM3U\n#EXTINF:-1,Chan\nhttp://x/1.ts\n")
    assert is_live_media_playlist(LIVE_MEDIA)
    assert not is_live_media_playlist(VOD_MEDIA)
    assert best_resolution(MASTER) == (1280, 720)
    assert first_variant_url(MASTER, "https://h/x/master.m3u8") == "https://h/x/low/index.m3u8"


def test_quality_labels():
    assert quality_label(720) == "720p HD"
    assert quality_label(1080) == "1080p FHD"
    assert quality_label(2160) == "2160p 4K"
    assert quality_label(480) == "480p SD"
    assert quality_label(None) is None


def test_segment_format():
    from app.services.proxy.hls import segment_format

    head = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n"
    assert segment_format(head + '#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4,\nseg1.m4s\n') == "fmp4"
    assert segment_format(head + '#EXT-X-MAP:URI="init-v1.cmfv?tok=1"\n#EXTINF:4,\nseg1\n') == "fmp4"
    assert segment_format(head + "#EXTINF:4,\nhttps://c/live/fileSequence1.mp4?x=1\n") == "fmp4"
    assert segment_format(head + "#EXTINF:4,\nchunk_1.aac\n") == "aac"
    assert segment_format(head + "#EXTINF:4,\nchunk_1.mp3\n") == "mp3"
    assert segment_format(head + "#EXTINF:4,\nseg1.ts\n") is None
    assert segment_format(head + '#EXT-X-MAP:URI="init.ts"\n#EXTINF:4,\nseg1.ts\n') is None
    assert segment_format("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nlow.m3u8\n") is None  # master


def test_audio_rendition_url_prefers_default_of_the_variant_group():
    from app.services.proxy.hls import audio_rendition_url

    master = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="lo",NAME="x",DEFAULT=YES,URI="lo/a.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="hi",NAME="en",DEFAULT=NO,URI="hi/en.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="hi",NAME="it",DEFAULT=YES,URI="hi/it.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="hi",NAME="s",DEFAULT=YES,URI="subs.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="hi"\nv.m3u8\n'
    )
    assert audio_rendition_url(master, "https://c/m/master.m3u8") == "https://c/m/hi/it.m3u8"
    # muxed audio (no URI) or no renditions at all
    assert audio_rendition_url('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="x"\n', "https://c/") is None
    assert audio_rendition_url("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nv.m3u8\n", "https://c/") is None


def test_sniff_segment():
    from app.services.proxy.hls import sniff_segment

    id3 = b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10
    assert sniff_segment((b"\x47" + b"\x00" * 187) * 2) == "ts"
    assert sniff_segment(b"\x00\x00\x00\x18styp" + b"\x00" * 16) == "fmp4"
    assert sniff_segment(b"\x00\x00\x00\x18moof" + b"\x00" * 16) == "fmp4"
    assert sniff_segment(id3 + b"\xff\xf1\x50\x80\x2e\x7f") == "aac"
    assert sniff_segment(b"\xff\xf9\x50\x80\x2e\x7f") == "aac"  # MPEG-2 ADTS, no ID3
    assert sniff_segment(id3 + b"\xff\xfb\x90\x64\x00\x00") == "mp3"
    assert sniff_segment(id3 + b"\x0b\x77\x00\x00\x00\x40") == "ac3"  # bsid 8
    assert sniff_segment(id3 + b"\x0b\x77\x00\x00\x00\x80") == "e_ac3"  # bsid 16
    assert sniff_segment(b"") is None
    assert sniff_segment(b"<html>not media</html>") is None


def test_filter_variants_keeps_the_first_variants_codec_family():
    """YouTube mixes avc1/TS and vp09/fMP4 variants; the LOAD describes one container."""
    out = filter_variants(MIXED_MASTER)
    uris = [ln for ln in out.splitlines() if ln and not ln.startswith("#")]
    assert uris == ["avc/720/index.m3u8", "avc/1080/index.m3u8", "audio/index.m3u8"]
    assert "vp09" not in out and 'URI="avc/iframes.m3u8"' in out
    assert "#EXT-X-INDEPENDENT-SEGMENTS" in out and out.endswith("\n")
    assert best_resolution(out) == (1920, 1080)
    # single family / no CODECS: untouched
    assert filter_variants(MASTER) == MASTER
    assert filter_variants(filter_variants(MIXED_MASTER)) == out
    vp9_first = MIXED_MASTER.replace("avc1.4d401f", "vp09.00.31.08")
    assert [ln for ln in filter_variants(vp9_first).splitlines() if ln and not ln.startswith("#")] == [
        "avc/720/index.m3u8", "vp9/2160/index.m3u8", "audio/index.m3u8"]
