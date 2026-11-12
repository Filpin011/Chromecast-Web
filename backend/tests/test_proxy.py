import httpx

from app.services.proxy.hls import encode_url
from app.services.proxy.stream import upstream_url
from app.services.proxy.tokens import ProxyTarget, TokenRegistry, clean_headers
from tests.fakes import LIVE_MEDIA, MASTER


def register(client, url, headers=None):
    return client.app.state.services.tokens.register(url, headers)


def test_token_registry_is_deterministic_and_filters_headers():
    reg = TokenRegistry()
    a = reg.register("https://x/a.m3u8", {"referer": "https://site/", "Accept": "*/*", "COOKIE": "a=b"})
    b = reg.register("https://x/a.m3u8", {"Referer": "https://site/", "Cookie": "a=b"})
    assert a.token == b.token and len(reg) == 1
    assert a.headers == {"Referer": "https://site/", "Cookie": "a=b"}
    assert clean_headers({"User-Agent": "u", "Host": "h", "Origin": ""}) == {"User-Agent": "u"}
    assert reg.get("nope") is None


def test_upstream_url_mapping():
    t = ProxyTarget(token="t", url="https://cdn/x/master.m3u8?a=1")
    assert upstream_url(t, "master.m3u8") == t.url
    assert upstream_url(t, "") == t.url
    assert upstream_url(t, f"u/{encode_url('https://o/s.ts')}/s.ts") == "https://o/s.ts"
    assert upstream_url(t, "low/index.m3u8") == "https://cdn/x/low/index.m3u8"


def test_master_and_media_playlists_rewritten_with_headers(client, mock_http):
    master = mock_http.get("https://cdn.example.com/live/master.m3u8").respond(
        200, text=MASTER, headers={"content-type": "application/vnd.apple.mpegurl"})
    media = mock_http.get("https://cdn.example.com/live/hi/index.m3u8").respond(200, text=LIVE_MEDIA)
    seg = mock_http.get("https://cdn.example.com/live/hi/seg100.ts").respond(
        200, content=b"TSDATA" * 100, headers={"content-type": "video/mp2t"})
    t = register(client, "https://cdn.example.com/live/master.m3u8", {"Referer": "https://site.example/", "Cookie": "k=v"})

    r = client.get(f"/proxy/{t.token}/master.m3u8")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert r.headers["access-control-allow-origin"] == "*"
    assert master.calls.last.request.headers["referer"] == "https://site.example/"
    assert master.calls.last.request.headers["cookie"] == "k=v"
    lines = [ln for ln in r.text.splitlines() if ln and not ln.startswith("#")]
    assert all(ln.startswith(f"/proxy/{t.token}/u/") for ln in lines)

    r = client.get(lines[1])
    assert r.status_code == 200 and media.called
    seg_path = next(ln for ln in r.text.splitlines() if ln and not ln.startswith("#"))
    assert seg_path.endswith("/seg100.ts")
    r = client.get(seg_path)
    assert r.content == b"TSDATA" * 100 and seg.calls.last.request.headers["referer"] == "https://site.example/"


