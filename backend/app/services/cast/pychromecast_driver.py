"""Real driver on top of pychromecast.

pychromecast is synchronous and threaded: every blocking call is wrapped in
``asyncio.to_thread``; listener callbacks fire on pychromecast's socket thread and
are marshalled to the event loop with ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
import uuid as uuidlib
from typing import Any

from app.models import Device, MediaTrack
from app.services.cast.base import (
    CastError,
    DeviceStatus,
    DriverEvent,
    DriverListener,
    MediaRequest,
    manual_device_id,
)

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 12.0
REQUEST_TIMEOUT = 10.0
STATUS_TIMEOUT = 2.5
LOAD_TIMEOUT = 25.0  # includes launching the Default Media Receiver
MEDIA_NAMESPACE = "urn:x-cast:com.google.cast.media"
# pychromecast reports FAILED / FAILED_RESOLVE for *every* failed attempt inside its retry
# loop; only DISCONNECTED means the socket thread has given up (or was stopped).
SESSION_OVER = ("DISCONNECTED",)
# Initial connect: fail fast so the API answers. Once connected, pychromecast's own
# reconnect loop gets this many attempts (retry_wait 5 s + connect timeout each, i.e.
# several minutes) before it gives up and the session is dropped.
CONNECT_TRIES = 2
RECONNECT_TRIES = 60
LOAD_ERRORS = ("LOAD_FAILED", "LOAD_CANCELLED", "INVALID_REQUEST", "INVALID_PLAYER_STATE", "ERROR")


def _track_type(t: str | None) -> str:
    t = (t or "").upper()
    return t if t in ("TEXT", "AUDIO", "VIDEO") else "TEXT"


def _safe_disconnect(cast: Any, timeout: float) -> None:
    try:
        cast.disconnect(timeout=timeout)
    except Exception:  # pragma: no cover
        log.debug("disconnect failed", exc_info=True)


def _fetch_media_status(cast: Any, timeout: float) -> Any:
    """Ask the running app for its media status and wait for the answer (blocking).

    Returns None when no app exposing the media namespace is running: sending
    GET_STATUS then would *launch* the Default Media Receiver (and switch the TV
    input via CEC) just because we connected.
    """
    mc = cast.media_controller
    if MEDIA_NAMESPACE not in (getattr(cast.socket_client, "app_namespaces", None) or []):
        return None
    done = threading.Event()
    try:
        mc.update_status(callback_function=lambda *_: done.set())
    except Exception:
        return None
    done.wait(timeout)
    return mc.status


def check_load_response(sent: bool, response: dict[str, Any] | None) -> None:
    """Raise CastError unless the receiver accepted the LOAD."""
    if not sent:
        raise CastError("Could not start the Default Media Receiver on the Chromecast")
    mtype = (response or {}).get("type")
    if mtype in LOAD_ERRORS:
        detail = (response or {}).get("detailedErrorCode") or (response or {}).get("reason")
        raise CastError(f"The Chromecast refused the media ({mtype}{f', {detail}' if detail else ''})")


class _Listener:
    """Bridges pychromecast's listener interfaces to the driver.

    Bound to one ``Chromecast`` object: callbacks from a cast that has since been
    replaced or dropped are ignored, so a stale socket thread can't overwrite the
    status of the current session.
    """

    def __init__(self, driver: PyChromecastDriver, device_id: str, cast: Any) -> None:
        self.driver = driver
        self.device_id = device_id
        self.cast = cast

    def _current(self) -> bool:
        return self.driver._casts.get(self.device_id) is self.cast

    # CastStatusListener
    def new_cast_status(self, status: Any) -> None:
        if self._current():
            self.driver._on_cast_status(self.device_id, status)

    # MediaStatusListener
    def new_media_status(self, status: Any) -> None:
        if self._current():
            self.driver._on_media_status(self.device_id, status)

    def load_media_failed(self, queue_item_id: int, error_code: int) -> None:
        if self._current():
            self.driver._threadsafe_emit("error", self.device_id, f"Load failed (error {error_code})")

    # ConnectionStatusListener
    def new_connection_status(self, status: Any) -> None:
        if self._current():
            self.driver._on_connection_status(self.device_id, self.cast, status)

    # LaunchErrorListener
    def new_launch_error(self, status: Any) -> None:
        if self._current():
            self.driver._threadsafe_emit("error", self.device_id, f"Launch error: {status}")


class PyChromecastDriver:
    name = "pychromecast"

    def __init__(self) -> None:
        self._listener: DriverListener | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._zconf: Any = None
        self._browser: Any = None
        self._manual: dict[str, Device] = {}
        self._casts: dict[str, Any] = {}
        # DefaultMediaReceiverController per cast: every LOAD goes to the Default Media
        # Receiver (launching it when another app such as YouTube is in front).
        self._dmr: dict[str, Any] = {}
        self._status: dict[str, DeviceStatus] = {}
        # Serializes connect/disconnect per device: two concurrent connects would each
        # create a Chromecast object and the overwritten one would leak its socket thread.
        self._conn_locks: dict[str, asyncio.Lock] = {}
        # Last CastInfo seen for every discovered id: a session must survive its mDNS
        # record going away (goodbye packet, TTL expiry on flaky Wi-Fi).
        self._known_info: dict[str, Any] = {}

    # ------------------------------------------------------------ plumbing
    def set_listener(self, listener: DriverListener) -> None:
        self._listener = listener

    def _emit(self, event: DriverEvent, device_id: str | None = None, msg: str | None = None) -> None:
        if self._listener:
            self._listener(event, device_id, msg)

    def _threadsafe_emit(self, event: DriverEvent, device_id: str | None = None, msg: str | None = None) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._emit, event, device_id, msg)

    async def start(self) -> None:
        import pychromecast
        import zeroconf

        self._loop = asyncio.get_running_loop()

        def _start() -> None:
            self._zconf = zeroconf.Zeroconf()
            listener = pychromecast.SimpleCastListener(
                add_callback=lambda *_: self._threadsafe_emit("devices"),
                remove_callback=lambda *_: self._threadsafe_emit("devices"),
                update_callback=lambda *_: self._threadsafe_emit("devices"),
            )
            self._browser = pychromecast.CastBrowser(listener, self._zconf)
            self._browser.start_discovery()

        try:
            await asyncio.to_thread(_start)
        except Exception:  # pragma: no cover - depends on host network
            log.exception("mDNS discovery could not start; manual devices still work")

    async def stop(self) -> None:
        def _stop() -> None:
            for cast in list(self._casts.values()):
                _safe_disconnect(cast, 2)
            if self._browser:
                try:
                    self._browser.stop_discovery()
                except Exception:
                    pass
            if self._zconf:
                try:
                    self._zconf.close()
                except Exception:
                    pass

        await asyncio.to_thread(_stop)
        self._casts.clear()
        self._dmr.clear()

    # ------------------------------------------------------------ devices
    def _discovered(self) -> dict[str, Any]:
        """Currently advertised devices, plus the last known record of any device we hold
        a session with (so it stays addressable if its mDNS record expires)."""
        found: dict[str, Any] = {}
        if self._browser:
            # the zeroconf thread mutates ``devices`` under this (private) lock
            lock = getattr(self._browser, "_services_lock", None) or contextlib.nullcontext()
            for _ in range(3):
                try:
                    with lock:
                        found = {str(k): v for k, v in dict(self._browser.devices).items()}
                    break
                except RuntimeError:  # "dictionary changed size during iteration"
                    continue
        self._known_info.update(found)
        for dev_id in self._casts:
            if dev_id not in found and dev_id in self._known_info:
                found[dev_id] = self._known_info[dev_id]
        return found

    @staticmethod
    def _from_info(dev_id: str, info: Any) -> Device:
        return Device(
            id=dev_id,
            name=info.friendly_name or info.host,
            model=info.model_name,
            host=info.host,
            port=info.port,
            cast_type=info.cast_type,
            manufacturer=info.manufacturer,
            manual=False,
            online=True,
        )

    def _manual_view(self, dev: Device, discovered: dict[str, Any]) -> Device:
        """A manual entry, enriched with mDNS data when the same host is also discovered."""
        info = next((i for i in discovered.values() if i.host == dev.host), None)
        if info is None:
            return dev
        return dev.model_copy(
            update={
                "name": (info.friendly_name or dev.name) if dev.name.startswith("Chromecast @") else dev.name,
                "model": info.model_name or dev.model,
                "cast_type": info.cast_type or dev.cast_type,
                "manufacturer": info.manufacturer or dev.manufacturer,
                "online": True,
            }
        )

    def devices(self) -> list[Device]:
        """One entry per host. A manual entry keeps its (persisted) id even when mDNS also
        finds the host; the discovered duplicate is only listed while it holds a session
        (connected under its own id), so every player always has a device row."""
        discovered = self._discovered()
        manual_hosts = {d.host for d in self._manual.values()}
        out = [self._manual_view(d, discovered) for d in self._manual.values()]
        for dev_id, info in discovered.items():
            if info.host in manual_hosts and dev_id not in self._casts:
                continue
            out.append(self._from_info(dev_id, info))
        return out

    def find_device(self, device_id: str) -> Device | None:
        discovered = self._discovered()
        if device_id in self._manual:
            return self._manual_view(self._manual[device_id], discovered)
        if device_id in discovered:
            return self._from_info(device_id, discovered[device_id])
        return None

    async def discover(self, seconds: float) -> list[Device]:
        if self._browser is None:
            await self.start()
        # Discovery runs continuously in the background; we just give it time to
        # (re)populate without blocking the event loop.
        await asyncio.sleep(seconds)
        self._emit("devices")
        return self.devices()

    async def add_manual(self, host: str, port: int, name: str | None) -> Device:
        # online=True: we can't know without connecting, and the UI must let the user
        # try (adding by IP is the fallback when mDNS doesn't see the device).
        dev = Device(
            id=manual_device_id(host),
            name=name or f"Chromecast @ {host}",
            model=None,
            host=host,
            port=port,
            cast_type="cast",
            manual=True,
            online=True,
        )
        self._manual[dev.id] = dev
        self._emit("devices")
        return dev

    async def remove_device(self, device_id: str) -> None:
        await self.disconnect(device_id)
        self._manual.pop(device_id, None)
        self._emit("devices")

    # ------------------------------------------------------------ connection
    def _cast_info_for(self, device_id: str) -> Any:
        """mDNS CastInfo for a device id (a manual id maps to the discovered entry with the same host)."""
        discovered = self._discovered()
        if device_id in discovered:
            return discovered[device_id]
        dev = self._manual.get(device_id)
        if dev is not None:
            return next((i for i in discovered.values() if i.host == dev.host and i.port == dev.port), None)
        return None

    def _conn_lock(self, device_id: str) -> asyncio.Lock:
        return self._conn_locks.setdefault(device_id, asyncio.Lock())

    async def connect(self, device_id: str) -> None:
        if self.is_connected(device_id):
            return  # session held (pychromecast reconnects by itself after a blip)
        async with self._conn_lock(device_id):
            if self.is_connected(device_id):
                return  # another caller connected while we waited
            await self._connect(device_id)

    async def _connect(self, device_id: str) -> None:
        import pychromecast
        from pychromecast.controllers.media import DefaultMediaReceiverController

        dev = self.find_device(device_id)
        if dev is None:
            raise CastError(f"Unknown device {device_id}")
        cast_info = self._cast_info_for(device_id)

        def _connect() -> Any:
            if cast_info is not None:
                cast = pychromecast.get_chromecast_from_cast_info(
                    cast_info, self._zconf, tries=CONNECT_TRIES, timeout=CONNECT_TIMEOUT
                )
            else:
                cast = pychromecast.get_chromecast_from_host(
                    (dev.host, dev.port, uuidlib.uuid4(), dev.model, dev.name),
                    tries=CONNECT_TRIES,
                    timeout=CONNECT_TIMEOUT,
                )
            try:
                cast.wait(timeout=CONNECT_TIMEOUT)
            except Exception:
                _safe_disconnect(cast, 0)
                raise
            # initialize_connection re-reads ``tries`` on every reconnect: give the
            # reconnect phase (Wi-Fi blip, TV rebooting) far more attempts than the first connect.
            with contextlib.suppress(Exception):
                cast.socket_client.tries = RECONNECT_TRIES
            return cast

        try:
            cast = await asyncio.to_thread(_connect)
        except Exception as exc:
            raise CastError(f"Could not connect: {exc}") from exc

        st = DeviceStatus(connected=True)
        self._apply_cast_status(st, cast.status)
        self._status[device_id] = st
        self._casts[device_id] = cast
        dmr = DefaultMediaReceiverController()
        cast.register_handler(dmr)
        self._dmr[device_id] = dmr
        listener = _Listener(self, device_id, cast)
        cast.register_status_listener(listener)
        cast.media_controller.register_status_listener(listener)
        cast.register_connection_listener(listener)
        try:
            cast.register_launch_error_listener(listener)
        except Exception:  # pragma: no cover
            pass
        if device_id in self._manual:
            m = self._manual[device_id]
            self._manual[device_id] = m.model_copy(
                update={
                    "online": True,
                    "model": cast.model_name or m.model,
                    "name": m.name if not m.name.startswith("Chromecast @") else (cast.name or m.name),
                }
            )
            self._emit("devices")
        # Sync with whatever is already playing *before* the service decides whether to
        # show the idle image (the receiver answers asynchronously).
        ms = await asyncio.to_thread(_fetch_media_status, cast, STATUS_TIMEOUT)
        if ms is not None:
            self._on_media_status(device_id, ms)
        self._emit("status", device_id)

    async def disconnect(self, device_id: str) -> None:
        async with self._conn_lock(device_id):
            cast = self._casts.pop(device_id, None)
            self._dmr.pop(device_id, None)
            self._status.pop(device_id, None)
            if cast is not None:
                await asyncio.to_thread(_safe_disconnect, cast, 3)
        self._emit("status", device_id)

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._casts and device_id in self._status

    def status(self, device_id: str) -> DeviceStatus:
        return self._status.get(device_id) or DeviceStatus()

    def _cast(self, device_id: str) -> Any:
        cast = self._casts.get(device_id)
        if cast is None:
            raise CastError(f"Device {device_id} not connected")
        st = self._status.get(device_id)
        if st is not None and not st.connected:
            raise CastError("Connection to the Chromecast lost, reconnecting… try again in a moment")
        return cast

    def _drop_session(self, device_id: str, cast: Any) -> None:
        """pychromecast gave up reconnecting: forget the session (event loop thread)."""
        if self._casts.get(device_id) is not cast:
            return
        self._casts.pop(device_id, None)
        self._dmr.pop(device_id, None)
        self._status.pop(device_id, None)
        _safe_disconnect(cast, 0)
        self._emit("status", device_id)

    # ------------------------------------------------------------ listeners (socket thread)
    @staticmethod
    def _apply_cast_status(st: DeviceStatus, status: Any) -> None:
        if status is None:
            return
        st.volume_level = float(status.volume_level)
        st.muted = bool(status.volume_muted)
        st.app_name = status.display_name
        st.app_id = status.app_id

    def _on_cast_status(self, device_id: str, status: Any) -> None:
        st = self._status.get(device_id)
        if not st or status is None:
            return
        self._apply_cast_status(st, status)
        self._threadsafe_emit("status", device_id)

    def _on_connection_status(self, device_id: str, cast: Any, status: Any) -> None:
        st = self._status.get(device_id)
        if not st:
            return
        value = status.status
        st.connected = value == "CONNECTED"
        if value in SESSION_OVER and self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._drop_session, device_id, cast)
            return
        # LOST / CONNECTING / FAILED / FAILED_RESOLVE: keep the session (and the player,
        # connected=False) while pychromecast keeps retrying
        self._threadsafe_emit("status", device_id)

    def _on_media_status(self, device_id: str, ms: Any) -> None:
        st = self._status.get(device_id)
        if not st or ms is None:
            return
        prev_state, prev_reason = st.player_state, st.idle_reason
        state = ms.player_state if ms.player_state in ("IDLE", "PLAYING", "PAUSED", "BUFFERING") else "UNKNOWN"
        st.player_state = state
        st.idle_reason = ms.idle_reason
        st.title = ms.title or st.title
        images = ms.images or []
        st.thumbnail = images[0].url if images else st.thumbnail
        st.media_url = ms.content_id
        st.stream_type = "LIVE" if ms.stream_type_is_live else ("BUFFERED" if ms.stream_type else None)
        st.current_time = float(ms.current_time or 0.0)
        st.duration = float(ms.duration) if ms.duration and not ms.stream_type_is_live else None
        st.seekable = bool(ms.supports_seek) and st.duration is not None
        st.status_at = time.time()
        tracks = []
        for t in ms.subtitle_tracks or []:
            try:
                tracks.append(
                    MediaTrack(
                        id=int(t.get("trackId")),
                        type=_track_type(t.get("type")),  # type: ignore[arg-type]
                        name=t.get("name"),
                        language=t.get("language"),
                    )
                )
            except Exception:
                continue
        st.tracks = tracks
        st.active_track_ids = list(ms.current_subtitle_tracks or [])
        self._threadsafe_emit("status", device_id)
        # Only a real transition counts (not the first status seen right after connecting).
        if state == "IDLE" and ms.idle_reason == "FINISHED" and prev_state in ("PLAYING", "PAUSED", "BUFFERING"):
            self._threadsafe_emit("finished", device_id, "FINISHED")
        elif state == "IDLE" and ms.idle_reason == "ERROR" and (prev_state, prev_reason) != ("IDLE", "ERROR"):
            # accepted LOAD that then failed (dead/expired URL): the service advances the queue
            self._threadsafe_emit("finished", device_id, "ERROR")

    # ------------------------------------------------------------ media commands
    @staticmethod
    def build_play_kwargs(media: MediaRequest) -> dict[str, Any]:
        """kwargs for ``MediaController.play_media`` (pure: unit-testable)."""
        metadata: dict[str, Any] = {"metadataType": 0, "title": media.title or ""}
        kwargs: dict[str, Any] = {
            "title": media.title,
            "thumb": media.thumbnail,  # pychromecast adds it to metadata.images
            "autoplay": media.autoplay,
            "stream_type": "NONE" if media.is_image else media.stream_type,
            "metadata": metadata,
        }
        if media.current_time:
            kwargs["current_time"] = media.current_time
        media_info: dict[str, Any] = {}
        if media.hls_segment_format and not media.is_image:
            # The Default Media Receiver assumes MPEG-TS segments for HLS otherwise
            media_info["hlsSegmentFormat"] = media.hls_segment_format
            if media.hls_segment_format == "fmp4":
                media_info["hlsVideoSegmentFormat"] = "fmp4"
        if media.subtitles:
            media_info |= {
                "tracks": [
                    {
                        "trackId": i,
                        "trackContentId": sub.url,
                        "trackContentType": "text/vtt",
                        "type": "TEXT",
                        "subtype": "SUBTITLES",
                        "language": sub.lang or "und",
                        "name": sub.label,
                    }
                    for i, sub in enumerate(media.subtitles, start=1)
                ],
                "textTrackStyle": {
                    "backgroundColor": "#00000000",
                    "edgeType": "OUTLINE",
                    "edgeColor": "#000000FF",
                },
            }
        if media_info:
            kwargs["media_info"] = media_info
        return kwargs

    async def play_media(self, device_id: str, media: MediaRequest) -> None:
        self._cast(device_id)
        dmr = self._dmr.get(device_id)
        if dmr is None:  # pragma: no cover - registered on connect
            raise CastError(f"Device {device_id} not connected")
        kwargs = self.build_play_kwargs(media)
        timeout = media.load_timeout or LOAD_TIMEOUT

        def _play() -> None:
            # DefaultMediaReceiverController (app_must_match=True) launches the Default
            # Media Receiver first when another app (YouTube, Spotify, ...) is in front,
            # instead of sending our LOAD to that app's media namespace.
            done = threading.Event()
            result: dict[str, Any] = {}

            def _cb(sent: bool, response: dict[str, Any] | None) -> None:
                result["sent"], result["response"] = sent, response
                done.set()

            dmr.play_media(media.url, media.mime_type, callback_function=_cb, **kwargs)
            if not done.wait(timeout):
                raise CastError("The Chromecast did not answer the LOAD request")
            check_load_response(result.get("sent", False), result.get("response"))

        try:
            await asyncio.to_thread(_play)
        except CastError:
            raise
        except Exception as exc:
            raise CastError(f"play_media failed: {exc}") from exc

    async def _mc_call(self, device_id: str, name: str, *args: Any) -> None:
        mc = self._cast(device_id).media_controller
        try:
            await asyncio.to_thread(getattr(mc, name), *args)
        except Exception as exc:
            raise CastError(f"{name} failed: {exc}") from exc

    async def play(self, device_id: str) -> None:
        await self._mc_call(device_id, "play")

    async def pause(self, device_id: str) -> None:
        await self._mc_call(device_id, "pause")

    async def stop_media(self, device_id: str) -> None:
        await self._mc_call(device_id, "stop")

    async def seek(self, device_id: str, position: float) -> None:
        await self._mc_call(device_id, "seek", max(0.0, position))

    async def set_volume(self, device_id: str, level: float) -> None:
        cast = self._cast(device_id)
        try:
            await asyncio.to_thread(cast.set_volume, max(0.0, min(1.0, level)))
        except Exception as exc:
            raise CastError(f"volume failed: {exc}") from exc

    async def set_muted(self, device_id: str, muted: bool) -> None:
        cast = self._cast(device_id)
        try:
            await asyncio.to_thread(cast.set_volume_muted, muted)
        except Exception as exc:
            raise CastError(f"mute failed: {exc}") from exc

    async def set_active_tracks(self, device_id: str, track_ids: list[int]) -> None:
        mc = self._cast(device_id).media_controller

        def _send() -> None:
            mc._send_command({"type": "EDIT_TRACKS_INFO", "activeTrackIds": track_ids}, None)

        try:
            await asyncio.to_thread(_send)
        except Exception as exc:
            raise CastError(f"tracks failed: {exc}") from exc
