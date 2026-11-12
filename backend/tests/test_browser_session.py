from __future__ import annotations

import asyncio
import time

import pytest

from app.errors import AppError
from app.models import Settings, Viewport
from app.services.browser.session import BrowserManager, normalize_url
from app.services.resolver.service import HlsInfo
from tests.fakes import MASTER, FakeFrame, FakeProvider, FakeRequest, Resource

PAGE = "https://tv.example.com/live"
M3U8 = "https://cdn.example.com/hls/master.m3u8?tok=1"


def site():
    return FakeProvider(
        site={PAGE: [
            Resource("https://cdn.example.com/hls/seg_0001.ts", "video/mp2t"),  # segment: ignored
            Resource("https://ads.example.com/ads/preroll.mp4", "video/mp4"),
            Resource(M3U8, "application/vnd.apple.mpegurl", MASTER, frame_url="https://player.example.net/embed"),
        ]},
        titles={PAGE: "Canale Live"},
        evaluate=lambda js, arg: {"x": 0, "y": 0, "width": 320, "height": 180, "vw": 1280, "vh": 720}
        if "querySelectorAll('video')" in js else None,
    )


async def probe(url, headers):
    return HlsInfo(is_master=True, is_live=True, width=1920, height=1080)


def manager(provider, **kw):
    return BrowserManager(provider, hls_probe=probe, preview=lambda u, h: "/proxy/tok/master.m3u8", **kw)


async def settle():
    for _ in range(10):
        await asyncio.sleep(0.01)


def test_normalize_url():
    assert normalize_url("example.com/x") == "https://example.com/x"
    assert normalize_url(" http://a ") == "http://a"


async def test_create_screencast_capture_and_enrich():
    prov = site()
    mgr = manager(prov)
    s = await mgr.create(PAGE, Viewport(width=390, height=844))
    q = s.subscribe()
    await settle()
    model = s.to_model()
    assert model.url == PAGE and model.title == "Canale Live"
    cdp = prov.contexts[0].cdp_sessions[0]
    assert cdp.sent[0][0] == "Page.startScreencast" and cdp.sent[0][1]["format"] == "jpeg"
    # ads are captured but ranked lower; segments are ignored
    urls = [c.url for c in model.captured]
    assert urls[0] == M3U8 and "https://cdn.example.com/hls/seg_0001.ts" not in urls
    best = model.captured[0]
    assert best.kind == "hls" and best.is_master and best.is_live
    assert best.quality == "1080p FHD" and best.height == 1080
    assert best.headers["referer"] == "https://player.example.net/embed"
    assert best.headers["cookie"] == "sess=abc"
    assert best.frame_url == "https://player.example.net/embed"
    assert best.preview_url == "/proxy/tok/master.m3u8"
    assert best.title == "Canale Live"
    assert best.thumbnail and best.thumbnail.startswith("data:image/jpeg;base64,")
    assert best.score > model.captured[1].score
    # frames are forwarded and acked
    cdp.emit("Page.screencastFrame", {"data": "QUJD", "sessionId": 7, "metadata": {"deviceWidth": 390, "deviceHeight": 844}})
    s._on_request(FakeRequest("https://cdn.example.com/vod/movie.mp4", {}, FakeFrame(PAGE)), "video/mp4")
    s._on_request(FakeRequest("https://cdn.example.com/vod/movie.mp4", {}, FakeFrame(PAGE)), "video/mp4")  # dup
    await settle()
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    types = [m["type"] for m in msgs]
    assert types[0] == "session"
    captured = [m["data"] for m in msgs if m["type"] == "captured"]
    assert {c["url"] for c in captured} == {"https://cdn.example.com/vod/movie.mp4"}
    assert captured[-1]["width"] == 1280 and captured[-1]["quality"] == "720p HD"  # from <video>.videoHeight
    frame = next(m for m in msgs if m["type"] == "frame")
    assert frame == {"type": "frame", "data": "QUJD", "width": 390, "height": 844}
    assert ("Page.screencastFrameAck", {"sessionId": 7}) in cdp.sent
    # a late subscriber immediately gets the session and the last frame
    q2 = s.subscribe()
    assert [q2.get_nowait()["type"], q2.get_nowait()["type"]] == ["session", "frame"]
    await mgr.shutdown()
    assert prov.contexts[0].closed
    assert any(q.get_nowait()["type"] == "closed" for _ in range(q.qsize()))


