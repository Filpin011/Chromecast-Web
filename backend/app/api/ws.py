"""``/ws``: full AppState snapshots to every client."""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import ws_services
from app.services.container import Services

router = APIRouter()


@router.websocket("/ws")
async def state_ws(websocket: WebSocket, s: Services = Depends(ws_services)) -> None:
    await websocket.accept()
    queue = s.hub.subscribe()
    await websocket.send_json({"type": "state", "data": s.hub.snapshot().model_dump(mode="json")})

    async def sender() -> None:
        while True:
            msg = await queue.get()
            if msg.get("type") == "closed":
                await websocket.close()
                return
            await websocket.send_json(msg)

    send_task = asyncio.create_task(sender())
    try:
        while True:
            recv = asyncio.create_task(websocket.receive_text())
            done, _ = await asyncio.wait({recv, send_task}, return_when=asyncio.FIRST_COMPLETED)
            if send_task in done:
                recv.cancel()
                break
            try:
                msg = json.loads(recv.result())
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        s.hub.unsubscribe(queue)
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task
