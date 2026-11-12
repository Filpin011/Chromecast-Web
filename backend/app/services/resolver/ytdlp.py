"""yt-dlp based resolution (YouTube & the many sites it supports)."""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.models import Subtitle

log = logging.getLogger(__name__)

# Fast path: hosts we always hand to yt-dlp without loading its extractor list.
KNOWN_HOSTS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "twitch.tv",
    "vimeo.com",
    "dailymotion.com",
    "dai.ly",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "soundcloud.com",
    "reddit.com",
    "bilibili.com",
    "kick.com",
    "rumble.com",
    "streamable.com",
    "raiplay.it",
    "mediasetplay.mediaset.it",
    "la7.it",
)

# Chromecast-friendly: muxed HLS first, then muxed MP4, then anything muxed. YouTube
# no longer serves muxed formats (only split video-only / audio-only ones): then pick
# split HLS, whose ``manifest_url`` is an HLS *master* with the audio renditions that
# the receiver plays directly (see ``parse_info``). ``b*`` last: audio-only sites.
FORMAT = (
    "best[vcodec!=none][acodec!=none][protocol^=m3u8]/"
    "best[vcodec!=none][acodec!=none][ext=mp4]/"
    "best[vcodec!=none][acodec!=none]/"
    "bv*[protocol^=m3u8]+ba/"
    "bv*+ba/"
    "b*"
)


@dataclass
class YtdlpResult:
    url: str
    title: str
    thumbnail: str | None
    is_live: bool
    protocol: str
    ext: str | None
    headers: dict[str, str] = field(default_factory=dict)
    subtitles: list[Subtitle] = field(default_factory=list)
    duration: float | None = None


def host_matches(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in KNOWN_HOSTS)


@functools.lru_cache(maxsize=1)
def _extractors() -> list[Any]:
    from yt_dlp.extractor import gen_extractor_classes

    return [e for e in gen_extractor_classes() if e.IE_NAME not in ("generic",) and e.working()]


def extractor_matches(url: str) -> bool:
    """True if a dedicated (non-generic) yt-dlp extractor claims this URL."""
    if host_matches(url):
        return True
    try:
        return any(e.suitable(url) for e in _extractors())
    except Exception:  # pragma: no cover
        log.debug("yt-dlp extractor check failed", exc_info=True)
        return False


def extract_info(url: str) -> dict[str, Any]:
    """Blocking yt-dlp extraction (run in a thread)."""
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "format": FORMAT,
        "writesubtitles": True,
        "subtitleslangs": ["all"],
    }
    with YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)  # type: ignore[return-value]


def _pick_entry(info: dict[str, Any]) -> dict[str, Any]:
    if info.get("_type") in ("playlist", "multi_video"):
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise ValueError("Empty playlist")
        return entries[0]
    return info


def _video_only(fmt: dict[str, Any]) -> bool:
    return fmt.get("acodec") == "none" and fmt.get("vcodec") not in (None, "none")


def _hls_master(info: dict[str, Any], picked: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The HLS format whose ``manifest_url`` (master playlist, audio groups included)
    should be cast instead of a video-only stream: the picked one, else any other."""
    candidates = picked + [f for f in (info.get("formats") or []) if f not in picked]
    for fmt in candidates:
        if str(fmt.get("protocol") or "").startswith("m3u8") and fmt.get("manifest_url"):
            return fmt
    return None


def parse_info(info: dict[str, Any]) -> YtdlpResult:
    info = _pick_entry(info)
    url = info.get("url")
    headers = dict(info.get("http_headers") or {})
    protocol = info.get("protocol") or ""
    ext = info.get("ext")
    split = list(info.get("requested_formats") or [])
    if (not url and split) or (url and _video_only(info)):
        # Separate video/audio streams (current YouTube) or a video-only pick: the
        # Chromecast can't merge them. An HLS master carries both → cast that.
        fmt = _hls_master(info, split or [info])
        if fmt is not None:
            url = fmt["manifest_url"]
            protocol = "m3u8_native"
            ext = "mp4"
        elif split:
            # no HLS anywhere: last resort, the video stream alone (no audio)
            fmt = split[0]
            log.warning("yt-dlp: only split DASH formats, casting video without audio")
            url = fmt.get("url")
            protocol = fmt.get("protocol") or protocol
            ext = fmt.get("ext") or ext
        if fmt is not None:
            headers = dict(fmt.get("http_headers") or headers)
    if not url:
        raise ValueError("yt-dlp returned no playable URL")
    subs: list[Subtitle] = []
    for lang, tracks in (info.get("subtitles") or {}).items():
        for t in tracks or []:
            if t.get("ext") == "vtt" and t.get("url"):
                subs.append(Subtitle(url=t["url"], lang=lang, label=t.get("name") or lang))
                break
    return YtdlpResult(
        url=url,
        title=info.get("title") or info.get("id") or url,
        thumbnail=info.get("thumbnail"),
        is_live=bool(info.get("is_live")),
        protocol=protocol,
        ext=ext,
        headers=headers,
        subtitles=subs,
        duration=info.get("duration"),
    )


async def resolve_ytdlp(url: str, extractor=extract_info) -> YtdlpResult:
    info = await asyncio.to_thread(extractor, url)
    return parse_info(info)
