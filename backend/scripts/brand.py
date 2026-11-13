"""Render the app icons, the social preview and the TV idle image from the SVG sources in docs/assets.

    make brand          # = cd backend && .venv/bin/python scripts/brand.py
    .venv/bin/python scripts/brand.py --idle    # only the TV idle image (backend/app/static/idle.jpg)
    .venv/bin/python scripts/brand.py --banner  # only the README banners (docs/assets/banner*.jpg)

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
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
PUBLIC_ICONS = ROOT / "frontend" / "public" / "icons"
APP_DIR = ROOT / "frontend" / "src" / "app"
IDLE_IMAGE = ROOT / "backend" / "app" / "static" / "idle.jpg"

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


def _wallpaper_html(
    icon: Path,
    *,
    width: int,
    height: int,
    mark: tuple[int, int, int],
    content: str,
    css: str,
    waves_from: float | None = None,
) -> str:
    """The brand wallpaper: the logo's own motif - a screen sending ")))" - blown up to fill the frame.

    Aurora glows in the icon's violets, a bundle of thin "signal" ribbons and giant cast waves spreading
    from the mark (``mark`` = centre x, centre y, icon size) past the right edge; a light grain keeps the
    gradients free of banding once compressed. Shapes come from the seeded script below, so every render
    is identical. Shared by the TV idle image and the README banners. ``waves_from``: radius of the first
    wave (default: just around the mark), e.g. to start the waves after text placed beside the mark.
    """
    mx, my, msize = mark
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Inter","Segoe UI",Roboto,sans-serif;
    color:#f4f3ff;background:#0a0913;position:relative}}
  .layer{{position:absolute;inset:0}}
  .base{{background:linear-gradient(150deg,#110f22 0%,#0a0913 45%,#07060d 100%)}}
  .blob{{position:absolute;border-radius:50%}}
  svg.art{{position:absolute;inset:0;width:{width}px;height:{height}px}}
  .vignette{{background:radial-gradient({width * 0.78:.0f}px {height * 0.93:.0f}px at 40% 50%,transparent 55%,
    rgba(4,3,10,.75) 100%)}}
  .grain{{opacity:.09;mix-blend-mode:overlay}}
  .mark{{position:absolute;left:{mx - msize / 2:.0f}px;top:{my - msize / 2:.0f}px;width:{msize}px;height:{msize}px;
    filter:drop-shadow(0 {msize / 8:.0f}px {msize / 3.4:.0f}px rgba(90,64,240,.65))}}
  .chip{{display:inline-flex;align-items:center;border-radius:999px;background:rgba(255,255,255,.08);
    border:1px solid rgba(255,255,255,.16);color:#e7e4ff;font-weight:600}}
  .dot{{border-radius:50%;background:#9d8cff;
    box-shadow:0 0 0 .5em rgba(143,125,255,.22),0 0 1.8em rgba(143,125,255,.95)}}
  h1{{line-height:1;margin:0;font-weight:700;text-shadow:0 8px 40px rgba(20,10,60,.6)}}
  {css}
</style></head><body>
<div class="layer base"></div>
<div class="layer" id="aurora"></div>
<svg class="art" id="art" viewBox="0 0 {width} {height}"></svg>
<div class="layer vignette"></div>
<svg class="layer grain" viewBox="0 0 {width} {height}"><filter id="n"><feTurbulence type="fractalNoise"
  baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/>
  <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .9 0"/>
  </filter><rect width="{width}" height="{height}" filter="url(#n)"/></svg>
<img class="mark" src="{_data_url(icon)}" alt="">
{content}
<script>
(() => {{  // scoped: Playwright's set_content() reuses the window, a second render would redeclare these
  const W = {width}, H = {height}, cx = {mx}, cy = {my};
  const S = H / 1080;  // shapes are designed on a 1920x1080 canvas
  const X = (v) => (v * W) / 1920, Y = (v) => (v * H) / 1080;
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, parent) => {{
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    parent.appendChild(e);
    return e;
  }};
  let seed = 7;  // deterministic pseudo-random: every render is identical
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

  // aurora: soft glows in the icon's violets, one cool accent (designed on 1920x1080)
  const aurora = document.getElementById("aurora");
  for (const [x, y, w, h, c] of [
    [-320, -320, 900, 700, "rgba(143,125,255,.20)"],
    [760, 40, 1100, 980, "rgba(106,85,240,.30)"],
    [1260, -320, 900, 720, "rgba(65,40,201,.48)"],
    [1320, 600, 900, 700, "rgba(150,70,230,.26)"],
    [1560, 160, 480, 480, "rgba(80,200,255,.12)"],
    [-260, 660, 900, 620, "rgba(28,16,100,.55)"],
  ]) {{
    const b = document.createElement("div");
    b.className = "blob";
    Object.assign(b.style, {{
      left: X(x) + "px", top: Y(y) + "px", width: X(w) + "px", height: Y(h) + "px",
      background: c, filter: `blur(${{110 * Math.max(S, 0.45)}}px)`,
    }});
    aurora.appendChild(b);
  }}

  const art = document.getElementById("art");
  const defs = el("defs", {{}}, art);
  const grad = (id, stops, x2 = 1, y2 = 0) => {{
    const g = el("linearGradient", {{ id, x1: 0, y1: 0, x2, y2 }}, defs);
    for (const [o, c, a] of stops) el("stop", {{ offset: o, "stop-color": c, "stop-opacity": a }}, g);
  }};
  grad("ribbon", [[0, "#8F7DFF", 0], [0.35, "#8F7DFF", 0.55], [0.7, "#5b8cff", 0.35], [1, "#4128C9", 0]]);
  grad("wave", [[0, "#ffffff", 0.0], [0.25, "#c9c0ff", 0.55], [1, "#6A55F0", 0.0]], 0, 1);

  // signal ribbons: a bundle of thin curves sweeping up to the right, behind everything
  const ribbons = el("g", {{ fill: "none", stroke: "url(#ribbon)" }}, art);
  for (let i = 0; i < 46; i++) {{
    const t = i / 45;
    const d = `M ${{X(380)}} ${{Y(1120 + i * 4)}} C ${{X(900)}} ${{Y(860 + i * 9)}},`
      + ` ${{X(1300)}} ${{Y(1150 - i * 8)}}, ${{X(2040)}} ${{Y(560 + i * 6)}}`;
    const width = (1.1 + (i % 7 === 0 ? 1.4 : 0)) * Math.max(S, 0.6);
    el("path", {{ d, "stroke-width": width, opacity: 0.18 + 0.5 * Math.sin(Math.PI * t) }}, ribbons);
  }}

  // giant cast waves ")))" from the mark, like the logo's own arcs, until past the right edge
  const waves = el("g", {{ fill: "none", "stroke-linecap": "round" }}, art);
  const step = 150 * Math.max(S, 0.5), first = {waves_from if waves_from is not None else "260 * Math.max(S, 0.5)"};
  const count = Math.ceil((W - cx - first) / step) + 2;
  for (let k = 0; k < count; k++) {{
    const r = first + k * step;
    const a = (Math.PI / 180) * Math.max(30, 46 - k * 1.6);
    const x1 = cx + r * Math.cos(-a), y1 = cy + r * Math.sin(-a);
    const x2 = cx + r * Math.cos(a), y2 = cy + r * Math.sin(a);
    el("path", {{
      d: `M ${{x1}} ${{y1}} A ${{r}} ${{r}} 0 0 1 ${{x2}} ${{y2}}`,
      stroke: "url(#wave)",
      "stroke-width": (3 + k * 0.9) * Math.max(S, 0.5),
      opacity: Math.max(0.12, 0.85 - k * 0.07),
      transform: `rotate(${{(k % 2 ? 1 : -1) * 1.2}} ${{cx}} ${{cy}})`,
    }}, waves);
    for (let j = 0; j < 4 + k; j++) {{  // particles riding the wave
      const ang = (rnd() * 2 - 1) * a;
      const rr = r + (rnd() - 0.5) * 18 * S;
      el("circle", {{
        cx: cx + rr * Math.cos(ang), cy: cy + rr * Math.sin(ang),
        r: (1 + rnd() * 2.6) * Math.max(S, 0.6), fill: "#d9d2ff", opacity: 0.25 + rnd() * 0.6,
      }}, waves);
    }}
  }}
  const halo = el("radialGradient", {{ id: "halo" }}, defs);  // soft halo right behind the mark
  el("stop", {{ offset: 0, "stop-color": "#7b66ff", "stop-opacity": 0.5 }}, halo);
  el("stop", {{ offset: 1, "stop-color": "#7b66ff", "stop-opacity": 0 }}, halo);
  el("circle", {{ cx, cy, r: {msize * 1.25}, fill: "url(#halo)" }}, art);
}})();
</script>
</body></html>"""


