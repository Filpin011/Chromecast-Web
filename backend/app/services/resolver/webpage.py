"""Extract a playable stream from a (JavaScript-heavy) web page with a real Chromium.

Per docs/ARCHITECTURE.md ("Dynamic / JavaScript-heavy pages") we never regex the static
HTML: the page is loaded in Playwright, playback is kicked (play buttons / largest player
clicked in *every* frame), and media is detected at the network layer of the whole
context (all frames, nested iframes, workers, popups), with ``<video>.currentSrc`` in every
frame as a fallback. The request headers actually sent (iframe Referer/Origin, Cookie, UA)
are kept so the stream can be replayed through the proxy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.services.browser.launcher import BrowserProvider
from app.services.proxy import hls
from app.services.resolver import sniff

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 25.0
SETTLE_SECONDS = 1.5
PROGRESSIVE_GRACE = 4.0
CLICK_EVERY = 2.0
MAX_CLICK_ROUNDS = 6

PLAY_SELECTORS = [
    ".vjs-big-play-button",
    ".jw-icon-playback",
    ".jw-icon-display",
    ".jw-display-icon-container",
    ".plyr__control--overlaid",
    ".fp-play",
    ".mejs__overlay-button",
    ".ytp-large-play-button",
    "[aria-label*='play' i]",
    "button[title*='play' i]",
    "button[class*='play' i]",
    "[class*='play-button' i]",
    "[class*='playButton' i]",
    "[class*='btn-play' i]",
    "[id*='play' i]",
]

CLICK_PLAY_JS = """
(selectors) => {
  for (const v of document.querySelectorAll('video')) {
    try { v.muted = true; const p = v.play(); if (p && p.catch) p.catch(() => {}); } catch (e) {}
  }
  for (const s of selectors) {
    let els = [];
    try { els = document.querySelectorAll(s); } catch (e) { continue; }
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        try { el.click(); return s; } catch (e) {}
      }
    }
  }
  return null;
}
"""

LARGEST_PLAYER_JS = """
() => {
  let best = null, area = 0;
  for (const el of document.querySelectorAll('video, iframe, object, embed, [class*=player i]')) {
    const r = el.getBoundingClientRect();
    const a = r.width * r.height;
    if (a > area && r.width > 80 && r.height > 60) { area = a; best = r; }
  }
  return best ? {x: best.x + best.width / 2, y: best.y + best.height / 2} : null;
}
"""

VIDEO_SRC_JS = """
() => Array.from(document.querySelectorAll('video, video source, audio'))
  .map(v => v.currentSrc || v.src || '')
  .filter(u => u && /^https?:/i.test(u))
"""

PAGE_META_JS = """
() => {
  const m = (sel) => { const el = document.querySelector(sel); return el ? el.content : null; };
  return {
    title: m('meta[property="og:title"]') || document.title || null,
    image: m('meta[property="og:image"]') || m('meta[name="twitter:image"]') || null,
  };
}
"""

NO_STREAM_HINT = (
    "No video stream found on the page. Open it in the interactive browser "
    "to click through manually."
)


@dataclass
class WebpageFind:
    url: str
    kind: str
    mime_type: str
    headers: dict[str, str] = field(default_factory=dict)
    title: str | None = None
    thumbnail: str | None = None
    is_master: bool | None = None
    is_live: bool | None = None


@dataclass
class _Found:
    url: str
    kind: str
    content_type: str | None
    headers: dict[str, str] = field(default_factory=dict)
    is_master: bool | None = None
    is_live: bool | None = None
    found_at: float = field(default_factory=time.monotonic)

    @property
    def score(self) -> float:
        return sniff.score(self.url, self.kind, self.is_master, None, None, self.is_live)


def dedupe_key(url: str) -> str:
    """URL identity without volatile query params (tokens, timestamps)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


