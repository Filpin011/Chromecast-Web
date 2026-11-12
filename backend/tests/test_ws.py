from tests.conftest import wait_for

DEV = "fake-ultra-0001"


def _next_state(ws, pred, limit=200):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == "state" and pred(msg["data"]):
            return msg["data"]
    raise AssertionError("state not received")


def test_snapshot_on_connect_and_ping(client):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "state" and len(first["data"]["devices"]) == 2
        ws.send_json({"type": "ping"})
        for _ in range(20):
            if ws.receive_json()["type"] == "pong":
                break
        else:
            raise AssertionError("no pong")


def test_all_clients_receive_every_change(client):
    client.put("/api/settings", json={"show_idle_on_connect": False})
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        v0 = a.receive_json()["data"]["version"]
        b.receive_json()
        client.post(f"/api/devices/{DEV}/connect")
        sa = _next_state(a, lambda d: d["active_device_id"] == DEV)
        sb = _next_state(b, lambda d: d["active_device_id"] == DEV)
        assert sa["version"] > v0 and sb["players"][DEV]["connected"]
        client.post(f"/api/devices/{DEV}/play", json={"input": "https://cdn.example.com/a.mp4"})
        playing = _next_state(a, lambda d: d["players"][DEV]["player_state"] == "PLAYING")
        # ticks while playing: progress keeps moving with growing versions
        later = _next_state(a, lambda d: d["version"] > playing["version"] + 1)
        assert later["players"][DEV]["current_time"] >= playing["players"][DEV]["current_time"]
        _next_state(b, lambda d: d["players"][DEV]["player_state"] == "PLAYING")


def test_toast_on_driver_error(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.portal.call(client.app.state.services.cast._on_event, "error", None, "boom")
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "toast":
                assert msg == {"type": "toast", "level": "error", "message": "boom"}
                break
        else:
            raise AssertionError("no toast")
    wait_for(lambda: client.app.state.services.hub.client_count == 0)
