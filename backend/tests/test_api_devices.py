import pytest

from tests.conftest import player, wait_for
from tests.fakes import LIVE_MEDIA

DEV = "fake-ultra-0001"
MP4 = "https://cdn.example.com/a.mp4"


@pytest.fixture(autouse=True)
def _no_idle(client):
    client.put("/api/settings", json={"show_idle_on_connect": False, "show_idle_on_stop": False})


def test_list_and_discover(client):
    assert len(client.get("/api/devices").json()) == 2
    r = client.post("/api/devices/discover")
    assert r.status_code == 200 and len(r.json()) == 2
    assert client.get("/api/state").json()["discovering"] is False


def test_manual_device_lifecycle(client):
    r = client.post("/api/devices/manual", json={"host": "192.168.1.99"})
    assert r.status_code == 201
    dev = r.json()
    assert dev["id"] == "manual-192.168.1.99" and dev["manual"] and dev["port"] == 8009
    assert any(d["id"] == dev["id"] for d in client.get("/api/state").json()["devices"])
    assert client.delete(f"/api/devices/{DEV}").status_code == 400
    assert client.delete(f"/api/devices/{dev['id']}").status_code == 204
    assert client.delete(f"/api/devices/{dev['id']}").json()["code"] == "device_not_found"
    assert client.post("/api/devices/manual", json={"host": ""}).status_code == 422


def test_connect_disconnect(client):
    p = client.post(f"/api/devices/{DEV}/connect").json()
    assert p["connected"] and p["device_id"] == DEV
    st = client.get("/api/state").json()
    assert st["active_device_id"] == DEV and DEV in st["players"]
    assert client.post(f"/api/devices/{DEV}/disconnect").status_code == 204
    st = client.get("/api/state").json()
    assert st["players"] == {} and st["active_device_id"] is None
    r = client.post("/api/devices/ghost/connect")
    assert r.status_code == 404 and r.json() == {"detail": "Device ghost not found", "code": "device_not_found"}


def test_connect_shows_idle_image_when_enabled(client):
    client.put("/api/settings", json={"show_idle_on_connect": True})
    p = client.post(f"/api/devices/{DEV}/connect").json()
    assert p["showing_idle_image"] and p["media_url"] == "http://cast.test:8000/idle.jpg"
    p = client.post(f"/api/devices/{DEV}/idle").json()
    assert p["showing_idle_image"]


