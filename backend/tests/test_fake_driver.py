import asyncio

import pytest

from app.models import Subtitle
from app.services.cast.base import CastDriver, CastError, MediaRequest
from app.services.cast.fake import FakeCastDriver

DEV = "fake-ultra-0001"


@pytest.fixture
async def drv():
    d = FakeCastDriver(delay=0.02, vod_duration=0.3)
    events: list = []
    d.set_listener(lambda e, dev, msg: events.append((e, dev)))
    d.events = events  # type: ignore[attr-defined]
    await d.start()
    yield d
    await d.stop()


async def test_protocol_and_devices(drv):
    assert isinstance(drv, CastDriver)
    names = [d.name for d in drv.devices()]
    assert "Chromecast Ultra (fake)" in names and len(names) == 2
    assert await drv.discover(0.01)
    manual = await drv.add_manual("10.0.0.9", 8009, None)
    assert manual.id == "manual-10.0.0.9" and manual.manual
    await drv.remove_device(manual.id)
    assert len(drv.devices()) == 2


async def test_requires_connection(drv):
    with pytest.raises(CastError):
        await drv.play(DEV)
    with pytest.raises(CastError):
        await drv.connect("nope")


async def test_play_progression_controls_and_finish(drv):
    await drv.connect(DEV)
    assert drv.status(DEV).player_state == "IDLE"
    await drv.play_media(DEV, MediaRequest(url="http://x/v.mp4", mime_type="video/mp4", title="V",
                                           subtitles=[Subtitle(url="http://x/s.vtt", lang="it", label="IT")]))
    st = drv.status(DEV)
    assert st.player_state == "BUFFERING" and st.duration == 0.3 and st.seekable
    assert {t.type for t in st.tracks} == {"AUDIO", "TEXT"}
    await asyncio.sleep(0.05)
    assert drv.status(DEV).player_state == "PLAYING"
    await drv.pause(DEV)
    pos = drv.status(DEV).position_now()
    await asyncio.sleep(0.05)
    assert drv.status(DEV).position_now() == pos
    await drv.seek(DEV, 0.1)
    await drv.set_volume(DEV, 1.7)
    await drv.set_muted(DEV, True)
    await drv.set_active_tracks(DEV, [1, 999])
    st = drv.status(DEV)
    assert st.current_time == 0.1 and st.volume_level == 1.0 and st.muted and st.active_track_ids == [1]
    await drv.play(DEV)
    await asyncio.sleep(0.4)
    st = drv.status(DEV)
    assert st.player_state == "IDLE" and st.idle_reason == "FINISHED"
    assert ("finished", DEV) in drv.events


async def test_live_and_image_media(drv):
    await drv.connect(DEV)
    await drv.play_media(DEV, MediaRequest(url="http://x/l.m3u8", mime_type="application/x-mpegURL",
                                           stream_type="LIVE"))
    st = drv.status(DEV)
    assert st.duration is None and not st.seekable and st.stream_type == "LIVE"
    await drv.play_media(DEV, MediaRequest(url="http://x/idle.jpg", mime_type="image/jpeg", is_image=True))
    assert drv.status(DEV).tracks == [] and drv.status(DEV).stream_type is None
    await drv.stop_media(DEV)
    assert drv.status(DEV).player_state == "IDLE" and drv.status(DEV).media_url is None
    await drv.disconnect(DEV)
    assert not drv.is_connected(DEV)


async def test_pause_while_buffering_sticks(drv):
    await drv.connect(DEV)
    await drv.play_media(DEV, MediaRequest(url="http://x/v.mp4", mime_type="video/mp4", title="V"))
    assert drv.status(DEV).player_state == "BUFFERING"
    await drv.pause(DEV)
    await asyncio.sleep(0.05)
    assert drv.status(DEV).player_state == "PAUSED"
    await drv.play(DEV)
    assert drv.status(DEV).player_state == "PLAYING"
