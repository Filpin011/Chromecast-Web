"""Local files under MEDIA_ROOT."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from app.errors import AppError
from app.models import LocalEntry, LocalListing

MEDIA_EXTS = {
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m2ts", ".flv", ".wmv",
    ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".wav", ".opus",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".vtt", ".srt", ".m3u", ".m3u8",
}
EXTRA_MIME = {
    ".mkv": "video/x-matroska",
    ".ts": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".m3u8": "application/x-mpegURL",
    ".flac": "audio/flac",
    ".vtt": "text/vtt",
    ".opus": "audio/ogg",
}
# Containers the Chromecast can't play directly → ffmpeg restream
NEEDS_RESTREAM = {".avi", ".wmv", ".flv", ".ts", ".m2ts"}


SUBTITLE_EXTS = (".vtt", ".srt")
MAX_SIDECARS = 12
_SRT_TIME = re.compile(r"(\d{1,2}:\d{2}:\d{2}),(\d{1,3})")


def sidecar_subtitles(video: Path) -> list[tuple[Path, str | None]]:
    """Subtitle files next to ``video``: ``Film.vtt``, ``Film.it.srt``, ``Film.en.forced.vtt``…

    Returns ``(path, lang)`` pairs, ``lang`` being the first dotted part after the stem
    (``None`` for a plain ``Film.srt``)."""
    stem = video.stem.lower()
    out: list[tuple[Path, str | None]] = []
    try:
        siblings = sorted(video.parent.iterdir(), key=lambda c: c.name.lower())
    except OSError:
        return out
    for child in siblings:
        name = child.name.lower()
        if child.suffix.lower() not in SUBTITLE_EXTS or not child.is_file():
            continue
        middle = name[: -len(child.suffix)]
        if middle == stem:
            out.append((child, None))
        elif middle.startswith(stem + "."):
            lang = middle[len(stem) + 1 :].split(".")[0] or None
            out.append((child, lang))
        if len(out) >= MAX_SIDECARS:
            break
    return out


def read_text_any(p: Path) -> str:
    """Subtitle files come in UTF-8 (with or without BOM) or legacy Windows code pages."""
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def srt_to_vtt(text: str) -> str:
    """Convert SubRip to WebVTT (the only text format the Default Media Receiver loads)."""
    body = text.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff\n ")
    body = _SRT_TIME.sub(lambda m: f"{m.group(1)}.{m.group(2).ljust(3, '0')}", body)
    return "WEBVTT\n\n" + body + "\n"


def guess_mime(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in EXTRA_MIME:
        return EXTRA_MIME[ext]
    return mimetypes.guess_type(path)[0]


def require_root(media_root: Path | None) -> Path:
    if media_root is None or not media_root.is_dir():
        raise AppError(404, "Local media browsing is disabled (MEDIA_ROOT not set)", "local_disabled")
    return media_root.resolve()


def safe_path(media_root: Path | None, rel: str) -> Path:
    """Resolve ``rel`` (relative to MEDIA_ROOT, or absolute under it) safely."""
    root = require_root(media_root)
    rel = rel.removeprefix("file://")
    candidate = Path(rel)
    p = candidate.resolve() if candidate.is_absolute() else (root / rel.lstrip("/")).resolve()
    if p != root and root not in p.parents:
        raise AppError(403, "Path outside MEDIA_ROOT", "forbidden_path")
    return p


def relative(media_root: Path, p: Path) -> str:
    return p.resolve().relative_to(media_root.resolve()).as_posix() if p.resolve() != media_root.resolve() else ""


def list_dir(media_root: Path | None, rel: str = "") -> LocalListing:
    root = require_root(media_root)
    p = safe_path(root, rel)
    if not p.is_dir():
        raise AppError(404, "Directory not found", "not_found")
    entries: list[LocalEntry] = []
    for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            entries.append(LocalEntry(name=child.name, path=relative(root, child), is_dir=True))
        elif child.suffix.lower() in MEDIA_EXTS and child.suffix.lower() not in SUBTITLE_EXTS:
            # subtitle files are not listed: they are attached to their video automatically
            entries.append(
                LocalEntry(
                    name=child.name,
                    path=relative(root, child),
                    is_dir=False,
                    size=child.stat().st_size,
                    mime_type=guess_mime(child.name),
                )
            )
    return LocalListing(path=relative(root, p), entries=entries)
