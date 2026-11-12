"""Take the README screenshots against the demo (scripts/demo.py) and compose docs/assets/hero.png.

    make screenshots     # builds the frontend, starts the demo on a spare port, shoots, stops it

Phone shots are 390x844 @2x, desktop 1440x900 @1x; English UI, dark theme (plus one light).
Output: docs/screenshots/*.png (palette-optimised, see brand.optimise_png) and docs/assets/hero.png.
Needs Pillow (installed by ``make screenshots``) and Playwright Chromium (``make browsers``).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import subprocess
import sys
from pathlib import Path

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from brand import ROOT, optimise_png, write  # noqa: E402
from demo import READY_LINE, resolver_rule  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1440, "height": 900}
AURORA = "http://demo-tv.example/watch/aurora-live"
POPUP = "http://demo-tv.example/watch/harbor-cup-final?popup"


class Shooter:
    def __init__(self, base: str, content_port: int) -> None:
        self.base = base
        self.content_port = content_port
        self.png: dict[str, bytes] = {}

    async def context(self, browser, *, phone: bool = True, theme: str = "dark") -> BrowserContext:
        ctx = await browser.new_context(
            viewport=PHONE if phone else DESKTOP,
            device_scale_factor=2 if phone else 1,
            is_mobile=phone,
            has_touch=phone,
            color_scheme=theme,
            locale="en-US",
            timezone_id="Europe/Rome",
        )
        await ctx.add_init_script(
            f"try{{localStorage.setItem('theme','{theme}');localStorage.setItem('cw.locale','en')}}catch(e){{}}"
        )
        return ctx

    async def goto(self, page: Page, path: str, settle: float = 1.5) -> None:
        await page.goto(self.base + path)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(settle * 1000)

    async def shot(self, page: Page, name: str) -> None:
        await page.wait_for_timeout(600)  # let sheet / panel animations finish
        data = await page.screenshot(animations="disabled", caret="hide")
        self.png[name] = data
        write(SHOTS / f"{name}.png", optimise_png(data))


async def close_browser_sessions(base: str) -> None:
    async with httpx.AsyncClient(base_url=base) as c:
        for s in (await c.get("/api/browser/sessions")).json():
            await c.delete(f"/api/browser/sessions/{s['id']}")


async def run(base: str, content_port: int) -> dict[str, bytes]:
    sh = Shooter(base, content_port)
    async with httpx.AsyncClient(base_url=base) as c:
        playlist = next(p for p in (await c.get("/api/playlists")).json() if p["name"] == "Free TV World")
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[resolver_rule(content_port)])

        # ---------------------------------------------------------------- phone, dark
        ctx = await sh.context(browser)
        page = await ctx.new_page()
        await sh.goto(page, "/")
        await sh.shot(page, "home")

        await page.get_by_label("Open player").filter(visible=True).first.click()
        await sh.shot(page, "now-playing")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        await page.get_by_label("Device: Living Room").filter(visible=True).first.click()
        await sh.shot(page, "devices")
        await page.keyboard.press("Escape")

        await sh.goto(page, f"/playlists/view/?id={playlist['id']}")
        await sh.shot(page, "playlist")

        await sh.goto(page, "/settings/")
        await sh.shot(page, "settings")

        await close_browser_sessions(base)
        await sh.goto(page, f"/browser/?url={AURORA}", settle=0)
        await page.get_by_text("1080p FHD").filter(visible=True).first.wait_for(timeout=30_000)
        await page.wait_for_timeout(2500)  # thumbnail + screencast frames
        await sh.shot(page, "browser")

        await close_browser_sessions(base)
        await page.evaluate("localStorage.removeItem('cw.browser.session')")
        await sh.goto(page, f"/browser/?url={POPUP}", settle=0)
        await page.get_by_text("The page wants to open:").filter(visible=True).first.wait_for(timeout=30_000)
        await page.wait_for_timeout(1500)
        await sh.shot(page, "popup")
        await ctx.close()
        await close_browser_sessions(base)

        # ---------------------------------------------------------------- phone, light
        ctx = await sh.context(browser, theme="light")
        page = await ctx.new_page()
        await sh.goto(page, "/")
        await page.get_by_label("Open player").filter(visible=True).first.click()
        await sh.shot(page, "now-playing-light")
        await ctx.close()

        # ---------------------------------------------------------------- desktop, dark
        ctx = await sh.context(browser, phone=False)
        page = await ctx.new_page()
        await sh.goto(page, "/")
        await sh.shot(page, "desktop-home")
        await sh.goto(page, f"/browser/?url={AURORA}", settle=0)
        await page.get_by_text("1080p FHD").filter(visible=True).first.wait_for(timeout=30_000)
        await page.wait_for_timeout(2500)
        await sh.shot(page, "desktop-browser")
        await ctx.close()
        await close_browser_sessions(base)
        await browser.close()
    return sh.png


def hero(png: dict[str, bytes], names: list[str]) -> None:
    """Three phone screenshots side by side on a subtle gradient, with rounded corners and shadows."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h, pad, gap = 2400, 1300, 140, 90
    bg = Image.new("RGB", (w, h))
    top, bottom = (24, 22, 46), (11, 11, 18)
    px = bg.load()
    for y in range(h):
        t = y / (h - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        for x in range(w):
            px[x, y] = row
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse((w * 0.15, -h * 0.4, w * 0.85, h * 0.7), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    bg = Image.composite(Image.new("RGB", (w, h), (106, 85, 240)), bg, glow)

    phone_h = h - 2 * pad
    phone_w = round(phone_h * PHONE["width"] / PHONE["height"])
    total = 3 * phone_w + 2 * gap
    x0 = (w - total) // 2
    radius = 64
    for i, name in enumerate(names):
        shot = Image.open(io.BytesIO(png[name])).convert("RGB").resize((phone_w, phone_h), Image.Resampling.LANCZOS)
        mask = Image.new("L", shot.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *shot.size), radius, fill=255)
        x = x0 + i * (phone_w + gap)
        y = pad + (0 if i == 1 else 40)
        shadow = Image.new("L", (w, h), 0)
        ImageDraw.Draw(shadow).rounded_rectangle((x, y + 30, x + phone_w, y + phone_h + 30), radius, fill=150)
        shadow = shadow.filter(ImageFilter.GaussianBlur(40))
        bg = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), bg, shadow)
        frame = Image.new("RGB", (phone_w + 16, phone_h + 16), (52, 50, 70))
        fmask = Image.new("L", frame.size, 0)
        ImageDraw.Draw(fmask).rounded_rectangle((0, 0, *frame.size), radius + 8, fill=255)
        bg.paste(frame, (x - 8, y - 8), fmask)
        bg.paste(shot, (x, y), mask)
    bg = bg.resize((w * 2 // 3, h * 2 // 3), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    bg.save(out, format="PNG")
    write(ROOT / "docs" / "assets" / "hero.png", optimise_png(out.getvalue()))


def start_demo(port: int, content_port: int) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "demo.py"), "--port", str(port), "--content-port", str(content_port),
         "--host", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print("  demo:", line.rstrip())
        if line.startswith(READY_LINE):
            return proc
    raise SystemExit("the demo exited before it was ready")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8077, help="port for the demo backend started by this script")
    ap.add_argument("--content-port", type=int, default=8765)
    ap.add_argument("--base", help="use an already running demo (e.g. http://localhost:8000) instead")
    args = ap.parse_args()
    proc = None if args.base else start_demo(args.port, args.content_port)
    try:
        png = asyncio.run(run(args.base or f"http://127.0.0.1:{args.port}", args.content_port))
        hero(png, ["now-playing", "home", "browser"])
    finally:
        if proc:
            proc.terminate()
            proc.wait(10)


if __name__ == "__main__":
    main()