def _idle_html(icon: Path) -> str:
    """The image the TV shows while idle (Default Media Receiver, 1920x1080). Text and mark stay inside
    the central safe area: TVs that overscan crop the borders."""
    content = """<div class="idle">
  <h1>Chromecast Web</h1>
  <div class="chip"><span class="dot"></span>Ready to cast</div>
</div>
<div class="hint">Open Chromecast Web from any browser to start casting</div>"""
    css = """.idle{position:absolute;left:250px;top:592px}
  .idle h1{font-size:104px;letter-spacing:-2.5px}
  .idle .chip{gap:16px;margin-top:34px;font-size:30px;padding:14px 30px}
  .idle .dot{width:14px;height:14px}
  .hint{position:absolute;left:250px;bottom:110px;font-size:26px;color:rgba(226,223,255,.55)}"""
    return _wallpaper_html(icon, width=1920, height=1080, mark=(370, 394, 240), content=content, css=css)


# README banners (rendered at 2x for sharp text on high-DPI screens), one per README language
BANNERS = {
    "banner.jpg": ("Cast live streams, IPTV playlists and web videos to your TV.", "Self-hosted · open source"),
    "banner-it.jpg": ("Trasmetti dirette, playlist IPTV e video dal web sulla TV.", "Self-hosted · open source"),
}


