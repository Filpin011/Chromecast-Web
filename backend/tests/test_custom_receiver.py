"""Optional custom Cast Web Receiver (CAST_APP_ID): default stays the Default Media Receiver."""

import asyncio
from collections.abc import Iterator

import pychromecast
import pytest
from fastapi.testclient import TestClient
from pychromecast import dial
from pychromecast.controllers.media import DefaultMediaReceiverController

from app.config import AppConfig
from app.main import create_app
from app.services.cast import pychromecast_driver as drv
from app.services.cast.base import (
    APP_BACKDROP,
    APP_MEDIA_RECEIVER,
    CastError,
    DeviceStatus,
    MediaRequest,
    is_own_receiver,
    receiver_app_id,
    set_receiver_app_id,
)
from app.services.cast.fake import FakeCastDriver
from app.services.cast.pychromecast_driver import MEDIA_NAMESPACE, PyChromecastDriver, check_load_response
from tests.test_pychromecast_driver import FakeCast

CUSTOM = "ABCD1234"
DEV = "fake-ultra-0001"


@pytest.fixture(autouse=True)
def reset_receiver() -> Iterator[None]:
    set_receiver_app_id(None)
    yield
    set_receiver_app_id(None)


@pytest.fixture
def lan(monkeypatch):
    monkeypatch.setattr(drv, "_port_open", lambda host, port, timeout: True)
    monkeypatch.setattr(dial, "get_device_info", lambda host, **kw: None)


def test_config_reads_env(monkeypatch):
    monkeypatch.setenv("CAST_APP_ID", CUSTOM)
    assert AppConfig().cast_app_id == CUSTOM
    monkeypatch.delenv("CAST_APP_ID")
    assert AppConfig().cast_app_id is None


def test_helper_defaults_and_normalizes():
    assert receiver_app_id() == APP_MEDIA_RECEIVER
    set_receiver_app_id("  abcd1234 ")
    assert receiver_app_id() == CUSTOM
    set_receiver_app_id("")
    assert receiver_app_id() == APP_MEDIA_RECEIVER


def test_create_app_applies_config(config):
    create_app(config)
    assert receiver_app_id() == APP_MEDIA_RECEIVER
    create_app(config.model_copy(update={"cast_app_id": CUSTOM}))
    assert receiver_app_id() == CUSTOM


def test_idle_image_check_treats_custom_receiver_as_ours():
    assert DeviceStatus(app_id=APP_MEDIA_RECEIVER, player_state="IDLE").free_for_idle_image()
    assert not DeviceStatus(app_id=CUSTOM, player_state="IDLE").free_for_idle_image()
    set_receiver_app_id(CUSTOM)
    assert is_own_receiver(CUSTOM) and is_own_receiver(APP_MEDIA_RECEIVER)
    assert DeviceStatus(app_id=CUSTOM, player_state="IDLE").free_for_idle_image()
    assert DeviceStatus(app_id=APP_BACKDROP).free_for_idle_image()
    assert not DeviceStatus(app_id=CUSTOM, player_state="PLAYING").free_for_idle_image()
    assert not DeviceStatus(app_id="CA5E8412", player_state="IDLE").free_for_idle_image()


@pytest.mark.parametrize(("configured", "expected"), [(None, APP_MEDIA_RECEIVER), (CUSTOM, CUSTOM)])
async def test_fake_driver_uses_configured_receiver(configured, expected):
    set_receiver_app_id(configured)
    d = FakeCastDriver(delay=0.01)
    await d.start()
    try:
        await d.connect(DEV)
        await d.play_media(DEV, MediaRequest(url="http://x/a.mp4", mime_type="video/mp4"))
        st = d.status(DEV)
        assert st.app_id == expected
        assert st.app_name == ("Default Media Receiver" if configured is None else "Chromecast-Web Receiver")
    finally:
        await d.stop()


async def _connected(monkeypatch, cast) -> PyChromecastDriver:
    d = PyChromecastDriver()
    d._loop = asyncio.get_running_loop()
    await d.add_manual("10.0.0.9", 8009, None)
    monkeypatch.setattr(pychromecast, "get_chromecast_from_cast_info", lambda ci, z, **kw: cast)
    await d.connect("manual-10.0.0.9")
    return d


async def test_driver_default_launches_default_media_receiver(monkeypatch, lan):
    cast = FakeCast(app_id=APP_BACKDROP, namespaces=[MEDIA_NAMESPACE])
    await _connected(monkeypatch, cast)
    ctrl = cast.handlers[0]
    assert type(ctrl) is DefaultMediaReceiverController
    assert ctrl.supporting_app_id == APP_MEDIA_RECEIVER and ctrl.app_must_match
    with pytest.raises(CastError, match="Default Media Receiver"):
        check_load_response(False, None)


async def test_driver_launches_custom_receiver_when_configured(monkeypatch, lan):
    set_receiver_app_id(CUSTOM)
    cast = FakeCast(app_id="233637DE", namespaces=[MEDIA_NAMESPACE])  # YouTube in front
    await _connected(monkeypatch, cast)
    ctrl = cast.handlers[0]
    assert not isinstance(ctrl, DefaultMediaReceiverController)
    # app_must_match: pychromecast launches our app first instead of LOADing into YouTube
    assert ctrl.supporting_app_id == CUSTOM and ctrl.app_must_match
    with pytest.raises(CastError, match="Chromecast-Web Receiver"):
        check_load_response(False, None)


@pytest.fixture
def plain_client(config) -> Iterator[TestClient]:
    app = create_app(config, driver=FakeCastDriver(delay=0.01))
    with TestClient(app) as c:
        yield c


def test_receiver_page_is_served(plain_client):
    r = plain_client.get("/receiver/index.html")
    assert r.status_code == 200 and "cast_receiver_framework.js" in r.text
    assert plain_client.get("/receiver/").status_code == 200
    js = plain_client.get("/receiver/receiver.js")
    assert js.status_code == 200 and "setMessageInterceptor" in js.text
    assert plain_client.get("/receiver/receiver.css").status_code == 200
    assert plain_client.get("/receiver/nope.js").status_code == 404
