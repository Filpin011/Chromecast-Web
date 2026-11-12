"""PyChromecastDriver logic that doesn't need a device (listeners, status mapping, kwargs)."""

import asyncio
import threading
import time
from types import SimpleNamespace

import pychromecast
import pytest
from pychromecast.controllers.media import DefaultMediaReceiverController, MediaStatus

from app.models import Subtitle
from app.services.cast.base import APP_BACKDROP, APP_MEDIA_RECEIVER, CastError, DeviceStatus, MediaRequest
from app.services.cast.pychromecast_driver import (
    CONNECT_TRIES,
    MEDIA_NAMESPACE,
    RECONNECT_TRIES,
    PyChromecastDriver,
    check_load_response,
)


def media_status(**kw):
    base = dict(player_state="PLAYING", idle_reason=None, title="T", images=[SimpleNamespace(url="http://i/1.jpg")],
                content_id="http://x/v.mp4", stream_type_is_live=False, stream_type="BUFFERED", current_time=12.5,
                duration=100.0, supports_seek=True,
                subtitle_tracks=[{"trackId": 1, "type": "TEXT", "name": "IT", "language": "it"}, {"trackId": "bad"}],
                current_subtitle_tracks=[1])
    base.update(kw)
    return SimpleNamespace(**base)


def test_build_play_kwargs_with_subtitles_and_image():
    kw = PyChromecastDriver.build_play_kwargs(MediaRequest(
        url="u", mime_type="video/mp4", title="T", thumbnail="http://t.jpg", stream_type="LIVE",
        subtitles=[Subtitle(url="http://s/it.vtt", lang="it", label="Italiano"),
                   Subtitle(url="http://s/en.vtt", lang=None, label="EN")]))
    assert kw["stream_type"] == "LIVE" and kw["thumb"] == "http://t.jpg" and kw["metadata"]["title"] == "T"
    tracks = kw["media_info"]["tracks"]
    assert [t["trackId"] for t in tracks] == [1, 2] and tracks[1]["language"] == "und"
    img = PyChromecastDriver.build_play_kwargs(MediaRequest(url="u", mime_type="image/jpeg", is_image=True))
    assert img["stream_type"] == "NONE" and "media_info" not in img


async def test_media_status_mapping_and_finished_event():
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    events = []
    d.set_listener(lambda e, dev, msg: events.append((e, dev)))
    d._status["dev"] = DeviceStatus(connected=True)
    d._on_media_status("dev", media_status())
    st = d.status("dev")
    assert st.player_state == "PLAYING" and st.duration == 100.0 and st.seekable and st.stream_type == "BUFFERED"
    assert st.thumbnail == "http://i/1.jpg" and [t.id for t in st.tracks] == [1] and st.active_track_ids == [1]
    d._on_media_status("dev", media_status(player_state="IDLE", idle_reason="FINISHED"))
    d._on_media_status("dev", media_status(stream_type_is_live=True, duration=None, player_state="WEIRD"))
    assert d.status("dev").stream_type == "LIVE" and d.status("dev").duration is None
    assert d.status("dev").player_state == "UNKNOWN" and not d.status("dev").seekable
    d._on_cast_status("dev", SimpleNamespace(volume_level=0.4, volume_muted=True,
                                             display_name="Default Media Receiver", app_id=APP_MEDIA_RECEIVER))
    d._on_connection_status("dev", object(), SimpleNamespace(status="LOST"))
    await asyncio.sleep(0)
    assert ("finished", "dev") in events and ("status", "dev") in events
    assert d.status("dev").volume_level == 0.4 and not d.status("dev").connected
    assert d.status("dev").app_id == APP_MEDIA_RECEIVER


async def test_first_status_after_connect_is_not_a_finish():
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    events = []
    d.set_listener(lambda e, dev, msg: events.append(e))
    d._status["dev"] = DeviceStatus(connected=True)  # player_state UNKNOWN
    d._on_media_status("dev", media_status(player_state="IDLE", idle_reason="FINISHED"))
    await asyncio.sleep(0)
    assert "finished" not in events


async def test_receiver_error_is_reported_once_as_finished_error():
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    events = []
    d.set_listener(lambda e, dev, msg: events.append((e, msg)))
    d._status["dev"] = DeviceStatus(connected=True)
    d._on_media_status("dev", media_status(player_state="BUFFERING"))
    d._on_media_status("dev", media_status(player_state="IDLE", idle_reason="ERROR"))
    d._on_media_status("dev", media_status(player_state="IDLE", idle_reason="ERROR"))  # repeated status
    d._on_media_status("dev", media_status(player_state="PLAYING"))
    d._on_media_status("dev", media_status(player_state="IDLE", idle_reason="FINISHED"))
    await asyncio.sleep(0)
    assert [e for e in events if e[0] == "finished"] == [("finished", "ERROR"), ("finished", "FINISHED")]


