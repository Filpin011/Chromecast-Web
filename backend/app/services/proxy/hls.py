"""HLS playlist rewriting so every URI goes back through ``/proxy/{token}/...``."""

from __future__ import annotations

import base64
import re
from urllib.parse import unquote, urljoin, urlsplit

URI_ATTR_RE = re.compile(r'URI="([^"]*)"')
HLS_MEDIA_TAGS = (
    "#EXT-X-TARGETDURATION",
    "#EXT-X-STREAM-INF",
    "#EXT-X-MEDIA-SEQUENCE",
    "#EXT-X-ENDLIST",
    "#EXT-X-KEY",
    "#EXT-X-MAP",
    "#EXT-X-PLAYLIST-TYPE",
    "#EXT-X-I-FRAME-STREAM-INF",
    "#EXT-X-PART-INF",
)


def is_hls_playlist(text: str) -> bool:
    """True when ``text`` is an HLS playlist (as opposed to an IPTV M3U list)."""
    head = text.lstrip("\ufeff \r\n\t")
    if not head.startswith("#EXTM3U"):
        return False
    return any(tag in text for tag in HLS_MEDIA_TAGS)


def is_master_playlist(text: str) -> bool:
    return "#EXT-X-STREAM-INF" in text


def encode_url(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def decode_url(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad).decode()


def url_filename(url: str) -> str:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or "res"
    # keep it path-safe and short; it's only a hint for players sniffing extensions
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[-80:]
    return name or "res"


def proxy_path(token: str, absolute_url: str, prefix: str = "/proxy") -> str:
    """Root-relative proxy path for an absolute upstream URL.

    Root-relative so the same playlist works for the Chromecast (absolute base URL)
    and the browser preview (same origin).
    """
    return f"{prefix}/{token}/u/{encode_url(absolute_url)}/{url_filename(absolute_url)}"


def _rewrite_uri(uri: str, base_url: str, token: str, prefix: str) -> str:
    uri = uri.strip()
    if not uri:
        return uri
    scheme = urlsplit(uri).scheme.lower()
    if scheme and scheme not in ("http", "https"):
        return uri  # data:, skd://, etc. — leave untouched
    absolute = urljoin(base_url, uri)
    return proxy_path(token, absolute, prefix)


def rewrite_playlist(text: str, base_url: str, token: str, prefix: str = "/proxy") -> str:
    """Rewrite a master or media playlist.

    - plain URI lines (variants, segments)
    - ``URI="..."`` attributes on any tag (EXT-X-KEY, EXT-X-MAP, EXT-X-MEDIA,
      EXT-X-I-FRAME-STREAM-INF, EXT-X-SESSION-KEY, EXT-X-PART, EXT-X-PRELOAD-HINT, ...)
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            out.append(line)
        elif stripped.startswith("#"):
            if "URI=" in stripped:
                line = URI_ATTR_RE.sub(
                    lambda mt: f'URI="{_rewrite_uri(mt.group(1), base_url, token, prefix)}"', line
                )
            out.append(line)
        else:
            out.append(_rewrite_uri(stripped, base_url, token, prefix))
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


RESOLUTION_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
BANDWIDTH_RE = re.compile(r"(?:AVERAGE-)?BANDWIDTH=(\d+)")


def best_resolution(master_text: str) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for mt in RESOLUTION_RE.finditer(master_text):
        w, h = int(mt.group(1)), int(mt.group(2))
        if best is None or h > best[1]:
            best = (w, h)
    return best


def first_variant_url(master_text: str, base_url: str) -> str | None:
    lines = master_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for nxt in lines[i + 1 :]:
                nxt = nxt.strip()
                if nxt and not nxt.startswith("#"):
                    return urljoin(base_url, nxt)
    return None


def first_segment_url(media_text: str, base_url: str) -> str | None:
    """URL of the first segment of a media playlist (None for masters/empty lists)."""
    if is_master_playlist(media_text):
        return None
    for line in media_text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return urljoin(base_url, line)
    return None


def is_live_media_playlist(text: str) -> bool:
    if "#EXT-X-ENDLIST" in text:
        return False
    return "#EXT-X-PLAYLIST-TYPE:VOD" not in text


def quality_label(height: int | None) -> str | None:
    if not height:
        return None
    if height >= 2160:
        return f"{height}p 4K"
    if height >= 1440:
        return f"{height}p QHD"
    if height >= 1080:
        return f"{height}p FHD"
    if height >= 720:
        return f"{height}p HD"
    return f"{height}p SD"


# Segment container → Cast ``hlsSegmentFormat``. The Default Media Receiver assumes
# MPEG-TS when it is not set, so fMP4/CMAF and packed-audio streams fail to load.
FMP4_SEGMENT_EXTS = (".m4s", ".mp4", ".m4v", ".m4a", ".cmfv", ".cmfa", ".cmf", ".fmp4")
PACKED_AUDIO_FORMATS = {".aac": "aac", ".mp3": "mp3", ".ac3": "ac3", ".ec3": "e_ac3", ".eac3": "e_ac3"}
MAP_URI_RE = re.compile(r'#EXT-X-MAP:.*?URI="([^"]*)"')


def _uri_ext(uri: str) -> str:
    name = urlsplit(uri.strip()).path.rsplit("/", 1)[-1].lower()
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def segment_format(media_text: str) -> str | None:
    """Cast ``hlsSegmentFormat`` for a *media* playlist: "fmp4", "aac", "mp3", "ac3",
    "e_ac3", or None for MPEG-TS / unknown (the receiver's default)."""
    if is_master_playlist(media_text):
        return None
    mt = MAP_URI_RE.search(media_text)
    if mt is not None:
        # EXT-X-MAP is how fMP4/CMAF declares its init segment (a TS init section is rare)
        return None if _uri_ext(mt.group(1)) == ".ts" else "fmp4"
    for line in media_text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ext = _uri_ext(line)
            if ext in FMP4_SEGMENT_EXTS:
                return "fmp4"
            return PACKED_AUDIO_FORMATS.get(ext)
    return None


ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _tag_attrs(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in ATTR_RE.findall(line.partition(":")[2])}


def audio_rendition_url(master_text: str, base_url: str) -> str | None:
    """Media playlist of the audio rendition the receiver will pick for the first variant.

    Separate ``#EXT-X-MEDIA:TYPE=AUDIO`` renditions (YouTube, many CDNs) can use a
    different container than the video variant (e.g. packed ID3+ADTS AAC next to TS
    video), and ``hlsSegmentFormat`` describes the *audio* segments.
    """
    lines = [ln.strip() for ln in master_text.splitlines()]
    group = next(
        (_tag_attrs(ln).get("AUDIO") for ln in lines if ln.startswith("#EXT-X-STREAM-INF")),
        None,
    )
    renditions = [
        a for ln in lines if ln.startswith("#EXT-X-MEDIA:")
        if (a := _tag_attrs(ln)).get("TYPE") == "AUDIO" and a.get("URI")
    ]
    if group:
        renditions = [a for a in renditions if a.get("GROUP-ID") == group] or renditions
    if not renditions:
        return None
    best = next((a for a in renditions if a.get("DEFAULT", "").upper() == "YES"), renditions[0])
    return urljoin(base_url, best["URI"])


# Video codec family by RFC 6381 sample entry. The Cast LOAD carries one segment format
# for the whole stream, but masters may mix containers across variants (YouTube: avc1 in
# MPEG-TS up to 1080p next to vp09 in fMP4 up to 2160p), so a receiver switching variants
# would parse fMP4 as TS. The family is the best container hint a master offers.
VIDEO_CODEC_FAMILIES = {
    "avc1": "avc", "avc3": "avc",
    "hvc1": "hevc", "hev1": "hevc", "dvh1": "hevc", "dvhe": "hevc",
    "vp09": "vp9", "vp9": "vp9", "vp08": "vp8", "vp8": "vp8",
    "av01": "av1", "dav1": "av1",
}


def _video_family(attrs: dict[str, str]) -> str | None:
    """Video codec family of a variant from its CODECS attribute; None for audio-only/unknown."""
    for codec in attrs.get("CODECS", "").split(","):
        family = VIDEO_CODEC_FAMILIES.get(codec.strip().split(".", 1)[0].lower())
        if family:
            return family
    return None


def filter_variants(master_text: str) -> str:
    """Keep only the variants whose video codec family matches the first variant's.

    The first variant is the one probed for ``hlsSegmentFormat``. Variants that are
    audio-only or have no CODECS are kept (nothing to compare). A master with a single
    video family is returned unchanged.
    """
    lines = master_text.splitlines()
    variants = [_video_family(_tag_attrs(ln)) for ln in lines if ln.startswith("#EXT-X-STREAM-INF")]
    families = {f for f in variants if f}
    if len(families) < 2:
        return master_text
    keep = next(f for f in variants if f) if variants[0] is None else variants[0]
    out: list[str] = []
    drop_uri = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("#EXT-X-STREAM-INF", "#EXT-X-I-FRAME-STREAM-INF")):
            family = _video_family(_tag_attrs(stripped))
            if family is not None and family != keep:
                drop_uri = stripped.startswith("#EXT-X-STREAM-INF")
                continue
        elif drop_uri and stripped and not stripped.startswith("#"):
            drop_uri = False
            continue
        out.append(line)
    result = "\n".join(out)
    return result + "\n" if master_text.endswith("\n") else result


# Enough for the ID3 timestamp tag packed-audio segments start with + a frame header.
SEGMENT_SNIFF_BYTES = 4096
FMP4_BOXES = (b"ftyp", b"styp", b"moof", b"moov", b"sidx", b"emsg", b"prft")


def sniff_segment(head: bytes) -> str | None:
    """Container of an HLS segment from its first bytes, regardless of its file name:
    "ts", "fmp4", "aac", "mp3", "ac3", "e_ac3", or None when unrecognised."""
    if len(head) >= 8 and head[4:8] in FMP4_BOXES:
        return "fmp4"
    if head[:1] == b"\x47" and (len(head) <= 188 or head[188:189] == b"\x47"):
        return "ts"
    pos = 0
    if head[:3] == b"ID3" and len(head) >= 10:
        # ID3v2 header: "ID3", version(2), flags(1), syncsafe size(4); optional 10-byte footer
        size = (head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F)
        pos = 10 + size + (10 if head[5] & 0x10 else 0)
    frame = head[pos : pos + 6]
    if len(frame) < 6:
        return None
    if frame[0] == 0xFF and frame[1] & 0xF6 == 0xF0:  # ADTS: sync 0xFFF, layer 00
        return "aac"
    if frame[0] == 0xFF and frame[1] & 0xE0 == 0xE0 and frame[1] & 0x06:  # MPEG audio, layer I-III
        return "mp3"
    if frame[:2] == b"\x0b\x77":  # (E-)AC-3 sync word; bsid > 10 means E-AC-3
        return "e_ac3" if frame[5] >> 3 > 10 else "ac3"
    return None
