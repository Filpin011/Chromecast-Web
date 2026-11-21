"""Auto-recovery of a stream the receiver dropped mid-playback, and stalled_since."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from app.config import AppConfig
from app.services.cast import service as cast_service
from app.services.cast.base import CastError
from app.services.cast.fake import FakeCastDriver
from app.services.container import build_services
from tests.fakes import ytdlp_info

DEV = "fake-ultra-0001"
LIVE = "https://cdn.example.com/live/index.m3u8"
MP4 = "https://cdn.example.com/a.mp4"
MP4B = "https://cdn.example.com/b.mp4"
LIVE_PLAYLIST = "#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXTINF:3,\ns.ts\n"


@pytest.fixture(autouse=True)
def fast_recovery(monkeypatch):
    monkeypatch.setattr(cast_service, "RECOVERY_BACKOFF", (0.02, 0.05, 0.1))
    monkeypatch.setattr(cast_service, "RECOVERY_MIN_PLAYED", 0.3)
    monkeypatch.setattr(cast_service, "RECOVERY_OUTCOME_TIMEOUT", 1.0)
    monkeypatch.setattr(cast_service, "STALL_AFTER", 0.1)
    monkeypatch.setattr(cast_service, "STEADY_AFTER", 0.05)
    monkeypatch.setattr(cast_service, "LIVE_STALL_RELOAD", 60.0)  # the watchdog has its own tests


@pytest.fixture
async def svc(config: AppConfig):
    driver = FakeCastDriver(delay=0.01, vod_duration=60)
    s = build_services(
        config, driver=driver, in_memory_db=True, http_client=httpx.AsyncClient(), ytdlp_extractor=ytdlp_info
    )
    s.db.update_settings({"show_idle_on_connect": False, "show_idle_on_stop": False})
    with respx.mock(assert_all_called=False):
        respx.get(LIVE).respond(200, text=LIVE_PLAYLIST)
        await s.start()
        yield s
        await s.stop()


async def wait(cond, timeout=3.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


def loads(svc):
    return [c[2] for c in svc.cast.driver.calls if c[0] == "play_media"]


def toasts(q):
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    return [m for m in msgs if m["type"] == "toast"]


def states(q):
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    return [m["data"]["players"].get(DEV) for m in msgs if m["type"] == "state"]


async def start_live(svc):
    await svc.cast.play(DEV, LIVE, title="Live")
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    assert svc.cast.player(DEV).stream_type == "LIVE"


async def test_dropped_live_stream_recovers_on_attempt_two(svc):
    await start_live(svc)
    await svc.cast.enqueue(DEV, MP4B, title="B")
    n = len(loads(svc))
    q = svc.hub.subscribe()
    svc.cast.driver.fail_next_loads = 1  # the first reload fails too
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).recovering)
    await wait(lambda: not svc.cast.player(DEV).recovering and svc.cast.player(DEV).player_state == "PLAYING")
    p = svc.cast.player(DEV)
    assert p.original_input == LIVE and p.recovery_attempt == 0
    assert [i.title for i in p.queue] == ["B"]  # the queue did not advance
    assert len(loads(svc)) == n + 2
    t = toasts(q)
    assert [m["code"] for m in t] == ["stream_reconnecting", "stream_reconnecting", "stream_restored"]
    assert t[0]["params"] == {"title": "Live", "attempt": 1, "max": 3}
    assert t[1]["params"]["attempt"] == 2
    assert not [m for m in t if m["level"] == "error"]


async def test_recovery_state_is_broadcast(svc):
    await start_live(svc)
    q = svc.hub.subscribe()
    svc.cast.driver.fail(DEV)
    await wait(lambda: not svc.cast.player(DEV).recovering and svc.cast.player(DEV).player_state == "PLAYING")
    players = [p for p in states(q) if p]
    assert any(p["recovering"] and p["recovery_attempt"] == 1 and p["title"] == "Live" for p in players)
    assert not players[-1]["recovering"] and players[-1]["recovery_attempt"] == 0


async def test_exhausted_attempts_fall_back_to_skip_and_toast(svc):
    await start_live(svc)
    await svc.cast.enqueue(DEV, MP4B, title="B")
    q = svc.hub.subscribe()
    svc.cast.driver.fail_next_loads = 3
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).original_input == MP4B)
    p = svc.cast.player(DEV)
    assert not p.recovering and p.queue == []
    t = toasts(q)
    assert [m["code"] for m in t] == [
        "stream_reconnecting",
        "stream_reconnecting",
        "stream_reconnecting",
        "playback_failed",
    ]
    assert t[-1]["params"] == {"title": "Live"}


async def test_exhausted_attempts_show_the_idle_image(svc):
    svc.db.update_settings({"show_idle_on_stop": True})
    await start_live(svc)
    svc.cast.driver.fail_next_loads = 3
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).showing_idle_image)
    assert not svc.cast.player(DEV).recovering


async def test_rejected_reload_counts_as_failed_attempt(svc, monkeypatch):
    await start_live(svc)
    driver = svc.cast.driver
    real_play = driver.play_media
    rejected = []

    async def reject_once(device_id, media):
        if not rejected:
            rejected.append(media.url)
            raise CastError("The Chromecast refused the media (LOAD_FAILED, 905)")
        return await real_play(device_id, media)

    monkeypatch.setattr(driver, "play_media", reject_once)
    driver.fail(DEV)
    await wait(lambda: not svc.cast.player(DEV).recovering and svc.cast.player(DEV).player_state == "PLAYING")
    assert rejected == [svc.cast.player(DEV).media_url]


async def test_user_stop_cancels_recovery(svc, monkeypatch):
    monkeypatch.setattr(cast_service, "RECOVERY_BACKOFF", (0.3, 0.3, 0.3))
    await start_live(svc)
    n = len(loads(svc))
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).recovering)
    p = await svc.cast.control(DEV, "stop", None)
    assert not p.recovering
    await asyncio.sleep(0.5)
    assert len(loads(svc)) == n  # no reload after the stop
    assert not svc.cast.player(DEV).recovering
    assert not svc.cast._recovery_tasks


async def test_new_media_cancels_recovery(svc, monkeypatch):
    monkeypatch.setattr(cast_service, "RECOVERY_BACKOFF", (0.3, 0.3, 0.3))
    await start_live(svc)
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).recovering)
    await svc.cast.play(DEV, MP4, title="A")
    await asyncio.sleep(0.5)
    assert loads(svc)[-1].url == MP4
    assert not svc.cast.player(DEV).recovering


async def test_play_while_recovering_retries_now(svc, monkeypatch):
    monkeypatch.setattr(cast_service, "RECOVERY_BACKOFF", (5.0, 5.0, 5.0))
    await start_live(svc)
    n = len(loads(svc))
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).recovering)
    p = await svc.cast.control(DEV, "toggle", None)
    assert not p.recovering
    assert len(loads(svc)) == n + 1
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")


async def test_vod_failing_early_keeps_the_old_behaviour(svc):
    q = svc.hub.subscribe()
    await svc.cast.play(DEV, MP4, title="Dead")
    await svc.cast.enqueue(DEV, MP4B, title="B")
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    svc.cast.driver.fail(DEV)  # after a few ms, well below RECOVERY_MIN_PLAYED
    await wait(lambda: svc.cast.player(DEV).original_input == MP4B)
    t = toasts(q)
    assert [m["code"] for m in t] == ["playback_failed"]


async def test_vod_that_played_long_enough_is_recovered(svc):
    await svc.cast.play(DEV, MP4, title="Film")
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    await asyncio.sleep(0.35)  # > RECOVERY_MIN_PLAYED (patched)
    svc.cast.driver.fail(DEV)
    await wait(lambda: svc.cast.player(DEV).recovering)
    await wait(lambda: not svc.cast.player(DEV).recovering and svc.cast.player(DEV).player_state == "PLAYING")
    assert loads(svc)[-1].url == MP4


async def test_live_that_never_played_is_not_recovered(svc):
    q = svc.hub.subscribe()
    svc.cast.driver.fail_next_loads = 1  # accepted, then IDLE/ERROR before any PLAYING
    await svc.cast.play(DEV, LIVE, title="Live")
    await wait(lambda: any(m.get("code") == "playback_failed" for m in toasts(q)))
    assert not svc.cast.player(DEV).recovering


async def test_live_that_keeps_dying_right_after_recovery_gives_up(svc):
    """The attempt budget refills only after the stream played RECOVERY_MIN_PLAYED again."""
    await start_live(svc)
    q = svc.hub.subscribe()
    for _ in range(3):
        svc.cast.driver.fail(DEV)
        await wait(lambda: svc.cast.player(DEV).recovering)
        await wait(lambda: not svc.cast.player(DEV).recovering and svc.cast.player(DEV).player_state == "PLAYING")
    svc.cast.driver.fail(DEV)  # 4th drop within seconds: no budget left
    await asyncio.sleep(0.1)
    codes = [m["code"] for m in toasts(q)]
    assert codes[-1] == "playback_failed"
    assert codes.count("stream_reconnecting") == 3


async def test_stale_media_is_resolved_again_before_reload(svc, monkeypatch):
    await start_live(svc)
    svc.cast._meta[DEV].resolved_at -= cast_service.RERESOLVE_AFTER + 1
    calls = []
    real = svc.resolver.resolve_media

    async def spy(*a, **kw):
        calls.append(a[0])
        return await real(*a, **kw)

    monkeypatch.setattr(svc.resolver, "resolve_media", spy)
    svc.cast.driver.fail(DEV)
    await wait(lambda: not svc.cast.player(DEV).recovering and svc.cast.player(DEV).player_state == "PLAYING")
    assert calls == [LIVE]


async def test_stalled_since_after_long_buffering(svc, monkeypatch):
    driver = svc.cast.driver
    driver.delay = 0.5  # BUFFERING lasts longer than STALL_AFTER (patched to 0.1 s)
    q = svc.hub.subscribe()
    await svc.cast.play(DEV, LIVE, title="Live")
    assert svc.cast.player(DEV).stalled_since is None
    await wait(lambda: any(p and p["stalled_since"] for p in states(q)))  # pushed without a status event
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    await wait(lambda: svc.cast.player(DEV).stalled_since is None)  # after STEADY_AFTER of PLAYING


def set_state(svc, state):
    """Make the fake receiver report ``state`` (as a real one does while it rebuffers)."""
    driver = svc.cast.driver
    driver.status(DEV).player_state = state
    driver._emit("status", DEV)


async def test_playing_blips_do_not_end_a_stall(svc):
    # a receiver starved by a stalled source: BUFFERING with sub-second PLAYING blips
    await start_live(svc)
    set_state(svc, "BUFFERING")
    await asyncio.sleep(0.15)
    since = svc.cast.player(DEV).stalled_since
    assert since is not None
    set_state(svc, "PLAYING")
    await asyncio.sleep(0.02)  # shorter than STEADY_AFTER
    set_state(svc, "BUFFERING")
    assert svc.cast.player(DEV).stalled_since == since  # still the same stall
    set_state(svc, "PLAYING")
    await wait(lambda: svc.cast.player(DEV).stalled_since is None)


async def test_stalled_live_stream_is_reloaded_by_the_watchdog(svc, monkeypatch):
    monkeypatch.setattr(cast_service, "LIVE_STALL_RELOAD", 0.3)
    await start_live(svc)
    q = svc.hub.subscribe()
    n = len(loads(svc))
    # flapping, never IDLE: only the watchdog can notice
    for _ in range(40):
        if svc.cast._meta[DEV].recovering:
            break
        set_state(svc, "BUFFERING")
        await asyncio.sleep(0.03)
        set_state(svc, "PLAYING")
        await asyncio.sleep(0.01)
    assert svc.cast._meta[DEV].recovering
    await wait(lambda: not svc.cast._meta[DEV].recovering)
    assert len(loads(svc)) == n + 1  # reloaded once
    assert "stream_restored" in [t.get("code") for t in toasts(q)]


async def test_watchdog_ignores_vod(svc, monkeypatch):
    monkeypatch.setattr(cast_service, "LIVE_STALL_RELOAD", 0.1)
    await svc.cast.play(DEV, MP4, title="A")
    await wait(lambda: svc.cast.player(DEV).player_state == "PLAYING")
    n = len(loads(svc))
    set_state(svc, "BUFFERING")
    await asyncio.sleep(0.3)
    assert not svc.cast._meta[DEV].recovering and len(loads(svc)) == n