async def test_manual_devices_stay_addressable_and_connectable(monkeypatch):
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    dev = await d.add_manual("10.0.0.5", 8009, None)
    assert dev.manual and dev.id == "manual-10.0.0.5" and dev.name == "Chromecast @ 10.0.0.5"
    assert dev.online  # the UI only lets users connect to online devices
    assert d.devices() == [dev]
    info = cast_info("10.0.0.5")
    d._browser = SimpleNamespace(devices={"uuid-1": info, "uuid-2": cast_info("10.0.0.6", "Camera")})
    devices = d.devices()
    # one row per host: the manual id survives mDNS finding the same device (enriched with its data)
    assert sorted(x.id for x in devices) == ["manual-10.0.0.5", "uuid-2"]
    manual = d.find_device("manual-10.0.0.5")
    assert manual is not None and manual.name == "Salotto" and manual.model == "Chromecast Ultra" and manual.online
    assert d.find_device("uuid-1") is not None and d.find_device("nope") is None
    # connecting by the manual id uses the discovered CastInfo (real uuid)
    used = {}

    def from_info(ci, zconf, **kw):
        used["info"] = ci
        return FakeCast()

    monkeypatch.setattr(pychromecast, "get_chromecast_from_cast_info", from_info)
    await d.connect("manual-10.0.0.5")
    assert used["info"] is info and d.is_connected("manual-10.0.0.5")
    with pytest.raises(CastError):
        await d.play("uuid-1")
    with pytest.raises(CastError):
        await d.connect("unknown")
    await d.remove_device("manual-10.0.0.5")
    assert d.find_device("manual-10.0.0.5") is None and not d.is_connected("manual-10.0.0.5")
    assert sorted(x.id for x in d.devices()) == ["uuid-1", "uuid-2"]


async def test_manual_device_by_ip_connects(monkeypatch):
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    await d.add_manual("10.0.0.9", 8009, None)
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda host, **kw: FakeCast(name="Studio"))
    await d.connect("manual-10.0.0.9")
    assert d.is_connected("manual-10.0.0.9") and d.status("manual-10.0.0.9").connected
    assert d.find_device("manual-10.0.0.9").name == "Studio"


async def test_reconnect_phase_gets_more_tries_than_first_connect(monkeypatch):
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    await d.add_manual("10.0.0.9", 8009, None)
    cast = FakeCast()
    seen = {}

    def from_host(host, **kw):
        seen.update(kw)
        cast.socket_client.tries = kw["tries"]
        return cast

    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", from_host)
    await d.connect("manual-10.0.0.9")
    assert seen["tries"] == CONNECT_TRIES
    assert cast.socket_client.tries == RECONNECT_TRIES and RECONNECT_TRIES > CONNECT_TRIES * 10


async def test_failed_connect_disconnects_the_half_open_cast(monkeypatch):
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    await d.add_manual("10.0.0.9", 8009, None)
    cast = FakeCast(wait_error=True)
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda host, **kw: cast)
    with pytest.raises(CastError):
        await d.connect("manual-10.0.0.9")
    assert cast.disconnected and not d.is_connected("manual-10.0.0.9")


async def connected(monkeypatch, cast) -> PyChromecastDriver:
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    await d.add_manual("10.0.0.9", 8009, None)
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda host, **kw: cast)
    await d.connect("manual-10.0.0.9")
    return d


async def test_play_media_goes_through_default_media_receiver(monkeypatch):
    cast = FakeCast(app_id="233637DE", namespaces=[MEDIA_NAMESPACE])  # YouTube in front
    d = await connected(monkeypatch, cast)
    dmr = cast.handlers[0]
    # LOADs must not go to whatever app is running (MediaController has app_must_match=False)
    assert isinstance(dmr, DefaultMediaReceiverController) and dmr.app_must_match
    assert dmr.supporting_app_id == APP_MEDIA_RECEIVER
    fake = FakeDMR({"type": "MEDIA_STATUS"})
    d._dmr["manual-10.0.0.9"] = fake
    await d.play_media("manual-10.0.0.9", MediaRequest(url="http://x/a.m3u8", mime_type="application/x-mpegURL"))
    assert fake.loads[0][0] == "http://x/a.m3u8"
    d._dmr["manual-10.0.0.9"] = FakeDMR({"type": "LOAD_FAILED", "detailedErrorCode": 905})
    with pytest.raises(CastError, match="LOAD_FAILED"):
        await d.play_media("manual-10.0.0.9", MediaRequest(url="u", mime_type="video/mp4"))
    d._dmr["manual-10.0.0.9"] = FakeDMR(None, sent=False)
    with pytest.raises(CastError):
        await d.play_media("manual-10.0.0.9", MediaRequest(url="u", mime_type="video/mp4"))


