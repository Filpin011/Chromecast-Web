"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from app import __version__
from app.api import browser, devices, media, playlists, resolve, system, ws
from app.config import AppConfig, get_settings
from app.errors import AppError, install_error_handlers
from app.services.browser.launcher import BrowserProvider
from app.services.cast.base import CastDriver
from app.services.container import build_services

log = logging.getLogger("app")

RESERVED_PREFIXES = ("api/", "ws", "proxy/", "restream/", "local/")
# Consumed cross-origin by the Cast receiver (Origin https://www.gstatic.com) and players.
MEDIA_PREFIXES = ("/proxy/", "/restream/", "/local/", "/idle.jpg")
MEDIA_PREFLIGHT_HEADERS = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-methods", b"GET, HEAD, OPTIONS"),
    (b"access-control-allow-headers", b"Range, Accept, Origin, Content-Type"),
    (b"access-control-max-age", b"86400"),
    (b"content-length", b"0"),
]


class MediaPreflightMiddleware:
    """Answers CORS preflights on the media endpoints for *any* origin.

    The app-wide CORSMiddleware only allows the dev frontend origins and rejects other
    preflights with 400; the Default Media Receiver (gstatic.com) preflights every XHR
    that carries a ``Range`` header (DASH SegmentBase, HLS byte-range fMP4).
    Installed outside CORSMiddleware so it sees the OPTIONS first.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "OPTIONS"
            and scope["path"].startswith(MEDIA_PREFIXES)
        ):
            await send({"type": "http.response.start", "status": 204, "headers": MEDIA_PREFLIGHT_HEADERS})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send)


def _frontend_file(root: Path, path: str) -> Path | None:
    """Resolve a request path against a Next.js static export (SPA fallback)."""
    root = root.resolve()
    clean = path.strip("/")
    candidates = [root / clean] if clean else []
    candidates += [root / f"{clean}.html", root / clean / "index.html"] if clean else [root / "index.html"]
    for c in candidates:
        try:
            c = c.resolve()
        except OSError:  # pragma: no cover
            continue
        if (c == root or root in c.parents) and c.is_file():
            return c
    return None


def mount_frontend(app: FastAPI, frontend_dir: Path) -> None:
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(full_path: str, request: Request) -> Response:
        if full_path.startswith(RESERVED_PREFIXES) or full_path == "ws":
            raise AppError(404, "Not found", "not_found")
        root = frontend_dir
        if not root.is_dir():
            raise AppError(404, "Frontend not built", "not_found")
        hit = _frontend_file(root, full_path)
        if hit is None:
            last = full_path.rsplit("/", 1)[-1]
            if "." in last:  # missing asset: real 404, not the SPA shell
                raise AppError(404, "Not found", "not_found")
            # dynamic segment fallback: nearest 404.html? → SPA shell
            hit = _frontend_file(root, "")
            if hit is None:
                raise AppError(404, "Frontend not built", "not_found")
        headers = {}
        if "/_next/static/" in f"/{full_path}":
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif hit.suffix == ".html":
            headers["Cache-Control"] = "no-cache"
        return FileResponse(hit, headers=headers)


def create_app(
    settings: AppConfig | None = None,
    *,
    driver: CastDriver | None = None,
    browser_provider: BrowserProvider | None = None,
    http_client: httpx.AsyncClient | None = None,
    ytdlp_extractor: Callable[[str], dict[str, Any]] | None = None,
    in_memory_db: bool = False,
) -> FastAPI:
    config = settings or get_settings()
    logging.basicConfig(level=config.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        services = build_services(
            config,
            driver=driver,
            browser_provider=browser_provider,
            http_client=http_client,
            ytdlp_extractor=ytdlp_extractor,
            in_memory_db=in_memory_db,
        )
        app.state.services = services
        await services.start()
        log.info("started (driver=%s, base url=%s)", services.cast.driver.name, services.base_url())
        try:
            yield
        finally:
            await services.stop()

    app = FastAPI(title="Chromecast Web", version=__version__, lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_origin_regex=config.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MediaPreflightMiddleware)  # added last = outermost, runs before CORS
    for r in (system.router, resolve.router, devices.router, playlists.router, browser.router, ws.router, media.router):
        app.include_router(r)
    mount_frontend(app, config.frontend_dir)
    return app


def __getattr__(name: str) -> Any:
    # ``uvicorn app.main:app`` — build lazily so importing this module has no side effects.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
