"""Ad blocking (uBO-style engine), popup control and quick close."""

from __future__ import annotations

import asyncio
import time

import httpx

from app.models import Settings
from app.services import adblock
from app.services.adblock import FilterManager, popup_rules
from app.services.browser.session import BrowserManager
from tests.conftest import wait_for
from tests.fakes import MASTER, FakeProvider, Resource

PAGE = "https://tv.example.com/live"
M3U8 = "https://cdn.example.com/hls/master.m3u8?tok=1"
AD_SCRIPT = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"
AD_FRAME = "https://ad.doubleclick.net/ddm/adi/x"


def filters() -> FilterManager:
    return FilterManager(None)  # bundled fallback list only (offline)


def ad_site() -> FakeProvider:
    return FakeProvider(
        site={
            PAGE: [
                Resource(AD_SCRIPT, None, resource_type="script"),
                Resource(AD_FRAME, None, resource_type="document", frame_url="https://player.example.net/embed"),
                Resource("https://www.googletagmanager.com/gtm.js?id=1", None, resource_type="script"),
                Resource("https://imasdk.googleapis.com/js/sdkloader/ima3.js", None, resource_type="script"),
                Resource(M3U8, "application/vnd.apple.mpegurl", MASTER, frame_url="https://player.example.net/embed"),
                Resource("https://tv.example.com/app.js", None, resource_type="script"),
            ]
        },
        titles={PAGE: "Canale Live"},
    )


class SettingsStore:
    def __init__(self, **kw) -> None:
        self.value = Settings(**kw)
        self.updates: list[dict] = []

    def get(self) -> Settings:
        return self.value.model_copy(deep=True)

    def update(self, patch: dict) -> Settings:
        self.updates.append(patch)
        self.value = self.value.model_copy(update=patch)
        return self.value


def manager(provider: FakeProvider, store: SettingsStore | None = None, fm: FilterManager | None = None):
    store = store or SettingsStore()
    return BrowserManager(
        provider, filters=fm or filters(), settings=store.get, update_settings=store.update
    ), store


async def settle(n: int = 10) -> None:
    for _ in range(n):
        await asyncio.sleep(0.01)


# ------------------------------------------------------------------ engine


def test_engine_blocks_known_ad_and_allows_stream():
    fm = filters()
    assert fm.check(AD_SCRIPT, PAGE, "script").blocked
    assert fm.check("https://www.googletagmanager.com/gtm.js", PAGE, "script").blocked
    assert not fm.check(M3U8, PAGE, "xmlhttprequest").blocked
    assert not fm.check("https://tv.example.com/app.js", PAGE, "script").blocked
    # redirect resources (uBO noop.js) are served instead of aborting
    d = fm.check("https://imasdk.googleapis.com/js/sdkloader/ima3.js", PAGE, "script")
    assert d.blocked and d.redirect and d.redirect.startswith("data:application/javascript")
    # $popup semantics
    assert fm.is_popup_ad("https://www.popads.net/go?x=1", PAGE)
    assert fm.is_popup_ad("https://popunder.example/win", PAGE)
    assert not fm.is_popup_ad("https://watch.tv.example.com/full", PAGE)
    names = [i.name for i in fm.info()]
    assert names == ["Bundled fallback"] and fm.info()[0].rules > 50


def test_popup_rules_and_helpers():
    assert popup_rules("||a.com^$popup\n||b.com^$script,popup\n||c.com^\n! x$popup") == ["||a.com^", "||b.com^$script"]
    assert adblock.hostname("https://www.Example.com/x") == "example.com"
    assert adblock.site("https://a.b.example.co.uk/") == "example.co.uk"
    assert adblock.host_in("video.example.com", ["example.com"]) and not adblock.host_in("example.org", ["example.com"])


def test_cosmetic_css_specific_and_generic():
    css = filters().cosmetic_css("https://any.site/", ["adsbygoogle", "content"], ["main"])
    assert ".adsbygoogle{display:none!important}" in css and ".content" not in css


