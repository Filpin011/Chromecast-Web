from tests.fakes import LIVE_MEDIA
from tests.test_m3u import IPTV

URL = "https://lists.example.com/italia.m3u"


def test_import_from_url_list_filter_paginate(client, mock_http):
    mock_http.get(URL).respond(200, text=IPTV)
    r = client.post("/api/playlists", json={"url": URL})
    assert r.status_code == 201
    pl = r.json()
    assert pl["name"] == "italia" and pl["channel_count"] == 5 and pl["source_url"] == URL
    assert pl["groups"] == ["Generalisti", "Sport, Calcio", "Musica", "Altro"]
    assert client.get("/api/playlists").json()[0]["id"] == pl["id"]
    assert client.get(f"/api/playlists/{pl['id']}").json()["channel_count"] == 5

    page = client.get(f"/api/playlists/{pl['id']}/channels", params={"limit": 2}).json()
    assert page["total"] == 5 and [c["name"] for c in page["items"]] == ["Rai 1 HD", "Sky Sport 24, Live"]
    page = client.get(f"/api/playlists/{pl['id']}/channels", params={"offset": 4}).json()
    assert [c["name"] for c in page["items"]] == ["bare.mp4"]
    page = client.get(f"/api/playlists/{pl['id']}/channels", params={"q": "sky"}).json()
    assert page["total"] == 1 and page["items"][0]["group"] == "Sport, Calcio"
    page = client.get(f"/api/playlists/{pl['id']}/channels", params={"q": "rai1.it"}).json()
    assert page["total"] == 1  # matches tvg-id
    page = client.get(f"/api/playlists/{pl['id']}/channels", params={"group": "Musica"}).json()
    assert [c["name"] for c in page["items"]] == ["Radio Italia"]
    assert page["items"][0]["playlist_id"] == pl["id"]


def test_import_from_content_with_name_and_refresh_rules(client):
    r = client.post("/api/playlists", json={"content": IPTV, "name": "Mia lista"})
    pl = r.json()
    assert pl["name"] == "Mia lista" and pl["source_url"] is None
    r = client.post(f"/api/playlists/{pl['id']}/refresh")
    assert r.status_code == 400 and r.json()["code"] == "no_source_url"


def test_refresh_replaces_channels(client, mock_http):
    route = mock_http.get(URL)
    route.respond(200, text=IPTV)
    pl = client.post("/api/playlists", json={"url": URL}).json()
    route.respond(200, text="#EXTM3U\n#EXTINF:-1 group-title=\"News\",Only One\nhttp://x/1.m3u8\n")
    pl2 = client.post(f"/api/playlists/{pl['id']}/refresh").json()
    assert pl2["channel_count"] == 1 and pl2["groups"] == ["News"]
    assert pl2["updated_at"] >= pl["updated_at"]


def test_errors(client, mock_http):
    assert client.post("/api/playlists", json={}).status_code == 422
    mock_http.get("https://lists.example.com/hls.m3u").respond(200, text=LIVE_MEDIA)
    r = client.post("/api/playlists", json={"url": "https://lists.example.com/hls.m3u"})
    assert r.status_code == 400 and r.json()["code"] == "unsupported_source"
    assert r.json()["reason"] == "hls_not_playlist"
    mock_http.get("https://lists.example.com/404.m3u").respond(404)
    r = client.post("/api/playlists", json={"url": "https://lists.example.com/404.m3u"})
    assert r.status_code == 502 and r.json()["code"] == "resolve_failed"
    # stable reason + params let the UI explain it in its own language; detail stays English
    assert r.json()["reason"] == "upstream_http" and r.json()["params"] == {"status": 404}
    assert r.json()["detail"] == "Upstream returned HTTP 404"
    r = client.post("/api/playlists", json={"content": "just text"})
    assert r.status_code == 400
    for method, path in [("get", "/api/playlists/x"), ("get", "/api/playlists/x/channels"),
                         ("post", "/api/playlists/x/refresh"), ("delete", "/api/playlists/x")]:
        r = getattr(client, method)(path)
        assert r.status_code == 404 and r.json()["code"] == "playlist_not_found"


def test_delete(client):
    pl = client.post("/api/playlists", json={"content": IPTV}).json()
    assert client.delete(f"/api/playlists/{pl['id']}").status_code == 204
    assert client.get("/api/playlists").json() == []


def test_channel_headers_persisted(client, mock_http):
    mock_http.get(URL).respond(200, text=IPTV)
    pl = client.post("/api/playlists", json={"url": URL}).json()
    items = client.get(f"/api/playlists/{pl['id']}/channels").json()["items"]
    sky = next(c for c in items if c["name"].startswith("Sky"))
    assert sky["headers"] == {"Referer": "https://sky.example.com/", "User-Agent": "Mozilla/5.0"}
    assert next(c for c in items if c["name"] == "Rai 1 HD")["headers"] == {}


def test_db_migrates_old_channels_table(tmp_path):
    import sqlite3

    from app.db import Database

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE channels (id VARCHAR PRIMARY KEY, playlist_id VARCHAR, position INTEGER, name VARCHAR,"
                " url VARCHAR, logo VARCHAR, group_title VARCHAR, tvg_id VARCHAR)")
    con.commit()
    con.close()
    db = Database(path)
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(channels)")]
    assert "headers_json" in cols
    db.close()