def test_check_load_response():
    check_load_response(True, {"type": "MEDIA_STATUS"})
    with pytest.raises(CastError):
        check_load_response(True, {"type": "INVALID_REQUEST", "reason": "INVALID_COMMAND"})


async def test_connect_waits_for_media_status_before_reporting(monkeypatch):
    # our app already playing (e.g. after a backend restart): status must be known when connect returns
    playing = media_status(player_state="PLAYING")
    cast = FakeCast(app_id=APP_MEDIA_RECEIVER, namespaces=[MEDIA_NAMESPACE], media=playing, status_delay=0.2)
    d = await connected(monkeypatch, cast)
    st = d.status("manual-10.0.0.9")
    assert cast.media_controller.status_requests == 1
    assert st.player_state == "PLAYING" and not st.free_for_idle_image()


async def test_connect_to_idle_device_does_not_launch_the_receiver(monkeypatch):
    cast = FakeCast(app_id=APP_BACKDROP, namespaces=[])
    d = await connected(monkeypatch, cast)
    # GET_STATUS without a media app would launch the Default Media Receiver (CEC input switch)
    assert cast.media_controller.status_requests == 0
    assert d.status("manual-10.0.0.9").free_for_idle_image()


async def test_other_app_is_never_free_for_idle_image(monkeypatch):
    cast = FakeCast(app_id="CA5E8412", namespaces=[])  # Netflix
    d = await connected(monkeypatch, cast)
    assert not d.status("manual-10.0.0.9").free_for_idle_image()


async def test_reconnect_keeps_session_and_giving_up_drops_it(monkeypatch):
    cast = FakeCast()
    d = await connected(monkeypatch, cast)
    dev = "manual-10.0.0.9"
    listener = cast.listeners[0]
    listener.new_connection_status(SimpleNamespace(status="LOST"))
    # session kept while pychromecast reconnects: no second Chromecast object is created
    assert d.is_connected(dev) and not d.status(dev).connected
    await d.connect(dev)
    assert d._casts[dev] is cast
    with pytest.raises(CastError, match="reconnecting"):
        await d.pause(dev)
    listener.new_connection_status(SimpleNamespace(status="CONNECTED"))
    assert d.status(dev).connected
    # every failed attempt inside pychromecast's retry loop: still reconnecting, session kept
    listener.new_connection_status(SimpleNamespace(status="LOST"))
    listener.new_connection_status(SimpleNamespace(status="CONNECTING"))
    listener.new_connection_status(SimpleNamespace(status="FAILED"))
    listener.new_connection_status(SimpleNamespace(status="FAILED_RESOLVE"))
    await asyncio.sleep(0.01)
    assert d.is_connected(dev) and not d.status(dev).connected and not cast.disconnected
    # DISCONNECTED = pychromecast gave up: the session is dropped
    listener.new_connection_status(SimpleNamespace(status="DISCONNECTED"))
    await asyncio.sleep(0.01)
    assert not d.is_connected(dev) and cast.disconnected
    # a stale listener from the dropped cast can't touch a new session
    cast2 = FakeCast()
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda host, **kw: cast2)
    await d.connect(dev)
    listener.new_connection_status(SimpleNamespace(status="LOST"))
    listener.new_cast_status(SimpleNamespace(volume_level=0.1, volume_muted=True, display_name="X", app_id="X"))
    assert d.status(dev).connected and d.status(dev).app_id != "X"


class FakeMediaController:
    def __init__(self, media=None, delay: float = 0.0) -> None:
        self.status = MediaStatus()
        self._media = media
        self._delay = delay
        self.status_requests = 0
        self.listeners = []

    def register_status_listener(self, listener) -> None:
        self.listeners.append(listener)

    def update_status(self, callback_function=None) -> None:
        self.status_requests += 1

        def answer() -> None:
            time.sleep(self._delay)
            if self._media is not None:
                self.status = self._media
            if callback_function:
                callback_function(True, {"type": "MEDIA_STATUS"})

        threading.Thread(target=answer, daemon=True).start()

    def pause(self) -> None:
        pass


