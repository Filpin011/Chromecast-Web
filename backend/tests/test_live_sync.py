"""Live sync of non-AppState data: `invalidate` messages on /ws, history delete and dedupe."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.db import Database
from app.main import create_app
from app.services.state import StateHub
from tests.test_m3u import IPTV

DEV = "fake-ultra-0001"
PL_URL = "https://lists.example.com/italia.m3u"


def _next_invalidate(ws, key: str, timeout: float = 3.0) -> dict:
    """Read until an `invalidate` that names ``key`` (state snapshots / toasts are skipped).

    The TestClient runs each websocket on its own event loop, and the hub (on the app's loop) puts into
    its queue without waking that loop: a ping/pong round trip keeps it turning while we wait.
    """
    deadline = time.monotonic() + timeout
    ws.send_json({"type": "ping"})
    while time.monotonic() < deadline:
        msg = ws.receive_json()
        if msg["type"] == "invalidate" and key in msg["keys"]:
            return msg
        if msg["type"] == "pong":
            time.sleep(0.01)
            ws.send_json({"type": "ping"})
    raise AssertionError(f"no invalidate for {key}")


def test_every_mutation_family_broadcasts_an_invalidate(client, mock_http):
    mock_http.get(PL_URL).respond(200, text=IPTV)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "state"

        client.put("/api/settings", json={"show_idle_on_connect": False})
        assert _next_invalidate(ws, "settings") == {"type": "invalidate", "keys": ["settings"]}

        fav = client.post("/api/favorites", json={"title": "A", "input": "https://x/a.mp4", "source_kind": "direct"}).json()
        _next_invalidate(ws, "favorites")
        client.patch(f"/api/favorites/{fav['id']}", json={"title": "B"})
        _next_invalidate(ws, "favorites")
        client.delete(f"/api/favorites/{fav['id']}")
        _next_invalidate(ws, "favorites")

        assert client.post(f"/api/devices/{DEV}/play", json={"input": "https://cdn.example.com/a.mp4"}).status_code == 200
        _next_invalidate(ws, "history")
        entry = client.get("/api/history").json()[0]
        assert client.delete(f"/api/history/{entry['id']}").status_code == 204
        _next_invalidate(ws, "history")
        client.delete("/api/history")
        _next_invalidate(ws, "history")

        pl = client.post("/api/playlists", json={"url": PL_URL}).json()
        _next_invalidate(ws, "playlists")
        assert client.post(f"/api/playlists/{pl['id']}/refresh").status_code == 200
        _next_invalidate(ws, "playlists")
        assert client.delete(f"/api/playlists/{pl['id']}").status_code == 204
        _next_invalidate(ws, "playlists")


def test_failed_mutations_do_not_invalidate(client):
    hub = client.app.state.services.hub
    q = hub.subscribe()
    try:
        assert client.delete("/api/favorites/nope").status_code == 404
        assert client.delete("/api/history/nope").status_code == 404
        assert client.delete("/api/playlists/nope").status_code == 404
        time.sleep(0.05)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        assert not [m for m in msgs if m["type"] == "invalidate"]
    finally:
        hub.unsubscribe(q)


def _drain(q: asyncio.Queue) -> list[list[str]]:
    out = []
    while not q.empty():
        msg = q.get_nowait()
        if msg["type"] == "invalidate":
            out.append(msg["keys"])
    return out


async def test_invalidate_bursts_are_coalesced_per_key():
    hub = StateHub(tick_interval=0, invalidate_window=0.1)
    q = hub.subscribe()
    hub.invalidate("history")  # leading edge: sent at once
    assert _drain(q) == [["history"]]
    for _ in range(20):  # burst inside the window: held back...
        hub.invalidate("history")
    hub.invalidate("favorites")  # ...while another key still goes out at once
    hub.invalidate("bogus")  # unknown keys are dropped
    assert _drain(q) == [["favorites"]]
    await asyncio.sleep(0.15)
    assert _drain(q) == [["history"]]  # ...and sent once at the end of the window
    await asyncio.sleep(0.15)
    assert _drain(q) == []
    await hub.stop()


async def test_invalidate_from_another_thread_reaches_the_loop():
    hub = StateHub(tick_interval=0, invalidate_window=0.05)
    hub.start()
    q = hub.subscribe()
    await asyncio.to_thread(hub.invalidate, "settings")
    await asyncio.sleep(0.02)
    assert _drain(q) == [["settings"]]
    await hub.stop()


def test_delete_history_entry(client):
    client.put("/api/settings", json={"show_idle_on_connect": False})
    for url in ("https://cdn.example.com/a.mp4", "https://cdn.example.com/b.mp4"):
        assert client.post(f"/api/devices/{DEV}/play", json={"input": url}).status_code == 200
    h = client.get("/api/history").json()
    assert [e["input"] for e in h] == ["https://cdn.example.com/b.mp4", "https://cdn.example.com/a.mp4"]
    assert client.delete(f"/api/history/{h[0]['id']}").status_code == 204
    assert [e["id"] for e in client.get("/api/history").json()] == [h[1]["id"]]
    r = client.delete(f"/api/history/{h[0]['id']}")
    assert r.status_code == 404 and r.json()["code"] == "history_not_found"


def test_replaying_moves_the_entry_to_the_top_without_duplicates():
    db = Database(None)
    first = db.add_history("A", "https://x/a.mp4", "direct", None, "dev1")
    db.add_history("B", "https://x/b.mp4", "direct", None, "dev1")
    again = db.add_history("A2", "https://x/a.mp4", "direct", "https://x/a.jpg", "dev2")
    h = db.list_history()
    assert [e.input for e in h] == ["https://x/a.mp4", "https://x/b.mp4"]
    assert again.id == first.id and again.played_at > first.played_at
    assert (h[0].title, h[0].thumbnail, h[0].device_id) == ("A2", "https://x/a.jpg", "dev2")
    db.close()


def test_existing_duplicate_history_rows_are_collapsed_on_startup(config: AppConfig, tmp_path: Path):
    db = Database(config.db_path)
    with db.engine.begin() as conn:
        for i, (rid, inp) in enumerate([("o1", "u1"), ("o2", "u2"), ("o3", "u1")]):
            conn.exec_driver_sql(
                "INSERT INTO history (id, title, input, source_kind, played_at) VALUES (?, ?, ?, 'direct', ?)",
                (rid, rid, inp, f"2026-01-0{i + 1} 00:00:00"),
            )
    db.close()
    with TestClient(create_app(config)) as c:
        h = c.get("/api/history").json()
        assert [(e["id"], e["input"]) for e in h] == [("o3", "u1"), ("o2", "u2")]
