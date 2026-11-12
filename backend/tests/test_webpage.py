"""Webpage extraction: collector logic with fakes + a real-Chromium integration test."""

from __future__ import annotations

import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.resolver import webpage
from tests.fakes import FakeFrame, FakeProvider, FakeRequest, FakeResponse, Resource

PAGE = "https://sport.example.com/match"


def test_dedupe_key_ignores_volatile_query():
    assert webpage.dedupe_key("https://a/x.m3u8?token=1&t=2") == webpage.dedupe_key("https://a/x.m3u8?token=9")


async def test_collector_ranks_master_over_media_and_skips_ads():
    c = webpage._Collector(context=None)
    frame = FakeFrame(PAGE)
    for url, ct, body in [
        ("https://cdn/x/720/index.m3u8?tok=1", "application/x-mpegurl", "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\na.ts\n"),
        ("https://cdn/x/master.m3u8?tok=1", "application/x-mpegurl", "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n720/index.m3u8\n"),
        ("https://cdn/x/master.m3u8?tok=2", "application/x-mpegurl", ""),  # same stream, new token: deduped
        ("https://imasdk.googleapis.com/ads/preroll.mp4", "video/mp4", ""),
        ("https://cdn/x/720/seg_00001.ts", "video/mp2t", ""),
    ]:
        req = FakeRequest(url, {"referer": PAGE}, frame)
        c.on_request(req)
        c.on_response(FakeResponse(req, ct, body))
    await c.settle()
    assert len(c.found) == 2
    best = c.best()
    assert best.url == "https://cdn/x/master.m3u8?tok=1" and best.is_master is True
    assert best.headers["referer"] == PAGE
    assert c.has_adaptive()


async def test_browser_extract_clicks_every_frame_and_uses_video_src_fallback():
    calls: list[str] = []

    def evaluate(js, arg):
        calls.append(js)
        if "currentSrc" in js:
            return ["https://media.example.com/vod/film.mp4"]
        return None

    provider = FakeProvider(site={PAGE: []}, titles={PAGE: "Film"}, evaluate=evaluate)
    found = await webpage.browser_extract(provider, PAGE, timeout=6)
    assert found is not None
    assert found.url == "https://media.example.com/vod/film.mp4" and found.kind == "progressive"
    assert found.headers["Referer"] == PAGE
    assert any("v.play()" in js for js in calls)  # play buttons were tried
    assert provider.contexts[0].closed


async def test_browser_extract_closes_popups_but_sniffs_them():
    provider = FakeProvider(site={PAGE: [], "https://pop.example.net/ad": [
        Resource("https://cdn.example.com/live/main.m3u8", "application/vnd.apple.mpegurl", "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\na.m3u8\n"),
    ]})
    ctx_holder = {}
    orig = provider.new_context

    async def new_context(*a):
        ctx = await orig(*a)
        ctx_holder["ctx"] = ctx
        return ctx

    provider.new_context = new_context  # type: ignore[method-assign]
    task = asyncio.create_task(webpage.browser_extract(provider, PAGE, timeout=8))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if ctx_holder.get("ctx") and ctx_holder["ctx"].pages:
            break
    ctx = ctx_holder["ctx"]
    popup = await ctx.open_popup("https://pop.example.net/ad")
    await ctx.simulate_network(popup, "https://pop.example.net/ad")
    found = await task
    assert found is not None and found.url == "https://cdn.example.com/live/main.m3u8" and found.is_master


# --------------------------------------------------------------------------- real Chromium

INDEX = """<!doctype html><html><head><title>Partita in diretta</title></head><body>
<div id="overlay" style="position:fixed;inset:0;background:#0008"></div>
<div id="slot" style="width:640px;height:360px"></div>
<script>
setTimeout(function () {
  var b = document.createElement('button');
  b.className = 'big-play-btn'; b.textContent = 'Play';
  b.style.cssText = 'position:fixed;left:200px;top:200px;width:120px;height:60px;z-index:9';
  b.onclick = function () {
    var f = document.createElement('iframe');
    f.src = 'http://localhost:PORT/embed.html'; f.width = 640; f.height = 360;
    document.getElementById('slot').appendChild(f); b.remove();
  };
  document.body.appendChild(b);
}, 400);
</script></body></html>"""

EMBED = """<!doctype html><html><body style="margin:0">
<iframe src="/inner.html" width="620" height="340"></iframe></body></html>"""

INNER = """<!doctype html><html><body><video width="600" height="300" muted></video><script>
var _0x = ['c3RyZWFt', 'L2FwaS8=', 'Lmpzb24='];
var u = atob(_0x[1]) + atob(_0x[0]) + atob(_0x[2]);
setTimeout(function () {
  fetch(u).then(function (r) { return r.json(); }).then(function (j) { return fetch(j['s' + 'rc']); });
}, 300);
</script></body></html>"""

