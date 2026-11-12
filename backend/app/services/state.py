"""StateHub: the single in-memory AppState, broadcast to every /ws client on change."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from app.models import AppState, Device, PlayerState, utcnow

log = logging.getLogger(__name__)

QUEUE_MAX = 64


class StateHub:
    def __init__(self, tick_interval: float = 1.0) -> None:
        self.devices: list[Device] = []
        self.active_device_id: str | None = None
        self.players: dict[str, PlayerState] = {}
        self.discovering = False
        self.version = 0
        self.tick_interval = tick_interval
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._tick_task: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[AppState], None]] = []

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._tick_task is None and self.tick_interval > 0:
            self._tick_task = asyncio.create_task(self._tick_loop(), name="statehub-tick")

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tick_task
            self._tick_task = None
        for q in list(self._clients):
            self._put(q, {"type": "closed"})

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_interval)
            try:
                if self._clients and self.any_playing():
                    self.notify()
            except Exception:  # pragma: no cover - defensive
                log.exception("tick failed")

    def any_playing(self) -> bool:
        return any(p.player_state == "PLAYING" and not p.showing_idle_image for p in self.players.values())

    # ------------------------------------------------------------ snapshot
    def snapshot(self) -> AppState:
        now = utcnow()
        players: dict[str, PlayerState] = {}
        for dev_id, p in self.players.items():
            ct = p.current_time
            if p.player_state == "PLAYING" and not p.showing_idle_image:
                ct += max(0.0, (now - p.updated_at).total_seconds())
                if p.duration:
                    ct = min(ct, p.duration)
            players[dev_id] = p.model_copy(update={"current_time": round(ct, 3), "updated_at": now})
        return AppState(
            devices=list(self.devices),
            active_device_id=self.active_device_id,
            players=players,
            discovering=self.discovering,
            version=self.version,
        )

    def player_snapshot(self, device_id: str) -> PlayerState | None:
        return self.snapshot().players.get(device_id)

    # ------------------------------------------------------------ mutations
    def set_devices(self, devices: list[Device]) -> None:
        self.devices = devices
        self.notify()

    def set_discovering(self, value: bool) -> None:
        self.discovering = value
        self.notify()

    def set_active(self, device_id: str | None) -> None:
        self.active_device_id = device_id
        self.notify()

    def set_player(self, player: PlayerState) -> None:
        self.players[player.device_id] = player
        self.notify()

    def remove_player(self, device_id: str) -> None:
        self.players.pop(device_id, None)
        if self.active_device_id == device_id:
            self.active_device_id = None
        self.notify()

    def notify(self) -> None:
        """Bump the version and broadcast a full snapshot to every client."""
        self.version += 1
        snap = self.snapshot()
        msg = {"type": "state", "data": snap.model_dump(mode="json")}
        for q in list(self._clients):
            self._put(q, msg)
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception:  # pragma: no cover
                log.exception("state listener failed")

    def toast(self, level: str, message: str) -> None:
        msg = {"type": "toast", "level": level, "message": message}
        for q in list(self._clients):
            self._put(q, msg)

    def add_listener(self, cb: Callable[[AppState], None]) -> None:
        self._listeners.append(cb)

    # ------------------------------------------------------------ clients
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @staticmethod
    def _put(q: asyncio.Queue[dict[str, Any]], msg: dict[str, Any]) -> None:
        if q.full():
            # slow consumer: drop the oldest message (state snapshots are idempotent)
            with contextlib.suppress(asyncio.QueueEmpty):
                q.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(msg)
