"""Shared media-URL classification and ranking (webpage resolver + remote browser)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

MEDIA_EXT = {
    ".m3u8": "hls",
    ".mpd": "dash",
    ".mp4": "progressive",
    ".m4v": "progressive",
    ".webm": "progressive",
    ".mkv": "progressive",
    ".mov": "progressive",
    ".flv": "progressive",
    ".ts": "progressive",
    ".mp3": "progressive",
    ".aac": "progressive",
    ".m4a": "progressive",
}
CT_KIND = {
    "application/vnd.apple.mpegurl": "hls",
    "application/x-mpegurl": "hls",
    "audio/mpegurl": "hls",
    "audio/x-mpegurl": "hls",
    "application/dash+xml": "dash",
}
AD_PATTERNS = re.compile(
    r"(doubleclick|googlesyndication|googleads|adservice|/ads?/|[_./-]ads?[_./-]|vast|preroll|"
    r"pre-roll|imasdk|adserver|advert|banner|promo|sponsor|tracking|analytics|pixel)",
    re.IGNORECASE,
)
SEGMENT_RE = re.compile(r"(seg|segment|chunk|frag|media_\d|_\d+\.ts$|/\d+\.ts$|\.m4s$|init\.mp4$)", re.I)
# Stricter, for non-.ts media paths (a VOD may well be called "/videos/12345.mp4"):
# seg-12-v1-a1.mp4, chunk_3.png, fragment-5.mp4, fileSequence123.mp4, init-v1.mp4, ...
SEGMENT_NAME_RE = re.compile(
    r"(?:^|[/_.-])(?:seg|segment|chunk|frag|fragment|part)[-_]?\d|filesequence\d|media_\d|/init[^/]*\.mp4$",
    re.I,
)
SEGMENT_EXTS = (".m4s", ".aac", ".cmfv", ".cmfa")
SEGMENT_CTS = ("video/mp2t", "video/iso.segment", "audio/mp2t")
# Query params that change on every request of the same stream (LL-HLS, tokens, cache busting)
VOLATILE_PARAMS = re.compile(
    r"^(_hls_(msn|part|skip|push)|_|t|ts|time|timestamp|cb|cachebust|cache|rnd|rand|random|nocache|"
    r"token|tok|auth|sig|signature|hdnts|hdnea|hmac|expires|exp|e|st|nonce|session|sid|wmsauthsign|"
    r"x-amz-[\w-]+|policy|key-pair-id)$",
    re.I,
)

MIME_BY_KIND = {
    "hls": "application/x-mpegURL",
    "dash": "application/dash+xml",
}
MIME_BY_EXT = {
    ".m3u8": "application/x-mpegURL",
    ".mpd": "application/dash+xml",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".flv": "video/x-flv",
    ".ts": "video/mp2t",
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def url_ext(url: str) -> str:
    path = urlsplit(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


TS_PACKET = 188


def sniff_container(head: bytes) -> str | None:
    """MIME type from the first bytes of a binary body, or None.

    Xtream/IPTV panels serve raw MPEG-TS (``/user/pass/12345``) and FLV as
    ``application/octet-stream`` with no extension: only the bytes tell.
    """
    if len(head) >= 2 * TS_PACKET + 1 and all(head[i] == 0x47 for i in (0, TS_PACKET, 2 * TS_PACKET)):
        return "video/mp2t"
    if head.startswith(b"FLV\x01"):
        return "video/x-flv"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video/x-msvideo"
    if head.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"):  # ASF (WMV)
        return "video/x-ms-wmv"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm" if b"webm" in head[:64] else "video/x-matroska"
    return None


def classify(url: str, content_type: str | None = None) -> str | None:
    """Return 'hls' | 'dash' | 'progressive' or None if it doesn't look like media."""
    if not url.startswith(("http://", "https://")):
        return None
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in CT_KIND:
        return CT_KIND[ct]
    if ct.startswith(("video/", "audio/")):
        return "progressive"
    ext = url_ext(url)
    if ext in MEDIA_EXT:
        return MEDIA_EXT[ext]
    # query-string hints, e.g. ...?format=m3u8 or /playlist.m3u8?token
    low = url.lower()
    if ".m3u8" in low:
        return "hls"
    if ".mpd" in low:
        return "dash"
    return None


def mime_for(url: str, kind: str | None = None, content_type: str | None = None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in CT_KIND:
        return MIME_BY_KIND[CT_KIND[ct]]
    if ct.startswith(("video/", "audio/", "image/")):
        return ct
    if kind in MIME_BY_KIND:
        return MIME_BY_KIND[kind]
    ext = url_ext(url)
    if ext in MIME_BY_EXT:
        return MIME_BY_EXT[ext]
    low = url.lower()
    if ".m3u8" in low:
        return MIME_BY_KIND["hls"]
    if ".mpd" in low:
        return MIME_BY_KIND["dash"]
    return "video/mp4"


def is_ad(url: str) -> bool:
    return bool(AD_PATTERNS.search(url))


def is_segment(url: str, content_type: str | None = None) -> bool:
    """A media *segment* (part of an HLS/DASH stream), not a playable stream by itself."""
    ext = url_ext(url)
    path = urlsplit(url).path
    ct = (content_type or "").split(";")[0].strip().lower()
    if ext in SEGMENT_EXTS:
        return True
    if ext == ".ts" and (SEGMENT_RE.search(url) or re.search(r"\d{2,}\.ts$", path)):
        return True
    mediaish = ext in MEDIA_EXT or ct.startswith(("video/", "audio/"))
    if mediaish and classify(url, content_type) == "progressive" and SEGMENT_NAME_RE.search(path):
        return True
    return ct in SEGMENT_CTS and bool(SEGMENT_RE.search(path))


def stream_key(url: str) -> str:
    """Identity of a stream URL without its volatile query params (LL-HLS ``_HLS_msn``,
    rotating tokens, cache busters), so playlist reloads aren't new captures."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not VOLATILE_PARAMS.match(k)]
    query = f"?{urlencode(sorted(kept))}" if kept else ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}{query}"


def score(
    url: str,
    kind: str | None,
    is_master: bool | None = None,
    height: int | None = None,
    content_length: int | None = None,
    is_live: bool | None = None,
) -> float:
    s = {"hls": 50.0, "dash": 45.0, "progressive": 30.0}.get(kind or "", 5.0)
    if is_master:
        s += 15
    if height:
        s += min(height, 2160) / 100
    if is_live:
        s += 2
    if is_ad(url):
        s -= 40
    if is_segment(url):
        s -= 30
    if content_length is not None and kind == "progressive" and content_length < 1_000_000:
        s -= 20  # short clips / teasers
    return round(s, 2)