async def request_headers(request: Any, context: Any = None) -> dict[str, str]:
    """All request headers actually sent (incl. Cookie) for a Playwright request."""
    headers: dict[str, str] = {}
    try:
        headers = dict(await request.all_headers())
    except Exception:
        with contextlib.suppress(Exception):
            headers = dict(request.headers)
    if context is not None and not any(k.lower() == "cookie" for k in headers):
        with contextlib.suppress(Exception):
            cookies = await context.cookies([request.url])
            if cookies:
                headers["cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return {k: v for k, v in headers.items() if not k.startswith(":")}


# Border + padding of an <iframe>: its document starts inside them, not at the border box.
IFRAME_INSET_JS = """e => { const cs = getComputedStyle(e);
  return {x: e.clientLeft + parseFloat(cs.paddingLeft || '0'),
          y: e.clientTop + parseFloat(cs.paddingTop || '0')}; }"""


async def _frame_offset(frame: Any) -> tuple[float, float]:
    """Top-left of ``frame``'s viewport in main-page coordinates.

    Playwright's ``bounding_box()`` is already relative to the main frame, even for an
    <iframe> nested several levels deep: only the deepest iframe element is measured
    (adding its ancestors' boxes would count every outer offset twice).
    """
    if getattr(frame, "parent_frame", None) is None:
        return 0.0, 0.0
    el = await frame.frame_element()
    box = await el.bounding_box()
    if not box:
        return 0.0, 0.0
    inset = {"x": 0.0, "y": 0.0}
    with contextlib.suppress(Exception):
        inset = await el.evaluate(IFRAME_INSET_JS)
    return box["x"] + inset["x"], box["y"] + inset["y"]


async def click_play(page: Any) -> None:
    """Try hard to start playback in every frame: known buttons, then a real click on the player."""
    frames = list(getattr(page, "frames", None) or [page])
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")  # dismiss simple overlays/modals
    for frame in frames:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(frame.evaluate(CLICK_PLAY_JS, PLAY_SELECTORS), 2)
    for frame in frames:
        with contextlib.suppress(Exception):
            pos = await asyncio.wait_for(frame.evaluate(LARGEST_PLAYER_JS), 2)
            if not pos:
                continue
            ox, oy = await asyncio.wait_for(_frame_offset(frame), 2)
            await page.mouse.click(ox + pos["x"], oy + pos["y"])


async def video_sources(page: Any) -> list[tuple[str, str]]:
    """(src, frame_url) of every <video> with an http(s) source, in every frame."""
    out: list[tuple[str, str]] = []
    for frame in list(getattr(page, "frames", None) or [page]):
        with contextlib.suppress(Exception):
            srcs = await asyncio.wait_for(frame.evaluate(VIDEO_SRC_JS), 2)
            out.extend((s, frame.url) for s in srcs or [])
    return out


class _Collector:
    """Network-layer media sniffer for one browser context."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self.found: dict[str, _Found] = {}
        self.tasks: set[asyncio.Task[Any]] = set()

    def _spawn(self, coro: Any) -> None:
        t = asyncio.ensure_future(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    def on_request(self, request: Any) -> None:
        self.consider(request, None, None)

    def on_response(self, response: Any) -> None:
        ct = None
        with contextlib.suppress(Exception):
            ct = response.headers.get("content-type")
        self.consider(response.request, ct, response)

    def consider(self, request: Any, content_type: str | None, response: Any) -> None:
        try:
            url = request.url
        except Exception:
            return
        kind = sniff.classify(url, content_type)
        if not kind or sniff.is_segment(url, content_type) or sniff.is_ad(url):
            return
        key = dedupe_key(url)
        f = self.found.get(key)
        if f is None:
            f = _Found(url=url, kind=kind, content_type=content_type)
            self.found[key] = f
            self._spawn(self._headers(f, request))
        elif content_type and not f.content_type:
            f.content_type, f.kind = content_type, kind
        if response is not None and f.kind == "hls" and f.is_master is None:
            self._spawn(self._inspect_hls(f, response))

    def add_video_src(self, url: str, frame_url: str, user_agent: str | None) -> None:
        kind = sniff.classify(url) or "progressive"
        key = dedupe_key(url)
        if key in self.found or sniff.is_ad(url):
            return
        headers = {"Referer": frame_url}
        if user_agent:
            headers["User-Agent"] = user_agent
        self.found[key] = _Found(url=url, kind=kind, content_type=None, headers=headers)

    async def _headers(self, f: _Found, request: Any) -> None:
        f.headers = await request_headers(request, self.context)

    @staticmethod
    async def _inspect_hls(f: _Found, response: Any) -> None:
        with contextlib.suppress(Exception):
            text = await response.text()
            if text.lstrip("\ufeff \r\n\t").startswith("#EXTM3U"):
                f.is_master = hls.is_master_playlist(text)
                if not f.is_master:
                    f.is_live = hls.is_live_media_playlist(text)

    def best(self) -> _Found | None:
        if not self.found:
            return None
        return max(self.found.values(), key=lambda f: (f.score, -f.found_at))

    def has_adaptive(self) -> bool:
        return any(f.kind in ("hls", "dash") for f in self.found.values())

    async def settle(self) -> None:
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=3)


async def _close_popup_later(popup: Any, delay: float = 3.0) -> None:
    """Ad popups: let them run briefly (their traffic is sniffed), then close."""
    await asyncio.sleep(delay)
    with contextlib.suppress(Exception):
        await popup.close()


async def browser_extract(
    provider: BrowserProvider, url: str, timeout: float = DEFAULT_TIMEOUT, *, filters: Any = None
) -> WebpageFind | None:
    context = await provider.new_context(1280, 720, False)
    collector = _Collector(context)
    main_page: Any = None
    if filters is not None:
        from app.services import adblock

        def on_stream(request: Any, req_url: str) -> bool:
            # sniffed before any abort decision; ad pre-rolls fall through to the filters
            if sniff.classify(req_url) and not sniff.is_ad(req_url):
                collector.on_request(request)
                return True
            return False

        async def on_popup(_source: Any, popup_url: str) -> None:
            # window.open is neutralised (no tab is created); a popup pointing at media is still a find
            if isinstance(popup_url, str) and sniff.classify(popup_url) and not sniff.is_ad(popup_url):
                collector.add_video_src(popup_url, main_page.url if main_page is not None else url, None)

        with contextlib.suppress(Exception):
            await adblock.install(
                context,
                filters,
                adblock.Hooks(enabled=lambda: True, on_stream=on_stream, on_blocked=lambda _u: None),
            )
            await context.expose_binding("__cwPopup", on_popup)
            await context.add_init_script(adblock.POPUP_GUARD_JS)
    popup_tasks: list[asyncio.Task[None]] = []

    def on_page(p: Any) -> None:
        if main_page is not None and p is not main_page:
            popup_tasks.append(asyncio.ensure_future(_close_popup_later(p)))

    context.on("request", collector.on_request)
    context.on("response", collector.on_response)
    context.on("page", on_page)
    try:
        main_page = page = await context.new_page()
        with contextlib.suppress(Exception):
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        user_agent = None
        with contextlib.suppress(Exception):
            user_agent = await page.evaluate("() => navigator.userAgent")
        deadline = time.monotonic() + timeout
        rounds = 0
        last_click = 0.0
        first_progressive: float | None = None
        while time.monotonic() < deadline:
            if collector.has_adaptive():
                await asyncio.sleep(SETTLE_SECONDS)  # let master/variants settle
                break
            if collector.found:
                first_progressive = first_progressive or time.monotonic()
                if time.monotonic() - first_progressive > PROGRESSIVE_GRACE:
                    break
            if rounds < MAX_CLICK_ROUNDS and time.monotonic() - last_click >= CLICK_EVERY:
                rounds += 1
                last_click = time.monotonic()
                await click_play(page)
                for src, frame_url in await video_sources(page):
                    collector.add_video_src(src, frame_url, user_agent)
            await asyncio.sleep(0.25)
        await collector.settle()
        best = collector.best()
        if best is None:
            return None
        meta: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            meta = await asyncio.wait_for(page.evaluate(PAGE_META_JS), 3) or {}
        return WebpageFind(
            url=best.url,
            kind=best.kind,
            mime_type=sniff.mime_for(best.url, best.kind, best.content_type),
            headers=best.headers,
            title=meta.get("title") or None,
            thumbnail=meta.get("image") or None,
            is_master=best.is_master,
            is_live=best.is_live,
        )
    finally:
        for t in popup_tasks:
            t.cancel()
        for t in list(collector.tasks):
            t.cancel()
        with contextlib.suppress(Exception):
            await context.close()