async def test_downloaded_lists_are_loaded_and_refreshed(tmp_path):
    lists = [("custom", "Custom list", "https://filters.test/custom.txt", "standard"),
             ("hosts", "Hosts", "https://filters.test/hosts.txt", "hosts")]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/custom.txt":
            return httpx.Response(200, text="! Title: custom\n||evil-ads.test^\n||pops.test^$popup\n")
        return httpx.Response(200, text="# hosts\n0.0.0.0 tracker-host.test\n0.0.0.0 other.test\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fm = FilterManager(tmp_path, http, lists=lists)
        assert fm.needs_refresh()
        assert not fm.check("https://evil-ads.test/x.js", PAGE, "script").blocked
        info = await fm.refresh()
    assert [i.name for i in info] == ["Bundled fallback", "Custom list", "Hosts"]
    assert info[1].rules == 2 and info[2].rules == 2 and info[1].updated_at is not None
    assert fm.check("https://evil-ads.test/x.js", PAGE, "script").blocked
    assert fm.check("https://tracker-host.test/p.gif", PAGE, "image").blocked
    assert fm.is_popup_ad("https://pops.test/", PAGE)
    assert not fm.needs_refresh()
    # a new manager (restart) loads the downloaded copies from DATA_DIR/filters
    again = FilterManager(tmp_path, None, lists=lists)
    assert again.check("https://evil-ads.test/x.js", PAGE, "script").blocked


# ------------------------------------------------------------------ remote browser


async def test_session_blocks_ads_but_captures_stream_and_reports_count():
    prov = ad_site()
    mgr, _ = manager(prov)
    s = await mgr.create(PAGE)
    q = s.subscribe()
    await settle()
    ctx = prov.contexts[0]
    assert ctx.route_for(AD_SCRIPT).action == "abort"
    assert ctx.route_for(AD_FRAME).action == "abort"
    assert ctx.route_for("https://imasdk.googleapis.com/js/sdkloader/ima3.js").action == "fulfill"
    assert ctx.route_for(M3U8).action == "continue"
    assert ctx.route_for("https://tv.example.com/app.js").action == "continue"
    assert [c.url for c in s.captured] == [M3U8]
    model = s.to_model()
    assert model.adblock_enabled and model.blocked_count == 4
    # cosmetic filtering is injected in every frame
    assert ctx.bindings.get("__cwCosmetic") and any("__cwCosmetic" in js for js in ctx.init_scripts)
    css = await ctx.bindings["__cwCosmetic"](None, PAGE, ["adsbygoogle"], [])
    assert ".adsbygoogle" in css
    await asyncio.sleep(0.6)
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert any(m["type"] == "blocked" and m["count"] == 4 for m in msgs)
    await mgr.shutdown()


async def test_ad_stream_matching_a_filter_is_still_captured():
    ad_m3u8 = "https://ads.example/vast/preroll.m3u8"
    prov = FakeProvider(site={PAGE: [Resource(ad_m3u8, "application/vnd.apple.mpegurl", MASTER)]})
    mgr, _ = manager(prov)
    s = await mgr.create(PAGE)
    await settle()
    assert [c.url for c in s.captured] == [ad_m3u8]  # sniffed before the abort decision
    assert prov.contexts[0].route_for(ad_m3u8).action == "abort" and s.blocked_count == 1
    await mgr.shutdown()


async def test_per_site_toggle_is_persisted_and_disables_blocking():
    prov = ad_site()
    store = SettingsStore()
    mgr, _ = manager(prov, store)
    s = await mgr.create(PAGE)
    await settle()
    await s.set_adblock(False)
    await settle()
    assert store.value.adblock_disabled_hosts == ["tv.example.com"]
    assert not s.to_model().adblock_enabled
    assert prov.contexts[0].route_for(AD_SCRIPT).action == "continue"  # page reloaded without blocking
    await s.set_adblock(True)
    await settle()
    assert store.value.adblock_disabled_hosts == [] and s.to_model().adblock_enabled
    assert prov.contexts[0].route_for(AD_SCRIPT).action == "abort"
    await mgr.shutdown()


async def test_ad_popup_closed_automatically_and_counted():
    prov = ad_site()
    mgr, _ = manager(prov)
    s = await mgr.create(PAGE)
    await settle()
    before = s.blocked_count
    pop = await prov.contexts[0].open_popup("https://www.popads.net/go?id=9")
    await settle()
    assert pop.closed and s.page is not pop
    assert s.blocked_count == before + 1 and s.to_model().pending_popups == []
    await mgr.shutdown()


async def test_popup_held_then_decisions_applied():
    prov = ad_site()
    store = SettingsStore()
    mgr, _ = manager(prov, store)
    s = await mgr.create(PAGE)
    q = s.subscribe()
    ctx = prov.contexts[0]
    held = await ctx.open_popup("https://partner.example.org/watch")
    await settle()
    assert held.closed and s.page is not held
    [req] = s.to_model().pending_popups
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert any(m["type"] == "popup" and m["data"]["id"] == req.id for m in msgs)
    # open → the session view switches to the popup page
    await s.handle_input({"type": "popup_decision", "id": req.id, "decision": "open"})
    await settle()
    assert s.page is not held and s.page.url == "https://partner.example.org/watch"
    assert s.url == "https://partner.example.org/watch" and s.to_model().pending_popups == []
    # block_always → opener host persisted, later popups from it are closed silently
    other = await ctx.open_popup("https://third.example.net/")
    await settle()
    [req2] = s.to_model().pending_popups
    await s.decide_popup(req2.id, "block_always")
    assert store.value.popup_blocked_hosts == ["partner.example.org"]
    again = await ctx.open_popup("https://fourth.example.net/")
    await settle()
    assert other.closed and again.closed and s.to_model().pending_popups == []
    await mgr.shutdown()


async def test_cross_site_redirect_without_gesture_is_blocked_and_prompts():
    prov = ad_site()
    mgr, _ = manager(prov)
    s = await mgr.create(PAGE)
    await settle()
    s._nav_allowed_until = 0  # the page finished loading a while ago
    await s.page.goto("https://redirect-ad.example.biz/landing")  # JS redirect, no user gesture
    await settle()
    assert s.page.url == PAGE
    [req] = s.to_model().pending_popups
    assert req.host == "redirect-ad.example.biz"
    # the same navigation right after a tap is user-initiated: allowed
    await s.handle_input({"type": "tap", "x": 1, "y": 1})
    await s.page.goto("https://other.example.biz/next")
    assert s.page.url == "https://other.example.biz/next"
    await mgr.shutdown()


async def test_stop_media_and_quick_close_is_fast():
    prov = ad_site()
    mgr, _ = manager(prov)
    s = await mgr.create(PAGE)
    q = s.subscribe()
    await s.handle_input({"type": "stop_media"})
    assert any("pause()" in js for js, _ in s.page.main_frame.evaluated)
    ctx = prov.contexts[0]
    ctx.close_delay = 5.0  # a hung Chromium must not block the caller
    t0 = time.monotonic()
    await mgr.close(s.id)
    assert time.monotonic() - t0 < 1.5
    assert s.closed and s.id not in mgr.sessions
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert msgs[-1] == {"type": "closed"}
    await wait_for_async(lambda: ctx.closed, 6)


async def wait_for_async(fn, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


# ------------------------------------------------------------------ API


def test_api_adblock_toggle_popups_and_filters(client, provider):
    provider.site[PAGE] = ad_site().site[PAGE]
    sess = client.post("/api/browser/sessions", json={"url": PAGE}).json()
    assert sess["adblock_enabled"] is True and sess["pending_popups"] == []
    sid = sess["id"]
    wait_for(lambda: client.get(f"/api/browser/sessions/{sid}").json()["blocked_count"] >= 3)

    off = client.post(f"/api/browser/sessions/{sid}/adblock", json={"enabled": False}).json()
    assert off["adblock_enabled"] is False
    assert client.get("/api/settings").json()["adblock_disabled_hosts"] == ["tv.example.com"]
    on = client.post(f"/api/browser/sessions/{sid}/adblock", json={"enabled": True}).json()
    assert on["adblock_enabled"] is True and client.get("/api/settings").json()["adblock_disabled_hosts"] == []

    r = client.post(f"/api/browser/sessions/{sid}/popups/nope", json={"decision": "open"})
    assert r.status_code == 404 and r.json()["code"] == "popup_not_found"
    assert client.post(f"/api/browser/sessions/{sid}/popups/nope", json={"decision": "x"}).status_code == 422

    lists = client.get("/api/filters").json()["lists"]
    assert lists[0]["name"] == "Bundled fallback" and lists[0]["rules"] > 50
    client.put("/api/settings", json={"adblock_enabled": False})
    assert client.get(f"/api/browser/sessions/{sid}").json()["adblock_enabled"] is False
    client.delete(f"/api/browser/sessions/{sid}")


def test_api_filters_refresh_downloads_lists(client, mock_http):
    for _id, _name, url, _fmt in adblock.DEFAULT_LISTS:
        mock_http.get(url).respond(200, text="! list\n||refresh-ads.test^\n")
    lists = client.post("/api/filters/refresh").json()["lists"]
    assert len(lists) == 1 + len(adblock.DEFAULT_LISTS)
    assert all(item["updated_at"] for item in lists[1:])


async def test_window_open_guard_applies_policy_without_creating_tabs():
    prov = ad_site()
    store = SettingsStore()
    mgr, _ = manager(prov, store)
    s = await mgr.create(PAGE)
    ctx = prov.contexts[0]
    report = ctx.bindings["__cwPopup"]
    assert any("__cwPopup" in js for js in ctx.init_scripts)
    pages_before = len(ctx.pages)
    before = s.blocked_count
    await report(None, "https://www.popads.net/go?z=1")  # ad → counted, nothing opened
    assert s.blocked_count == before + 1 and s.to_model().pending_popups == []
    await report(None, "https://partner.example.org/watch")  # ask → prompt
    [req] = s.to_model().pending_popups
    assert req.url == "https://partner.example.org/watch" and len(ctx.pages) == pages_before
    store.value = store.value.model_copy(update={"popup_policy": "allow"})
    await report(None, "https://watch.tv.example.com/full")  # allow → view switches to it
    assert s.page.url == "https://watch.tv.example.com/full" and s.url == "https://watch.tv.example.com/full"
    await report(None, "https://cdn.example.com/direct/movie.mp4")  # media popup: captured
    await settle()
    assert any(c.url == "https://cdn.example.com/direct/movie.mp4" for c in s.captured)
    await mgr.shutdown()
