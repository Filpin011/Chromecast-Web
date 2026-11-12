from app.services.proxy import dash
from app.services.proxy.hls import encode_url
from app.services.proxy.stream import upstream_url
from app.services.proxy.tokens import ProxyTarget

MPD_URL = "https://cdn.example.com/live/dash/manifest.mpd?tok=9"

MPD = """<?xml version="1.0" encoding="UTF-8"?>
<!-- a comment with <BaseURL>ignored</BaseURL> -->
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic">
  <Location>https://cdn.example.com/live/dash/manifest.mpd?tok=10&amp;x=1</Location>
  <Period id="1">
    <AdaptationSet mimeType="video/mp4">
      <SegmentTemplate media="../chunks/$RepresentationID$/seg_$Number%05d$.m4s" initialization="init_$RepresentationID$.mp4"/>
      <Representation id="v1" bandwidth="1"/>
    </AdaptationSet>
    <AdaptationSet mimeType="audio/mp4">
      <BaseURL>https://audio.cdn.example.net/a/</BaseURL>
      <Representation id="a1" bandwidth="1">
        <BaseURL>eng/</BaseURL>
        <SegmentTemplate media="/abs/$Number$.m4s" initialization="https://other.example.org/init.mp4"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""


def test_mpd_attrs():
    assert dash.mpd_attrs(MPD) == {"xmlns": "urn:mpeg:dash:schema:mpd:2011", "type": "dynamic"}
    assert dash.mpd_attrs("#EXTM3U") is None and not dash.is_mpd("<html></html>")


def test_rewrite_mpd_keeps_templates_and_relative_paths_inside_the_token():
    out = dash.rewrite_mpd(MPD, MPD_URL, "tok")
    # no MPD-level BaseURL → one pointing at the manifest is inserted right after <MPD>
    assert 'type="dynamic"><BaseURL>/proxy/tok/' in out
    assert "<BaseURL>/proxy/tok/a/https/cdn.example.com/live/dash/manifest.mpd?tok=9</BaseURL>" in out
    # relative template untouched: the receiver resolves it in the clear proxy space
    assert 'media="../chunks/$RepresentationID$/seg_$Number%05d$.m4s"' in out
    # absolute BaseURL mapped; relative child BaseURL kept
    assert "<BaseURL>/proxy/tok/a/https/audio.cdn.example.net/a/</BaseURL>" in out
    assert "<BaseURL>eng/</BaseURL>" in out
    # host-relative and absolute attributes mapped against the right base
    assert 'media="/proxy/tok/a/https/audio.cdn.example.net/abs/$Number$.m4s"' in out
    assert 'initialization="/proxy/tok/a/https/other.example.org/init.mp4"' in out
    assert "<Location>/proxy/tok/a/https/cdn.example.com/live/dash/manifest.mpd?tok=10&amp;x=1</Location>" in out
    assert "<!-- a comment with <BaseURL>ignored</BaseURL> -->" in out

    # what the receiver would request after template substitution and URL resolution
    from urllib.parse import urljoin

    t = ProxyTarget(token="tok", url=MPD_URL)
    base = "http://cast.test:8000/proxy/tok/a/https/cdn.example.com/live/dash/manifest.mpd?tok=9"
    seg = urljoin(base, "../chunks/v1/seg_00042.m4s")
    path = seg.split("/proxy/tok/", 1)[1]
    assert upstream_url(t, path) == "https://cdn.example.com/live/chunks/v1/seg_00042.m4s"


def test_existing_mpd_level_base_url_is_absolutized():
    mpd = '<MPD type="static"><BaseURL>media/</BaseURL><Period><BaseURL>p1/</BaseURL></Period></MPD>'
    out = dash.rewrite_mpd(mpd, "https://c.example/v/manifest.mpd", "t")
    assert out == ('<MPD type="static"><BaseURL>/proxy/t/a/https/c.example/v/media/</BaseURL>'
                   "<Period><BaseURL>p1/</BaseURL></Period></MPD>")


def test_upstream_url_clear_and_malformed_paths():
    import pytest

    from app.errors import AppError

    t = ProxyTarget(token="t", url="https://cdn/x/manifest.mpd")
    assert upstream_url(t, "a/https/cdn2.example/v/seg_1.m4s", "k=1") == "https://cdn2.example/v/seg_1.m4s?k=1"
    assert upstream_url(t, "seg.ts", "q=2") == "https://cdn/x/seg.ts?q=2"
    for bad in ("u/!!!notb64", f"u/{encode_url('file:///etc/passwd')}", "a/ftp/host/x", "a/https/"):
        with pytest.raises(AppError) as e:
            upstream_url(t, bad)
        assert e.value.status_code == 404 and e.value.code == "token_not_found"


def test_proxy_serves_rewritten_mpd_and_clear_segments(client, mock_http):
    mock_http.get("https://cdn.example.com/live/dash/manifest.mpd").respond(
        200, text=MPD, headers={"content-type": "application/dash+xml"})
    seg = mock_http.get("https://cdn.example.com/live/chunks/v1/seg_00001.m4s").respond(
        200, content=b"MOOF", headers={"content-type": "video/iso.segment"})
    sniffed = mock_http.get("https://cdn.example.com/other/stream").respond(
        200, text=MPD, headers={"content-type": "text/xml"})
    tokens = client.app.state.services.tokens
    t = tokens.register("https://cdn.example.com/live/dash/manifest.mpd", {"Referer": "https://site.example/"})
    r = client.get(f"/proxy/{t.token}/manifest.mpd")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/dash+xml")
    assert f"<BaseURL>/proxy/{t.token}/a/https/cdn.example.com/live/dash/manifest.mpd</BaseURL>" in r.text
    r = client.get(f"/proxy/{t.token}/a/https/cdn.example.com/live/chunks/v1/seg_00001.m4s")
    assert r.content == b"MOOF" and seg.calls.last.request.headers["referer"] == "https://site.example/"
    t2 = tokens.register("https://cdn.example.com/other/stream")
    r = client.get(f"/proxy/{t2.token}/stream")
    assert sniffed.called and f"/proxy/{t2.token}/a/https/" in r.text
    r = client.get(f"/proxy/{t.token}/u/%21%21notb64/x.ts")
    assert r.status_code == 404 and r.json()["code"] == "token_not_found"
