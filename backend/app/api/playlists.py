"""M3U/IPTV playlists."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app import models as m
from app.api.deps import services
from app.errors import AppError
from app.services.container import Services

router = APIRouter(prefix="/api/playlists")


def _require(s: Services, playlist_id: str) -> m.Playlist:
    pl = s.db.get_playlist(playlist_id)
    if pl is None:
        raise AppError(404, "Playlist not found", "playlist_not_found")
    return pl


@router.get("", response_model=list[m.Playlist])
async def list_playlists(s: Services = Depends(services)) -> list[m.Playlist]:
    return s.db.list_playlists()


@router.post("", response_model=m.Playlist, status_code=201)
async def import_playlist(body: m.PlaylistIn, s: Services = Depends(services)) -> m.Playlist:
    url = (body.url or "").strip() or None
    content = body.content if body.content and body.content.strip() else None
    if not url and not content:
        raise AppError(422, "Provide either 'url' or 'content'", "validation_error")
    name, channels, is_hls = await s.resolver.load_m3u(url=url, content=content)
    if is_hls:
        raise AppError(400, "This is an HLS stream, not an IPTV playlist: play it directly", "unsupported_source")
    if not channels:
        raise AppError(400, "The playlist contains no channels", "resolve_failed")
    return s.db.create_playlist((body.name or "").strip() or name, url, channels)


@router.get("/{playlist_id}", response_model=m.Playlist)
async def get_playlist(playlist_id: str, s: Services = Depends(services)) -> m.Playlist:
    return _require(s, playlist_id)


@router.get("/{playlist_id}/channels", response_model=m.ChannelPage)
async def channels(
    playlist_id: str,
    q: str | None = None,
    group: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    s: Services = Depends(services),
) -> m.ChannelPage:
    _require(s, playlist_id)
    items, total = s.db.list_channels(playlist_id, q=q, group=group, offset=offset, limit=limit)
    return m.ChannelPage(items=items, total=total)


@router.post("/{playlist_id}/refresh", response_model=m.Playlist)
async def refresh(playlist_id: str, s: Services = Depends(services)) -> m.Playlist:
    pl = _require(s, playlist_id)
    if not pl.source_url:
        raise AppError(400, "Playlist was imported from content: nothing to refresh", "no_source_url")
    _, channels, _ = await s.resolver.load_m3u(url=pl.source_url)
    result = s.db.replace_channels(playlist_id, channels)
    assert result is not None
    return result


@router.delete("/{playlist_id}", status_code=204)
async def delete_playlist(playlist_id: str, s: Services = Depends(services)) -> Response:
    if not s.db.delete_playlist(playlist_id):
        raise AppError(404, "Playlist not found", "playlist_not_found")
    return Response(status_code=204)
