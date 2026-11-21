"""Log format, noise filters, proxy observability and receiver error logging."""

import logging

import httpx
import pytest
from pychromecast.controllers.media import DefaultMediaReceiverController

from app.logging_setup import (
    AccessFilter,
    Formatter,
    UvicornErrorFilter,
    configure_logging,
    short_path,
    short_url,
    shorten_urls,
)
from app.services.cast import pychromecast_driver as drv
from app.services.cast.base import DeviceStatus
from app.services.cast.pychromecast_driver import (
    PyChromecastDriver,
    describe_error_code,
    log_receiver_errors,
)
from app.services.proxy.hls import encode_url
from app.services.proxy.stats import ProxyStats
from tests.test_pychromecast_driver import FakeCast, FakeMediaController, connected, lan, media_status  # noqa: F401

STATS = "app.services.proxy.stats"
DRIVER = "app.services.cast.pychromecast_driver"
TOKEN = "0123456789abcdef01234567"


def record(name: str, msg: str, args: tuple, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, args, None)


# ---------------------------------------------------------------- formatting


def test_short_url_drops_query_tokens_and_base64():
    long_b64 = encode_url("https://cdn.example.com/live/hi/seg100.ts?token=SECRET")
    assert short_url("https://user:pw@cdn.example.com/a/b/seg100.ts?token=SECRET#x") == "cdn.example.com/…/seg100.ts"
    assert short_url("https://cdn.example.com/index.m3u8?auth=1") == "cdn.example.com/index.m3u8"
    assert short_url("https://cdn.example.com") == "cdn.example.com/"
    assert short_url(None) == "-"
    cut = short_url(f"http://10.0.0.2:8000/proxy/{TOKEN}/u/{long_b64}")
    assert cut.startswith("10.0.0.2:8000/…/") and cut.endswith("…") and long_b64 not in cut
    assert "SECRET" not in shorten_urls("ReadTimeout on https://cdn.example.com/x/y.ts?token=SECRET now")


def test_short_path_for_access_log():
    path = f"/proxy/{TOKEN}/u/{encode_url('https://cdn.example.com/a/seg.ts')}/seg.ts?x=1"
    assert short_path(path) == "/proxy/012345/…/seg.ts"
    assert short_path("/api/devices/abc/play") == "/api/devices/abc/play"


def test_formatter_uses_short_logger_names():
    f = Formatter()
    line = f.format(record("app.services.proxy.stats", "hello %s", ("x",)))
    assert line.endswith("INFO    proxy.stats: hello x")
    assert " uvicorn: " in f.format(record("uvicorn.error", "Started", ()))


def test_access_filter_hides_successful_reads_but_keeps_mutations_and_errors():
    flt = AccessFilter()
    fmt = '%s - "%s %s HTTP/%s" %d'
    seg = f"/proxy/{TOKEN}/u/{encode_url('https://cdn.example.com/seg.ts')}/seg.ts"
    assert not flt.filter(record("uvicorn.access", fmt, ("1.2.3.4:5", "GET", seg, "1.1", 200)))
    assert not flt.filter(record("uvicorn.access", fmt, ("1.2.3.4:5", "GET", "/api/state", "1.1", 200)))
    assert not flt.filter(record("uvicorn.access", fmt, ("1.2.3.4:5", "GET", "/_next/static/a.js", "1.1", 304)))
    assert flt.filter(record("uvicorn.access", fmt, ("1.2.3.4:5", "POST", "/api/devices/x/play", "1.1", 200)))
    err = record("uvicorn.access", fmt, ("1.2.3.4:5", "GET", seg, "1.1", 404))
    assert flt.filter(err) and TOKEN not in err.getMessage() and "/proxy/012345/…/seg.ts" in err.getMessage()
    assert AccessFilter(verbose=True).filter(record("uvicorn.access", fmt, ("c", "GET", "/api/state", "1.1", 200)))
    ws = UvicornErrorFilter()
    assert not ws.filter(record("uvicorn.error", "connection open", ()))
    assert not ws.filter(record("uvicorn.error", '%s - "WebSocket %s" [accepted]', ("c", "/ws")))
    assert ws.filter(record("uvicorn.error", "Application startup complete.", ()))


