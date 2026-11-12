"""Media endpoints consumed by the Chromecast and the browser preview (no /api prefix)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from app.api.deps import services
from app.errors import AppError
from app.services.container import Services
from app.services.proxy.stream import CORS
from app.services.resolver import local as localres

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.api_route("/proxy/{token}/{path:path}", methods=["GET", "HEAD"])
async def proxy(token: str, path: str, request: Request, s: Services = Depends(services)) -> Response:
    target = s.tokens.get(token)
    if target is None:
        raise AppError(404, "Unknown or expired proxy token", "token_not_found")
    return await s.proxy.handle(target, path, request)


@router.api_route("/restream/{token}/{name}", methods=["GET", "HEAD"])
async def restream(token: str, name: str, s: Services = Depends(services)) -> Response:
    job = s.restream.get(token)
    if job is None:
        raise AppError(404, "Unknown restream token", "token_not_found")
    if name == "index.m3u8":
        try:
            await s.restream.ensure_running(job)
        except RuntimeError as exc:
            raise AppError(502, str(exc), "restream_failed") from exc
        return Response(
            job.playlist.read_text(),
            media_type="application/vnd.apple.mpegurl",
            headers={**CORS, "Cache-Control": "no-cache"},
        )
    p = s.restream.file_path(job, name)
    if p is None:
        raise AppError(404, "Segment not found", "not_found")
    return FileResponse(p, media_type="video/mp2t", headers=CORS)


@router.api_route("/local/{path:path}", methods=["GET", "HEAD"])
async def local_file(path: str, request: Request, s: Services = Depends(services)) -> Response:
    p = localres.safe_path(s.config.media_root, path)
    if not p.is_file():
        raise AppError(404, "File not found", "not_found")
    if p.suffix.lower() == ".srt" and request.query_params.get("as") == "vtt":
        # Sidecar SubRip subtitles are cast as WebVTT text tracks.
        vtt = localres.srt_to_vtt(localres.read_text_any(p))
        return Response(vtt, media_type="text/vtt; charset=utf-8", headers=CORS)
    return FileResponse(p, media_type=localres.guess_mime(p.name) or "application/octet-stream", headers=CORS)


@router.get("/idle.jpg")
async def idle_image() -> Response:
    return FileResponse(STATIC_DIR / "idle.jpg", media_type="image/jpeg", headers=CORS)
