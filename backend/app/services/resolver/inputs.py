"""Inputs that carry upstream request headers.

Kodi/IPTV convention: ``https://host/stream.m3u8|Referer=https%3A%2F%2Fsite%2F&User-Agent=VLC``.
This is the canonical way an input carries headers through the whole app (play,
queue, history, favorites), so replaying an entry later still sends them.
"""

from __future__ import annotations

from urllib.parse import quote, unquote, urlsplit

from app.services.proxy.tokens import clean_headers

# alternative spellings found in IPTV lists
ALIASES = {"referrer": "referer", "http-referrer": "referer", "http-user-agent": "user-agent",
           "useragent": "user-agent", "http-origin": "origin", "http-cookie": "cookie"}


def normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Map IPTV spellings to real header names and keep only forwardable ones."""
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        key = ALIASES.get(k.strip().lower(), k.strip().lower())
        if v:
            out[key] = v.strip()
    return clean_headers(out)


def split_input(value: str) -> tuple[str, dict[str, str]]:
    """``url|Header=value&...`` → (url, headers). Anything else → (value, {})."""
    value = value.strip()
    url, sep, opts = value.partition("|")
    if not sep or "=" not in opts or not urlsplit(url.strip()).scheme:
        return value, {}
    raw: dict[str, str] = {}
    for part in opts.split("&"):
        k, eq, v = part.partition("=")
        if eq and k.strip():
            raw[k] = unquote(v)
    return url.strip(), normalize_headers(raw)


def join_input(url: str, headers: dict[str, str] | None) -> str:
    """Inverse of ``split_input``; merges with headers already present in ``url``."""
    base, existing = split_input(url)
    hdrs = {**existing, **normalize_headers(headers)}
    if not hdrs:
        return base
    return base + "|" + "&".join(f"{k}={quote(v, safe='')}" for k, v in hdrs.items())