async def test_input_forwarding_mobile_and_desktop():
    prov = site()
    mgr = manager(prov)
    mobile = await mgr.create(PAGE)
    page = prov.contexts[0].pages[0]
    for msg in [
        {"type": "tap", "x": 10, "y": 20},
        {"type": "click", "x": 1, "y": 2, "button": "right"},
        {"type": "scroll", "x": 5, "y": 5, "dx": 0, "dy": 300},
        {"type": "key", "key": "Enter"},
        {"type": "text", "text": "ciao"},
        {"type": "mousemove", "x": 3, "y": 4},
        {"type": "click"},  # malformed: ignored
        {"type": "unknown"},
    ]:
        await mobile.handle_input(msg)
    assert page.input_log == [
        ("touchscreen.tap", 10.0, 20.0),
        ("mouse.click", 1.0, 2.0, "right"),
        ("mouse.move", 5.0, 5.0),
        ("mouse.wheel", 0.0, 300.0),
        ("keyboard.press", "Enter"),
        ("keyboard.type", "ciao"),
        ("mouse.move", 3.0, 4.0),
    ]
    desktop = await mgr.create(PAGE, Viewport(width=1280, height=720))
    dpage = prov.contexts[1].pages[0]
    await desktop.handle_input({"type": "tap", "x": 1, "y": 1})
    assert dpage.input_log == [("mouse.click", 1.0, 1.0)]
    await mgr.shutdown()


async def test_navigation_and_back():
    prov = site()
    mgr = manager(prov)
    s = await mgr.create(PAGE)
    await s.navigate("example.org/other")
    assert s.url == "https://example.org/other"
    await s.navigate(action="back")
    assert s.url == PAGE
    await s.navigate(action="reload")
    await mgr.shutdown()


async def test_session_limit_and_idle_reaping():
    mgr = manager(site(), max_sessions=2, idle_timeout=0.05)
    a = await mgr.create(PAGE)
    b = await mgr.create(PAGE)
    q = b.subscribe()  # b is being watched → never idle
    a.last_activity = time.monotonic() - 1
    b.last_activity = time.monotonic() - 1
    c = await mgr.create(PAGE)  # a reaped to make room
    assert set(mgr.sessions) == {b.id, c.id}
    with pytest.raises(AppError) as e:
        await mgr.create(PAGE)
    assert e.value.code == "browser_limit" and e.value.status_code == 429
    b.unsubscribe(q)
    b.last_activity = c.last_activity = time.monotonic() - 1
    assert await mgr.reap_idle() == 2 and mgr.sessions == {}


async def test_screenshot_fallback_when_cdp_fails():
    prov = FakeProvider(site={}, cdp_fail=True)
    mgr = manager(prov)
    s = await mgr.create(PAGE)
    q = s.subscribe()
    for _ in range(50):
        await asyncio.sleep(0.02)
        if any(m["type"] == "frame" for m in list(q._queue)):  # type: ignore[attr-defined]
            break
    frames = [m for m in list(q._queue) if m["type"] == "frame"]  # type: ignore[attr-defined]
    assert frames and frames[0]["width"] == 390
    await mgr.shutdown()