def _banner_html(icon: Path, tagline: str, chip: str) -> str:
    content = f"""<div class="scrim"></div>
<div class="banner">
  <h1>Chromecast Web</h1>
  <p>{tagline}</p>
  <div class="chip"><span class="dot"></span>{chip}</div>
</div>"""
    css = """.scrim{position:absolute;inset:0;background:
    radial-gradient(560px 300px at 470px 50%,rgba(8,7,15,.62),transparent 75%)}
  .banner{position:absolute;left:236px;top:50%;transform:translateY(-50%)}
  .banner h1{font-size:68px;letter-spacing:-1.5px}
  .banner p{margin:14px 0 0;font-size:24px;color:#d6d2f5;white-space:nowrap}
  .banner .chip{gap:11px;margin-top:20px;font-size:17px;padding:8px 18px}
  .banner .dot{width:9px;height:9px}"""
    return _wallpaper_html(
        icon, width=1280, height=400, mark=(132, 200, 132), content=content, css=css, waves_from=760
    )


async def render_banners(page: Page, icon: Path) -> None:
    """``page`` should have device_scale_factor=2. Stored as JPEG: a gradient wallpaper is several times
    smaller than as a PNG."""
    await page.set_viewport_size({"width": 1280, "height": 400})
    for name, (tagline, chip) in BANNERS.items():
        await page.set_content(_banner_html(icon, tagline, chip))
        await page.wait_for_load_state("load")
        write(ASSETS / name, await page.screenshot(type="jpeg", quality=86))


async def render_idle(page: Page, icon: Path) -> None:
    await page.set_viewport_size({"width": 1920, "height": 1080})
    await page.set_content(_idle_html(icon))
    await page.wait_for_load_state("load")
    write(IDLE_IMAGE, await page.screenshot(type="jpeg", quality=88))


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
    icon, maskable = ASSETS / "icon.svg", ASSETS / "icon-maskable.svg"
    only = {a.lstrip("-") for a in sys.argv[1:]} & {"idle", "banner"}
    if only:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            if "idle" in only:
                await render_idle(await browser.new_page(), icon)
            if "banner" in only:
                await render_banners(await browser.new_page(device_scale_factor=2), icon)
            await browser.close()
        return

    from PIL import Image

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
        await render_idle(page, icon)
        await render_banners(await browser.new_page(device_scale_factor=2), icon)
        await browser.close()
    shutil.copyfile(icon, PUBLIC_ICONS / "icon.svg")
    print(f"  {(PUBLIC_ICONS / 'icon.svg').relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
