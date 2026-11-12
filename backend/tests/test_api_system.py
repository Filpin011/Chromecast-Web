from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from tests.conftest import player


def test_health_and_state(client):
    assert client.get("/api/health").json() == {"status": "ok", "driver": "fake", "version": "0.1.0"}
    st = client.get("/api/state").json()
    assert {d["name"] for d in st["devices"]} >= {"Chromecast Ultra (fake)"}
    assert st["players"] == {} and st["active_device_id"] is None and st["version"] >= 1


def test_settings_roundtrip_and_partial_update(client):
    s = client.get("/api/settings").json()
    assert s == {"idle_image_url": None, "show_idle_on_connect": True, "show_idle_on_stop": True,
                 "default_device_id": None, "public_base_url": None, "force_proxy": False,
                 "adblock_enabled": True, "adblock_disabled_hosts": [], "popup_policy": "ask",
                 "popup_blocked_hosts": []}
    s = client.put("/api/settings", json={"force_proxy": True, "idle_image_url": "https://x/i.jpg"}).json()
    assert s["force_proxy"] and s["idle_image_url"] == "https://x/i.jpg" and s["show_idle_on_stop"]
    s = client.put("/api/settings", json={"idle_image_url": None}).json()
    assert s["idle_image_url"] is None and s["force_proxy"]
    assert client.put("/api/settings", json={"force_proxy": "nope"}).status_code == 422
    s = client.put("/api/settings", json={"popup_policy": "block", "adblock_disabled_hosts": ["example.com"]}).json()
    assert s["popup_policy"] == "block" and s["adblock_disabled_hosts"] == ["example.com"]
    assert client.put("/api/settings", json={"popup_policy": "maybe"}).status_code == 422


def test_settings_persist_across_restarts(config: AppConfig):
    with TestClient(create_app(config)) as c:
        c.put("/api/settings", json={"public_base_url": "http://10.0.0.2:8000", "show_idle_on_connect": False})
        fav = c.post("/api/favorites", json={"title": "T", "input": "https://x/a.mp4", "source_kind": "direct"})
        assert fav.status_code == 201
    with TestClient(create_app(config)) as c:
        s = c.get("/api/settings").json()
        assert s["public_base_url"] == "http://10.0.0.2:8000" and s["show_idle_on_connect"] is False
        assert len(c.get("/api/favorites").json()) == 1
    assert (config.data_dir / "app.db").exists()


def test_favorites_crud_and_dedupe(client):
    body = {"title": "Rai 1", "input": "https://x/rai1.m3u8", "source_kind": "direct", "thumbnail": None}
    a = client.post("/api/favorites", json=body).json()
    b = client.post("/api/favorites", json={**body, "title": "Rai 1 HD"}).json()
    assert a["id"] == b["id"] and b["title"] == "Rai 1 HD"
    assert [f["title"] for f in client.get("/api/favorites").json()] == ["Rai 1 HD"]
    assert client.delete(f"/api/favorites/{a['id']}").status_code == 204
    r = client.delete(f"/api/favorites/{a['id']}")
    assert r.status_code == 404 and r.json()["code"] == "favorite_not_found"
    assert client.post("/api/favorites", json={"title": "x", "input": "y", "source_kind": "bad"}).status_code == 422


def test_history_recorded_on_play_and_cleared(client):
    client.put("/api/settings", json={"show_idle_on_connect": False})
    r = client.post("/api/devices/fake-ultra-0001/play", json={"input": "https://cdn.example.com/a.mp4"})
    assert r.status_code == 200
    h = client.get("/api/history?limit=5").json()
    assert h[0]["input"] == "https://cdn.example.com/a.mp4" and h[0]["device_id"] == "fake-ultra-0001"
    assert client.delete("/api/history").status_code == 204
    assert client.get("/api/history").json() == []


def test_local_listing_and_file_serving(client):
    root = client.get("/api/local").json()
    assert root["path"] == ""
    assert [e["name"] for e in root["entries"]] == ["Movies"]  # dirs first, non-media & hidden skipped
    movies = client.get("/api/local", params={"path": "Movies"}).json()
    film = next(e for e in movies["entries"] if e["name"] == "film.mp4")
    assert film == {"name": "film.mp4", "path": "Movies/film.mp4", "is_dir": False, "size": 2048,
                    "mime_type": "video/mp4"}
    assert client.get("/api/local", params={"path": "../.."}).status_code == 403
    r = client.get("/local/Movies/film.mp4", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert r.headers["content-range"] == "bytes 0-99/2048"
    assert client.get("/local/Movies/missing.mp4").status_code == 404


def test_local_disabled(config: AppConfig):
    config.media_root = None
    with TestClient(create_app(config, in_memory_db=True)) as c:
        r = c.get("/api/local")
        assert r.status_code == 404 and r.json()["code"] == "local_disabled"


def test_idle_image(client):
    r = client.get("/idle.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"


def test_cors_for_dev_frontend(client):
    r = client.options("/api/state", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    # `make dev` opened from a phone: the Next dev server is on the LAN IP
    for origin in ("http://192.168.1.20:3000", "http://10.0.0.7:3000", "http://nas.local:3000"):
        r = client.get("/api/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == origin
    r = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_origins_env_is_comma_separated(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example:3000, http://b.example:3000")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", "")
    cfg = AppConfig()
    assert cfg.cors_origins == ["http://a.example:3000", "http://b.example:3000"]
    assert not cfg.cors_origin_regex


def test_frontend_static_export_and_spa_fallback(config: AppConfig):
    front: Path = config.frontend_dir
    (front / "index.html").write_text("<html>home</html>")
    (front / "settings.html").write_text("<html>settings</html>")
    (front / "_next" / "static").mkdir(parents=True)
    (front / "_next" / "static" / "app.js").write_text("console.log(1)")
    with TestClient(create_app(config, in_memory_db=True)) as c:
        assert c.get("/").text == "<html>home</html>"
        assert c.get("/settings").text == "<html>settings</html>"
        assert c.get("/browser/abc").text == "<html>home</html>"  # SPA fallback
        r = c.get("/_next/static/app.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert c.get("/_next/static/missing.js").status_code == 404
        assert c.get("/api/nope").status_code == 404
        assert c.get("/api/nope").json()["code"] == "not_found"


def test_unknown_routes_without_frontend(client):
    assert client.get("/").status_code == 404
    assert player(client, "fake-ultra-0001") is None


def test_unexpected_errors_keep_the_error_contract(config, driver, provider, mock_http):
    from tests.fakes import ytdlp_info

    app = create_app(config, driver=driver, browser_provider=provider, ytdlp_extractor=ytdlp_info)
    with TestClient(app, raise_server_exceptions=False) as c:
        async def boom(*_a, **_kw):
            raise RuntimeError("bug")

        app.state.services.resolver.resolve = boom
        r = c.post("/api/resolve", json={"input": "https://cdn.example.com/a.mp4"})
        assert r.status_code == 500 and r.json() == {"detail": "Internal error: RuntimeError", "code": "internal_error"}


def test_malformed_resolve_input_is_a_400(client):
    r = client.post("/api/resolve", json={"input": "http://[bad/x"})
    assert r.status_code == 400 and r.json()["code"] == "unsupported_source"
