"""CastDriver protocol shared by the real and fake drivers."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from app.models import Device, MediaTrack, PlayerStateName, StreamType, Subtitle

# "finished": the loaded media ended; message = idle reason ("FINISHED", or "ERROR" when
# the receiver gave up on it after accepting the LOAD). None means FINISHED.
DriverEvent = Literal["devices", "status", "finished", "error"]
# callback(event, device_id | None, message | None) — always invoked on the event loop thread
DriverListener = Callable[[DriverEvent, str | None, str | None], None]

# Cast receiver app ids
APP_BACKDROP = "E8C28D3C"  # idle screen / ambient mode
APP_MEDIA_RECEIVER = "CC1AD845"  # Default Media Receiver (what we LOAD into by default)

# Optional custom Web Receiver (CAST_APP_ID, see docs/CUSTOM_RECEIVER.md): set once by
# create_app from the config. None = the Default Media Receiver, exactly as before.
_custom_receiver_app_id: str | None = None


def set_receiver_app_id(app_id: str | None) -> None:
    global _custom_receiver_app_id
    _custom_receiver_app_id = (app_id or "").strip().upper() or None


def receiver_app_id() -> str:
    """The receiver app every LOAD goes to: CAST_APP_ID when configured, else CC1AD845."""
    return _custom_receiver_app_id or APP_MEDIA_RECEIVER


def receiver_app_name() -> str:
    return "Chromecast-Web Receiver" if _custom_receiver_app_id else "Default Media Receiver"


def is_own_receiver(app_id: str | None) -> bool:
    """``app_id`` is a receiver we LOAD into (the configured one, or the Default Media Receiver)."""
    return app_id is not None and app_id in (APP_MEDIA_RECEIVER, receiver_app_id())


class CastError(Exception):
    """Raised by drivers when a device operation fails."""


@dataclass
class MediaRequest:
    url: str
    mime_type: str
    title: str | None = None
    thumbnail: str | None = None
    stream_type: StreamType = "BUFFERED"
    subtitles: list[Subtitle] = field(default_factory=list)
    autoplay: bool = True
    current_time: float | None = None
    is_image: bool = False
    hls_segment_format: str | None = None  # "fmp4" | "aac" | ... (None = MPEG-TS)
    hls_video_segment_format: str | None = None  # "fmp4" (None = MPEG-TS video)
    load_timeout: float | None = None  # seconds to wait for the LOAD answer (None = driver default)


@dataclass
class DeviceStatus:
    """Raw status as reported by a device (before the service adds queue/meta)."""

    connected: bool = False  # control socket is up (False while the driver is reconnecting)
    app_name: str | None = None
    app_id: str | None = None  # running receiver app; None/APP_BACKDROP = nothing running
    player_state: PlayerStateName = "UNKNOWN"
    idle_reason: str | None = None
    title: str | None = None
    thumbnail: str | None = None
    media_url: str | None = None
    stream_type: StreamType | None = None
    current_time: float = 0.0
    duration: float | None = None
    seekable: bool = False
    volume_level: float = 1.0
    muted: bool = False
    tracks: list[MediaTrack] = field(default_factory=list)
    active_track_ids: list[int] = field(default_factory=list)
    status_at: float = field(default_factory=time.time)

    def free_for_idle_image(self) -> bool:
        """True when casting the idle image would not interrupt anything.

        Only when no app is running (or the Backdrop), or our receiver (Default Media
        Receiver or the configured custom one) is loaded but idle. Never over another app
        (Netflix, YouTube, ...) or over media that is already playing.
        """
        if self.app_id in (None, APP_BACKDROP):
            return True
        return is_own_receiver(self.app_id) and self.player_state == "IDLE"

    def position_now(self) -> float:
        ct = self.current_time
        if self.player_state == "PLAYING":
            ct += max(0.0, time.time() - self.status_at)
            if self.duration:
                ct = min(ct, self.duration)
        return ct


@runtime_checkable
class CastDriver(Protocol):
    name: str

    def set_listener(self, listener: DriverListener) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    def devices(self) -> list[Device]: ...
    def find_device(self, device_id: str) -> Device | None:
        """Look a device up by id, including entries hidden from ``devices()`` by dedupe."""
        ...
    async def discover(self, seconds: float) -> list[Device]: ...
    async def add_manual(self, host: str, port: int, name: str | None) -> Device: ...
    async def remove_device(self, device_id: str) -> None: ...

    async def connect(self, device_id: str) -> None: ...
    async def disconnect(self, device_id: str) -> None: ...
    def is_connected(self, device_id: str) -> bool:
        """A session is held for the device (may be transiently reconnecting, see DeviceStatus.connected)."""
        ...
    def status(self, device_id: str) -> DeviceStatus: ...

    async def play_media(self, device_id: str, media: MediaRequest) -> None: ...
    async def play(self, device_id: str) -> None: ...
    async def pause(self, device_id: str) -> None: ...
    async def stop_media(self, device_id: str) -> None: ...
    async def seek(self, device_id: str, position: float) -> None: ...
    async def set_volume(self, device_id: str, level: float) -> None: ...
    async def set_muted(self, device_id: str, muted: bool) -> None: ...
    async def set_active_tracks(self, device_id: str, track_ids: list[int]) -> None: ...


def manual_device_id(host: str) -> str:
    return f"manual-{host}"
