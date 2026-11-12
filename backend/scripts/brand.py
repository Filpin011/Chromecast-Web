"""Render the app icons and the social preview from the SVG sources in docs/assets.

    make brand          # = cd backend && .venv/bin/python scripts/brand.py

Sources (hand-written, original artwork): ``docs/assets/icon.svg`` (rounded app icon) and
``docs/assets/icon-maskable.svg`` (full-bleed, mark inside the 80% safe zone). Rendered with the
Playwright Chromium already used by the backend; ``favicon.ico`` and PNG optimisation need Pillow
(``make brand`` installs it into backend/.venv, it is not a runtime dependency).
"""

from __future__ import annotations

import asyncio
import base64
import io
import shutil
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
PUBLIC_ICONS = ROOT / "frontend" / "public" / "icons"
APP_DIR = ROOT / "frontend" / "src" / "app"

TAGLINE = "Cast live streams, IPTV playlists and web videos to your TV — from any phone on your home network."
CHIPS = ["Live HLS / DASH", "IPTV playlists", "Remote browser", "Ad blocking", "yt-dlp", "Real-time sync"]


def _data_url(svg: Path) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.read_bytes()).decode()


async def _render_svg(page: Page, svg: Path, size: int) -> bytes:
    await page.set_viewport_size({"width": size, "height": size})
    await page.set_content(
        "<html><body style='margin:0;background:transparent'>"
        f"<img src='{_data_url(svg)}' width='{size}' height='{size}' style='display:block'></body></html>"
    )
    await page.wait_for_load_state("load")
    return await page.screenshot(omit_background=True)


def _social_html(icon: Path) -> str:
    chips = "".join(f"<span class='chip'>{c}</span>" for c in CHIPS)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;width:1280px;height:640px;overflow:hidden}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Inter","Segoe UI",Roboto,sans-serif;
    color:#f4f3ff;background:#0d0d14;position:relative}}
  .bg{{position:absolute;inset:0;background:
    radial-gradient(900px 520px at 12% 20%,rgba(122,104,255,.38),transparent 60%),
    radial-gradient(700px 480px at 95% 110%,rgba(65,40,201,.45),transparent 60%),
    linear-gradient(135deg,#12111f 0%,#0b0b12 100%)}}
  .grid{{position:absolute;inset:0;opacity:.07;background-image:
    linear-gradient(#fff 1px,transparent 1px),linear-gradient(90deg,#fff 1px,transparent 1px);
    background-size:48px 48px;mask-image:radial-gradient(circle at 70% 40%,#000,transparent 70%)}}
  .wrap{{position:absolute;inset:0;display:flex;align-items:center;gap:64px;padding:0 104px}}
  img{{width:248px;height:248px;filter:drop-shadow(0 24px 48px rgba(80,60,230,.55))}}
  h1{{font-size:88px;line-height:1;margin:0 0 22px;font-weight:800;letter-spacing:-2.5px}}
  p{{font-size:30px;line-height:1.35;margin:0 0 30px;color:#c9c6e6;max-width:760px}}
  .chips{{display:flex;flex-wrap:wrap;gap:12px;max-width:780px}}
  .chip{{font-size:20px;padding:8px 16px;border-radius:999px;background:rgba(255,255,255,.08);
    border:1px solid rgba(255,255,255,.14);color:#e7e5ff}}
</style></head><body><div class="bg"></div><div class="grid"></div>
<div class="wrap"><img src="{_data_url(icon)}" alt="">
<div><h1>Chromecast Web</h1><p>{TAGLINE}</p><div class="chips">{chips}</div></div></div></body></html>"""


def optimise_png(data: bytes, colors: int = 256) -> bytes:
    """Shrink a PNG like pngquant: opaque images get a dithered 256-colour palette (no banding on
    gradients), images with transparency are re-encoded losslessly."""
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    out = io.BytesIO()
    if img.getextrema()[3][0] == 255:
        rgb = img.convert("RGB")
        palette = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        rgb.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG).save(out, format="PNG", optimize=True)
    else:
        img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  {path.relative_to(ROOT)}  ({len(data) // 1024} KB)")


async def main() -> None:
    from PIL import Image

    icon, maskable = ASSETS / "icon.svg", ASSETS / "icon-maskable.svg"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        for size in (192, 512):
            write(PUBLIC_ICONS / f"icon-{size}.png", optimise_png(await _render_svg(page, icon, size)))
            write(PUBLIC_ICONS / f"icon-maskable-{size}.png", optimise_png(await _render_svg(page, maskable, size)))
        # iOS masks the icon itself and shows transparent corners as black: use the full-bleed art
        write(PUBLIC_ICONS / "apple-touch-icon.png", optimise_png(await _render_svg(page, maskable, 180)))
        write(ASSETS / "icon-256.png", optimise_png(await _render_svg(page, icon, 256)))
        ico_src = Image.open(io.BytesIO(await _render_svg(page, icon, 256)))
        buf = io.BytesIO()
        ico_src.save(buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
        write(APP_DIR / "favicon.ico", buf.getvalue())

        await page.set_viewport_size({"width": 1280, "height": 640})
        await page.set_content(_social_html(icon))
        await page.wait_for_load_state("load")
        write(ASSETS / "social-preview.png", optimise_png(await page.screenshot()))
        await browser.close()
    shutil.copyfile(icon, PUBLIC_ICONS / "icon.svg")
    print(f"  {(PUBLIC_ICONS / 'icon.svg').relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
