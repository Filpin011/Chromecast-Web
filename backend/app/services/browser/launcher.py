"""Lazily-started shared Playwright Chromium."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, Protocol

from app.services.net import DESKTOP_UA as DESKTOP_UA  # re-exported

log = logging.getLogger(__name__)

LOCALE = "it-IT"
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Mobile Safari/537.36"
)
STEALTH_JS = """
Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['it-IT', 'it', 'en'] });
// Anti-devtools scripts (e.g. "disable-devtool", which redirects to about:blank) detect the CDP connection
// Playwright keeps open: the attached inspector serialises console arguments, firing getters on logged
// objects and slowing console.table down measurably. Nothing here reads page console output, so turn the
// console methods into no-ops that still look native.
(() => {
  const toString = Function.prototype.toString;
  for (const k of ['log', 'debug', 'info', 'warn', 'error', 'table', 'dir', 'dirxml', 'clear', 'trace',
                   'group', 'groupCollapsed', 'groupEnd', 'count', 'countReset', 'time', 'timeLog', 'timeEnd',
                   'profile', 'profileEnd', 'assert']) {
    const orig = console[k];
    if (typeof orig !== 'function') continue;
    const noop = function () {};
    try {
      Object.defineProperty(noop, 'name', { value: k });
      Object.defineProperty(noop, 'toString', { value: toString.bind(orig) });
      console[k] = noop;
    } catch (e) {}
  }
})();
"""
# The full Chromium in "new" headless mode, not chromium-headless-shell: the shell's brand
# is "HeadlessChrome", which no UA override hides from the Sec-CH-UA client hints or
# navigator.userAgentData (every frame, worker and popup). Full Chromium reports the same
# brands as a regular desktop Chromium.
CHROMIUM_CHANNEL = "chromium"
CHROMIUM_ARGS = [
    "--autoplay-policy=no-user-gesture-required",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    # background services a remote viewer never uses (no effect on pages, players or capture)
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,MediaRouter,OptimizationHints,InterestFeedContentSuggestions",
    # the screencast carries no sound: decode audio as usual (players keep working), output none
    "--mute-audio",
    # headless Chromium screencasts at 1x whatever the context's device_scale_factor: rasterize at 2x
    # so frames can be sharp on retina phones/tablets; each session's screencast maxWidth/maxHeight
    # (viewport x Viewport.scale) scales them back down for 1x viewers
    "--force-device-scale-factor=2",
]
# Chromium is closed once no context (remote-browser session or page probe) has been open for
# this long, and launched again on the next request (~1-2 s).
BROWSER_IDLE_SHUTDOWN = 60.0


class BrowserProvider(Protocol):
    async def new_context(self, width: int, height: int, mobile: bool, scale: float = 1.0) -> Any: ...
    async def close(self) -> None: ...


class PlaywrightProvider:
    """Owns one Playwright + Chromium instance; each caller gets its own context."""

    def __init__(self, idle_shutdown: float = BROWSER_IDLE_SHUTDOWN) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()
        self.idle_shutdown = idle_shutdown
        self._open_contexts = 0
        self._idle_timer: asyncio.TimerHandle | None = None

    async def _ensure(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright

            if self._pw is None:
                self._pw = await async_playwright().start()
            started = time.monotonic()
            self._browser = await self._pw.chromium.launch(
                headless=True, channel=CHROMIUM_CHANNEL, args=CHROMIUM_ARGS
            )
            log.info("chromium started in %.1fs", time.monotonic() - started)
            return self._browser

    def _user_agent(self, mobile: bool) -> str:
        """Realistic UA matching the real Chromium major version (no "HeadlessChrome")."""
        ua = MOBILE_UA if mobile else DESKTOP_UA
        try:
            major = str(self._browser.version).split(".")[0]
            if major.isdigit():
                ua = ua.replace("Chrome/130.0.0.0", f"Chrome/{major}.0.0.0")
        except Exception:  # pragma: no cover
            pass
        return ua

    async def new_context(self, width: int, height: int, mobile: bool, scale: float = 1.0) -> Any:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        self._open_contexts += 1
        try:
            browser = await self._ensure()
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                user_agent=self._user_agent(mobile),
                is_mobile=mobile,
                has_touch=mobile,
                device_scale_factor=scale,
                locale=LOCALE,
                timezone_id="Europe/Rome",
                ignore_https_errors=True,
                extra_http_headers={"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"},
            )
        except BaseException:
            self._context_closed()
            raise
        context.on("close", lambda *_: self._context_closed())
        await context.add_init_script(STEALTH_JS)
        return context

    def _context_closed(self) -> None:
        self._open_contexts = max(0, self._open_contexts - 1)
        if self._open_contexts or self._browser is None or self.idle_shutdown <= 0:
            return
        with contextlib.suppress(RuntimeError):
            loop = asyncio.get_running_loop()
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_timer = loop.call_later(self.idle_shutdown, lambda: asyncio.ensure_future(self._idle_close()))

    async def _idle_close(self) -> None:
        self._idle_timer = None
        async with self._lock:
            if self._open_contexts or self._browser is None:
                return
            browser, self._browser = self._browser, None
        log.info("chromium closed: no page open for %.0fs", self.idle_shutdown)
        with contextlib.suppress(Exception):
            await browser.close()

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:  # pragma: no cover
                    pass
                self._browser = None
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:  # pragma: no cover
                    pass
                self._pw = None
