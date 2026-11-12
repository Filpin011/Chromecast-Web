"""Fictional demo content for screenshots: artwork, channel logos, IPTV playlists, live HLS and web pages.

Everything here is original and made up (names, logos, artwork). It is served by a tiny ASGI app on
127.0.0.1; the demo maps the reserved ``*.example`` domains (RFC 2606) to it, so the UI shows
believable URLs such as ``http://demo-tv.example/watch/aurora-live`` instead of loopback addresses.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

SITE = "http://demo-tv.example"
IPTV = "http://iptv.example"
SEGMENT_SECONDS = 6


# --------------------------------------------------------------------------- artwork (1280x720 SVG)
def _stars(rng: random.Random, n: int, h: int) -> str:
    return "".join(
        f'<circle cx="{rng.uniform(0, 1280):.0f}" cy="{rng.uniform(0, h):.0f}" r="{rng.uniform(0.6, 2.2):.1f}" '
        f'fill="#fff" opacity="{rng.uniform(0.3, 0.95):.2f}"/>'
        for _ in range(n)
    )


def art_aurora() -> str:
    rng = random.Random(7)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
<defs>
 <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#030712"/>
  <stop offset=".55" stop-color="#0b2140"/><stop offset="1" stop-color="#12425a"/></linearGradient>
 <filter id="b" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
 <linearGradient id="lake" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d3a4c"/>
  <stop offset="1" stop-color="#02080f"/></linearGradient>
</defs>
<rect width="1280" height="720" fill="url(#sky)"/>{_stars(rng, 140, 420)}
<g filter="url(#b)" opacity=".85">
 <path d="M-40 300 C 220 120, 420 360, 640 210 S 1040 90, 1320 230" stroke="#34f5a4" stroke-width="90" fill="none"/>
 <path d="M-40 230 C 260 80, 520 300, 760 160 S 1100 60, 1320 140" stroke="#7c6cff" stroke-width="70"
  fill="none" opacity=".8"/>
 <path d="M80 360 C 360 250, 600 380, 900 270 S 1200 250, 1320 300" stroke="#2dd4bf" stroke-width="40"
  fill="none" opacity=".7"/>
</g>
<path d="M0 470 L120 380 L210 430 L330 300 L450 420 L560 350 L700 460 L820 330 L960 440 L1080 360 L1280 470
 L1280 720 L0 720 Z" fill="#0a1424"/>
<path d="M0 500 L160 430 L300 480 L420 410 L600 500 L760 420 L900 490 L1060 430 L1280 500 L1280 720 L0 720 Z"
 fill="#050b14"/>
<rect y="540" width="1280" height="180" fill="url(#lake)" opacity=".9"/>
<g filter="url(#b)" opacity=".25"><path d="M-40 640 C 300 600, 640 680, 1320 610" stroke="#34f5a4"
 stroke-width="40" fill="none"/></g>
</svg>"""


def art_city() -> str:
    rng = random.Random(3)
    buildings = []
    x = -10
    while x < 1290:
        w = rng.randint(50, 120)
        h = rng.randint(140, 420)
        buildings.append(f'<rect x="{x}" y="{720 - h}" width="{w}" height="{h}" fill="#1b1033"/>')
        for wy in range(720 - h + 18, 700, 26):
            for wx in range(x + 10, x + w - 12, 18):
                if rng.random() < 0.38:
                    buildings.append(
                        f'<rect x="{wx}" y="{wy}" width="8" height="12" fill="#ffd38a" '
                        f'opacity="{rng.uniform(.5, 1):.2f}"/>'
                    )
        x += w + rng.randint(2, 10)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a1b5e"/>
 <stop offset=".45" stop-color="#c2417a"/><stop offset=".8" stop-color="#ff9a5a"/>
 <stop offset="1" stop-color="#ffc977"/>
</linearGradient><radialGradient id="sun"><stop offset="0" stop-color="#fff3c4"/><stop offset=".5" stop-color="#ffcf70"
 stop-opacity=".9"/><stop offset="1" stop-color="#ff9a5a" stop-opacity="0"/></radialGradient></defs>
