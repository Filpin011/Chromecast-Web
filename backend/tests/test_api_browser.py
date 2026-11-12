import pytest

from tests.conftest import wait_for
from tests.fakes import LIVE_MEDIA, MASTER, FakeProvider, Resource

PAGE = "https://tv.example.com/live"
M3U8 = "https://cdn.example.com/hls/master.m3u8"


@pytest.fixture
def provider():
    return FakeProvider(
        site={PAGE: [Resource(M3U8, "application/vnd.apple.mpegurl", MASTER, frame_url="https://player.example.net/e")]},
        titles={PAGE: "Canale Live"},
    )


@pytest.fixture(autouse=True)
def upstream(mock_http):
    mock_http.get(M3U8).respond(200, text=MASTER)
    mock_http.get("https://cdn.example.com/hls/low/index.m3u8").respond(200, text=LIVE_MEDIA)


def create(client):
    r = client.post("/api/browser/sessions", json={"url": PAGE})
    assert r.status_code == 201
    sid = r.json()["id"]
    sess = wait_for(lambda: (s := client.get(f"/api/browser/sessions/{sid}").json())["captured"] and
                    s["captured"][0]["quality"] and s)
    return sid, sess


def test_session_rest_lifecycle(client):
    sid, sess = create(client)
    assert sess["viewport"] == {"width": 390, "height": 844} and sess["title"] == "Canale Live"
    stream = sess["captured"][0]
    assert stream["url"] == M3U8 and stream["is_live"] is True and stream["quality"] == "720p HD"
    assert stream["preview_url"].startswith("/proxy/")
    assert [s["id"] for s in client.get("/api/browser/sessions").json()] == [sid]
    r = client.post(f"/api/browser/sessions/{sid}/navigate", json={"url": "https://example.org/"})
    assert r.json()["url"] == "https://example.org/"
    assert client.post(f"/api/browser/sessions/{sid}/navigate", json={}).status_code == 422
    assert client.delete(f"/api/browser/sessions/{sid}").status_code == 204
    assert client.get(f"/api/browser/sessions/{sid}").json()["code"] == "session_not_found"


def test_cast_enqueue_and_favorite_captured_stream(client):
    client.put("/api/settings", json={"show_idle_on_connect": False})
    sid, sess = create(client)
    stream_id = sess["captured"][0]["id"]
    p = client.post(f"/api/browser/sessions/{sid}/cast", json={"stream_id": stream_id, "device_id": "fake-ultra-0001"}).json()
    assert p["media_url"].startswith("http://cast.test:8000/proxy/")  # replayed with captured Referer
    assert p["stream_type"] == "LIVE" and p["title"] == "Canale Live"
    token = p["media_url"].split("/proxy/")[1].split("/")[0]
    target = client.app.state.services.tokens.get(token)
    assert target.headers["Referer"] == "https://player.example.net/e"
    hist = client.get("/api/history").json()
    assert hist[0]["input"] == PAGE and hist[0]["source_kind"] == "webpage"
    wait_for(lambda: client.get("/api/state").json()["players"]["fake-ultra-0001"]["player_state"] == "PLAYING")
    p = client.post(f"/api/browser/sessions/{sid}/cast",
                    json={"stream_id": stream_id, "device_id": "fake-ultra-0001", "enqueue": True}).json()
    assert len(p["queue"]) == 1 and p["queue"][0]["input"] == PAGE
    fav = client.post(f"/api/browser/sessions/{sid}/favorite", json={"stream_id": stream_id})
    assert fav.status_code == 201 and fav.json()["input"] == PAGE and fav.json()["title"] == "Canale Live"
    r = client.post(f"/api/browser/sessions/{sid}/cast", json={"stream_id": "zzz", "device_id": "fake-ultra-0001"})
    assert r.status_code == 404 and r.json()["code"] == "stream_not_found"
    r = client.post(f"/api/browser/sessions/{sid}/cast", json={"stream_id": stream_id, "device_id": "ghost"})
    assert r.json()["code"] == "device_not_found"


def test_browser_websocket(client, provider):
    sid, _ = create(client)
    with client.websocket_connect(f"/ws/browser/{sid}") as ws:
        first = ws.receive_json()
        assert first["type"] == "session" and first["data"]["id"] == sid
        ws.send_json({"type": "tap", "x": 100, "y": 200})
        ws.send_json({"type": "key", "key": "Enter"})
        ws.send_json({"type": "ping"})
        for _ in range(20):
            if ws.receive_json()["type"] == "pong":
                break
        page = provider.contexts[0].pages[0]
        assert ("touchscreen.tap", 100.0, 200.0) in page.input_log
        assert ("keyboard.press", "Enter") in page.input_log
        cdp = provider.contexts[0].cdp_sessions[0]
        client.portal.call(cdp.emit, "Page.screencastFrame", {"data": "Zm9v", "sessionId": 1, "metadata": {}})
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "frame":
                assert msg["data"] == "Zm9v" and msg["width"] == 390
                break
        client.delete(f"/api/browser/sessions/{sid}")
        for _ in range(20):
            if ws.receive_json()["type"] == "closed":
                break
        else:
            raise AssertionError("no closed message")


def test_ws_unknown_session(client):
    with client.websocket_connect("/ws/browser/nope") as ws:
        assert ws.receive_json() == {"type": "closed"}


def test_session_limit_via_api(client):
    for _ in range(2):
        assert client.post("/api/browser/sessions", json={"url": PAGE}).status_code == 201
    r = client.post("/api/browser/sessions", json={"url": PAGE})
    assert r.status_code == 429 and r.json()["code"] == "browser_limit"


def test_browser_queue_on_disconnected_device_starts_playback(client):
    client.put("/api/settings", json={"show_idle_on_connect": False})
    sid, sess = create(client)
    stream_id = sess["captured"][0]["id"]
    p = client.post(f"/api/browser/sessions/{sid}/cast",
                    json={"stream_id": stream_id, "device_id": "fake-ultra-0001", "enqueue": True}).json()
    assert p["connected"] and p["queue"] == [] and p["media_url"].startswith("http://cast.test:8000/proxy/")
    assert "fake-ultra-0001" in client.get("/api/state").json()["players"]
