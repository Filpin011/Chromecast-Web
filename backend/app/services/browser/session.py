"""Interactive remote browser sessions (Playwright Chromium).

Each session owns one browser context + page. The viewport is streamed over
CDP ``Page.startScreencast`` (fallback: periodic screenshots), user input is
forwarded with ``page.mouse`` / ``page.touchscreen`` / ``page.keyboard``, and every
network request of the context (main page, iframes, workers, popups) is sniffed
for media streams.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.errors import AppError
from app.models import BrowserSession, CapturedStream, PopupRequest, Settings, Viewport, utcnow
from app.services import adblock
from app.services.browser.launcher import BrowserProvider
from app.services.proxy.hls import quality_label
from app.services.resolver import sniff
from app.services.resolver.webpage import request_headers

log = logging.getLogger(__name__)

MAX_CAPTURED = 50
# control messages (session/captured/popup/blocked/...) buffered per viewer; frames never
# take a slot of their own: at most one (the latest) is ever queued
SUBSCRIBER_QUEUE = 64
SCREENSHOT_INTERVAL = 0.5
NAV_TIMEOUT_MS = 20_000
THUMB_MAX_BYTES = 120_000
USER_GESTURE_WINDOW = 2.0  # s after a tap/click/key during which navigations count as user-initiated
NAV_GRACE = 4.0  # s after an explicit navigate() during which JS redirects are allowed
POPUP_HOLD_TIMEOUT = 6.0  # a held popup that never navigates is closed
MAX_PENDING_POPUPS = 5
CLOSE_TIMEOUT = 1.0

STOP_MEDIA_JS = """
() => { for (const m of document.querySelectorAll('video, audio')) { try { m.pause(); m.muted = true; } catch (e) {} } }
"""

LARGEST_VIDEO_JS = """
() => {
  let best = null, area = 0;
  for (const el of document.querySelectorAll('video')) {
    const r = el.getBoundingClientRect();
    const a = r.width * r.height;
    if (a > area && r.width > 40 && r.height > 30) { area = a; best = r; }
  }
  return best ? {x: Math.max(0, best.x), y: Math.max(0, best.y), width: best.width, height: best.height,
                 vw: (document.querySelector('video')||{}).videoWidth || null,
                 vh: (document.querySelector('video')||{}).videoHeight || null} : null;
}
"""

# (url, headers) -> info with is_master / is_live / width / height (see Resolver.hls_info)
HlsProbe = Callable[[str, dict[str, str]], Awaitable[Any]]
# (url, headers) -> same-origin preview path
PreviewRegistrar = Callable[[str, dict[str, str]], str]
SettingsGetter = Callable[[], Settings]
SettingsUpdater = Callable[[dict[str, Any]], Settings]


class ViewerQueue(asyncio.Queue):  # type: ignore[type-arg]
    """Per-viewer outbox that never lets screencast frames push out real messages.

    Frames are coalesced: a new frame replaces the one still waiting (a stale frame is
    worthless), so a slow phone link only ever skips frames. When the queue is full of
    control messages the oldest one is dropped (last resort, the viewer is far behind).
    """

    def _init(self, maxsize: int) -> None:
        self._queue: deque[dict[str, Any]] = deque()

    def _put(self, item: dict[str, Any]) -> None:
        self._queue.append(item)

    def _get(self) -> dict[str, Any]:
        return self._queue.popleft()

    def _drop_frame(self) -> bool:
        for i, queued in enumerate(self._queue):
            if queued.get("type") == "frame":
                del self._queue[i]
                return True
        return False

    def offer(self, item: dict[str, Any]) -> None:
        """Non-blocking put that never raises."""
        if item.get("type") == "frame":
            self._drop_frame()  # replace the frame still waiting, if any
        if self.full() and not self._drop_frame():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self.put_nowait(item)


def normalize_url(url: str) -> str:
    url = url.strip()
    if not urlsplit(url).scheme:
        url = "https://" + url
    return url


class RemoteBrowserSession:
    def __init__(
        self,
        session_id: str,
        context: Any,
        viewport: Viewport,
        *,
        hls_probe: HlsProbe | None = None,
        preview: PreviewRegistrar | None = None,
        filters: adblock.FilterManager | None = None,
        settings: SettingsGetter | None = None,
        update_settings: SettingsUpdater | None = None,
    ) -> None:
        self.id = session_id
        self.context = context
        self.viewport = viewport
        self.page: Any = None
        self.cdp: Any = None
        self.created_at: datetime = utcnow()
        self.title: str | None = None
        self.url: str = "about:blank"
        self.captured: list[CapturedStream] = []
        self.last_activity = time.monotonic()
        self.closed = False
        self.hls_probe = hls_probe
        self.preview = preview
        self.mobile = viewport.width < 800
        self._subscribers: set[ViewerQueue] = set()
        self._last_frame: dict[str, Any] | None = None
        self._screencast_ok = False
        # > 0 while a thumbnail screenshot runs: Chromium then emits screencast frames sized like the clip
        self._capturing = 0
        self._shot_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._seen_urls: set[str] = set()  # sniff.stream_key() of every URL already handled
        self._manifest_frames: set[str] = set()  # frames that loaded an HLS/DASH manifest
        self._manifest_hosts: set[str] = set()  # hosts that served an HLS/DASH manifest
        # ad blocking / popups
        self.filters = filters
        self._settings = settings or Settings
        self._update_settings = update_settings
        self.blocked_count = 0
        self._blocked_flush: asyncio.TimerHandle | None = None
        self._blocked_limiter = adblock.RateLimiter(0.5)
        self.pending_popups: dict[str, tuple[PopupRequest, str]] = {}  # id -> (request, "popup"|"navigation")
        self._held: set[Any] = set()  # popup pages waiting for a policy decision
        self._own_pages: set[Any] = set()  # pages we opened ourselves (never treated as popups)
        self._last_input = 0.0
        self._nav_allowed_until = 0.0
        self._allowed_urls: set[str] = set()
        self._opening_own = False

    # ------------------------------------------------------------ model
    def to_model(self) -> BrowserSession:
        return BrowserSession(
            id=self.id,
            url=self.url,
            title=self.title,
            viewport=self.viewport,
            captured=sorted(self.captured, key=lambda c: c.score, reverse=True),
            created_at=self.created_at,
            adblock_enabled=self.adblock_enabled,
            blocked_count=self.blocked_count,
            pending_popups=[p for p, _ in self.pending_popups.values()],
        )

    def get_stream(self, stream_id: str) -> CapturedStream:
        for c in self.captured:
            if c.id == stream_id:
                return c
        raise AppError(404, "Captured stream not found", "stream_not_found")

    # ------------------------------------------------------------ lifecycle
    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def start(self, url: str) -> None:
        self.context.on("request", lambda req: self._on_request(req, None))
        self.context.on("response", self._on_response)
        self.context.on("page", self._on_page)
        await adblock.install(
            self.context,
            self.filters,
            adblock.Hooks(
                enabled=lambda: self.adblock_enabled,
                on_stream=self._route_stream,
                on_blocked=lambda _url: self._count_blocked(),
                on_navigation=self._route_navigation,
            ),
        )
        with contextlib.suppress(Exception):
            await self.context.expose_binding("__cwPopup", self._on_popup_binding)
            await self.context.add_init_script(adblock.POPUP_GUARD_JS)
        page = await self._new_own_page()
        await self._attach(page)
        await self.navigate(url)

    async def _new_own_page(self) -> Any:
        self._opening_own = True
        try:
            page = await self.context.new_page()
        finally:
            self._opening_own = False
        self._own_pages.add(page)
        return page

    async def _attach(self, page: Any) -> None:
        """Make ``page`` the session's visible page and start streaming it."""
        await self._stop_screencast()
        self.page = page
        page.on("framenavigated", self._on_framenavigated)
        with contextlib.suppress(Exception):
            page.on("load", lambda *_: self._spawn(self._refresh_meta()))
        await self._start_screencast()

    async def close(self) -> None:
        """Quick close: viewers are told first, the context is torn down within ~1s."""
        if self.closed:
            return
        self.closed = True
        self._broadcast({"type": "closed"})
        if self._blocked_flush is not None:
            self._blocked_flush.cancel()
        for t in list(self._tasks):
            t.cancel()
        teardown = asyncio.ensure_future(self._teardown())
        done, _ = await asyncio.wait({teardown}, timeout=CLOSE_TIMEOUT)
        if not done:  # keep tearing down in the background, don't block the caller
            log.info("browser session %s still closing in background", self.id)

    async def _teardown(self) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._stop_screencast(), 0.5)
        with contextlib.suppress(Exception):
            await self.context.close()

    # ------------------------------------------------------------ screencast
    async def _start_screencast(self) -> None:
        self._screencast_ok = False
        try:
            self.cdp = await self.context.new_cdp_session(self.page)
            self.cdp.on("Page.screencastFrame", self._on_frame)
            await self.cdp.send("Page.startScreencast", self._screencast_params())
            self._screencast_ok = True
        except Exception as exc:
            log.info("CDP screencast unavailable (%s); falling back to screenshots", exc)
            self.cdp = None
            self._shot_task = asyncio.create_task(self._screenshot_loop())

    def _screencast_params(self) -> dict[str, Any]:
        return {
            "format": "jpeg",
            "quality": 60,
            "maxWidth": self.viewport.width,
            "maxHeight": self.viewport.height,
            "everyNthFrame": 1,
        }

    async def _refresh_screencast(self) -> None:
        """Restart the screencast so it emits a fresh full-viewport frame right away (a static page
        sends no new frame on its own, and the viewers would keep the last one)."""
        cdp = self.cdp
        if cdp is None or not self._screencast_ok:
            return
        with contextlib.suppress(Exception):
            await cdp.send("Page.stopScreencast")
            await cdp.send("Page.startScreencast", self._screencast_params())

    async def _stop_screencast(self) -> None:
        if self.cdp is not None:
            with contextlib.suppress(Exception):
                await self.cdp.send("Page.stopScreencast")
            with contextlib.suppress(Exception):
                await self.cdp.detach()
            self.cdp = None
        if self._shot_task:
            self._shot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._shot_task
            self._shot_task = None

    def _on_frame(self, params: dict[str, Any]) -> None:
        meta = params.get("metadata") or {}
        frame = {
            "type": "frame",
            "data": params.get("data", ""),
            "width": int(meta.get("deviceWidth") or self.viewport.width),
            "height": int(meta.get("deviceHeight") or self.viewport.height),
        }
        cdp = self.cdp
        if self._capturing and (frame["width"], frame["height"]) != (self.viewport.width, self.viewport.height):
            # artefact of a clipped page.screenshot() (the thumbnail): only the clip, letterboxed by the
            # viewers; _thumbnail() restarts the screencast afterwards for a fresh full frame
            if cdp is not None and "sessionId" in params:
                self._spawn(self._ack(cdp, params["sessionId"]))
            return
        self._last_frame = frame
        self._broadcast(frame)
        if cdp is not None and "sessionId" in params:
            self._spawn(self._ack(cdp, params["sessionId"]))

    @staticmethod
    async def _ack(cdp: Any, session_id: int) -> None:
        with contextlib.suppress(Exception):
            await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})

    async def _screenshot_loop(self) -> None:
        while not self.closed:
            if self._subscribers and self.page is not None:
                try:
                    shot = await self.page.screenshot(type="jpeg", quality=55)
                    frame = {
                        "type": "frame",
                        "data": base64.b64encode(shot).decode(),
                        "width": self.viewport.width,
                        "height": self.viewport.height,
                    }
                    self._last_frame = frame
                    self._broadcast(frame)
                except Exception:
                    log.debug("screenshot failed", exc_info=True)
            await asyncio.sleep(SCREENSHOT_INTERVAL)

    # ------------------------------------------------------------ subscribers
    def subscribe(self) -> ViewerQueue:
        q = ViewerQueue(maxsize=SUBSCRIBER_QUEUE)
        self._subscribers.add(q)
        self.touch()
        # the first snapshot is complete (thumbnails included): the viewer has nothing yet
        q.offer({"type": "session", "data": self.to_model().model_dump(mode="json")})
        if self._last_frame:
            q.offer(self._last_frame)
        return q

    def unsubscribe(self, q: ViewerQueue) -> None:
        self._subscribers.discard(q)
        self.touch()

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    def _broadcast(self, msg: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            q.offer(msg)

    def _broadcast_session(self) -> None:
        # Captured thumbnails (data URLs) are left out: viewers already got each one in its
        # "captured" message and upsert by id, so the key is omitted (not nulled).
        data = self.to_model().model_dump(mode="json", exclude={"captured": {"__all__": {"thumbnail"}}})
        self._broadcast({"type": "session", "data": data})

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    # ------------------------------------------------------------ navigation
    async def navigate(self, url: str | None = None, action: str | None = None) -> None:
        self.touch()
        self._nav_allowed_until = time.monotonic() + NAV_TIMEOUT_MS / 1000
        page = self.page
        try:
            if url:
                await page.goto(normalize_url(url), wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            elif action == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            elif action == "forward":
                await page.go_forward(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            elif action == "reload":
                await page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as exc:  # navigation errors (timeouts, aborted) are not fatal
            log.info("navigation issue: %s", exc)
        self._nav_allowed_until = time.monotonic() + NAV_GRACE
        await self._refresh_meta()

    async def _refresh_meta(self) -> None:
        page = self.page
        if page is None:
            return
        changed = False
        with contextlib.suppress(Exception):
            url = page.url
            if url and url != self.url:
                self.url, changed = url, True
        with contextlib.suppress(Exception):
            title = await page.title()
            if (title or None) != self.title:
                self.title, changed = title or None, True
        if changed:
            self._broadcast_session()

    def _on_framenavigated(self, frame: Any) -> None:
        with contextlib.suppress(Exception):
            if frame is not getattr(self.page, "main_frame", frame):
                return
        self._spawn(self._refresh_meta())

    # ------------------------------------------------------------ ad blocking
    @property
    def adblock_enabled(self) -> bool:
        if self.filters is None:
            return False
        st = self._settings()
        return st.adblock_enabled and not adblock.host_in(adblock.hostname(self.url), st.adblock_disabled_hosts)

    async def set_adblock(self, enabled: bool) -> None:
        """uBO "power button": toggle blocking for the current host (persisted), then reload."""
        host = adblock.hostname(self.url)
        if host and self._update_settings is not None:
            st = self._settings()
            hosts = [h for h in st.adblock_disabled_hosts if not adblock.host_in(host, [h])]
            if not enabled:
                hosts.append(host)
            patch: dict[str, Any] = {"adblock_disabled_hosts": sorted(set(hosts))}
            if enabled and not st.adblock_enabled:
                patch["adblock_enabled"] = True
            self._update_settings(patch)
        await self.navigate(action="reload")
        self._broadcast_session()

    def _count_blocked(self) -> None:
        self.blocked_count += 1
        if self._blocked_limiter.ready():
            self._broadcast({"type": "blocked", "count": self.blocked_count})
        elif self._blocked_flush is None:
            loop = asyncio.get_running_loop()
            self._blocked_flush = loop.call_later(self._blocked_limiter.interval, self._flush_blocked)

    def _flush_blocked(self) -> None:
        self._blocked_flush = None
        if not self.closed:
            self._broadcast({"type": "blocked", "count": self.blocked_count})

    def _route_stream(self, request: Any, url: str) -> bool:
        """Sniff before deciding: recognised media is captured and never blocked (ads excepted)."""
        if not sniff.classify(url):
            return False
        self._on_request(request, None)
        return not sniff.is_ad(url)

    def _user_gesture(self) -> bool:
        return time.monotonic() - self._last_input < USER_GESTURE_WINDOW

    async def _route_navigation(self, route: Any, request: Any) -> bool:
        """Top-level document requests: held popups and redirect-ads. True = handled (aborted)."""
        url = request.url
        page = None
        try:
            page = request.frame.page
        except Exception:
            # Playwright: "Frame for this navigation request is not available" = a popup's first navigation
            held = next(iter(self._held), None)
            await self._decide_new_popup(route, held, url)
            return True
        if page is not None and page is not self.page and page not in self._own_pages:
            await self._decide_new_popup(route, page, url)
            return True
        if url in self._allowed_urls:
            self._allowed_urls.discard(url)
            self._page_load_started()
            return False
        current = self.url
        cross_site = current.startswith("http") and adblock.site(url) != adblock.site(current)
        if not cross_site or time.monotonic() < self._nav_allowed_until or self._user_gesture():
            self._page_load_started()
            return False
        # cross-site navigation without a user gesture: redirect-ad
        st = self._settings()
        if self.adblock_enabled and self.filters is not None and self.filters.is_popup_ad(url, current):
            await self._abort(route)
            self._count_blocked()
            return True
        if st.popup_policy == "allow":
            self._page_load_started()
            return False
        await self._abort(route)
        if st.popup_policy == "block" or adblock.host_in(adblock.hostname(current), st.popup_blocked_hosts):
            self._count_blocked()
        else:
            self._add_pending(url, current, "navigation")
        return True

    def _page_load_started(self) -> None:
        if self.blocked_count:
            self.blocked_count = 0
            self._broadcast({"type": "blocked", "count": 0})

    @staticmethod
    async def _abort(route: Any) -> None:
        with contextlib.suppress(Exception):
            await route.abort("blockedbyclient")

    def _on_page(self, page: Any) -> None:
        """Every new tab/window is held: never shown before the popup policy decides."""
        if page is self.page or page in self._own_pages or self._opening_own:
            self._own_pages.add(page)
            return
        self._held.add(page)
        self._spawn(self._expire_held(page))

    async def _expire_held(self, page: Any) -> None:
        await asyncio.sleep(POPUP_HOLD_TIMEOUT)
        if page in self._held:  # never navigated anywhere useful (about:blank tab-under, ...)
            self._held.discard(page)
            with contextlib.suppress(Exception):
                await page.close()

    def _popup_verdict(self, url: str, opener: str) -> str:
        """"block" (ad / policy / site always blocked), "allow" or "ask"."""
        st = self._settings()
        if self.adblock_enabled and self.filters is not None and self.filters.is_popup_ad(url, opener):
            return "block"
        if st.popup_policy == "block" or adblock.host_in(adblock.hostname(opener), st.popup_blocked_hosts):
            return "block"
        return "allow" if st.popup_policy == "allow" else "ask"

    async def _on_popup_binding(self, source: Any, url: str) -> None:
        """window.open / target=_blank reported by the in-page guard (no real tab was created)."""
        if self.closed or not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return
        opener = self.url
        if sniff.classify(url):  # a popup pointing straight at media: capture it, never open it
            with contextlib.suppress(Exception):
                self._spawn(self._capture_url(url, opener))
        verdict = self._popup_verdict(url, opener)
        if verdict == "block":
            log.info("popup blocked: %s", url)
            self._count_blocked()
        elif verdict == "allow":
            self._allowed_urls.add(url)
            page = await self._new_own_page()
            await self._switch_to(page, goto=url)
        else:
            self._add_pending(url, opener, "popup")

    async def _capture_url(self, url: str, page_url: str) -> None:
        key = sniff.stream_key(url)
        if key in self._seen_urls:
            return
        kind = sniff.classify(url)
        if not kind:
            return
        self._seen_urls.add(key)
        stream = CapturedStream(
            id=uuid.uuid4().hex[:12],
            url=url,
            mime_type=sniff.mime_for(url, kind, None),
            kind=kind,  # type: ignore[arg-type]
            page_url=page_url,
            headers={"Referer": page_url},
            title=self.title,
            score=sniff.score(url, kind),
        )
        self.captured.append(stream)
        self._broadcast({"type": "captured", "data": stream.model_dump(mode="json")})
        await self._enrich(stream)

    async def _decide_new_popup(self, route: Any, page: Any, url: str) -> None:
        """A real popup tab (guard bypassed) started loading ``url`` (already sniffed): apply the policy."""
        self._held.discard(page)
        opener = self.url
        verdict = self._popup_verdict(url, opener)
        if verdict == "allow":
            with contextlib.suppress(Exception):
                await route.continue_()
            self._own_pages.add(page)
            self._spawn(self._switch_to(page))
            return
        await self._abort(route)
        if page is not None:
            with contextlib.suppress(Exception):
                await page.close()
        if verdict == "block":
            log.info("popup blocked: %s", url)
            self._count_blocked()
        else:
            self._add_pending(url, opener, "popup")

    def _add_pending(self, url: str, opener: str, kind: str) -> None:
        for req, _ in self.pending_popups.values():
            if req.url == url:
                return
        req = PopupRequest(
            id=uuid.uuid4().hex[:10], url=url, host=adblock.hostname(url) or url, opener_url=opener
        )
        self.pending_popups[req.id] = (req, kind)
        while len(self.pending_popups) > MAX_PENDING_POPUPS:
            self.pending_popups.pop(next(iter(self.pending_popups)))
        self._broadcast({"type": "popup", "data": req.model_dump(mode="json")})
        self._broadcast_session()

    async def decide_popup(self, popup_id: str, decision: str) -> None:
        self.touch()
        entry = self.pending_popups.pop(popup_id, None)
        if entry is None:
            raise AppError(404, "Popup request not found", "popup_not_found")
        req, kind = entry
        if decision == "open":
            self._allowed_urls.add(req.url)
            if kind == "navigation":
                await self.navigate(req.url)
            else:
                page = await self._new_own_page()
                await self._switch_to(page, goto=req.url)
        elif decision == "block_always" and self._update_settings is not None:
            host = adblock.hostname(req.opener_url)
            st = self._settings()
            if host and not adblock.host_in(host, st.popup_blocked_hosts):
                self._update_settings({"popup_blocked_hosts": sorted({*st.popup_blocked_hosts, host})})
        self._broadcast_session()

    async def _switch_to(self, page: Any, goto: str | None = None) -> None:
        """Make ``page`` (an allowed popup) the visible page; the old one is closed."""
        old = self.page
        if old is page:
            return
        await self._attach(page)
        if goto:
            self._nav_allowed_until = time.monotonic() + NAV_TIMEOUT_MS / 1000
            with contextlib.suppress(Exception):
                await page.goto(goto, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            self._nav_allowed_until = time.monotonic() + NAV_GRACE
        else:
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
        await self._refresh_meta()
        self._broadcast_session()
        if old is not None:
            self._own_pages.discard(old)
            with contextlib.suppress(Exception):
                await old.close()

    async def stop_media(self) -> None:
        """Pause/mute every <video>/<audio> in every frame of the visible page."""
        for frame in list(getattr(self.page, "frames", None) or [self.page]):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(frame.evaluate(STOP_MEDIA_JS), 2)

    # ------------------------------------------------------------ input
    async def handle_input(self, msg: dict[str, Any]) -> None:
        self.touch()
        page = self.page
        kind = msg.get("type")
        if kind == "popup_decision":
            decision = msg.get("decision")
            if decision in ("open", "block", "block_always"):
                with contextlib.suppress(AppError):
                    await self.decide_popup(str(msg.get("id")), decision)
            return
        if kind == "stop_media":
            await self.stop_media()
            return
        if kind in ("click", "tap", "key", "text"):
            self._last_input = time.monotonic()
        try:
            if kind == "click":
                await page.mouse.click(float(msg["x"]), float(msg["y"]), button=msg.get("button") or "left")
            elif kind == "tap":
                x, y = float(msg["x"]), float(msg["y"])
                try:
                    if not self.mobile:
                        raise RuntimeError("no touch")
                    await page.touchscreen.tap(x, y)
                except Exception:
                    await page.mouse.click(x, y)
            elif kind == "scroll":
                await page.mouse.move(float(msg.get("x", 0)), float(msg.get("y", 0)))
                await page.mouse.wheel(float(msg.get("dx", 0)), float(msg.get("dy", 0)))
            elif kind == "key":
                await page.keyboard.press(str(msg["key"]))
            elif kind == "text":
                await page.keyboard.type(str(msg["text"]))
            elif kind == "mousemove":
                await page.mouse.move(float(msg["x"]), float(msg["y"]))
            else:
                return
        except (KeyError, TypeError, ValueError):
            log.debug("bad browser input %s", msg)
        except Exception as exc:
            log.info("browser input failed: %s", exc)

    # ------------------------------------------------------------ sniffing
    def _on_response(self, response: Any) -> None:
        with contextlib.suppress(Exception):
            ct = response.headers.get("content-type")
            self._on_request(response.request, ct)

    def _on_request(self, request: Any, content_type: str | None) -> None:
        try:
            url = request.url
        except Exception:
            return
        kind = sniff.classify(url, content_type)
        if not kind or sniff.is_segment(url, content_type):
            return
        key = sniff.stream_key(url)  # LL-HLS reloads / token refreshes are the same stream
        if key in self._seen_urls:
            return
        frame_url = ""
        with contextlib.suppress(Exception):
            frame_url = request.frame.url or ""
        host = urlsplit(url).netloc.lower()
        ct = (content_type or "").split(";")[0].strip().lower()
        if kind in ("hls", "dash"):
            self._manifest_frames.add(frame_url)
            self._manifest_hosts.add(host)
        elif frame_url in self._manifest_frames:
            # progressive hit (hash-named .ts, fMP4 part, video/mp2t behind ?id=) in a frame
            # that is already playing an HLS/DASH manifest: one of its segments
            return
        elif ct in sniff.SEGMENT_CTS and host in self._manifest_hosts:
            # segment-typed body from the host serving a manifest, fetched outside the player frame
            # (worker / service worker / sibling frame), often disguised (``/1794557807184.json``)
            return
        self._seen_urls.add(key)
        self._spawn(self._capture(request, url, kind, content_type))

    async def _capture(self, request: Any, url: str, kind: str, content_type: str | None) -> None:
        headers = await request_headers(request, self.context)
        frame_url = None
        with contextlib.suppress(Exception):
            frame_url = request.frame.url
        page_url = self.url if self.url != "about:blank" else (frame_url or url)
        with contextlib.suppress(Exception):
            self.title = (await self.page.title()) or self.title
        stream = CapturedStream(
            id=uuid.uuid4().hex[:12],
            url=url,
            mime_type=sniff.mime_for(url, kind, content_type),
            kind=kind,  # type: ignore[arg-type]
            page_url=page_url,
            frame_url=frame_url if frame_url != page_url else None,
            headers=headers,
            title=self.title,
            score=sniff.score(url, kind),
        )
        if self.preview is not None:
            with contextlib.suppress(Exception):
                stream.preview_url = self.preview(url, headers)
        self.captured.append(stream)
        pruned = len(self.captured) > MAX_CAPTURED
        if pruned:
            self.captured.sort(key=lambda c: c.score, reverse=True)
            del self.captured[MAX_CAPTURED:]
        kept = any(c is stream for c in self.captured)
        if kept:
            self._broadcast({"type": "captured", "data": stream.model_dump(mode="json")})
        if pruned:
            # viewers drop the ids missing from this snapshot (Cast/Queue on them would 404)
            self._broadcast_session()
        if kept:
            await self._enrich(stream)

    async def _enrich(self, stream: CapturedStream) -> None:
        """Probe quality/live and grab a thumbnail, then re-broadcast the stream."""
        if stream.kind == "hls" and self.hls_probe is not None:
            with contextlib.suppress(Exception):
                info = await self.hls_probe(stream.url, stream.headers)
                stream.is_master = info.is_master
                stream.is_live = info.is_live
                if info.height:
                    stream.width, stream.height = info.width, info.height
        thumb, vw, vh = await self._thumbnail()
        if thumb:
            stream.thumbnail = thumb
        if not stream.height and vh:
            stream.width, stream.height = vw, vh
        stream.quality = quality_label(stream.height) if stream.height else None
        stream.score = sniff.score(
            stream.url, stream.kind, stream.is_master, stream.height, None, stream.is_live
        )
        if stream in self.captured:
            self._broadcast({"type": "captured", "data": stream.model_dump(mode="json")})
            self._broadcast_session()

    async def _thumbnail(self) -> tuple[str | None, int | None, int | None]:
        self._capturing += 1
        try:
            return await self._capture_thumbnail()
        finally:
            self._capturing -= 1
            if not self._capturing:
                await self._refresh_screencast()

    async def _capture_thumbnail(self) -> tuple[str | None, int | None, int | None]:
        page = self.page
        vw = vh = None
        data: bytes | None = None
        with contextlib.suppress(Exception):
            rect = await asyncio.wait_for(page.evaluate(LARGEST_VIDEO_JS), 2)
            if rect:
                vw, vh = rect.get("vw") or None, rect.get("vh") or None
                data = await asyncio.wait_for(
                    page.screenshot(
                        type="jpeg",
                        quality=50,
                        clip={k: rect[k] for k in ("x", "y", "width", "height")},
                    ),
                    3,
                )
        if data and len(data) <= THUMB_MAX_BYTES:
            return "data:image/jpeg;base64," + base64.b64encode(data).decode(), vw, vh
        # fallback: a low-quality viewport shot, then the last screencast frame, both capped
        shot: bytes | None = None
        with contextlib.suppress(Exception):
            shot = await asyncio.wait_for(page.screenshot(type="jpeg", quality=30, scale="css"), 3)
        if shot and len(shot) <= THUMB_MAX_BYTES:
            return "data:image/jpeg;base64," + base64.b64encode(shot).decode(), vw, vh
        frame = (self._last_frame or {}).get("data") or ""
        if frame and len(frame) * 3 // 4 <= THUMB_MAX_BYTES:
            return "data:image/jpeg;base64," + frame, vw, vh
        return None, vw, vh


class BrowserManager:
    def __init__(
        self,
        provider: BrowserProvider | None,
        *,
        max_sessions: int = 2,
        idle_timeout: float = 600.0,
        hls_probe: HlsProbe | None = None,
        preview: PreviewRegistrar | None = None,
        filters: adblock.FilterManager | None = None,
        settings: SettingsGetter | None = None,
        update_settings: SettingsUpdater | None = None,
    ) -> None:
        self.provider = provider
        self.filters = filters
        self.settings = settings
        self.update_settings = update_settings
        self.max_sessions = max_sessions
        self.idle_timeout = idle_timeout
        self.hls_probe = hls_probe
        self.preview = preview
        self.sessions: dict[str, RemoteBrowserSession] = {}
        self._reaper: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_loop(), name="browser-reaper")

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, min(30.0, self.idle_timeout / 4)))
            await self.reap_idle()

    async def reap_idle(self) -> int:
        now = time.monotonic()
        closed = 0
        for s in list(self.sessions.values()):
            if not s.has_subscribers and now - s.last_activity > self.idle_timeout:
                log.info("closing idle browser session %s", s.id)
                await self.close(s.id)
                closed += 1
        return closed

    async def create(self, url: str, viewport: Viewport | None = None) -> RemoteBrowserSession:
        if self.provider is None:
            raise AppError(503, "Remote browser is disabled (ENABLE_PLAYWRIGHT=false)", "browser_disabled")
        async with self._lock:
            if len(self.sessions) >= self.max_sessions:
                # free idle ones first
                await self.reap_idle()
            if len(self.sessions) >= self.max_sessions:
                raise AppError(
                    429,
                    f"Too many browser sessions (max {self.max_sessions}): close one first",
                    "browser_limit",
                    params={"max": self.max_sessions},
                )
            vp = viewport or Viewport()
            try:
                context = await self.provider.new_context(vp.width, vp.height, vp.width < 800)
            except Exception as exc:
                raise AppError(503, f"Could not start the browser: {exc}", "browser_unavailable") from exc
            session = RemoteBrowserSession(
                uuid.uuid4().hex[:12],
                context,
                vp,
                hls_probe=self.hls_probe,
                preview=self.preview,
                filters=self.filters,
                settings=self.settings,
                update_settings=self.update_settings,
            )
            self.sessions[session.id] = session
        try:
            await session.start(url)
        except Exception as exc:
            await self.close(session.id)
            raise AppError(502, f"Could not open the page: {exc}", "browser_error") from exc
        return session

    def get(self, session_id: str) -> RemoteBrowserSession:
        s = self.sessions.get(session_id)
        if s is None:
            raise AppError(404, "Browser session not found", "session_not_found")
        return s

    def list(self) -> list[RemoteBrowserSession]:
        return sorted(self.sessions.values(), key=lambda s: s.created_at)

    async def close(self, session_id: str) -> None:
        s = self.sessions.pop(session_id, None)
        if s is not None:
            await s.close()

    async def shutdown(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        for sid in list(self.sessions):
            await self.close(sid)