# Same page with an ad iframe and a click-triggered popunder (window.open), like real sport-streaming sites.
ADSITE = INDEX.replace(
    "<div id=\"slot\"",
    '<iframe id="ad" src="https://ads.example/banner.html" width="300" height="50"></iframe>'
    "<script>document.addEventListener('click', function () {"
    " window.open('https://popunder.example/win?z=1', '_blank'); }, {once: true});</script>"
    "<div id=\"slot\"",
)

PLAYLIST = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:1\n#EXTINF:4,\nseg1.ts\n"


class _DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _serve() -> tuple[ThreadingHTTPServer, int, list[dict[str, str]]]:
    seen: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            port = self.server.server_address[1]
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, INDEX.replace("PORT", str(port)), "text/html")
            elif path == "/adsite":
                self._send(200, ADSITE.replace("PORT", str(port)), "text/html")
            elif path == "/embed.html":
                self._send(200, EMBED, "text/html")
            elif path == "/inner.html":
                self._send(200, INNER, "text/html")
            elif path == "/api/stream.json":
                self._send(200, '{"src": "/live/x9/playlist.m3u8?st=abc"}', "application/json")
            elif path == "/live/x9/playlist.m3u8":
                seen.append(dict(self.headers))
                if "/inner.html" not in (self.headers.get("Referer") or ""):
                    self._send(403, "forbidden", "text/plain")
                else:
                    self._send(200, PLAYLIST, "application/vnd.apple.mpegurl")
            else:
                self._send(404, "", "text/plain")

    server = _DualStackServer(("::", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], seen


@pytest.mark.browser
async def test_real_chromium_captures_stream_from_nested_iframe_after_click():
    from app.services.browser.launcher import PlaywrightProvider

    provider = PlaywrightProvider()
    try:
        await provider._ensure()
    except Exception as exc:  # Chromium not installed
        await provider.close()
        pytest.skip(f"Playwright Chromium unavailable: {exc}")
    server, port, seen = _serve()
    try:
        found = await webpage.browser_extract(provider, f"http://127.0.0.1:{port}/", timeout=25)
    finally:
        server.shutdown()
        await provider.close()
    assert found is not None, "stream not captured"
    assert found.url == f"http://localhost:{port}/live/x9/playlist.m3u8?st=abc"
    assert found.kind == "hls" and found.mime_type == "application/x-mpegURL"
    referer = {k.lower(): v for k, v in found.headers.items()}["referer"]
    assert referer == f"http://localhost:{port}/inner.html"
    assert found.title == "Partita in diretta"
    assert found.is_live is True
    assert any("/inner.html" in (h.get("Referer") or "") for h in seen)
    # looks like a normal Chrome: no "HeadlessChrome" in the UA nor in the client hints
    for h in seen:
        assert "Headless" not in h.get("User-Agent", "")
        assert '"Chromium"' in h["sec-ch-ua"] and "Headless" not in h["sec-ch-ua"], h["sec-ch-ua"]
    assert "Headless" not in str(found.headers)


@pytest.mark.browser
async def test_real_chromium_interactive_session_screencast_tap_and_capture():
    from app.models import Viewport
    from app.services.browser.launcher import PlaywrightProvider
    from app.services.browser.session import BrowserManager

    provider = PlaywrightProvider()
    try:
        await provider._ensure()
    except Exception as exc:
        await provider.close()
        pytest.skip(f"Playwright Chromium unavailable: {exc}")
    server, port, seen = _serve()
    mgr = BrowserManager(provider)
    try:
        s = await mgr.create(f"http://127.0.0.1:{port}/", Viewport(width=1280, height=720))
        q = s.subscribe()
        got_frame = False
        for _ in range(100):
            msg = await asyncio.wait_for(q.get(), 10)
            if msg["type"] == "frame" and msg["data"]:
                got_frame = True
                break
        assert got_frame
        await asyncio.sleep(0.8)  # the play button appears after 400ms
        await s.handle_input({"type": "tap", "x": 260, "y": 230})
        for _ in range(100):
            if s.captured:
                break
            await asyncio.sleep(0.1)
        assert s.captured and s.captured[0].url.startswith(f"http://localhost:{port}/live/x9/playlist.m3u8")
        assert s.captured[0].headers["referer"] == f"http://localhost:{port}/inner.html"
        assert s.title == "Partita in diretta"
        # the headers stored for replay and those the CDN saw carry no headless brand
        assert "Headless" not in str(s.captured[0].headers)
        assert seen and all("Headless" not in h.get("sec-ch-ua", "") for h in seen)
        brands = await s.page.evaluate("() => navigator.userAgentData.brands.map(b => b.brand)")
        assert "Chromium" in brands and not any("Headless" in b for b in brands)
    finally:
        await mgr.shutdown()
        server.shutdown()
        await provider.close()


@pytest.mark.browser
async def test_real_chromium_blocks_ad_iframe_and_popunder_but_captures_stream():
    from app.models import Viewport
    from app.services.adblock import FilterManager
    from app.services.browser.launcher import PlaywrightProvider
    from app.services.browser.session import BrowserManager

    provider = PlaywrightProvider()
    try:
        await provider._ensure()
    except Exception as exc:
        await provider.close()
        pytest.skip(f"Playwright Chromium unavailable: {exc}")
    server, port, _ = _serve()
    mgr = BrowserManager(provider, filters=FilterManager(None))  # bundled list: ads.example, $popup rules
    try:
        s = await mgr.create(f"http://127.0.0.1:{port}/adsite", Viewport(width=1280, height=720))
        for _ in range(50):  # the ad iframe is aborted by the engine
            if s.blocked_count >= 1:
                break
            await asyncio.sleep(0.1)
        assert s.blocked_count >= 1
        await asyncio.sleep(0.8)  # the play button appears after 400ms
        await s.handle_input({"type": "tap", "x": 260, "y": 230})  # also fires the popunder
        for _ in range(100):
            if s.captured:
                break
            await asyncio.sleep(0.1)
        assert s.captured and s.captured[0].url.startswith(f"http://localhost:{port}/live/x9/playlist.m3u8")
        assert s.captured[0].headers["referer"] == f"http://localhost:{port}/inner.html"
        for _ in range(50):  # popunder matched a $popup filter: closed automatically, counted, no prompt
            if s.blocked_count >= 2 and len(s.context.pages) == 1:
                break
            await asyncio.sleep(0.1)
        assert s.blocked_count >= 2
        assert [p.url for p in s.context.pages] == [s.page.url]
        assert s.page.url.endswith("/adsite") and s.to_model().pending_popups == []
    finally:
        await mgr.shutdown()
        server.shutdown()
        await provider.close()


@pytest.mark.browser
async def test_real_chromium_resolver_with_adblock_on_ad_page():
    from app.services.adblock import FilterManager
    from app.services.browser.launcher import PlaywrightProvider

    provider = PlaywrightProvider()
    try:
        await provider._ensure()
    except Exception as exc:
        await provider.close()
        pytest.skip(f"Playwright Chromium unavailable: {exc}")
    server, port, _ = _serve()
    try:
        found = await webpage.browser_extract(
            provider, f"http://127.0.0.1:{port}/adsite", timeout=25, filters=FilterManager(None)
        )
    finally:
        server.shutdown()
        await provider.close()
    assert found is not None and found.url == f"http://localhost:{port}/live/x9/playlist.m3u8?st=abc"
    assert {k.lower(): v for k, v in found.headers.items()}["referer"] == f"http://localhost:{port}/inner.html"


@pytest.mark.browser
async def test_real_chromium_frame_offset_of_nested_iframes():
    """bounding_box() is main-frame relative: nested offsets must not be summed twice,
    and the iframe's border/padding shift its document."""
    from playwright.async_api import async_playwright

    pages = {
        "/top": "<body style='margin:0'><iframe src='/mid' style='position:absolute;left:100px;"
        "top:50px;border:0;width:900px;height:600px'></iframe></body>",
        "/mid": "<body style='margin:0'><iframe src='/inner' style='position:absolute;left:200px;"
        "top:150px;border:3px solid red;padding:5px;width:400px;height:300px'></iframe></body>",
        "/inner": "<body style='margin:0'>x</body>",
    }
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except Exception as exc:  # Chromium not installed
            pytest.skip(f"Playwright Chromium unavailable: {exc}")
        try:
            page = await browser.new_page()

            async def handler(route):
                from urllib.parse import urlsplit

                await route.fulfill(body=pages[urlsplit(route.request.url).path], content_type="text/html")

            await page.route("http://frames.test/**", handler)
            await page.goto("http://frames.test/top")
            for _ in range(50):
                inner = [f for f in page.frames if f.url.endswith("/inner")]
                if inner:
                    break
                await asyncio.sleep(0.1)
            deepest = inner[0]
            assert await webpage._frame_offset(page.main_frame) == (0, 0)
            assert await webpage._frame_offset(deepest.parent_frame) == (100, 50)
            assert await webpage._frame_offset(deepest) == (100 + 200 + 8, 50 + 150 + 8)
        finally:
            await browser.close()

