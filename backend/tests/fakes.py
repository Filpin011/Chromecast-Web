"""Test doubles: a minimal fake of the Playwright objects we use, and yt-dlp info."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


class Emitter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Any]] = defaultdict(list)

    def on(self, event: str, cb: Any) -> None:
        self._handlers[event].append(cb)

    def emit(self, event: str, *args: Any) -> None:
        for cb in list(self._handlers[event]):
            cb(*args)


@dataclass
class Resource:
    """A network request the fake page performs when navigated to."""

    url: str
    content_type: str | None = None
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    frame_url: str | None = None
    resource_type: str | None = None


class FakeFrame:
    def __init__(self, url: str, parent: FakeFrame | None = None, evaluate_result: Any = None,
                 page: Any = None) -> None:
        self.url = url
        self.parent_frame = parent
        self.evaluate_result = evaluate_result
        self.evaluated: list[Any] = []
        self.page = page

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        self.evaluated.append((js, arg))
        if callable(self.evaluate_result):
            return self.evaluate_result(js, arg)
        return self.evaluate_result


class FakeRequest:
    def __init__(self, url: str, headers: dict[str, str], frame: FakeFrame, resource_type: str = "other",
                 navigation: bool = False) -> None:
        self.url = url
        self.headers = headers
        self.frame = frame
        self.resource_type = resource_type
        self._navigation = navigation

    def is_navigation_request(self) -> bool:
        return self._navigation

    async def all_headers(self) -> dict[str, str]:
        return dict(self.headers)


class FakeResponse:
    def __init__(self, request: FakeRequest, content_type: str | None, body: str) -> None:
        self.request = request
        self.url = request.url
        self.headers = {"content-type": content_type} if content_type else {}
        self._body = body

    async def text(self) -> str:
        return self._body


class FakeRoute:
    """Records what the ``context.route`` handler decided for one request."""

    def __init__(self, request: FakeRequest) -> None:
        self.request = request
        self.action: str | None = None
        self.fulfilled: dict[str, Any] | None = None

    async def continue_(self, **_: Any) -> None:
        self.action = "continue"

    async def abort(self, error_code: str = "failed") -> None:
        self.action = "abort"

    async def fulfill(self, **kwargs: Any) -> None:
        self.action = "fulfill"
        self.fulfilled = kwargs


class Recorder:
    def __init__(self, name: str, log: list[tuple[Any, ...]]) -> None:
        self._name = name
        self._log = log

    def __getattr__(self, method: str) -> Any:
        async def call(*args: Any, **kwargs: Any) -> None:
            self._log.append((f"{self._name}.{method}", *args, *(kwargs.values())))

        return call


class FakeCDP(Emitter):
    def __init__(self, fail: bool = False) -> None:
        super().__init__()
        self.sent: list[tuple[str, Any]] = []
        self.fail = fail

    async def send(self, method: str, params: Any = None) -> Any:
        if self.fail:
            raise RuntimeError("CDP not available")
        self.sent.append((method, params))
        return {}

    async def detach(self) -> None:
        pass


class FakePage(Emitter):
    def __init__(self, context: FakeContext, url: str = "about:blank") -> None:
        super().__init__()
        self.context = context
        self.url = url
        self.input_log: list[tuple[Any, ...]] = []
        self.mouse = Recorder("mouse", self.input_log)
        self.keyboard = Recorder("keyboard", self.input_log)
        self.touchscreen = Recorder("touchscreen", self.input_log)
        self.main_frame = FakeFrame(url, evaluate_result=context.evaluate, page=self)
        self.frames = [self.main_frame]
        self.closed = False
        self.history: list[str] = []

    async def goto(self, url: str, **_: Any) -> None:
        nav = await self.context.route_request(
            FakeRequest(url, {"user-agent": "FakeUA"}, self.main_frame, "document", navigation=True)
        )
        if nav is not None and nav.action == "abort":
            return
        self.url = url
        self.main_frame.url = url
        self.history.append(url)
        self.emit("framenavigated", self.main_frame)
        await self.context.simulate_network(self, url)

    async def go_back(self, **_: Any) -> None:
        if len(self.history) > 1:
            self.history.pop()
            self.url = self.history[-1]

    async def go_forward(self, **_: Any) -> None:
        pass

    async def reload(self, **_: Any) -> None:
        await self.context.simulate_network(self, self.url)

    async def title(self) -> str:
        return self.context.titles.get(self.url, "Fake page")

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        return await self.main_frame.evaluate(js, arg)

    async def screenshot(self, **_: Any) -> bytes:
        return b"\xff\xd8fakejpeg"

    async def wait_for_load_state(self, *_: Any, **__: Any) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


class FakeContext(Emitter):
    def __init__(self, site: dict[str, list[Resource]], titles: dict[str, str], cdp_fail: bool = False,
                 evaluate: Any = None) -> None:
        super().__init__()
        self.evaluate = evaluate
        self.site = site
        self.titles = titles
        self.pages: list[FakePage] = []
        self.cdp_sessions: list[FakeCDP] = []
        self.cdp_fail = cdp_fail
        self.closed = False
        self.route_handler: Any = None
        self.routes: list[FakeRoute] = []
        self.init_scripts: list[str] = []
        self.bindings: dict[str, Any] = {}
        self.close_delay = 0.0

    async def route(self, pattern: str, handler: Any) -> None:
        self.route_handler = handler

    async def expose_binding(self, name: str, cb: Any) -> None:
        self.bindings[name] = cb

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    async def route_request(self, req: FakeRequest) -> FakeRoute | None:
        if self.route_handler is None:
            return None
        route = FakeRoute(req)
        self.routes.append(route)
        await self.route_handler(route, req)
        return route

    def route_for(self, url: str) -> FakeRoute | None:
        for r in reversed(self.routes):
            if r.request.url == url:
                return r
        return None

    async def new_page(self) -> FakePage:
        page = FakePage(self)
        self.pages.append(page)
        self.emit("page", page)
        return page

    async def new_cdp_session(self, page: FakePage) -> FakeCDP:
        cdp = FakeCDP(fail=self.cdp_fail)
        self.cdp_sessions.append(cdp)
        return cdp

    async def cookies(self, urls: list[str] | None = None) -> list[dict[str, str]]:
        return [{"name": "sess", "value": "abc"}]

    async def close(self) -> None:
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        self.closed = True

    async def simulate_network(self, page: FakePage, url: str) -> None:
        for res in self.site.get(url, []):
            frame = FakeFrame(res.frame_url or url, parent=page.main_frame if res.frame_url else None, page=page)
            req = FakeRequest(res.url, {"user-agent": "FakeUA", "referer": res.frame_url or url, **res.headers}, frame,
                              res.resource_type or ("media" if res.content_type else "other"))
            self.emit("request", req)
            route = await self.route_request(req)
            if route is None or route.action == "continue":
                self.emit("response", FakeResponse(req, res.content_type, res.body))
        await asyncio.sleep(0)

    async def open_popup(self, url: str) -> FakePage:
        """window.open(url): the page event fires, then its top-level navigation request."""
        page = FakePage(self, "about:blank")
        self.pages.append(page)
        self.emit("page", page)
        await asyncio.sleep(0)
        nav = await self.route_request(FakeRequest(url, {"user-agent": "FakeUA"}, page.main_frame, "document", True))
        if nav is None or nav.action == "continue":
            page.url = page.main_frame.url = url
            await self.simulate_network(page, url)
        await asyncio.sleep(0)
        return page


class FakeProvider:
    def __init__(self, site: dict[str, list[Resource]] | None = None, titles: dict[str, str] | None = None,
                 cdp_fail: bool = False, evaluate: Any = None) -> None:
        self.evaluate = evaluate
        self.site = site or {}
        self.titles = titles or {}
        self.cdp_fail = cdp_fail
        self.contexts: list[FakeContext] = []
        self.closed = False

    async def new_context(self, width: int, height: int, mobile: bool) -> FakeContext:
        ctx = FakeContext(self.site, self.titles, self.cdp_fail, self.evaluate)
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.closed = True


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720
hi/index.m3u8
"""

