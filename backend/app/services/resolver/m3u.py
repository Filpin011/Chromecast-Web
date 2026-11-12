"""IPTV-style M3U parser (``#EXTINF`` lists, not HLS playlists)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from app.models import Channel
from app.services.resolver.inputs import normalize_headers, split_input

# #EXTINF attributes some lists use for per-channel headers
HEADER_ATTRS = ("user-agent", "http-user-agent", "http-referrer", "referrer", "referer", "http-origin")


@dataclass
class ParsedEntry:
    name: str
    url: str
    duration: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    group: str | None = None
    vlc_opts: dict[str, str] = field(default_factory=dict)
    http_headers: dict[str, str] = field(default_factory=dict)  # from #EXTHTTP

    @property
    def headers(self) -> dict[str, str]:
        """Request headers the channel needs (Referer, User-Agent, ...), from every
        convention: EXTINF attributes, #EXTVLCOPT, #EXTHTTP and Kodi ``url|Header=v``."""
        raw: dict[str, str] = {k: v for k, v in self.attrs.items() if k in HEADER_ATTRS}
        raw.update(self.vlc_opts)
        raw.update(self.http_headers)
        _, from_url = split_input(self.url)
        return {**normalize_headers(raw), **from_url}

    @property
    def clean_url(self) -> str:
        return split_input(self.url)[0]


@dataclass
class ParsedPlaylist:
    attrs: dict[str, str]
    entries: list[ParsedEntry]


def parse_attributes(s: str) -> tuple[dict[str, str], str]:
    """Parse ``key="value" key2=value2 ...`` up to the first unquoted comma.

    Returns (attrs, rest_after_comma). Quoted values may contain commas.
    """
    attrs: dict[str, str] = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            return attrs, ""
        if s[i] == ",":
            return attrs, s[i + 1 :]
        start = i
        while i < n and s[i] not in "= \t,":
            i += 1
        key = s[start:i]
        if i < n and s[i] == "=":
            i += 1
            if i < n and s[i] in "\"'":
                quote = s[i]
                i += 1
                vstart = i
                while i < n and s[i] != quote:
                    i += 1
                value = s[vstart:i]
                i += 1  # closing quote
            else:
                vstart = i
                while i < n and s[i] not in " \t,":
                    i += 1
                value = s[vstart:i]
            if key:
                attrs[key.lower()] = value.strip()
        elif not key:
            i += 1
    return attrs, ""


def _parse_extinf(line: str) -> tuple[str | None, dict[str, str], str]:
    body = line[len("#EXTINF:") :]
    # duration runs until whitespace or comma
    j = 0
    while j < len(body) and body[j] not in " \t,":
        j += 1
    duration = body[:j].strip() or None
    attrs, name = parse_attributes(body[j:])
    return duration, attrs, name.strip()


def parse_m3u(text: str) -> ParsedPlaylist:
    lines = text.lstrip("\ufeff").splitlines()
    header: dict[str, str] = {}
    entries: list[ParsedEntry] = []
    pending: ParsedEntry | None = None
    pending_group: str | None = None
    pending_opts: dict[str, str] = {}
    pending_http: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            header.update(parse_attributes(line[len("#EXTM3U") :])[0])
        elif line.startswith("#EXTINF:"):
            duration, attrs, name = _parse_extinf(line)
            pending = ParsedEntry(name=name, url="", duration=duration, attrs=attrs)
        elif line.startswith("#EXTGRP:"):
            pending_group = line[len("#EXTGRP:") :].strip() or None
        elif line.startswith("#EXTVLCOPT:"):
            opt = line[len("#EXTVLCOPT:") :]
            if "=" in opt:
                k, v = opt.split("=", 1)
                pending_opts[k.strip().lower()] = v.strip()
        elif line.startswith("#EXTHTTP:"):
            try:
                data = json.loads(line[len("#EXTHTTP:") :])
            except ValueError:
                data = None
            if isinstance(data, dict):
                pending_http.update({str(k): str(v) for k, v in data.items()})
        elif line.startswith("#"):
            continue
        else:
            entry = pending or ParsedEntry(name=line.rsplit("/", 1)[-1] or line, url="")
            entry.url = line
            entry.group = entry.attrs.get("group-title") or pending_group
            entry.vlc_opts = pending_opts
            entry.http_headers = pending_http
            if not entry.name:
                entry.name = entry.attrs.get("tvg-name") or line
            entries.append(entry)
            pending, pending_group, pending_opts, pending_http = None, None, {}, {}
    return ParsedPlaylist(attrs=header, entries=entries)


def looks_like_m3u_list(text: str) -> bool:
    """IPTV list: starts with #EXTM3U, has #EXTINF and no HLS-specific tags."""
    from app.services.proxy.hls import is_hls_playlist

    head = text.lstrip("\ufeff \r\n\t")
    return head.startswith("#EXTM3U") and "#EXTINF" in text and not is_hls_playlist(text)


def to_channels(parsed: ParsedPlaylist, playlist_id: str | None = None) -> list[Channel]:
    out: list[Channel] = []
    for e in parsed.entries:
        out.append(
            Channel(
                id=uuid.uuid4().hex,
                playlist_id=playlist_id,
                name=e.name or e.attrs.get("tvg-name") or e.clean_url,
                url=e.clean_url,
                headers=e.headers,
                logo=e.attrs.get("tvg-logo") or e.attrs.get("logo") or None,
                group=e.group,
                tvg_id=e.attrs.get("tvg-id") or None,
            )
        )
    return out
