"""StateHub: the single in-memory AppState, broadcast to every /ws client on change."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from app.models import AppState, Device, PlayerState, utcnow

log = logging.getLogger(__name__)

QUEUE_MAX = 64
# Non-AppState data the clients cache (TanStack Query keys); see ``StateHub.invalidate``.
INVALIDATE_KEYS = frozenset({"settings", "favorites", "history", "playlists"})
INVALIDATE_WINDOW = 0.25


class StateHub:
    def __init__(self, tick_interval: float = 1.0, invalidate_window: float = INVALIDATE_WINDOW) -> None:
        self.devices: list[Device] = []
        self.active_device_id: str | None = None
        self.players: dict[str, PlayerState] = {}
        self.discovering = False
        self.version = 0
        self.tick_interval = tick_interval
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._tick_task: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[AppState], None]] = []
        self.invalidate_window = invalidate_window
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inv_last: dict[str, float] = {}
        self._inv_pending: set[str] = set()
        self._inv_timer: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        with contextlib.suppress(RuntimeError):
            self._loop = asyncio.get_running_loop()
        if self._tick_task is None and self.tick_interval > 0:
            self._tick_task = asyncio.create_task(self._tick_loop(), name="statehub-tick")

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tick_task
            self._tick_task = None
        if self._inv_timer is not None:
            self._inv_timer.cancel()
            self._inv_timer = None
        self._inv_pending.clear()
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

    def toast(
        self, level: str, message: str, code: str | None = None, params: dict[str, str | int] | None = None
    ) -> None:
        """Broadcast a notification. ``message`` is English (fallback); clients translate by
        ``code`` (stable, see docs/ARCHITECTURE.md) interpolating ``params``."""
        msg: dict[str, Any] = {"type": "toast", "level": level, "message": message}
        if code:
            msg["code"] = code
            msg["params"] = params or {}
        for q in list(self._clients):
            self._put(q, msg)

    def invalidate(self, *keys: str) -> None:
        """Tell every client that cached non-AppState data changed: ``{"type": "invalidate", "keys": [...]}``.

        Keys are ``settings`` / ``favorites`` / ``history`` / ``playlists``. Bursts are coalesced: a key is
        sent at once if it wasn't sent in the last ``invalidate_window`` seconds, otherwise once more at the
        end of that window, so one key goes out at most once per window. Safe to call from any thread.
        """
        wanted = [k for k in keys if k in INVALIDATE_KEYS]
        if not wanted:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            if self._loop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self.invalidate, *wanted)
            return
        self._loop = loop
        now = time.monotonic()
        ready: list[str] = []
        for k in wanted:
            if k in self._inv_pending:
                continue
            if now - self._inv_last.get(k, float("-inf")) >= self.invalidate_window:
                ready.append(k)
                self._inv_last[k] = now
            else:
                self._inv_pending.add(k)
        if ready:
            self._send_invalidate(ready)
        self._schedule_invalidate(loop)

    def _schedule_invalidate(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._inv_timer is not None or not self._inv_pending:
            return
        due = min(self._inv_last[k] for k in self._inv_pending) + self.invalidate_window
        self._inv_timer = loop.call_later(max(0.0, due - time.monotonic()), self._flush_invalidate, loop)

    def _flush_invalidate(self, loop: asyncio.AbstractEventLoop) -> None:
        self._inv_timer = None
        now = time.monotonic()
        # tiny slack: call_later may fire a hair early on coarse clocks
        ready = sorted(k for k in self._inv_pending if now - self._inv_last[k] >= self.invalidate_window - 0.005)
        for k in ready:
            self._inv_pending.discard(k)
            self._inv_last[k] = now
        if ready:
            self._send_invalidate(ready)
        self._schedule_invalidate(loop)

    def _send_invalidate(self, keys: Iterable[str]) -> None:
        msg: dict[str, Any] = {"type": "invalidate", "keys": list(keys)}
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
