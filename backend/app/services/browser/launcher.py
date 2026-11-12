"""Lazily-started shared Playwright Chromium."""

from __future__ import annotations

import asyncio
import logging
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
]


class BrowserProvider(Protocol):
    async def new_context(self, width: int, height: int, mobile: bool) -> Any: ...
    async def close(self) -> None: ...


class PlaywrightProvider:
    """Owns one Playwright + Chromium instance; each caller gets its own context."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright

            if self._pw is None:
                self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True, channel=CHROMIUM_CHANNEL, args=CHROMIUM_ARGS
            )
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

    async def new_context(self, width: int, height: int, mobile: bool) -> Any:
        browser = await self._ensure()
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            user_agent=self._user_agent(mobile),
            is_mobile=mobile,
            has_touch=mobile,
            device_scale_factor=1,
            locale=LOCALE,
            timezone_id="Europe/Rome",
            ignore_https_errors=True,
            extra_http_headers={"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"},
        )
        await context.add_init_script(STEALTH_JS)
        return context

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