def test_configure_logging_levels_and_idempotence():
    configure_logging("INFO")
    configure_logging("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("app").level == logging.INFO
    access = logging.getLogger("uvicorn.access")
    assert access.propagate and not access.handlers
    assert sum(isinstance(f, AccessFilter) for f in access.filters) == 1
    configure_logging("DEBUG")
    assert logging.getLogger("httpx").level == logging.INFO and logging.getLogger("app").level == logging.DEBUG
    configure_logging("INFO")


# ---------------------------------------------------------------- proxy observability


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


LIVE = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:{seq}\n#EXTINF:4.0,\nseg{seq}.ts\n#EXTINF:4.0,\nseg{n}.ts\n"
PL = "https://cdn.example.com/live/hi/index.m3u8?token=SECRET"


def live(seq: int) -> str:
    return LIVE.format(seq=seq, n=seq + 1)


def test_live_playlist_stall_is_logged_once_and_recovery_too(caplog):
    clock = Clock()
    stats = ProxyStats(clock)
    with caplog.at_level(logging.DEBUG, logger=STATS):
        stats.playlist(TOKEN, PL, live(10))
        for _ in range(5):  # same media sequence for 5 x 4 s > 3 target durations
            clock.now += 4
            stats.playlist(TOKEN, PL, live(10))
        clock.now += 4
        stats.playlist(TOKEN, PL, live(11))
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 2
    assert "not advancing: seq=10 unchanged for 16s" in info[0] and "advancing again: seq=11" in info[1]
    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug[0] == "proxy 012345 playlist cdn.example.com/…/index.m3u8: seq=10 segments=2 target=4s"
    assert not any("SECRET" in r.getMessage() or TOKEN in r.getMessage() for r in caplog.records)


def test_segment_lines_slow_aborted_and_summary(caplog):
    clock = Clock()
    stats = ProxyStats(clock)
    seg = "https://cdn.example.com/live/hi/seg10.ts"
    stats.playlist(TOKEN, PL, live(10))  # seg10.ts lasts 4 s
    with caplog.at_level(logging.DEBUG, logger=STATS):
        stats.segment(TOKEN, seg, status=200, nbytes=1000, ttfb=0.05, total=0.2)
        stats.segment(TOKEN, seg, status=200, nbytes=1000, ttfb=0.05, total=4.5)  # longer than its 4 s
        stats.segment(TOKEN, seg, status=200, nbytes=300, ttfb=0.1, total=10.2, outcome="client-gone")
        stats.segment(TOKEN, seg, status=403, nbytes=0, ttfb=0.1, total=0.1)
        clock.now += 61
        stats.segment(TOKEN, seg, status=200, nbytes=2_000_000, ttfb=0.05, total=0.2)
    lines = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert lines[0] == ("DEBUG", "proxy 012345 segment cdn.example.com/…/seg10.ts: "
                                 "status=200 bytes=1000 ttfb=50ms total=200ms duration=4s")
    assert lines[1][0] == "INFO" and ": slow (" in lines[1][1]
    assert lines[2][0] == "WARNING" and "client gave up after 10.2 s, 300 bytes" in lines[2][1]
    assert lines[3][0] == "WARNING" and "upstream returned 403" in lines[3][1]
    summary = lines[-1]
    assert summary[0] == "INFO"
    assert summary[1].startswith("proxy 012345 cdn.example.com: 5 segments, 2.0 MB, avg ")
    assert "slow 2, aborted 1" in summary[1]


def test_proxied_segment_logs_one_debug_line(client, mock_http, caplog):
    seg_url = "https://cdn.example.com/live/hi/seg100.ts?token=SECRET"
    mock_http.get(seg_url).respond(200, content=b"\x47" * 600, headers={"content-type": "video/mp2t"})
    mock_http.get("https://cdn.example.com/live/hi/gone.ts").respond(404)
    mock_http.get("https://cdn.example.com/live/hi/dead.ts").mock(side_effect=httpx.ConnectError("refused"))
    t = client.app.state.services.tokens.register("https://cdn.example.com/live/master.m3u8")
    with caplog.at_level(logging.DEBUG, logger="app.services.proxy"):
        assert client.get(f"/proxy/{t.token}/u/{encode_url(seg_url)}/seg100.ts").status_code == 200
        gone = encode_url("https://cdn.example.com/live/hi/gone.ts")
        assert client.get(f"/proxy/{t.token}/u/{gone}/gone.ts").status_code == 404
        dead = encode_url("https://cdn.example.com/live/hi/dead.ts")
        assert client.get(f"/proxy/{t.token}/u/{dead}/dead.ts").status_code == 502
    msgs = [(r.levelname, r.getMessage()) for r in caplog.records]
    ok = [m for lvl, m in msgs if lvl == "DEBUG" and "seg100.ts" in m]
    assert len(ok) == 1 and "status=200 bytes=600 ttfb=" in ok[0]
    assert any(lvl == "WARNING" and "gone.ts: upstream returned 404" in m for lvl, m in msgs)
    assert any(lvl == "WARNING" and "upstream error GET cdn.example.com/…/dead.ts: refused" in m for lvl, m in msgs)
    assert not any("SECRET" in m or t.token in m for _, m in msgs)


# ---------------------------------------------------------------- receiver errors


def test_describe_error_code():
    assert describe_error_code(314) == "314 HLS_NETWORK_KEY_LOAD"
    assert describe_error_code(310) == "310 network error (3xx)"
    assert describe_error_code(1234) == "1234"
    assert describe_error_code(None) == "-"


class RecordingMediaController(FakeMediaController):
    def receive_message(self, message, data):
        return True


@pytest.fixture(autouse=True)
def _fresh_dedup(monkeypatch):
    monkeypatch.setattr(drv, "_last_receiver_error", {})


async def test_receiver_error_logged_once_per_message(monkeypatch, caplog):
    cast = FakeCast(name="Salotto")
    cast.media_controller = RecordingMediaController()
    d = await connected(monkeypatch, cast)
    dmr = next(h for h in cast.handlers if isinstance(h, DefaultMediaReceiverController))
    error = {"type": "ERROR", "detailedErrorCode": 310, "reason": None, "itemId": 1}
    with caplog.at_level(logging.DEBUG, logger=DRIVER):
        # pychromecast's SocketClient._route_message: every handler of the namespace
        for _ in range(2):  # and the receiver repeating itself
            for handler in (dmr, cast.media_controller):
                handler.receive_message(None, dict(error))
        cast.media_controller.receive_message(None, {**error, "detailedErrorCode": 104})
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        'receiver ERROR on "Salotto" (manual-1): detailedErrorCode=310 network error (3xx) reason=None itemId=1',
        'receiver ERROR on "Salotto" (manual-1): detailedErrorCode=104 MEDIA_SRC_NOT_SUPPORTED reason=None itemId=1',
    ]
    assert d.is_connected("manual-10.0.0.9")