# YouTube-like: avc1 variants (MPEG-TS) up to 1080p next to vp09 variants (fMP4) up to 2160p
MIXED_MASTER = """#EXTM3U
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"
avc/720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=3840x2160,CODECS="vp09.00.51.08,mp4a.40.2"
vp9/2160/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
avc/1080/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=64000,CODECS="mp4a.40.2"
audio/index.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=90000,CODECS="vp09.00.51.08",URI="vp9/iframes.m3u8"
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=50000,CODECS="avc1.640028",URI="avc/iframes.m3u8"
"""

LIVE_MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXTINF:6.0,
seg100.ts
#EXTINF:6.0,
seg101.ts
"""

VOD_MEDIA = LIVE_MEDIA + "#EXT-X-ENDLIST\n"


def ytdlp_info(url: str) -> dict[str, Any]:
    if "fail" in url:
        raise RuntimeError("Unsupported URL")
    if "live" in url:
        return {
            "id": "live1",
            "title": "Live Channel",
            "url": "https://cdn.example.com/live/master.m3u8",
            "protocol": "m3u8_native",
            "ext": "mp4",
            "is_live": True,
            "thumbnail": "https://img.example.com/live.jpg",
            "http_headers": {"User-Agent": "yt-dlp-UA"},
        }
    return {
        "id": "vid1",
        "title": "Some Video",
        "url": "https://rr1.googlevideo.com/videoplayback?id=1",
        "protocol": "https",
        "ext": "mp4",
        "is_live": False,
        "duration": 213,
        "thumbnail": "https://i.ytimg.com/vi/x/hq.jpg",
        "http_headers": {"User-Agent": "yt-dlp-UA", "Accept": "*/*"},
        "subtitles": {"it": [{"ext": "json3", "url": "https://x/sub.json"}, {"ext": "vtt", "url": "https://x/it.vtt", "name": "Italiano"}]},
    }
