from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from app.config import AppConfig
from app.errors import AppError
from app.services.cast.fake import FakeCastDriver
from app.services.container import build_services
from tests.fakes import ytdlp_info

DEV = "fake-ultra-0001"
MP4 = "https://cdn.example.com/a.mp4"
MP4B = "https://cdn.example.com/b.mp4"


@pytest.fixture
async def svc(config: AppConfig):
    driver = FakeCastDriver(delay=0.01, vod_duration=0.25)
    s = build_services(config, driver=driver, in_memory_db=True, http_client=httpx.AsyncClient(),
                       ytdlp_extractor=ytdlp_info)
    s.db.update_settings({"show_idle_on_connect": False, "show_idle_on_stop": False})
    with respx.mock(assert_all_called=False):
        await s.start()
        yield s
        await s.stop()


async def wait(cond, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


async def test_connect_sets_active_and_broadcasts(svc):
    q = svc.hub.subscribe()
    p = await svc.cast.connect(DEV)
    assert p.connected and svc.hub.active_device_id == DEV
    assert DEV in svc.hub.snapshot().players
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    assert msgs and all(m["type"] == "state" for m in msgs)
    versions = [m["data"]["version"] for m in msgs]
    assert versions == sorted(versions)


async def test_unknown_device(svc):
    with pytest.raises(AppError) as e:
        await svc.cast.connect("ghost")
    assert e.value.code == "device_not_found"


async def test_play_records_history_and_metadata(svc):
    p = await svc.cast.play(DEV, MP4, title="My film")  # auto-connects
    assert p.title == "My film" and p.original_input == MP4
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    hist = svc.db.list_history()
    assert hist[0].input == MP4 and hist[0].device_id == DEV and hist[0].source_kind == "direct"


async def test_control_actions(svc):
    await svc.cast.play(DEV, MP4)
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    assert (await svc.cast.control(DEV, "pause", None)).player_state == "PAUSED"
    assert (await svc.cast.control(DEV, "toggle", None)).player_state == "PLAYING"
    p = await svc.cast.control(DEV, "seek", 0.1)
    assert p.current_time >= 0.1
    p = await svc.cast.control(DEV, "volume", 0.3)
    assert p.volume_level == pytest.approx(0.3)
    p = await svc.cast.control(DEV, "volume_relative", -0.5)
    assert p.volume_level == 0.0
    assert (await svc.cast.control(DEV, "mute", None)).muted
    assert not (await svc.cast.control(DEV, "unmute", None)).muted
    with pytest.raises(AppError):
        await svc.cast.control(DEV, "seek", None)
    with pytest.raises(AppError) as e:
        await svc.cast.control(DEV, "next", None)
    assert e.value.code == "queue_empty"
    p = await svc.cast.control(DEV, "stop", None)
    assert p.player_state == "IDLE"


async def test_control_requires_connection(svc):
    with pytest.raises(AppError) as e:
        await svc.cast.control(DEV, "play", None)
    assert e.value.code == "not_connected"


async def test_queue_advances_on_finished_then_idle_image(svc):
    svc.db.update_settings({"show_idle_on_stop": True})
    await svc.cast.play(DEV, MP4)
    p = await svc.cast.play(DEV, MP4B, enqueue=True)
    assert [i.input for i in p.queue] == [MP4B]
    await wait(lambda: svc.cast.player(DEV).original_input == MP4B, timeout=3)
    assert svc.cast.player(DEV).queue == []
    await wait(lambda: svc.cast.player(DEV).showing_idle_image, timeout=3)
    assert svc.cast.player(DEV).title is None


async def test_enqueue_when_idle_plays_immediately_and_queue_ops(svc):
    await svc.cast.connect(DEV)
    p = await svc.cast.enqueue(DEV, MP4)
    assert p.original_input == MP4 and p.queue == []
    await svc.cast.enqueue(DEV, MP4B, title="B")
    p = await svc.cast.enqueue(DEV, "https://cdn.example.com/c.mp4", title="C")
    ids = [i.id for i in p.queue]
    assert [i.title for i in p.queue] == ["B", "C"]
    p = svc.cast.reorder_queue(DEV, list(reversed(ids)))
    assert [i.title for i in p.queue] == ["C", "B"]
    p = svc.cast.remove_from_queue(DEV, ids[0])
    assert [i.title for i in p.queue] == ["C"]
    with pytest.raises(AppError):
        svc.cast.remove_from_queue(DEV, "missing")
    p = await svc.cast.control(DEV, "next", None)
    assert p.original_input == "https://cdn.example.com/c.mp4"
    p = await svc.cast.control(DEV, "previous", None)
    assert p.original_input == MP4


async def test_idle_image_on_connect(svc):
    svc.db.update_settings({"show_idle_on_connect": True, "idle_image_url": "https://img.example.com/x.png"})
    p = await svc.cast.connect(DEV)
    assert p.showing_idle_image and p.media_url == "https://img.example.com/x.png"
    assert svc.cast.driver.calls[-1][2].mime_type == "image/png"


async def test_go_live_reloads_live_stream(svc):
    respx.get("https://cdn.example.com/live/index.m3u8").respond(200, text="#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\ns.ts\n")
    await svc.cast.play(DEV, "https://cdn.example.com/live/index.m3u8")
    n = len([c for c in svc.cast.driver.calls if c[0] == "play_media"])
    await svc.cast.control(DEV, "go_live", None)
    assert len([c for c in svc.cast.driver.calls if c[0] == "play_media"]) == n + 1


async def test_manual_device_persisted_and_removed(svc):
    dev = await svc.cast.add_manual("192.168.1.77", 8009, "Kitchen")
    assert any(d.id == dev.id for d in svc.hub.devices)
    assert svc.db.list_manual_devices()[0].host == "192.168.1.77"
    with pytest.raises(AppError):
        await svc.cast.remove_device(DEV)  # not manual
    await svc.cast.remove_device(dev.id)
    assert svc.db.list_manual_devices() == []


async def test_discover_toggles_flag(svc):
    seen = []
    svc.hub.add_listener(lambda st: seen.append(st.discovering))
    devices = await svc.cast.discover()
    assert len(devices) == 2
    assert True in seen and seen[-1] is False


async def test_tracks(svc):
    await svc.cast.play(DEV, MP4)
    p = await svc.cast.set_tracks(DEV, [100])
    assert p.active_track_ids == [100]


async def test_enqueue_on_disconnected_device_connects_and_plays(svc):
    assert not svc.cast.driver.is_connected(DEV)
    p = await svc.cast.enqueue(DEV, MP4, title="A")
    assert p.connected and p.original_input == MP4 and p.queue == []
    assert DEV in svc.hub.snapshot().players and svc.hub.active_device_id == DEV


async def test_idle_image_never_covers_another_app_or_playing_media(svc):
    svc.db.update_settings({"show_idle_on_connect": True})
    driver = svc.cast.driver
    original = driver.connect

    async def connect_into_netflix(device_id):
        await original(device_id)
        st = driver.status(device_id)
        st.app_id, st.app_name, st.player_state = "CA5E8412", "Netflix", "PLAYING"

    driver.connect = connect_into_netflix
    p = await svc.cast.connect(DEV)
    assert not p.showing_idle_image
    assert not [c for c in driver.calls if c[0] == "play_media"]


async def test_idle_image_skipped_when_our_receiver_is_already_playing(svc):
    svc.db.update_settings({"show_idle_on_connect": True})
    driver = svc.cast.driver
    original = driver.connect

    async def connect_playing(device_id):
        await original(device_id)
        st = driver.status(device_id)
        st.app_id, st.player_state, st.media_url = "CC1AD845", "PLAYING", "http://x/live.m3u8"

    driver.connect = connect_playing
    p = await svc.cast.connect(DEV)
    assert not p.showing_idle_image and p.player_state == "PLAYING"


def loads(svc) -> list:
    return [c[2] for c in svc.cast.driver.calls if c[0] == "play_media"]


async def test_finish_racing_with_enqueue_loads_once(svc):
    await svc.cast.play(DEV, MP4)
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    await svc.cast.enqueue(DEV, MP4B, title="B")  # busy → queued
    # the receiver reports the end of A: the "finished" task is spawned...
    svc.cast.driver._cancel(DEV)
    st = svc.cast.driver.status(DEV)
    st.player_state, st.idle_reason = "IDLE", "FINISHED"
    n = len(loads(svc))
    svc.cast._on_event("finished", DEV, None)
    # ...and before it runs another phone enqueues C on the now idle device
    await svc.cast.enqueue(DEV, "https://cdn.example.com/c.mp4", title="C")
    await asyncio.sleep(0.05)
    new = loads(svc)[n:]
    assert [m.url for m in new] == [MP4B]  # one LOAD, nothing silently skipped
    assert [i.title for i in svc.cast.player(DEV).queue] == ["C"]


async def test_next_racing_with_finish_does_not_skip(svc):
    await svc.cast.play(DEV, MP4)
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    await svc.cast.enqueue(DEV, MP4B, title="B")
    await svc.cast.enqueue(DEV, "https://cdn.example.com/c.mp4", title="C")
    svc.cast.driver._cancel(DEV)
    n = len(loads(svc))
    svc.cast._on_event("finished", DEV, None)  # stale once "next" has loaded B
    await svc.cast.control(DEV, "next", None)
    await asyncio.sleep(0.05)
    assert [m.url for m in loads(svc)[n:]] == [MP4B]
    assert [i.title for i in svc.cast.player(DEV).queue] == ["C"]


async def test_restreamed_load_waits_longer_and_warms_ffmpeg(svc, monkeypatch):
    from app.services.cast.service import RESTREAM_LOAD_TIMEOUT

    warmed = []
    monkeypatch.setattr(svc.resolver.restream, "warm", lambda job: warmed.append(job.token))
    await svc.cast.play(DEV, "rtmp://live.example.com/app/key")
    req = loads(svc)[-1]
    assert req.load_timeout == RESTREAM_LOAD_TIMEOUT and "/restream/" in req.url
    assert warmed and req.url.endswith(f"/restream/{warmed[0]}/index.m3u8")
    await svc.cast.play(DEV, MP4)
    assert loads(svc)[-1].load_timeout is None


async def test_fmp4_hls_segment_format_reaches_the_driver(svc):
    acao = {"access-control-allow-origin": "*"}
    with respx.mock(assert_all_called=True) as router:
        router.get("https://cdn.example.com/cmaf/index.m3u8").respond(
            200, text='#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4,\ns1.m4s\n',
            headers=acao)
        router.get("https://cdn.example.com/cmaf/s1.m4s").respond(200, content=b"x", headers=acao)
        await svc.cast.play(DEV, "https://cdn.example.com/cmaf/index.m3u8")
    req = loads(svc)[-1]
    assert req.hls_segment_format == "fmp4" and req.url == "https://cdn.example.com/cmaf/index.m3u8"


async def test_stale_queue_entries_are_resolved_again(svc, monkeypatch):
    """yt-dlp/page URLs expire: an entry that waited in the queue is resolved again."""
    from app.services.cast import service as cast_service

    svc.cast.driver.vod_duration = 60  # nothing finishes by itself during the test
    await svc.cast.play(DEV, MP4)
    await svc.cast.enqueue(DEV, "https://www.youtube.com/watch?v=abc")
    (entry,) = svc.cast.queue._items[DEV]
    assert entry.media is not None and not entry.pinned
    calls = []
    real = svc.resolver.resolve_media

    async def counting(value, kind=None, title=None):
        calls.append(value)
        media = await real(value, kind, title)
        media.cast_url += "&fresh=1"
        return media

    monkeypatch.setattr(svc.resolver, "resolve_media", counting)
    entry.resolved_at -= cast_service.RERESOLVE_AFTER + 1
    p = await svc.cast.control(DEV, "next", None)
    assert calls == ["https://www.youtube.com/watch?v=abc"]
    assert loads(svc)[-1].url.endswith("&fresh=1") and p.title == "Some Video"
    # a fresh entry is played as resolved at enqueue time
    await svc.cast.enqueue(DEV, MP4B)  # resolved here (enqueue validates the input)...
    await svc.cast.control(DEV, "next", None)  # ...and not again when it plays right away
    assert calls == ["https://www.youtube.com/watch?v=abc", MP4B] and loads(svc)[-1].url.startswith(MP4B)


async def test_pinned_entries_are_never_resolved_again(svc, monkeypatch):
    from app.services.cast import service as cast_service

    svc.cast.driver.vod_duration = 60
    await svc.cast.play(DEV, MP4)
    media = await svc.resolver.resolve_media(MP4B)
    media.cast_url = "http://cast.test/proxy/tok/captured.m3u8"
    await svc.cast.enqueue(DEV, "https://page.example.com/watch", "webpage", "Captured", media=media, pinned=True)
    (entry,) = svc.cast.queue._items[DEV]
    entry.resolved_at -= cast_service.RERESOLVE_AFTER + 1

    async def boom(*a, **kw):
        raise AssertionError("must not re-resolve a captured stream")

    monkeypatch.setattr(svc.resolver, "resolve_media", boom)
    await svc.cast.control(DEV, "next", None)
    assert loads(svc)[-1].url == "http://cast.test/proxy/tok/captured.m3u8"


async def test_receiver_error_after_load_advances_the_queue(svc):
    """The receiver accepts the LOAD of a dead URL and then reports IDLE/ERROR: skip it."""
    q = svc.hub.subscribe()
    svc.cast.driver.vod_duration = 60
    await svc.cast.play(DEV, MP4, title="Dead")
    await svc.cast.enqueue(DEV, MP4B, title="B")
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).original_input == MP4B)
    assert svc.cast.player(DEV).queue == []
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    assert any(m["type"] == "toast" and m["level"] == "error" and "Dead" in m["message"] for m in msgs)


async def test_restream_of_loaded_media_survives_the_reaper(svc):
    await svc.cast.play(DEV, "rtmp://live.example.com/app/key")
    job = svc.resolver.restream.job_for_url(loads(svc)[-1].url)
    assert job is not None and svc.resolver.restream.in_use(job)
    await svc.cast.play(DEV, MP4)
    assert not svc.resolver.restream.in_use(job)