def test_receiver_error_wrapper_is_idempotent(caplog):
    ctl = RecordingMediaController()
    log_receiver_errors(ctl, "dev1")
    log_receiver_errors(ctl, "dev1")
    with caplog.at_level(logging.INFO, logger=DRIVER):
        ctl.receive_message(None, {"type": "LOAD_FAILED", "itemId": 3})
    assert [r.getMessage() for r in caplog.records] == [
        "receiver LOAD_FAILED on dev1: detailedErrorCode=- reason=None itemId=3"
    ]


async def test_media_status_log_names_device_idle_reason_and_content_once(caplog):
    d = PyChromecastDriver()
    d._casts["uuid-1234567890"] = FakeCast(name="Salotto")
    d._status["uuid-1234567890"] = DeviceStatus(connected=True)
    url = "http://10.0.0.2:8000/proxy/" + TOKEN + "/index.m3u8?x=1"
    with caplog.at_level(logging.INFO, logger=DRIVER):
        d._on_media_status("uuid-1234567890", media_status(content_id=url))
        d._on_media_status("uuid-1234567890", media_status(content_id=url, player_state="IDLE", idle_reason="ERROR"))
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == [
        'media status "Salotto" (uuid-123): UNKNOWN -> PLAYING content=10.0.0.2:8000/…/index.m3u8',
        'media status "Salotto" (uuid-123): PLAYING -> IDLE idleReason=ERROR',
    ]
    assert caplog.records[1].levelno == logging.WARNING
