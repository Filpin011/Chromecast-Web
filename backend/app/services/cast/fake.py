"""FakeCastDriver: two simulated devices with realistic state progression.

Used with ``CAST_DRIVER=fake`` for frontend development and in tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from app.models import Device, MediaTrack
from app.services.cast.base import (
    APP_BACKDROP,
    APP_MEDIA_RECEIVER,
    CastError,
    DeviceStatus,
    DriverEvent,
    DriverListener,
    MediaRequest,
    manual_device_id,
)

FAKE_VOD_DURATION = 600.0

FAKE_DEVICES = [
    Device(
        id="fake-ultra-0001",
        name="Chromecast Ultra (fake)",
        model="Chromecast Ultra",
        host="192.168.1.50",
        port=8009,
        cast_type="cast",
        manufacturer="Google Inc.",
    ),
    Device(
        id="fake-tv-0002",
        name="Living Room TV (fake)",
        model="Google TV Streamer",
        host="192.168.1.51",
        port=8009,
        cast_type="cast",
        manufacturer="Google Inc.",
    ),
]


class FakeCastDriver:
    name = "fake"

    def __init__(self, delay: float = 0.4, vod_duration: float = FAKE_VOD_DURATION) -> None:
        self.delay = delay
        self.vod_duration = vod_duration
        self._devices: dict[str, Device] = {}
        self._status: dict[str, DeviceStatus] = {}
        self._listener: DriverListener | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._last_media: dict[str, MediaRequest] = {}
        self.calls: list[tuple[str, str, object]] = []  # for tests

    # ------------------------------------------------------------ plumbing
    def set_listener(self, listener: DriverListener) -> None:
        self._listener = listener

    def _emit(self, event: DriverEvent, device_id: str | None = None, msg: str | None = None) -> None:
        if self._listener:
            self._listener(event, device_id, msg)

    async def start(self) -> None:
        for d in FAKE_DEVICES:
            self._devices.setdefault(d.id, d.model_copy())
        self._emit("devices")

    async def stop(self) -> None:
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()

    # ------------------------------------------------------------ devices
    def devices(self) -> list[Device]:
        return list(self._devices.values())

    def find_device(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    async def discover(self, seconds: float) -> list[Device]:
        await asyncio.sleep(min(seconds, 1.0))
        for d in FAKE_DEVICES:
            self._devices.setdefault(d.id, d.model_copy())
        self._emit("devices")
        return self.devices()

    async def add_manual(self, host: str, port: int, name: str | None) -> Device:
        dev = Device(
            id=manual_device_id(host),
            name=name or f"Chromecast @ {host}",
            model="Chromecast (manual)",
            host=host,
            port=port,
            cast_type="cast",
            manufacturer=None,
            manual=True,
            online=True,
        )
        self._devices[dev.id] = dev
        self._emit("devices")
        return dev

    async def remove_device(self, device_id: str) -> None:
        await self.disconnect(device_id)
        self._devices.pop(device_id, None)
        self._emit("devices")

    def _require(self, device_id: str) -> DeviceStatus:
        st = self._status.get(device_id)
        if st is None or not st.connected:
            raise CastError(f"Device {device_id} not connected")
        return st

    # ------------------------------------------------------------ connection
    async def connect(self, device_id: str) -> None:
        if device_id not in self._devices:
            raise CastError(f"Unknown device {device_id}")
        self.calls.append(("connect", device_id, None))
        if self._status.get(device_id) and self._status[device_id].connected:
            return
        await asyncio.sleep(self.delay / 4)
        self._status[device_id] = DeviceStatus(
            connected=True, app_name="Backdrop", app_id=APP_BACKDROP, player_state="IDLE", volume_level=0.5
        )
        self._emit("status", device_id)

    async def disconnect(self, device_id: str) -> None:
        self._cancel(device_id)
        if device_id in self._status:
            self._status.pop(device_id)
            self._emit("status", device_id)

    def is_connected(self, device_id: str) -> bool:
        st = self._status.get(device_id)
        return bool(st and st.connected)

    def status(self, device_id: str) -> DeviceStatus:
        return self._status.get(device_id) or DeviceStatus()

    # ------------------------------------------------------------ media
    def _cancel(self, device_id: str) -> None:
        t = self._tasks.pop(device_id, None)
        if t and t is not asyncio.current_task():
            t.cancel()

    def _snap(self, st: DeviceStatus) -> None:
        """Freeze the extrapolated position before a state transition."""
        st.current_time = st.position_now()
        st.status_at = time.time()

    async def play_media(self, device_id: str, media: MediaRequest) -> None:
        st = self._require(device_id)
        self.calls.append(("play_media", device_id, media))
        self._cancel(device_id)
        self._last_media[device_id] = media
        live = media.stream_type == "LIVE"
        tracks: list[MediaTrack] = []
        if not media.is_image:
            tracks.append(MediaTrack(id=100, type="AUDIO", name="Audio", language="und"))
            for i, sub in enumerate(media.subtitles, start=1):
                tracks.append(MediaTrack(id=i, type="TEXT", name=sub.label, language=sub.lang))
        st.app_name = "Default Media Receiver"
        st.app_id = APP_MEDIA_RECEIVER
        st.player_state = "BUFFERING"
        st.idle_reason = None
        st.title = media.title
        st.thumbnail = media.thumbnail
        st.media_url = media.url
        st.stream_type = None if media.is_image else media.stream_type
        st.current_time = media.current_time or 0.0
        st.duration = None if (live or media.is_image) else self.vod_duration
        st.seekable = not live and not media.is_image
        st.tracks = tracks
        st.active_track_ids = [100] if tracks else []
        st.status_at = time.time()
        self._emit("status", device_id)
        self._tasks[device_id] = asyncio.create_task(self._progress(device_id, media))

    async def _progress(self, device_id: str, media: MediaRequest) -> None:
        await asyncio.sleep(self.delay)
        st = self._status.get(device_id)
        if not st:
            return
        st.player_state = "PLAYING" if media.autoplay else "PAUSED"
        st.status_at = time.time()
        self._emit("status", device_id)
        await self._watch_end(device_id)

    async def _watch_end(self, device_id: str) -> None:
        st = self._status.get(device_id)
        if not st or not st.duration or st.player_state != "PLAYING":
            return
        remaining = st.duration - st.position_now()
        await asyncio.sleep(max(0.0, remaining))
        self.finish(device_id)

    def finish(self, device_id: str) -> None:
        """Simulate the media reaching its end (FINISHED)."""
        st = self._status.get(device_id)
        if not st:
            return
        st.current_time = st.duration or st.position_now()
        st.player_state = "IDLE"
        st.idle_reason = "FINISHED"
        st.status_at = time.time()
        self._emit("status", device_id)
        self._emit("finished", device_id)

    def fail(self, device_id: str) -> None:
        """Simulate the receiver giving up on accepted media (IDLE / ERROR, e.g. expired URL)."""
        st = self._status.get(device_id)
        if not st:
            return
        self._cancel(device_id)
        st.player_state = "IDLE"
        st.idle_reason = "ERROR"
        st.status_at = time.time()
        self._emit("status", device_id)
        self._emit("finished", device_id, "ERROR")

    def _restart_watch(self, device_id: str) -> None:
        self._cancel(device_id)
        self._tasks[device_id] = asyncio.create_task(self._watch_end(device_id))

    async def play(self, device_id: str) -> None:
        st = self._require(device_id)
        if st.player_state in ("PAUSED", "BUFFERING"):
            self._snap(st)
            st.player_state = "PLAYING"
            self._emit("status", device_id)
            self._restart_watch(device_id)
        elif st.player_state == "IDLE" and device_id in self._last_media:
            await self.play_media(device_id, self._last_media[device_id])

    async def pause(self, device_id: str) -> None:
        st = self._require(device_id)
        if st.player_state in ("PLAYING", "BUFFERING"):
            self._snap(st)
            st.player_state = "PAUSED"
            self._cancel(device_id)
            self._emit("status", device_id)

    async def stop_media(self, device_id: str) -> None:
        st = self._require(device_id)
        self._cancel(device_id)
        st.player_state = "IDLE"
        st.idle_reason = "CANCELLED"
        st.app_name = "Backdrop"
        st.app_id = APP_BACKDROP
        st.media_url = None
        st.title = None
        st.thumbnail = None
        st.duration = None
        st.current_time = 0.0
        st.tracks = []
        st.active_track_ids = []
        st.status_at = time.time()
        self._emit("status", device_id)

    async def seek(self, device_id: str, position: float) -> None:
        st = self._require(device_id)
        if st.duration:
            position = min(position, st.duration)
        st.current_time = max(0.0, position)
        st.status_at = time.time()
        self._emit("status", device_id)
        if st.player_state == "PLAYING":
            self._restart_watch(device_id)

    async def set_volume(self, device_id: str, level: float) -> None:
        st = self._require(device_id)
        st.volume_level = max(0.0, min(1.0, level))
        self._emit("status", device_id)

    async def set_muted(self, device_id: str, muted: bool) -> None:
        st = self._require(device_id)
        st.muted = muted
        self._emit("status", device_id)

    async def set_active_tracks(self, device_id: str, track_ids: list[int]) -> None:
        st = self._require(device_id)
        valid = {t.id for t in st.tracks}
        st.active_track_ids = [t for t in track_ids if t in valid]
        self._emit("status", device_id)

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):
            await self.stop()