<rect width="1280" height="720" fill="url(#s)"/><circle cx="820" cy="430" r="260" fill="url(#sun)"/>
<circle cx="820" cy="430" r="90" fill="#fff1c9"/>{''.join(buildings)}</svg>"""


def art_ocean() -> str:
    rng = random.Random(11)
    bubbles = "".join(
        f'<circle cx="{rng.uniform(0, 1280):.0f}" cy="{rng.uniform(0, 720):.0f}" r="{rng.uniform(2, 9):.1f}" '
        f'fill="none" stroke="#bdeaff" stroke-opacity="{rng.uniform(.15, .5):.2f}" stroke-width="2"/>'
        for _ in range(60)
    )
    fish = "".join(
        f'<g transform="translate({x} {y}) scale({s})" fill="#0f2e4f" opacity=".85">'
        '<ellipse cx="0" cy="0" rx="46" ry="16"/><path d="M40 0 L72 -18 L72 18 Z"/></g>'
        for x, y, s in [(300, 300, 1.2), (380, 340, 0.8), (250, 360, 0.9), (900, 250, 0.7), (960, 280, 0.6)]
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
<defs><linearGradient id="w" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1aa3c9"/>
 <stop offset=".45" stop-color="#0b4f86"/><stop offset="1" stop-color="#03152e"/></linearGradient>
 <filter id="b"><feGaussianBlur stdDeviation="12"/></filter></defs>
<rect width="1280" height="720" fill="url(#w)"/>
<g filter="url(#b)" fill="#e6fbff" opacity=".12"><path d="M420 0 L520 0 L380 720 L220 720 Z"/>
 <path d="M700 0 L760 0 L820 720 L660 720 Z"/><path d="M980 0 L1060 0 L1200 720 L1040 720 Z"/></g>
<path d="M560 470 C 640 420, 820 410, 930 460 C 990 480, 1040 470, 1080 440 L1100 500 C 1060 500, 1020 500,
 990 510 C 900 560, 700 560, 560 470 Z" fill="#082a46"/>
{fish}{bubbles}<path d="M0 640 C 200 600, 380 660, 640 630 S 1080 600, 1280 650 L1280 720 L0 720 Z" fill="#021022"/>
</svg>"""


