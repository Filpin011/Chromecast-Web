"""Run the app with the fake Chromecast driver and realistic (fictional) demo data — used for screenshots.

    make demo                     # builds the frontend, then runs this on http://localhost:8000
    cd backend && .venv/bin/python scripts/demo.py [--port 8000] [--data-dir DIR] [--no-seed]

What it does:
- starts a small content server (scripts/demo_content.py) with original artwork, channel logos, two IPTV
  playlists, fake live HLS streams and web pages with a player, and maps the reserved ``*.example``
  domains to it (in the backend's HTTP client and Chromium), so no external network is needed;
- starts the backend in-process with ``CAST_DRIVER=fake`` (devices renamed "Living Room" / "Bedroom"),
  ``PUBLIC_BASE_URL=http://192.168.1.10:8000`` (placeholder), a fresh ``DATA_DIR`` and no filter downloads;
- seeds it through the REST API: playlists, favorites, history, a live stream playing on "Living Room"
  with a queue.

Remote-browser pages to try: http://demo-tv.example/watch/aurora-live (stream detected) and
http://demo-tv.example/watch/harbor-cup-final?popup (popup prompt). The *.example names resolve only inside
the app's own Chromium, and in a browser started with ``--host-resolver-rules`` (see scripts/screenshots.py).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(Path(__file__).resolve().parent)]

import demo_content as content  # noqa: E402

READY_LINE = "DEMO READY"
LIVING_ROOM = "fake-ultra-0001"


def resolver_rule(port: int) -> str:
    """Chromium flag mapping every *.example host to the local content server."""
    return f"--host-resolver-rules=MAP *.example 127.0.0.1:{port}"


class DemoTransport(httpx.AsyncHTTPTransport):
    """Sends requests for ``*.example`` hosts to the content server (the Host header is kept)."""

    def __init__(self, port: int, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.port = port

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith(".example"):
            request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return await super().handle_async_request(request)


def build_backend(args: argparse.Namespace):  # -> FastAPI
    os.environ.update(
        CAST_DRIVER="fake",
        PUBLIC_BASE_URL=args.public_base_url,
        DATA_DIR=str(args.data_dir),
        FRONTEND_DIR=str(args.frontend_dir),
        FILTERS_AUTO_UPDATE="false",
        LOG_LEVEL=os.environ.get("LOG_LEVEL", "warning"),
        PORT=str(args.port),
    )
    from app.config import AppConfig
    from app.main import create_app
    from app.services import net
    from app.services.browser import launcher
    from app.services.cast import fake

    names = {"fake-ultra-0001": ("Living Room", "Chromecast Ultra"), "fake-tv-0002": ("Bedroom", "Chromecast")}
    fake.FAKE_DEVICES[:] = [
        d.model_copy(update={"name": names[d.id][0], "model": names[d.id][1]}) for d in fake.FAKE_DEVICES
    ]
    launcher.CHROMIUM_ARGS.append(resolver_rule(args.content_port))
    client = httpx.AsyncClient(
        transport=DemoTransport(args.content_port),
        headers={"User-Agent": net.DESKTOP_UA},
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=True,
    )
    return create_app(AppConfig(), http_client=client)


async def seed(api: str, data_dir: Path) -> None:
    async with httpx.AsyncClient(base_url=api, timeout=60) as c:

        async def call(method: str, path: str, **kw: object) -> httpx.Response:
            r = await c.request(method, path, **kw)  # type: ignore[arg-type]
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text}")
            return r

        for key, (name, _) in content.PLAYLISTS.items():
            await call("POST", "/api/playlists", json={"url": f"{content.IPTV}/lists/{key}.m3u", "name": name})

        def show(slug: str) -> dict[str, str]:
            s = content.SHOWS[slug]
            return {"input": f"{content.SITE}/watch/{slug}", "title": s.title}

        def channel(slug: str) -> dict[str, str]:
            ch = content.ALL_CHANNELS[slug]
            return {"input": f"{content.IPTV}/live/{slug}/index.m3u8", "title": ch.name}

        favorites = [
            {**show("aurora-live"), "source_kind": "webpage", "thumbnail": f"{content.SITE}/art/aurora.svg"},
            {**show("harbor-cup-final"), "source_kind": "webpage", "thumbnail": f"{content.SITE}/art/stadium.svg"},
            {**channel("deep-blue-planet"), "source_kind": "direct", "thumbnail": f"{content.SITE}/art/ocean.svg"},
            {**channel("lo-fi-lounge"), "source_kind": "direct", "thumbnail": f"{content.SITE}/art/city.svg"},
        ]
        for fav in reversed(favorites):
            await call("POST", "/api/favorites", json=fav)

        dev = f"/api/devices/{LIVING_ROOM}"
        # history, oldest first; the last one stays on the TV
        for item in (
            {**channel("meridian-news-24")},
            {**show("harbor-cup-final"), "kind": "webpage"},
            {**show("deep-blue"), "kind": "webpage"},
            {**show("skyline-timelapse"), "kind": "webpage"},
            {**show("aurora-live"), "kind": "webpage"},
        ):
            await call("POST", f"{dev}/play", json=item)
        await call("POST", f"{dev}/queue", json={**channel("lo-fi-lounge")})
        await call("POST", f"{dev}/queue", json={**channel("terra-docs")})
        await call("POST", f"{dev}/control", json={"action": "volume", "value": 0.62})
        await call("PUT", "/api/settings", json={"default_device_id": LIVING_ROOM})

    # spread the history over the last day so the relative times look natural
    db = sqlite3.connect(data_dir / "app.db")
    with db:
        rows = db.execute("SELECT id FROM history ORDER BY played_at DESC").fetchall()
        now = datetime.now(UTC).replace(tzinfo=None)
        for (row_id,), age in zip(rows, [timedelta(minutes=1), timedelta(minutes=48), timedelta(hours=3),
                                         timedelta(hours=9), timedelta(days=1, hours=2)], strict=False):
            db.execute("UPDATE history SET played_at = ? WHERE id = ?", ((now - age).isoformat(sep=" "), row_id))
    db.close()


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--content-port", type=int, default=8765)
    p.add_argument("--data-dir", type=Path, default=None, help="default: a fresh temporary directory")
    p.add_argument("--frontend-dir", type=Path, default=BACKEND.parent / "frontend" / "out")
    p.add_argument("--public-base-url", default="http://192.168.1.10:8000")
    p.add_argument("--no-seed", action="store_true")
    args = p.parse_args()
    args.data_dir = (args.data_dir or Path(tempfile.mkdtemp(prefix="chromecast-web-demo-"))).resolve()
    args.frontend_dir = args.frontend_dir.resolve()
    if not (args.frontend_dir / "index.html").is_file():
        sys.exit(f"Frontend not built ({args.frontend_dir}): run `make build` first (or `make demo`).")

    backend = uvicorn.Server(uvicorn.Config(build_backend(args), host=args.host, port=args.port, log_level="warning"))
    contents = uvicorn.Server(
        uvicorn.Config(content.create_content_app(), host="127.0.0.1", port=args.content_port, log_level="warning")
    )
    tasks = [asyncio.create_task(backend.serve()), asyncio.create_task(contents.serve())]
    while not (backend.started and contents.started):
        if any(t.done() for t in tasks):
            sys.exit("server failed to start (port in use?)")
        await asyncio.sleep(0.1)
    if not args.no_seed:
        print("seeding demo data (a few web pages are opened in Chromium, ~20 s)…", flush=True)
        await seed(f"http://127.0.0.1:{args.port}", args.data_dir)
    print(f"{READY_LINE}: http://localhost:{args.port}  (data: {args.data_dir})", flush=True)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
