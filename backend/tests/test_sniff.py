from app.services.resolver import sniff


def test_classify_by_extension_and_content_type():
    assert sniff.classify("https://a/x/master.m3u8?t=1") == "hls"
    assert sniff.classify("https://a/manifest.mpd") == "dash"
    assert sniff.classify("https://a/v.mp4") == "progressive"
    assert sniff.classify("https://a/play?id=1", "application/vnd.apple.mpegurl") == "hls"
    assert sniff.classify("https://a/play?id=1", "video/mp4; codecs=x") == "progressive"
    assert sniff.classify("https://a/page.html", "text/html") is None
    assert sniff.classify("blob:https://a/123") is None


def test_mime_for():
    assert sniff.mime_for("https://a/x.m3u8") == "application/x-mpegURL"
    assert sniff.mime_for("https://a/x.ts") == "video/mp2t"
    assert sniff.mime_for("https://a/x", "dash") == "application/dash+xml"
    assert sniff.mime_for("https://a/x", None, "video/webm") == "video/webm"


def test_ads_and_segments_rank_low():
    main = sniff.score("https://cdn.site.com/live/master.m3u8", "hls", is_master=True, height=1080)
    media = sniff.score("https://cdn.site.com/live/720/index.m3u8", "hls", is_master=False)
    ad = sniff.score("https://ads.doubleclick.net/preroll.mp4", "progressive")
    seg = sniff.score("https://cdn.site.com/live/seg_00123.ts", "progressive")
    teaser = sniff.score("https://cdn.site.com/teaser.mp4", "progressive", content_length=200_000)
    assert main > media > teaser > ad
    assert media > seg
    assert sniff.is_ad("https://imasdk.googleapis.com/js/sdkloader/ima3.js")
    assert sniff.is_segment("https://cdn/x/chunk_12.m4s")
    assert not sniff.is_segment("https://cdn/x/movie.mp4")


def test_segments_beyond_ts_and_m4s():
    for url, ct in [
        ("https://cdn.x/live/seg-12-v1-a1.mp4", None),
        ("https://cdn.x/live/fileSequence123.mp4", "video/mp4"),
        ("https://cdn.x/chunk_3.png", "video/mp2t"),
        ("https://cdn.x/live/init-v1.mp4", None),
        ("https://cdn.x/v/frag-7.cmfv", None),
    ]:
        assert sniff.is_segment(url, ct), url
    for url in ("https://site/videos/12345.mp4", "https://site/segunda-parte.mp4", "https://cdn/x/movie.mp4"):
        assert not sniff.is_segment(url, "video/mp4"), url


def test_stream_key_drops_volatile_params_only():
    k = sniff.stream_key
    assert k("https://c/x/i.m3u8?_HLS_msn=5&_HLS_part=2") == k("https://c/x/i.m3u8?_HLS_msn=6") == "https://c/x/i.m3u8"
    assert k("https://c/x/i.m3u8?token=a&_=1&id=7") == k("https://c/x/i.m3u8?id=7&token=b") == "https://c/x/i.m3u8?id=7"
    assert k("https://c/p.php?ch=1") != k("https://c/p.php?ch=2")


def test_sniff_container_magic_bytes():
    from app.services.resolver.sniff import sniff_container

    ts = b"".join(b"\x47" + b"\x00" * 187 for _ in range(3))
    assert sniff_container(ts) == "video/mp2t"
    assert sniff_container(ts[:200]) is None  # one sync byte is not enough (could be text "G...")
    assert sniff_container(b"GET / HTTP/1.1\r\n" * 30) is None
    assert sniff_container(b"FLV\x01\x05" + b"\0" * 20) == "video/x-flv"
    assert sniff_container(b"RIFF\0\0\0\0AVI LIST") == "video/x-msvideo"
    assert sniff_container(b"\0\0\0\x20ftypisom") == "video/mp4"
    assert sniff_container(b"\x1a\x45\xdf\xa3\x01\0\0\0webm") == "video/webm"
    assert sniff_container(b"\x1a\x45\xdf\xa3\x01\0\0\0matroska") == "video/x-matroska"
    assert sniff_container(b"#EXTM3U\n") is None and sniff_container(b"") is None