def test_range_passthrough(client, mock_http):
    route = mock_http.route(url="https://cdn.example.com/movie.mp4").respond(
        206, content=b"x" * 10,
        headers={"content-type": "video/mp4", "content-range": "bytes 0-9/1000", "accept-ranges": "bytes",
                 "content-length": "10"})
    t = register(client, "https://cdn.example.com/movie.mp4")
    r = client.get(f"/proxy/{t.token}/movie.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 0-9/1000" and r.headers["accept-ranges"] == "bytes"
    assert route.calls.last.request.headers["range"] == "bytes=0-9"
    h = client.head(f"/proxy/{t.token}/movie.mp4")
    assert h.status_code == 206 and route.calls.last.request.method == "HEAD"


def test_upstream_errors(client, mock_http):
    mock_http.get("https://down.example.com/x.m3u8").mock(side_effect=httpx.ConnectError("refused"))
    t = register(client, "https://down.example.com/x.m3u8")
    assert client.get(f"/proxy/{t.token}/x.m3u8").status_code == 502
    mock_http.get("https://cdn.example.com/403.m3u8").respond(403, text="forbidden")
    t = register(client, "https://cdn.example.com/403.m3u8")
    assert client.get(f"/proxy/{t.token}/403.m3u8").status_code == 403
    r = client.get("/proxy/unknown/x.m3u8")
    assert r.status_code == 404 and r.json()["code"] == "token_not_found"


def test_non_hls_text_under_m3u8_name_passthrough(client, mock_http):
    mock_http.get("https://cdn.example.com/weird.m3u8").respond(200, text="<html>nope</html>",
                                                              headers={"content-type": "text/html"})
    t = register(client, "https://cdn.example.com/weird.m3u8")
    r = client.get(f"/proxy/{t.token}/weird.m3u8")
    assert r.text == "<html>nope</html>"


def test_upstream_url_resolves_relative_uris_under_encoded_paths():
    t = ProxyTarget(token="t", url="https://cdn/x/master.m3u8")
    enc = encode_url("https://cdn2.example/live/stream.php?id=5")
    # player resolved "seg2.ts" against /proxy/t/u/<b64>/stream.php → must not refetch the playlist
    assert upstream_url(t, f"u/{enc}/stream.php") == "https://cdn2.example/live/stream.php?id=5"
    assert upstream_url(t, f"u/{enc}") == "https://cdn2.example/live/stream.php?id=5"
    assert upstream_url(t, f"u/{enc}/seg2.ts") == "https://cdn2.example/live/seg2.ts"


def test_disguised_playlists_are_sniffed_and_rewritten(client, mock_http):
    body = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nhttps://cdn2.example/seg2.ts\n#EXTINF:4,\nseg3.ts\n"
    for ct in ("text/plain", "application/octet-stream", ""):
        url = f"https://cdn2.example/live/stream.php?id=5&ct={ct.replace('/', '_')}"
        mock_http.get(url).respond(200, content=body.encode(), headers={"content-type": ct} if ct else {})
        t = register(client, url, {"Referer": "https://site.example/"})
        r = client.get(f"/proxy/{t.token}/{t.filename}")
        assert r.status_code == 200, ct
        assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
        uris = [ln for ln in r.text.splitlines() if ln and not ln.startswith("#")]
        assert len(uris) == 2 and all(u.startswith(f"/proxy/{t.token}/u/") for u in uris), r.text
        assert "https://cdn2.example" not in r.text


def test_binary_octet_stream_is_streamed_untouched(client, mock_http):
    payload = b"\x47" + b"\x00" * 5000 + b"END"
    mock_http.get("https://cdn2.example/chunk?n=1").respond(
        200, content=payload, headers={"content-type": "application/octet-stream"})
    t = register(client, "https://cdn2.example/chunk?n=1")
    r = client.get(f"/proxy/{t.token}/{t.filename}")
    assert r.status_code == 200 and r.content == payload
    assert r.headers["content-type"] == "application/octet-stream"


def test_proxy_sends_browser_user_agent_unless_one_was_captured(client, mock_http):
    route = mock_http.get("https://cdn.example.com/v/movie.mp4").respond(
        200, content=b"x", headers={"content-type": "video/mp4"})
    t = register(client, "https://cdn.example.com/v/movie.mp4")
    assert client.get(f"/proxy/{t.token}/movie.mp4").status_code == 200
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith("Mozilla/") and "python-httpx" not in ua
    t2 = register(client, "https://cdn.example.com/v/movie.mp4", {"User-Agent": "VLC/3.0"})
    client.get(f"/proxy/{t2.token}/movie.mp4")
    assert route.calls.last.request.headers["user-agent"] == "VLC/3.0"


def test_cast_receiver_preflight_on_media_endpoints(client, mock_http):
    """The Default Media Receiver (Origin gstatic.com) preflights Range XHRs (DASH SegmentBase,
    HLS byte ranges): the app-wide dev CORS policy must not answer them with 400."""
    t = register(client, "https://cdn.example.com/v/movie.mp4")
    for path in (f"/proxy/{t.token}/a.mp4", "/restream/abc/index.m3u8", "/local/Movies/film.mp4", "/idle.jpg"):
        r = client.options(path, headers={
            "Origin": "https://www.gstatic.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "range",
        })
        assert r.status_code == 204, path
        assert r.headers["access-control-allow-origin"] == "*"
        assert "range" in r.headers["access-control-allow-headers"].lower()
        assert "GET" in r.headers["access-control-allow-methods"]
    # the API keeps its own (dev-only) CORS policy
    r = client.options("/api/state", headers={
        "Origin": "https://www.gstatic.com", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 400
    # a real GET from the receiver still gets ACAO *
    route = mock_http.get("https://cdn.example.com/v/movie.mp4").respond(
        206, content=b"x", headers={"content-type": "video/mp4", "content-range": "bytes 0-0/10"})
    r = client.get(f"/proxy/{t.token}/movie.mp4", headers={"Origin": "https://www.gstatic.com", "Range": "bytes=0-0"})
    assert r.status_code == 206 and r.headers["access-control-allow-origin"] == "*" and route.called