def test_play_and_controls(client):
    p = client.post(f"/api/devices/{DEV}/play", json={"input": MP4, "title": "Film"}).json()
    assert p["title"] == "Film" and p["original_input"] == MP4 and p["media_url"] == MP4
    wait_for(lambda: player(client, DEV)["player_state"] == "PLAYING")
    p = client.post(f"/api/devices/{DEV}/control", json={"action": "pause"}).json()
    assert p["player_state"] == "PAUSED"
    p = client.post(f"/api/devices/{DEV}/control", json={"action": "seek", "value": 42}).json()
    assert p["current_time"] == 42 and p["seekable"] and p["duration"] == 600
    p = client.post(f"/api/devices/{DEV}/control", json={"action": "seek_relative", "value": -10}).json()
    assert p["current_time"] == 32
    p = client.post(f"/api/devices/{DEV}/control", json={"action": "volume", "value": 0.8}).json()
    assert p["volume_level"] == 0.8
    p = client.post(f"/api/devices/{DEV}/tracks", json={"active_track_ids": [100]}).json()
    assert p["active_track_ids"] == [100]
    r = client.post(f"/api/devices/{DEV}/control", json={"action": "explode"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    p = client.post(f"/api/devices/{DEV}/control", json={"action": "stop"}).json()
    assert p["player_state"] == "IDLE"


def test_control_not_connected(client):
    r = client.post("/api/devices/fake-tv-0002/control", json={"action": "play"})
    assert r.status_code == 409 and r.json()["code"] == "not_connected"


def test_play_live_hls(client, mock_http):
    mock_http.get("https://cdn.example.com/live/index.m3u8").respond(200, text=LIVE_MEDIA)
    p = client.post(f"/api/devices/{DEV}/play", json={"input": "https://cdn.example.com/live/index.m3u8"}).json()
    assert p["stream_type"] == "LIVE" and p["duration"] is None and not p["seekable"]
    assert p["media_url"].startswith("http://cast.test:8000/proxy/")  # no CORS upstream → proxied


def test_play_resolve_error(client):
    r = client.post(f"/api/devices/{DEV}/play", json={"input": "https://www.youtube.com/watch?v=fail"})
    assert r.status_code == 422 and r.json()["code"] == "resolve_failed"
    r = client.post(f"/api/devices/{DEV}/play", json={"input": "hello"})
    assert r.status_code == 400 and r.json()["code"] == "unsupported_source"
    assert r.json()["reason"] == "unsupported_input" and "params" not in r.json()


def test_queue_endpoints(client):
    client.post(f"/api/devices/{DEV}/play", json={"input": MP4})
    wait_for(lambda: player(client, DEV)["player_state"] == "PLAYING")
    p = client.post(f"/api/devices/{DEV}/play", json={"input": "https://cdn.example.com/b.mp4", "enqueue": True}).json()
    assert [i["title"] for i in p["queue"]] == ["b"]
    p = client.post(f"/api/devices/{DEV}/queue", json={"input": "https://cdn.example.com/c.mp4", "title": "C"}).json()
    ids = [i["id"] for i in p["queue"]]
    p = client.put(f"/api/devices/{DEV}/queue", json={"item_ids": ids[::-1]}).json()
    assert [i["title"] for i in p["queue"]] == ["C", "b"]
    p = client.delete(f"/api/devices/{DEV}/queue/{ids[1]}").json()
    assert [i["title"] for i in p["queue"]] == ["b"]
    assert client.delete(f"/api/devices/{DEV}/queue/zzz").status_code == 404
    p = client.post(f"/api/devices/{DEV}/control", json={"action": "next"}).json()
    assert p["original_input"] == "https://cdn.example.com/b.mp4" and p["queue"] == []


def test_resolve_endpoint(client, mock_http):
    from tests.test_m3u import IPTV

    mock_http.get("https://lists.example.com/tv.m3u").respond(200, text=IPTV)
    r = client.post("/api/resolve", json={"input": "https://lists.example.com/tv.m3u"}).json()
    assert r["type"] == "playlist" and len(r["channels"]) == 5 and r["channels"][0]["logo"]
    r = client.post("/api/resolve", json={"input": "https://youtu.be/xyz"}).json()
    assert r["type"] == "media" and r["media"]["source_kind"] == "ytdlp"
    assert client.post("/api/resolve", json={"input": ""}).status_code == 422


def test_queue_on_disconnected_device_connects_and_starts(client):
    client.put("/api/settings", json={"show_idle_on_connect": False})
    assert DEV not in client.get("/api/state").json()["players"]
    p = client.post(f"/api/devices/{DEV}/queue", json={"input": MP4, "title": "A"}).json()
    assert p["connected"] and p["original_input"] == MP4 and p["queue"] == []
    state = client.get("/api/state").json()
    assert DEV in state["players"] and state["active_device_id"] == DEV


def test_play_with_channel_headers(client, mock_http):
    route = mock_http.get("https://iptv.example.com/ch1/index.m3u8").respond(200, text=LIVE_MEDIA)
    r = client.post(f"/api/devices/{DEV}/play", json={
        "input": "https://iptv.example.com/ch1/index.m3u8", "title": "Ch 1",
        "headers": {"Referer": "https://panel.example/", "User-Agent": "VLC"}})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["media_url"].startswith("http://cast.test:8000/proxy/")  # headers replayed by the proxy
    assert route.calls.last.request.headers["referer"] == "https://panel.example/"
    token = p["media_url"].split("/proxy/")[1].split("/")[0]
    assert client.app.state.services.tokens.get(token).headers["Referer"] == "https://panel.example/"
    # history keeps the headers (Kodi syntax) so replaying it works
    hist = client.get("/api/history").json()[0]
    assert hist["input"].startswith("https://iptv.example.com/ch1/index.m3u8|") and "Referer=" in hist["input"]
