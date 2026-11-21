"""Health, state, settings, favorites, history, local file listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app import __version__
from app import models as m
from app.api.deps import services
from app.errors import AppError
from app.services.container import Services
from app.services.resolver import local as localres

router = APIRouter(prefix="/api")


@router.get("/health", response_model=m.Health)
async def health(s: Services = Depends(services)) -> m.Health:
    return m.Health(driver=s.cast.driver.name, version=__version__, local_enabled=s.config.media_root is not None)


@router.get("/state", response_model=m.AppState)
async def state(s: Services = Depends(services)) -> m.AppState:
    return s.hub.snapshot()


# ---------------------------------------------------------------- settings
@router.get("/settings", response_model=m.Settings)
async def get_settings(s: Services = Depends(services)) -> m.Settings:
    return s.db.get_settings()


@router.put("/settings", response_model=m.Settings)
async def put_settings(body: m.SettingsUpdate, s: Services = Depends(services)) -> m.Settings:
    patch = body.model_dump(exclude_unset=True)
    for key in (
        "show_idle_on_connect",
        "show_idle_on_stop",
        "force_proxy",
        "adblock_enabled",
        "adblock_disabled_hosts",
        "popup_policy",
        "popup_blocked_hosts",
    ):
        if key in patch and patch[key] is None:
            patch.pop(key)
    for key in ("idle_image_url", "public_base_url", "default_device_id"):
        if isinstance(patch.get(key), str) and not patch[key].strip():
            patch[key] = None
    result = s.db.update_settings(patch)
    s.hub.notify()  # public base URL / defaults may affect clients
    return result


# ---------------------------------------------------------------- favorites
@router.get("/favorites", response_model=list[m.Favorite])
async def list_favorites(s: Services = Depends(services)) -> list[m.Favorite]:
    return s.db.list_favorites()


@router.post("/favorites", response_model=m.Favorite, status_code=201)
async def add_favorite(body: m.FavoriteIn, s: Services = Depends(services)) -> m.Favorite:
    return s.db.add_favorite(body)


@router.patch("/favorites/{fav_id}", response_model=m.Favorite)
async def rename_favorite(fav_id: str, body: m.FavoriteRename, s: Services = Depends(services)) -> m.Favorite:
    fav = s.db.rename_favorite(fav_id, body.title)
    if fav is None:
        raise AppError(404, "Favorite not found", "favorite_not_found")
    return fav


@router.delete("/favorites/{fav_id}", status_code=204)
async def delete_favorite(fav_id: str, s: Services = Depends(services)) -> Response:
    if not s.db.delete_favorite(fav_id):
        raise AppError(404, "Favorite not found", "favorite_not_found")
    return Response(status_code=204)


# ---------------------------------------------------------------- history
@router.get("/history", response_model=list[m.HistoryEntry])
async def history(limit: int = Query(50, ge=1, le=500), s: Services = Depends(services)) -> list[m.HistoryEntry]:
    return s.db.list_history(limit)


@router.delete("/history", status_code=204)
async def clear_history(s: Services = Depends(services)) -> Response:
    s.db.clear_history()
    return Response(status_code=204)


# ---------------------------------------------------------------- local files
@router.get("/local", response_model=m.LocalListing)
async def local_listing(path: str = "", s: Services = Depends(services)) -> m.LocalListing:
    return localres.list_dir(s.config.media_root, path)