def art_stadium() -> str:
    rng = random.Random(5)
    crowd = "".join(
        f'<circle cx="{rng.uniform(0, 1280):.0f}" cy="{rng.uniform(250, 330):.0f}" r="3" '
        f'fill="{rng.choice(["#f87171", "#fbbf24", "#60a5fa", "#e5e7eb", "#a78bfa"])}" opacity=".7"/>'
        for _ in range(500)
    )
    stripes = "".join(
        f'<path d="M{-200 + i * 170} 720 L{300 + i * 85} 340 L{385 + i * 85} 340 L{-30 + i * 170} 720 Z" '
        f'fill="#1f8f4a" opacity="{0.55 if i % 2 else 0}"/>'
        for i in range(10)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
<defs><linearGradient id="n" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#050a1a"/>
 <stop offset="1" stop-color="#1b2a4a"/></linearGradient><radialGradient id="l"><stop offset="0" stop-color="#fff"/>
 <stop offset=".2" stop-color="#e0f2fe" stop-opacity=".7"/><stop offset="1" stop-color="#e0f2fe" stop-opacity="0"/>
 </radialGradient><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22a35a"/>
 <stop offset="1" stop-color="#14713b"/></linearGradient></defs>
<rect width="1280" height="720" fill="url(#n)"/>
<rect y="230" width="1280" height="120" fill="#121a30"/>{crowd}
<circle cx="140" cy="120" r="150" fill="url(#l)"/><circle cx="1140" cy="120" r="150" fill="url(#l)"/>
<path d="M0 720 L300 340 L980 340 L1280 720 Z" fill="url(#g)"/>{stripes}
<path d="M300 340 L980 340 L1280 720 L0 720 Z" fill="none" stroke="#e8fff0" stroke-width="5" opacity=".9"/>
<path d="M640 340 L640 720" stroke="#e8fff0" stroke-width="5" opacity=".9"/>
<ellipse cx="640" cy="500" rx="150" ry="62" fill="none" stroke="#e8fff0" stroke-width="5" opacity=".9"/>
<circle cx="700" cy="560" r="14" fill="#fff"/></svg>"""


ARTWORK = {"aurora": art_aurora, "city": art_city, "ocean": art_ocean, "stadium": art_stadium}


# --------------------------------------------------------------------------- shows (web pages with a player)
@dataclass(frozen=True)
class Show:
    slug: str
    art: str
    title: str
    blurb: str
    viewers: str


SHOWS = {
    s.slug: s
    for s in (
        Show("aurora-live", "aurora", "Northern Lights Live — Arctic Sky Cam",
             "A quiet night under the aurora, streamed live from a lakeside cabin.", "2.4K watching"),
        Show("skyline-timelapse", "city", "Golden Hour Skyline",
             "Sunset over the city, one frame every four seconds.", "812 watching"),
        Show("deep-blue", "ocean", "Deep Blue Planet: The Reef at Dawn",
             "Documentary series · Episode 3 · Live premiere.", "5.1K watching"),
        Show("harbor-cup-final", "stadium", "Harbor Cup Final — Live",
             "Bayside Rovers vs. North Pier United, kick-off 20:45.", "18K watching"),
    )
}


def _page(show: Show, popup: bool) -> str:
    others = "".join(
        f'<a class="card" href="/watch/{o.slug}"><img src="/art/{o.art}.svg" alt=""><span>{escape(o.title)}</span></a>'
        for o in SHOWS.values()
        if o.slug != show.slug
    )
    popup_js = (
        "setTimeout(()=>window.open('http://prize-wheel.example/claim?ref=demo-tv','_blank'),1200);" if popup else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(show.title)}</title>
<meta property="og:title" content="{escape(show.title)}">
<meta property="og:image" content="{SITE}/art/{show.art}.svg">
<script src="http://ads.example/prebid.js"></script>
<style>
 *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 background:#0f1117;color:#e8e9f1}} header{{display:flex;align-items:center;gap:10px;padding:12px 16px;
 background:#151823;border-bottom:1px solid #222637}} .logo{{font-weight:800;letter-spacing:-.5px;font-size:19px}}
 .logo b{{color:#f97362}} nav{{margin-left:auto;display:flex;gap:14px;font-size:14px;color:#9aa0b8}}
 .wrap{{max-width:900px;margin:0 auto}} @media(min-width:700px){{.wrap{{padding:20px 0}} .player{{border-radius:12px}}}}
 .player{{position:relative;aspect-ratio:16/9;background:#000;overflow:hidden}}
 video{{width:100%;height:100%;object-fit:cover;display:block}}
 .live{{position:absolute;top:12px;left:12px;background:#ef4444;color:#fff;font-weight:700;font-size:12px;
 padding:3px 8px;border-radius:4px;letter-spacing:.5px}} .eye{{position:absolute;top:12px;left:66px;
 background:rgba(0,0,0,.55);font-size:12px;padding:3px 8px;border-radius:4px}}
 .bar{{position:absolute;left:0;right:0;bottom:0;height:42px;background:linear-gradient(transparent,rgba(0,0,0,.7));
 display:flex;align-items:center;gap:14px;padding:0 14px;font-size:14px}}
 .bar i{{display:inline-block;width:0;height:0;border-left:12px solid #fff;border-top:7px solid transparent;
 border-bottom:7px solid transparent}} .bar .track{{flex:1;height:4px;border-radius:2px;background:#ef4444}}
 main{{padding:16px}} h1{{font-size:21px;line-height:1.25;margin:4px 0 8px}} p{{color:#a3a8bf;margin:0 0 16px;
 font-size:15px;line-height:1.45}} .chips{{display:flex;gap:8px;margin-bottom:20px}} .chips span{{background:#1d2130;
 border:1px solid #2a2f44;border-radius:999px;padding:6px 12px;font-size:13px}} h2{{font-size:15px;color:#c9cce0}}
 .card{{display:flex;gap:12px;align-items:center;margin-bottom:12px;color:inherit;text-decoration:none;font-size:14px}}
 .card img{{width:132px;aspect-ratio:16/9;border-radius:8px;object-fit:cover}}
</style></head><body>
<header><span class="logo">example<b>tv</b></span>
 <nav><span>Live</span><span>Shows</span><span>Sports</span></nav></header>
<div class="wrap"><div class="player"><video id="v" muted playsinline poster="/art/{show.art}.svg"></video>
 <span class="live">LIVE</span><span class="eye">{escape(show.viewers)}</span>
 <div class="bar"><i></i><div class="track"></div><span>LIVE</span></div></div>
<div class="ad-banner">Advertisement</div>
<main><h1>{escape(show.title)}</h1><p>{escape(show.blurb)}</p>
<div class="chips"><span>♥ Follow</span><span>↗ Share</span><span>HD</span></div>
<h2>Up next</h2>{others}</main></div>
<script>
 // what a typical hls.js player does: fetch the master playlist, then a variant and its segments
 async function start(){{
  const base = location.origin + '/hls/{show.slug}/';
  const master = await (await fetch(base + 'master.m3u8')).text();
  const variant = master.split('\\n').find(l => l && !l.startsWith('#'));
  const media = await (await fetch(base + variant)).text();
  const seg = media.split('\\n').filter(l => l && !l.startsWith('#')).pop();
  await fetch(new URL(seg, base + variant));
 }}
 setTimeout(start, 500);
 {popup_js}
</script>
<script src="http://ads.example/pop.js"></script>
</body></html>"""


# --------------------------------------------------------------------------- IPTV channels and logos
@dataclass(frozen=True)
class Channel:
    name: str
    group: str
    colors: tuple[str, str]
    referer: bool = False

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-").replace("&", "and").replace("'", "")

    @property
    def initials(self) -> str:
        words = [w for w in self.name.replace("-", " ").split() if w[0].isalnum()]
        return "".join(w[0] for w in words[:2]).upper() if len(words) > 1 else self.name[:2].upper()


FREE_TV = [
    Channel("Meridian News 24", "News", ("#ef4444", "#7f1d1d")),
    Channel("Northwind Weather", "News", ("#38bdf8", "#1e3a8a")),
    Channel("Civic Channel", "News", ("#64748b", "#1e293b")),
    Channel("Harbor Sports", "Sports", ("#22c55e", "#14532d"), referer=True),
    Channel("Velocity Racing", "Sports", ("#f97316", "#7c2d12")),
    Channel("Summit Outdoors", "Sports", ("#84cc16", "#365314")),
    Channel("Pixel Pals", "Kids", ("#facc15", "#c2410c")),
    Channel("Doodle Junior", "Kids", ("#f472b6", "#9d174d")),
    Channel("Neon Beats", "Music", ("#d946ef", "#4c1d95")),
    Channel("Lo-Fi Lounge", "Music", ("#a78bfa", "#312e81")),
    Channel("Retro Reel", "Movies", ("#fbbf24", "#78350f")),
    Channel("Midnight Cinema", "Movies", ("#6366f1", "#111827")),
    Channel("Terra Docs", "Documentary", ("#10b981", "#064e3b")),
    Channel("Deep Blue Planet", "Documentary", ("#06b6d4", "#0c4a6e")),
    Channel("Wanderlust TV", "Travel", ("#fb7185", "#881337")),
    Channel("Kitchen Table", "Lifestyle", ("#fdba74", "#9a3412")),
]
CITY_CAMS = [
    Channel("Alpine Lake Cam", "Nature", ("#7dd3fc", "#0f766e")),
    Channel("Harbor Webcam", "City", ("#93c5fd", "#1e40af")),
    Channel("Old Town Square", "City", ("#fca5a5", "#7f1d1d")),
    Channel("Seabird Cliffs", "Nature", ("#a7f3d0", "#065f46")),
    Channel("Night Train Cab View", "Travel", ("#c4b5fd", "#3730a3")),
]
PLAYLISTS = {"free-tv-world": ("Free TV World", FREE_TV), "city-cams": ("City & Nature Cams", CITY_CAMS)}
ALL_CHANNELS = {c.slug: c for c in FREE_TV + CITY_CAMS}


def logo_svg(ch: Channel) -> str:
    a, b = ch.colors
    seed = int(hashlib.sha1(ch.slug.encode()).hexdigest()[:6], 16)
    angle = seed % 360
    ring = (
        f'<circle cx="128" cy="128" r="{86 + seed % 12}" fill="none" stroke="#fff" stroke-opacity=".18" '
        f'stroke-width="10" stroke-dasharray="{40 + seed % 60} 18" transform="rotate({angle} 128 128)"/>'
    )
    size = 92 if len(ch.initials) > 1 else 112
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/>
<stop offset="1" stop-color="{b}"/></linearGradient></defs><rect width="256" height="256" rx="56" fill="url(#g)"/>
{ring}<text x="128" y="128" dy=".35em" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',
Roboto,Helvetica,Arial,sans-serif" font-weight="800" font-size="{size}" fill="#fff"
 letter-spacing="-3">{escape(ch.initials)}</text>
</svg>"""


def m3u(key: str) -> str:
    _, channels = PLAYLISTS[key]
    lines = ["#EXTM3U"]
    for ch in channels:
        lines.append(
            f'#EXTINF:-1 tvg-id="{ch.slug}" tvg-logo="{IPTV}/logos/{ch.slug}.svg" group-title="{ch.group}",{ch.name}'
        )
        if ch.referer:  # a channel that needs upstream headers, like many IPTV lists
            lines.append(f"#EXTVLCOPT:http-referrer={IPTV}/")
        lines.append(f"{IPTV}/live/{ch.slug}/index.m3u8")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- live HLS (fake segments)
def _media_playlist(prefix: str = "") -> str:
    seq = int(time.time() // SEGMENT_SECONDS)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{SEGMENT_SECONDS}", f"#EXT-X-MEDIA-SEQUENCE:{seq}"]
    for n in range(seq, seq + 5):
        lines += [f"#EXTINF:{SEGMENT_SECONDS}.000,", f"{prefix}seg-{n}.ts"]
    return "\n".join(lines) + "\n"  # no EXT-X-ENDLIST: live


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
1080p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
720p/index.m3u8
"""
# 0x47 sync bytes every 188: recognised as MPEG-TS by the probes; nothing ever decodes it (fake driver)
TS_SEGMENT = (b"\x47" + b"\x1f\xff\x10" + b"\xff" * 184) * 64
HLS_TYPE = "application/vnd.apple.mpegurl"
CORS = {"Access-Control-Allow-Origin": "*"}


def create_content_app() -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get("/art/{name}.svg")
    def art(name: str) -> Response:
        fn = ARTWORK.get(name)
        if fn is None:
            return Response(status_code=404)
        return Response(fn(), media_type="image/svg+xml", headers=CORS)

    @app.get("/logos/{slug}.svg")
    def logo(slug: str) -> Response:
        ch = ALL_CHANNELS.get(slug)
        if ch is None:
            return Response(status_code=404)
        return Response(logo_svg(ch), media_type="image/svg+xml", headers=CORS)

    @app.get("/lists/{key}.m3u")
    def playlist(key: str) -> Response:
        if key not in PLAYLISTS:
            return Response(status_code=404)
        return PlainTextResponse(m3u(key), media_type="audio/x-mpegurl", headers=CORS)

    @app.get("/live/{slug}/index.m3u8")
    def live(slug: str) -> Response:
        return Response(_media_playlist(), media_type=HLS_TYPE, headers=CORS)

    @app.get("/hls/{slug}/master.m3u8")
    def master(slug: str) -> Response:
        return Response(MASTER, media_type=HLS_TYPE, headers=CORS)

    @app.get("/hls/{slug}/{variant}/index.m3u8")
    def variant(slug: str, variant: str) -> Response:
        return Response(_media_playlist(), media_type=HLS_TYPE, headers=CORS)

    @app.get("/{path:path}/seg-{n}.ts")
    def segment(path: str, n: int) -> Response:
        return Response(TS_SEGMENT, media_type="video/mp2t", headers=CORS)

    @app.get("/watch/{slug}")
    def watch(slug: str, request: Request) -> Response:
        show = SHOWS.get(slug)
        if show is None:
            return Response(status_code=404)
        return HTMLResponse(_page(show, popup="popup" in request.query_params))

    @app.get("/claim")
    def claim() -> HTMLResponse:  # the popup target (prize-wheel.example)
        return HTMLResponse("<!doctype html><title>Spin the wheel!</title><h1>You won!</h1>")

    @app.get("/")
    def home() -> HTMLResponse:
        links = "".join(f'<li><a href="/watch/{s.slug}">{escape(s.title)}</a></li>' for s in SHOWS.values())
        return HTMLResponse(f"<!doctype html><title>example tv</title><ul>{links}</ul>")

    return app


__all__ = ["ALL_CHANNELS", "IPTV", "PLAYLISTS", "SHOWS", "SITE", "create_content_app"]