async def test_popups_are_held_and_follow_the_policy():
    policy = {"value": "ask"}
    mgr = manager(site(), settings=lambda: Settings(popup_policy=policy["value"]))
    prov = mgr.provider
    s = await mgr.create(PAGE)
    ctx = prov.contexts[0]
    # ask (default): never shown, the navigation is aborted and a prompt is queued
    held = await ctx.open_popup("https://www.other-site.com/player")
    await settle()
    assert held.closed and s.page is not held and ctx.route_for("https://www.other-site.com/player").action == "abort"
    [pending] = s.to_model().pending_popups
    assert pending.host == "other-site.com" and pending.opener_url == PAGE
    # allow: followed into the session
    policy["value"] = "allow"
    follow = await ctx.open_popup("https://watch.tv.example.com/full")
    await settle()
    assert s.page is follow and not follow.closed
    assert s.url == "https://watch.tv.example.com/full"
    # block: closed silently, counted
    policy["value"] = "block"
    before = s.blocked_count
    blocked = await ctx.open_popup("https://elsewhere.example.org/")
    await settle()
    assert blocked.closed and s.blocked_count == before + 1
    await mgr.shutdown()


async def test_disabled_and_unknown():
    mgr = BrowserManager(None)
    with pytest.raises(AppError) as e:
        await mgr.create(PAGE)
    assert e.value.code == "browser_disabled"
    with pytest.raises(AppError) as e:
        mgr.get("nope")
    assert e.value.code == "session_not_found"


async def test_segments_and_playlist_reloads_are_not_new_captures():
    embed = "https://player.example.net/embed"
    live = "https://cdn.example.com/ll/index.m3u8"
    prov = FakeProvider(
        site={PAGE: [
            Resource(f"{live}?_HLS_msn=1&_HLS_part=0", "application/vnd.apple.mpegurl", MASTER, frame_url=embed),
            Resource(f"{live}?_HLS_msn=1&_HLS_part=1", "application/vnd.apple.mpegurl", MASTER, frame_url=embed),
            Resource(f"{live}?token=abc&_=17", "application/vnd.apple.mpegurl", MASTER, frame_url=embed),
            Resource("https://cdn.x/live/seg-12-v1-a1.mp4", "video/mp4", frame_url=embed),
            Resource("https://cdn.x/live/fileSequence123.mp4", "video/mp4", frame_url=embed),
            Resource("https://cdn.x/live/a8f3e1.ts", None, frame_url=embed),
            Resource("https://cdn.x/get?id=5", "video/mp2t", frame_url=embed),
            Resource("https://cdn.x/chunk_3.png", "video/mp2t"),  # even outside the player frame
            Resource("https://cdn.example.com/other/index.m3u8?ch=2", "application/vnd.apple.mpegurl", MASTER,
                     frame_url=embed),  # a different stream (non-volatile param) is still captured
        ]},
        titles={PAGE: "Live"},
    )
    s = await manager(prov).create(PAGE)
    await settle()
    urls = [c.url for c in s.captured]
    assert len(urls) == 2 and urls[0].startswith(live) and urls[1].endswith("other/index.m3u8?ch=2")


async def test_session_broadcasts_omit_thumbnails_but_first_snapshot_has_them():
    s = await manager(site()).create(PAGE)
    await settle()
    assert s.captured[0].thumbnail
    q = s.subscribe()
    first = q.get_nowait()
    assert first["type"] == "session" and all(c["thumbnail"] for c in first["data"]["captured"])
    s._broadcast_session()
    later = q.get_nowait()
    assert later["type"] == "session" and later["data"]["captured"]
    assert all("thumbnail" not in c for c in later["data"]["captured"])  # omitted, not nulled


async def test_thumbnail_fallback_is_capped():
    from app.services.browser import session as sess

    s = await manager(site()).create(PAGE)
    await settle()
    page = s.page
    big = b"\xff" * (sess.THUMB_MAX_BYTES + 1)

    async def huge_shot(**_):
        return big

    page.screenshot = huge_shot
    page.main_frame.evaluate_result = None  # no <video>: fallback path
    s._last_frame = {"type": "frame", "data": "A" * (sess.THUMB_MAX_BYTES * 2)}
    assert (await s._thumbnail())[0] is None
    s._last_frame = {"type": "frame", "data": "QUJD"}
    assert (await s._thumbnail())[0] == "data:image/jpeg;base64,QUJD"