class FakeCast:
    def __init__(self, app_id=None, namespaces=None, media=None, status_delay=0.0, name="Chromecast",
                 wait_error=False) -> None:
        self.status = SimpleNamespace(volume_level=0.5, volume_muted=False, display_name="App", app_id=app_id)
        self.socket_client = SimpleNamespace(app_namespaces=list(namespaces or []))
        self.media_controller = FakeMediaController(media, status_delay)
        self.model_name = "Chromecast Ultra"
        self.name = name
        self.handlers = []
        self.listeners = []
        self.disconnected = False
        self.wait_error = wait_error

    def wait(self, timeout=None) -> None:
        if self.wait_error:
            raise TimeoutError("wait")

    def disconnect(self, timeout=None) -> None:
        self.disconnected = True

    def register_handler(self, handler) -> None:
        self.handlers.append(handler)

    def register_status_listener(self, listener) -> None:
        self.listeners.append(listener)

    def register_connection_listener(self, listener) -> None:
        pass

    def register_launch_error_listener(self, listener) -> None:
        pass


class FakeDMR:
    def __init__(self, response, sent: bool = True) -> None:
        self.response = response
        self.sent = sent
        self.loads = []

    def play_media(self, url, content_type, callback_function=None, **kw) -> None:
        self.loads.append((url, content_type, kw))
        callback_function(self.sent, self.response)


def cast_info(host: str, name: str = "Salotto"):
    return SimpleNamespace(friendly_name=name, host=host, port=8009, model_name="Chromecast Ultra",
                           cast_type="cast", manufacturer="Google Inc.")


def test_build_play_kwargs_hls_segment_formats():
    fmp4 = PyChromecastDriver.build_play_kwargs(MediaRequest(
        url="u", mime_type="application/x-mpegURL", hls_segment_format="fmp4",
        subtitles=[Subtitle(url="http://s/it.vtt", lang="it", label="IT")]))
    info = fmp4["media_info"]
    assert info["hlsSegmentFormat"] == "fmp4" and info["hlsVideoSegmentFormat"] == "fmp4"
    assert info["tracks"][0]["trackContentId"] == "http://s/it.vtt"  # merged, not replaced
    aac = PyChromecastDriver.build_play_kwargs(MediaRequest(
        url="u", mime_type="application/x-mpegURL", hls_segment_format="aac"))
    assert aac["media_info"] == {"hlsSegmentFormat": "aac"}
    ts = PyChromecastDriver.build_play_kwargs(MediaRequest(url="u", mime_type="application/x-mpegURL"))
    assert "media_info" not in ts


async def test_play_media_honours_request_load_timeout(monkeypatch):
    cast = FakeCast()
    d = await connected(monkeypatch, cast)

    class SilentDMR:
        def play_media(self, *a, **kw):
            pass  # the receiver never answers

    d._dmr["manual-10.0.0.9"] = SilentDMR()
    started = time.monotonic()
    with pytest.raises(CastError, match="did not answer"):
        await d.play_media("manual-10.0.0.9", MediaRequest(url="u", mime_type="video/mp4", load_timeout=0.2))
    assert time.monotonic() - started < 5


async def test_concurrent_connects_create_a_single_cast(monkeypatch):
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    await d.add_manual("10.0.0.9", 8009, None)
    created = []

    def slow_connect(host, **kw):
        time.sleep(0.1)  # blocking connect in the worker thread
        created.append(FakeCast())
        return created[-1]

    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", slow_connect)
    await asyncio.gather(*(d.connect("manual-10.0.0.9") for _ in range(3)))
    assert len(created) == 1 and d._casts["manual-10.0.0.9"] is created[0]
    await asyncio.gather(d.disconnect("manual-10.0.0.9"), d.connect("manual-10.0.0.9"))
    # whatever the order, no Chromecast object is left connected without being tracked
    live = [c for c in created if not c.disconnected]
    assert len(live) == len(d._casts) <= 1


class RacyDevices(dict):
    """A CastBrowser.devices whose first copy fails like a concurrent zeroconf update."""

    def __init__(self, *a):
        super().__init__(*a)
        self.fail = 1

    def _check(self):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("dictionary changed size during iteration")

    def __iter__(self):  # makes dict(self) take the keys()/__getitem__ path
        self._check()
        return super().__iter__()

    def keys(self):
        self._check()
        return super().keys()


async def test_connected_device_survives_mdns_removal_and_racy_copies(monkeypatch):
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    info = cast_info("10.0.0.7", "Camera")
    d._browser = SimpleNamespace(devices=RacyDevices({"uuid-7": info}), _services_lock=threading.Lock())
    assert [x.id for x in d.devices()] == ["uuid-7"]  # retried, not an empty list
    assert d._browser.devices.fail == 0
    monkeypatch.setattr(pychromecast, "get_chromecast_from_cast_info", lambda ci, z, **kw: FakeCast())
    await d.connect("uuid-7")
    d._browser.devices = {}  # mDNS goodbye / TTL expiry while connected
    assert d.find_device("uuid-7") is not None and [x.id for x in d.devices()] == ["uuid-7"]
    await d.disconnect("uuid-7")
    assert d.find_device("uuid-7") is None  # only sessions keep a vanished record alive
