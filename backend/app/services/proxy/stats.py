"""Proxy observability: per-segment timings, live playlist stalls, a periodic summary.

The access log can't show these: uvicorn logs the status when the headers go out, so a
segment whose body stalls mid-stream (or that the receiver gives up on) is invisible.
Per-request lines are DEBUG; INFO/WARNING only for what explains a playback stop.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from app.logging_setup import short_url

log = logging.getLogger(__name__)

SLOW_SECONDS = 5.0  # a segment slower than this (or than its own duration) is "slow"
SUMMARY_INTERVAL = 60.0
STALL_TARGETS = 3  # a live playlist is stalled after this many target durations unchanged
MAX_TOKENS = 32
MAX_DURATIONS = 256  # remembered EXTINF durations per token
MAX_PLAYLISTS = 8  # live playlists (renditions) followed per token

_SEQ_RE = re.compile(r"^#EXT-X-MEDIA-SEQUENCE:\s*(\d+)", re.M)
_TARGET_RE = re.compile(r"^#EXT-X-TARGETDURATION:\s*([\d.]+)", re.M)
_EXTINF_RE = re.compile(r"^#EXTINF:\s*([\d.]+)")


@dataclass
class PlaylistInfo:
    media_sequence: int | None
    target_duration: float | None
    segments: dict[str, float]  # absolute upstream URL -> EXTINF duration
    ended: bool


def parse_media_playlist(text: str, base_url: str) -> PlaylistInfo:
    seq = _SEQ_RE.search(text)
    target = _TARGET_RE.search(text)
    segments: dict[str, float] = {}
    duration: float | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _EXTINF_RE.match(line)
            if m:
                duration = float(m.group(1))
            continue
        if duration is not None:
            segments[urljoin(base_url, line)] = duration
            duration = None
    return PlaylistInfo(
        media_sequence=int(seq.group(1)) if seq else None,
        target_duration=float(target.group(1)) if target else None,
        segments=segments,
        ended="#EXT-X-ENDLIST" in text,
    )


@dataclass
class _LivePlaylist:
    sequence: int | None
    changed_at: float
    stalled: bool = False


@dataclass
class _TokenStats:
    host: str
    since: float
    segments: int = 0
    bytes: int = 0
    total_ms: float = 0.0
    slow: int = 0
    aborted: int = 0
    durations: OrderedDict[str, float] = field(default_factory=OrderedDict)
    playlists: OrderedDict[str, _LivePlaylist] = field(default_factory=OrderedDict)
    noted: set[str] = field(default_factory=set)


class ProxyStats:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._tokens: OrderedDict[str, _TokenStats] = OrderedDict()

    def _get(self, token: str, url: str) -> _TokenStats:
        st = self._tokens.get(token)
        if st is None:
            st = _TokenStats(host=urlsplit(url).hostname or "?", since=self.clock())
            self._tokens[token] = st
            while len(self._tokens) > MAX_TOKENS:
                self._tokens.popitem(last=False)
        else:
            self._tokens.move_to_end(token)
        return st

    def first_time(self, token: str, url: str, what: str) -> bool:
        """True the first time ``what`` happens for ``token`` (log it at INFO once, then DEBUG)."""
        st = self._get(token, url)
        if what in st.noted:
            return False
        st.noted.add(what)
        return True

    # ------------------------------------------------------------ playlists
    def playlist(self, token: str, url: str, text: str) -> None:
        """A media playlist went out: DEBUG line, remember durations, detect live stalls."""
        st = self._get(token, url)
        info = parse_media_playlist(text, url)
        for seg_url, dur in info.segments.items():
            st.durations[seg_url] = dur
            st.durations.move_to_end(seg_url)
        while len(st.durations) > MAX_DURATIONS:
            st.durations.popitem(last=False)
        log.debug(
            "proxy %s playlist %s: seq=%s segments=%d target=%ss%s",
            token[:6], short_url(url), info.media_sequence, len(info.segments),
            _num(info.target_duration), " ended" if info.ended else "",
        )
        if info.ended or info.media_sequence is None:
            return
        key = url.split("?", 1)[0]
        now = self.clock()
        live = st.playlists.get(key)
        if live is None:
            st.playlists[key] = _LivePlaylist(info.media_sequence, now)
            while len(st.playlists) > MAX_PLAYLISTS:
                st.playlists.popitem(last=False)
            return
        if info.media_sequence != live.sequence:
            if live.stalled:
                log.info(
                    "proxy %s live playlist %s advancing again: seq=%s after %.0fs",
                    token[:6], short_url(url), info.media_sequence, now - live.changed_at,
                )
            live.sequence, live.changed_at, live.stalled = info.media_sequence, now, False
            return
        limit = STALL_TARGETS * (info.target_duration or 6.0)
        if not live.stalled and now - live.changed_at > limit:
            live.stalled = True
            log.info(
                "proxy %s live playlist %s not advancing: seq=%s unchanged for %.0fs (target %ss)",
                token[:6], short_url(url), live.sequence, now - live.changed_at, _num(info.target_duration),
            )

    # ------------------------------------------------------------ segments
    def segment(
        self,
        token: str,
        url: str,
        *,
        status: int,
        nbytes: int,
        ttfb: float | None,
        total: float,
        outcome: str = "ok",
        detail: str = "",
        kind: str = "segment",
    ) -> None:
        """A proxied media segment finished (``outcome``: ok, upstream-error, client-gone)."""
        st = self._get(token, url)
        duration = st.durations.get(url)
        slow = total > SLOW_SECONDS or (duration is not None and total > duration)
        aborted = outcome != "ok"
        st.segments += 1
        st.bytes += nbytes
        st.total_ms += total * 1000
        st.slow += slow
        st.aborted += aborted
        where = f"proxy {token[:6]} {kind} {short_url(url)}"
        timing = (
            f"status={status} bytes={nbytes} ttfb={_ms(ttfb)} total={_ms(total)}"
            + (f" duration={_num(duration)}s" if duration is not None else "")
        )
        if outcome == "client-gone":
            log.warning("%s: client gave up after %.1f s, %d bytes (%s)", where, total, nbytes, timing)
        elif outcome == "upstream-error":
            log.warning("%s: upstream aborted mid-stream after %.1f s: %s (%s)", where, total, detail, timing)
        elif status >= 400:
            log.warning("%s: upstream returned %d (%s)", where, status, timing)
        elif slow:
            log.info("%s: slow (%s)", where, timing)
        else:
            log.debug("%s: %s", where, timing)
        self._maybe_summary(token, st)

    def _maybe_summary(self, token: str, st: _TokenStats) -> None:
        now = self.clock()
        if now - st.since < SUMMARY_INTERVAL or not st.segments:
            return
        log.info(
            "proxy %s %s: %d segments, %.1f MB, avg %.0f ms, slow %d, aborted %d (last %.0fs)",
            token[:6], st.host, st.segments, st.bytes / 1_000_000, st.total_ms / st.segments,
            st.slow, st.aborted, now - st.since,
        )
        st.since, st.segments, st.bytes, st.total_ms, st.slow, st.aborted = now, 0, 0, 0.0, 0, 0


def _ms(seconds: float | None) -> str:
    return "-" if seconds is None else f"{seconds * 1000:.0f}ms"


def _num(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:g}"
