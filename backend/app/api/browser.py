"""Interactive remote browser: REST + ``/ws/browser/{id}``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect

from app import models as m
from app.api.deps import services, ws_services
from app.errors import AppError
from app.services.browser.session import RemoteBrowserSession
from app.services.container import Services
from app.services.resolver.service import Candidate

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/browser/sessions", response_model=m.BrowserSession, status_code=201)
async def create_session(body: m.BrowserSessionIn, s: Services = Depends(services)) -> m.BrowserSession:
    session = await s.browser.create(body.url, body.viewport)
    return session.to_model()


@router.get("/api/browser/sessions", response_model=list[m.BrowserSession])
async def list_sessions(s: Services = Depends(services)) -> list[m.BrowserSession]:
    return [x.to_model() for x in s.browser.list()]


@router.get("/api/browser/sessions/{session_id}", response_model=m.BrowserSession)
async def get_session(session_id: str, s: Services = Depends(services)) -> m.BrowserSession:
    return s.browser.get(session_id).to_model()


@router.post("/api/browser/sessions/{session_id}/navigate", response_model=m.BrowserSession)
async def navigate(session_id: str, body: m.BrowserNavigateIn, s: Services = Depends(services)) -> m.BrowserSession:
    if not body.url and not body.action:
        raise AppError(422, "Provide 'url' or 'action'", "validation_error")
    session = s.browser.get(session_id)
    await session.navigate(body.url, body.action)
    return session.to_model()


@router.delete("/api/browser/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, s: Services = Depends(services)) -> Response:
    s.browser.get(session_id)
    await s.browser.close(session_id)
    return Response(status_code=204)


async def _captured_media(s: Services, session: RemoteBrowserSession, stream_id: str) -> m.ResolvedMedia:
    stream = session.get_stream(stream_id)
    live = stream.is_live
    cand = Candidate(
        url=stream.url,
        source_kind="webpage",
        original_input=stream.page_url,
        title=stream.title or session.title,
        thumbnail=stream.thumbnail if (stream.thumbnail or "").startswith("http") else None,
        mime_type=stream.mime_type,
        stream_type=None if live is None else ("LIVE" if live else "BUFFERED"),
        headers=stream.headers,
    )
    return await s.resolver.finalize(cand)


@router.post("/api/browser/sessions/{session_id}/cast", response_model=m.PlayerState)
async def cast_stream(session_id: str, body: m.BrowserCastIn, s: Services = Depends(services)) -> m.PlayerState:
    session = s.browser.get(session_id)
    session.touch()
    s.cast.get_device(body.device_id)
    media = await _captured_media(s, session, body.stream_id)
    if body.enqueue:
        return await s.cast.enqueue(
            body.device_id, media.original_input, "webpage", media.title, media=media, pinned=True
        )
    # pinned: the captured stream (with its headers) can't be re-derived from the page URL
    await s.cast.play_media(
        body.device_id, media, history_input=media.original_input, history_kind="webpage", pinned=True
    )
    return s.cast.player(body.device_id)


@router.post("/api/browser/sessions/{session_id}/favorite", response_model=m.Favorite, status_code=201)
async def favorite_stream(session_id: str, body: m.BrowserFavoriteIn, s: Services = Depends(services)) -> m.Favorite:
    session = s.browser.get(session_id)
    stream = session.get_stream(body.stream_id)
    # Captured URLs carry expiring tokens/cookies: bookmark the page, which is re-resolved on play.
    return s.db.add_favorite(
        m.FavoriteIn(
            title=stream.title or session.title or stream.page_url,
            input=stream.page_url,
            source_kind="webpage",
            thumbnail=stream.thumbnail if (stream.thumbnail or "").startswith("http") else None,
        )
    )


@router.post("/api/browser/sessions/{session_id}/adblock", response_model=m.BrowserSession)
async def set_adblock(session_id: str, body: m.BrowserAdblockIn, s: Services = Depends(services)) -> m.BrowserSession:
    session = s.browser.get(session_id)
    session.touch()
    await session.set_adblock(body.enabled)
    return session.to_model()


@router.post("/api/browser/sessions/{session_id}/popups/{popup_id}", response_model=m.BrowserSession)
async def popup_decision(
    session_id: str, popup_id: str, body: m.PopupDecisionIn, s: Services = Depends(services)
) -> m.BrowserSession:
    session = s.browser.get(session_id)
    await session.decide_popup(popup_id, body.decision)
    return session.to_model()


@router.get("/api/filters", response_model=m.FilterLists)
async def filter_lists(s: Services = Depends(services)) -> m.FilterLists:
    return m.FilterLists(lists=s.filters.info())


@router.post("/api/filters/refresh", response_model=m.FilterLists)
async def refresh_filters(s: Services = Depends(services)) -> m.FilterLists:
    return m.FilterLists(lists=await s.filters.refresh())


@router.websocket("/ws/browser/{session_id}")
async def browser_ws(websocket: WebSocket, session_id: str, s: Services = Depends(ws_services)) -> None:
    session = s.browser.sessions.get(session_id)
    await websocket.accept()
    if session is None:
        await websocket.send_json({"type": "closed"})
        await websocket.close(code=4404)
        return
    queue = session.subscribe()

    async def sender() -> None:
        while True:
            msg = await queue.get()
            await websocket.send_json(msg)
            if msg.get("type") == "closed":
                await websocket.close()
                return

    send_task = asyncio.create_task(sender())
    try:
        while True:
            recv = asyncio.create_task(websocket.receive_text())
            done, _ = await asyncio.wait({recv, send_task}, return_when=asyncio.FIRST_COMPLETED)
            if send_task in done:
                recv.cancel()
                break
            raw = recv.result()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            await session.handle_input(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        session.unsubscribe(queue)
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task