async def test_thumbnail_drops_clip_sized_screencast_frames_and_refreshes():
    """A clipped page.screenshot() makes Chromium emit screencast frames sized like the clip: viewers
    would show them letterboxed (and keep them on a static page). They are dropped and the screencast is
    restarted for a fresh full-viewport frame."""
    s = await manager(site()).create(PAGE, Viewport(width=390, height=700))
    await settle()
    cdp = s.cdp
    page = s.page
    good = {"type": "frame", "data": "R09PRA==", "width": 390, "height": 700}
    s._last_frame = good

    async def shot_emitting_clip_frame(**_):
        s._on_frame({"data": "Q0xJUA==", "sessionId": 7, "metadata": {"deviceWidth": 390, "deviceHeight": 219}})
        return b"jpeg"

    page.screenshot = shot_emitting_clip_frame
    page.main_frame.evaluate_result = {"x": 0, "y": 0, "width": 390, "height": 219, "vw": None, "vh": None}
    sent_before = len(cdp.sent)
    assert (await s._thumbnail())[0] == "data:image/jpeg;base64," + "anBlZw=="
    assert s._last_frame is good
    assert [m for m, _ in cdp.sent[sent_before:] if m != "Page.screencastFrameAck"] == [
        "Page.stopScreencast",
        "Page.startScreencast",
    ]
    # outside a capture, frames of any size are kept (e.g. after a viewport change)
    s._on_frame({"data": "TkVX", "metadata": {"deviceWidth": 1280, "deviceHeight": 720}})
    assert s._last_frame["data"] == "TkVX"


def test_viewer_queue_never_drops_messages_for_frames():
    from app.services.browser.session import ViewerQueue

    q = ViewerQueue(maxsize=3)
    q.offer({"type": "captured", "n": 1})
    for i in range(50):
        q.offer({"type": "frame", "n": i})
    q.offer({"type": "popup", "n": 2})
    q.offer({"type": "blocked", "n": 3})  # full: the waiting frame goes, not a message
    got = [q.get_nowait() for _ in range(q.qsize())]
    assert [m["type"] for m in got] == ["captured", "popup", "blocked"]
    q.offer({"type": "frame", "n": 100})
    q.offer({"type": "frame", "n": 101})
    assert q.qsize() == 1 and q.get_nowait()["n"] == 101  # coalesced to the latest
    for i in range(5):
        q.offer({"type": "captured", "n": i})
    assert [q.get_nowait()["n"] for _ in range(q.qsize())] == [2, 3, 4]  # last resort: oldest message


async def test_pruned_captures_are_announced_with_a_session_snapshot(monkeypatch):
    """Past MAX_CAPTURED the lowest-scored streams are dropped: viewers must get a fresh
    snapshot without them, and a new stream that is itself pruned is never announced."""
    from app.services.browser import session as session_mod

    monkeypatch.setattr(session_mod, "MAX_CAPTURED", 2)
    prov = site()
    mgr = manager(prov)
    s = await mgr.create(PAGE)
    await settle()
    for i in range(3):
        s._on_request(FakeRequest(f"https://cdn.example.com/vod/movie{i}.mp4", {}, FakeFrame(PAGE)), "video/mp4")
        await settle()
    q = s.subscribe()
    q.get_nowait()  # initial snapshot
    # same score as the kept progressive one: the newcomer is the one pruned
    s._on_request(FakeRequest("https://cdn.example.com/vod/movie9.mp4", {}, FakeFrame(PAGE)), "video/mp4")
    await settle()
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    kept = {c.id for c in s.captured}
    assert len(kept) == 2
    snapshots = [m["data"] for m in msgs if m["type"] == "session"]
    assert snapshots and {c["id"] for c in snapshots[-1]["captured"]} == kept
    announced = {m["data"]["id"] for m in msgs if m["type"] == "captured"}
    assert announced <= kept  # the pruned newcomer was never sent as "captured"
    assert all("movie9" not in c.url for c in s.captured)
    await mgr.shutdown()
