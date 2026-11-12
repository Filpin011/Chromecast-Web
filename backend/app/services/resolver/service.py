"""Source resolution: detect the kind of an input and turn it into a ``ResolvedMedia``.

Also owns the "should this go through the proxy / restream?" decision and builds
``cast_url`` (absolute, reachable by the Chromecast) and ``preview_url`` (same-origin
path usable by the browser preview).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.errors import AppError
from app.models import (
    Channel,
    MediaResult,
    PlaylistResult,
    ResolvedMedia,
    SourceKind,
    StreamType,
    Subtitle,
)
from app.services.browser.launcher import DESKTOP_UA, BrowserProvider
from app.services.proxy import dash, hls
from app.services.proxy.restream import RestreamManager
from app.services.proxy.tokens import TokenRegistry, clean_headers
from app.services.resolver import local as localres
from app.services.resolver import m3u, sniff, webpage, ytdlp
from app.services.resolver.inputs import split_input

log = logging.getLogger(__name__)

PROBE_BYTES = 64 * 1024
SNIFF_BYTES = 1024  # enough for 3 MPEG-TS packets / any container magic
HLS_MIME = "application/x-mpegURL"
DASH_MIME = "application/dash+xml"
# Headers whose presence means the upstream needs them → must proxy for the Chromecast.
SENSITIVE_HEADERS = ("referer", "origin", "cookie", "authorization")
# Origin the Default Media Receiver sends on its XHR/MSE requests
CAST_RECEIVER_ORIGIN = "https://www.gstatic.com"
RESTREAM_SCHEMES = ("rtmp", "rtmps", "rtsp", "rtp", "udp", "srt", "mms")
# contentType announced to the receiver instead of the real one. The Default Media
# Receiver checks canPlayType(), which is "" for video/x-matroska on Cast Chromium,
# although its demuxer plays H.264/AAC (and VP8/9) Matroska fine.
CAST_MIME_ALIASES = {"video/x-matroska": "video/mp4", "video/mkv": "video/mp4"}
RESTREAM_MIMES = ("video/mp2t", "video/x-flv", "video/x-msvideo", "video/x-ms-wmv", "video/avi")


@dataclass
class Probe:
    status: int
    url: str
    content_type: str
    text: str
    content_length: int | None = None
    head: bytes = b""  # first bytes of a binary (octet-stream) body

    @property
    def sniffed_mime(self) -> str | None:
        """Container recognised from the body bytes (raw TS / FLV served as octet-stream)."""
        return sniff.sniff_container(self.head) if self.head else None

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type or self.text.lstrip()[:15].lower().startswith(
            ("<!doctype html", "<html")
        )

    @property
    def is_m3u(self) -> bool:
        return self.text.lstrip("\ufeff \r\n\t").startswith("#EXTM3U")


@dataclass
class HlsInfo:
    is_master: bool | None = None
    is_live: bool | None = None
    width: int | None = None
    height: int | None = None
    cors: bool | None = None  # upstream sends Access-Control-Allow-Origin
    segment_format: str | None = None  # Cast hlsSegmentFormat (audio); None = MPEG-TS/unknown
    # Cast hlsVideoSegmentFormat: "fmp4" when the video is fMP4, even next to a packed
    # audio rendition (then segment_format is the audio's "aac"/...); None = MPEG-TS.
    video_segment_format: str | None = None
    # The master mixes video codec families (YouTube: avc1/TS + vp09/fMP4): only the
    # proxy can serve the receiver a master limited to the probed variant's family.
    mixed_variants: bool = False


@dataclass
class _ProbeState:
    origin: str | None  # the Origin sent (None: CORS not checked)
    rejected: bool = False  # a playlist or segment request answered an HTTP error

    def allows(self, headers: httpx.Headers) -> bool:
        return self.origin is not None and _allows_origin(headers, self.origin)


@dataclass
class DashInfo:
    is_live: bool | None = None  # MPD type="dynamic"
    cors: bool | None = None  # manifest answers the receiver's Origin


@dataclass
class Candidate:
    """An intermediate, not yet proxied media URL."""

    url: str
    source_kind: SourceKind
    original_input: str
    title: str | None = None
    thumbnail: str | None = None
    mime_type: str | None = None
    stream_type: StreamType | None = None
    headers: dict[str, str] = field(default_factory=dict)
    subtitles: list[Subtitle] = field(default_factory=list)
    local_path: Path | None = None
    # The user / playlist explicitly asked for a User-Agent (``url|User-Agent=...``,
    # #EXTVLCOPT:http-user-agent): the Chromecast sends its own CrKey UA, so proxy.
    # The UA yt-dlp or the headless browser add on their own does not count.
    pinned_user_agent: bool = False


def is_url(value: str) -> bool:
    try:
        return urlsplit(value).scheme.lower() in ("http", "https")
    except ValueError:  # e.g. "http://[bad" (unbalanced IPv6 bracket)
        return False


def validate_url(value: str) -> None:
    """Reject malformed inputs early with a clean 400 instead of a crash deep in httpx."""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() in ("http", "https"):
            httpx.URL(value)
            if not parts.hostname:
                raise ValueError("missing host")
    except (ValueError, httpx.InvalidURL) as exc:
        raise AppError(
            400, f"Malformed URL ({exc}): {value[:80]}", "unsupported_source", reason="malformed_url"
        ) from exc


CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


def _host(url: str) -> str:
    return urlsplit(url).hostname or url[:80]


def _connect_failed(url: str, exc: Exception) -> AppError:
    host = _host(url)
    return AppError(
        502,
        f"Could not connect to {host}: {exc or type(exc).__name__}",
        "resolve_failed",
        reason="connect_failed",
        params={"host": host},
    )


def title_from_url(url: str) -> str:
    parts = urlsplit(url)
    name = parts.path.rstrip("/").rsplit("/", 1)[-1]
    if name and "." in name:
        name = name.rsplit(".", 1)[0]
    return name or parts.hostname or url


def _allows_origin(headers: httpx.Headers, origin: str) -> bool:
    acao = headers.get("access-control-allow-origin", "").strip()
    return acao == "*" or acao == origin


def needs_header_proxy(headers: dict[str, str]) -> bool:
    return any(k.lower() in SENSITIVE_HEADERS and v for k, v in headers.items())


class Resolver:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: TokenRegistry,
        restream: RestreamManager,
        *,
        media_root: Path | None,
        browser: BrowserProvider | None,
        enable_playwright: bool = True,
        webpage_timeout: float = 20.0,
        ytdlp_extractor: Callable[[str], dict[str, Any]] = ytdlp.extract_info,
        base_url: Callable[[], str],
        force_proxy: Callable[[], bool] = lambda: False,
        filters: Any = None,
        adblock_enabled: Callable[[str], bool] = lambda _url: True,
    ) -> None:
        self.client = client
        self.tokens = tokens
        self.restream = restream
        self.media_root = media_root
        self.browser = browser
        self.enable_playwright = enable_playwright
        self.webpage_timeout = webpage_timeout
        self.ytdlp_extractor = ytdlp_extractor
        self.base_url = base_url
        self.force_proxy = force_proxy
        self.filters = filters  # FilterManager | None (ad blocking inside the headless page)
        self.adblock_enabled = adblock_enabled

    # ------------------------------------------------------------ http helpers
    async def probe(self, url: str, headers: dict[str, str] | None = None) -> Probe:
        hdrs = {"User-Agent": DESKTOP_UA, **(headers or {})}
        req = self.client.build_request("GET", url, headers=hdrs)
        resp = await self.client.send(req, stream=True, follow_redirects=True)
        try:
            buf = bytearray()
            ct = resp.headers.get("content-type", "").lower()
            media = ct.startswith(("video/", "audio/", "image/"))
            binary = not media and ("octet-stream" in ct or "binary" in ct)
            limit = SNIFF_BYTES if binary else PROBE_BYTES
            if not media and resp.status_code < 400:
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) >= limit:
                        break
            cl = resp.headers.get("content-length")
            data = bytes(buf)
            if not binary and sniff.sniff_container(data[:SNIFF_BYTES]):
                binary = True  # e.g. raw TS answered as text/plain or with no content type
            return Probe(
                status=resp.status_code,
                url=str(resp.url),
                content_type=ct,
                text="" if binary else data.decode("utf-8", errors="replace"),
                content_length=int(cl) if cl and cl.isdigit() else None,
                head=data[:SNIFF_BYTES] if binary else b"",
            )
        finally:
            await resp.aclose()

    async def probe_reachable(self, url: str, headers: dict[str, str] | None = None) -> Probe | None:
        """``probe`` that turns "host unreachable" into 502 resolve_failed (anything else → None)."""
        try:
            return await self.probe(url, headers)
        except CONNECT_ERRORS as exc:
            raise _connect_failed(url, exc) from exc
        except Exception as exc:
            log.debug("probe failed for %s: %s", url, exc)
            return None

    async def _get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        hdrs = {"User-Agent": DESKTOP_UA, **(headers or {})}
        try:
            resp = await self.client.get(url, headers=hdrs, follow_redirects=True)
        except CONNECT_ERRORS as exc:
            raise _connect_failed(url, exc) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                502,
                f"Could not fetch {url}: {exc}",
                "resolve_failed",
                reason="fetch_failed",
                params={"host": _host(url)},
            ) from exc
        if resp.status_code >= 400:
            raise AppError(
                502,
                f"Upstream returned HTTP {resp.status_code}",
                "resolve_failed",
                reason="upstream_http",
                params={"status": resp.status_code},
            )
        return resp

    async def fetch_text(self, url: str, headers: dict[str, str] | None = None) -> tuple[str, str]:
        resp = await self._get(url, headers)
        return resp.text, str(resp.url)

    async def hls_info(self, url: str, headers: dict[str, str] | None = None) -> HlsInfo:
        """Best effort: master/media, live (no ENDLIST), best resolution, CORS, segment format.

        CORS is checked the way the Cast receiver will hit it: with an ``Origin`` header
        (many CDNs only answer ACAO when one is sent), on the playlist, on the first
        variant, on the audio rendition and on their first segments (some CDNs allow the
        .m3u8 but not segments). ``cors`` stays None when it could not be verified.

        A CDN that allow-lists Origins (hotlink protection) answers that probe with an
        HTTP error: the stream is then probed again without ``Origin`` (the way the proxy
        fetches it) for master/live/segment format, with ``cors`` False so it is proxied.

        The segment format comes from the segment bytes (names lie: YouTube serves packed
        ID3+ADTS audio as ``seg.ts``), falling back to the playlist's URIs. A separate
        audio rendition decides ``segment_format`` (``hlsSegmentFormat`` describes the
        audio); ``video_segment_format`` keeps the video's own fMP4.
        """
        base = dict(headers or {})
        info, rejected = await self._hls_probe(url, {"Origin": CAST_RECEIVER_ORIGIN, **base})
        if rejected and not any(k.lower() == "origin" for k in base):
            log.debug("hls probe: %s rejects the receiver's Origin, probing without it", url)
            info, _ = await self._hls_probe(url, base)
            info.cors = False
        return info

    async def _hls_probe(self, url: str, hdrs: dict[str, str]) -> tuple[HlsInfo, bool]:
        """(info, an upstream answered an HTTP error). Without an ``Origin`` in ``hdrs``
        CORS is not checked (``cors`` False)."""
        info = HlsInfo()
        state = _ProbeState(origin=hdrs.get("Origin"))
        resp = await self._manifest(url, hdrs, state)
        if resp is None:
            return info, state.rejected
        try:
            text, final = resp.text, str(resp.url)
            cors = state.allows(resp.headers)
            if not text.lstrip("\ufeff \r\n\t").startswith("#EXTM3U"):
                return info, state.rejected
            info.is_master = hls.is_master_playlist(text)
            media_text, media_base = text, final
            audio_url: str | None = None
            if info.is_master:
                filtered = hls.filter_variants(text)
                info.mixed_variants = filtered != text
                text = filtered  # what the proxy serves the receiver
                res = hls.best_resolution(text)
                if res:
                    info.width, info.height = res
                audio_url = hls.audio_rendition_url(text, final)
                variant = hls.first_variant_url(text, final)
                if variant:
                    vresp = await self._probe_get(variant, hdrs, state)
                    media_text, media_base = vresp.text, str(vresp.url)
                    cors = cors and state.allows(vresp.headers)
                    info.is_live = hls.is_live_media_playlist(media_text)
            else:
                info.is_live = hls.is_live_media_playlist(text)
            fmt, seg_cors = await self._media_playlist_format(media_text, media_base, hdrs, state)
            cors = cors and seg_cors
            info.segment_format = fmt
            info.video_segment_format = "fmp4" if fmt == "fmp4" else None
            if audio_url:
                aresp = await self._probe_get(audio_url, hdrs, state)
                cors = cors and state.allows(aresp.headers)
                afmt, seg_cors = await self._media_playlist_format(aresp.text, str(aresp.url), hdrs, state)
                cors = cors and seg_cors
                if afmt in ("fmp4", "aac", "mp3", "ac3", "e_ac3"):
                    info.segment_format = afmt  # the audio rendition's own container
            info.cors = cors
        except Exception as exc:  # network errors are not fatal here
            log.debug("hls probe failed for %s: %s", url, exc)
        return info, state.rejected

    async def _probe_get(self, url: str, headers: dict[str, str], state: _ProbeState) -> httpx.Response:
        try:
            return await self._get(url, headers)
        except AppError as exc:
            if exc.reason == "upstream_http":
                state.rejected = True
            raise

    async def _media_playlist_format(
        self, text: str, base: str, headers: dict[str, str], state: _ProbeState | None = None
    ) -> tuple[str | None, bool]:
        """(Cast hlsSegmentFormat, first segment answers the receiver's Origin) of a media playlist."""
        fmt = hls.segment_format(text)
        segment = hls.first_segment_url(text, base)
        if not segment:
            return fmt, True
        allowed, head = await self._segment_head(segment, headers, state)
        sniffed = hls.sniff_segment(head)
        if sniffed is not None:
            fmt = None if sniffed == "ts" else sniffed
        return fmt, allowed

    async def dash_info(self, url: str, headers: dict[str, str] | None = None) -> DashInfo:
        """Best effort: live (dynamic MPD) and CORS on the manifest, as the receiver sees it."""
        info = DashInfo()
        hdrs = {"Origin": CAST_RECEIVER_ORIGIN, **(headers or {})}
        resp = await self._manifest(url, hdrs)
        if resp is None:
            return info
        try:
            info.cors = _allows_origin(resp.headers, hdrs["Origin"])
            mpd = dash.mpd_attrs(resp.text)
            if mpd is not None:
                info.is_live = mpd.get("type", "static").lower() == "dynamic"
        except Exception as exc:
            log.debug("dash probe failed for %s: %s", url, exc)
        return info

    async def _manifest(
        self, url: str, headers: dict[str, str], state: _ProbeState | None = None
    ) -> httpx.Response | None:
        """Fetch a manifest for probing. An unreachable host is fatal (502 resolve_failed:
        casting it can only fail on the TV); any other problem (4xx, CORS, garbage) is not."""
        try:
            return await self._get(url, headers)
        except AppError as exc:
            if isinstance(exc.__cause__, CONNECT_ERRORS):
                raise
            if state is not None and exc.reason == "upstream_http":
                state.rejected = True
            log.debug("manifest probe failed for %s: %s", url, exc)
        except Exception as exc:  # anything else is not fatal for a best-effort probe
            log.debug("manifest probe failed for %s: %s", url, exc)
        return None

    async def _segment_head(
        self, url: str, headers: dict[str, str], state: _ProbeState | None = None
    ) -> tuple[bool, bytes]:
        """(answers the receiver's Origin, first bytes) of a segment; only a few KB are read."""
        try:
            req = self.client.build_request("GET", url, headers={"User-Agent": DESKTOP_UA, **headers})
            resp = await self.client.send(req, stream=True, follow_redirects=True)
            try:
                if resp.status_code >= 400:
                    if state is not None:
                        state.rejected = True
                    return False, b""
                origin = headers.get("Origin")
                allowed = origin is not None and _allows_origin(resp.headers, origin)
                buf = bytearray()
                with contextlib.suppress(httpx.HTTPError):
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) >= hls.SEGMENT_SNIFF_BYTES:
                            break
                return allowed, bytes(buf[: hls.SEGMENT_SNIFF_BYTES])
            finally:
                await resp.aclose()
        except Exception:
            return False, b""

    # ------------------------------------------------------------ detection
    def _local_candidate(self, value: str) -> Path | None:
        if self.media_root is None:
            return None
        if is_url(value) or urlsplit(value).scheme not in ("", "file"):
            return None
        try:
            p = localres.safe_path(self.media_root, value)
        except AppError:
            return None
        return p if p.is_file() else None

    async def detect_kind(self, value: str) -> SourceKind:
        """Cheap detection (may do one small HTTP probe)."""
        value, headers = split_input(value)
        validate_url(value)
        if self._local_candidate(value) is not None:
            return "local"
        scheme = urlsplit(value).scheme.lower()
        if scheme in RESTREAM_SCHEMES:
            return "direct"
        if not is_url(value):
            if value.startswith(("/", "file:")):
                raise AppError(
                    400, "Local file not found or MEDIA_ROOT not set", "unsupported_source", reason="local_unavailable"
                )
            raise AppError(400, f"Unsupported input: {value[:80]}", "unsupported_source", reason="unsupported_input")
        ext = sniff.url_ext(value)
        if ext == ".m3u8":
            # IPTV providers often name channel lists "list.m3u8": look at the body
            pr = await self.probe_reachable(value, headers)  # unreachable host → 502 here
            return "m3u" if pr is not None and pr.is_m3u and m3u.looks_like_m3u_list(pr.text) else "direct"
        if ext == ".m3u":
            return "m3u"
        if ytdlp.host_matches(value):
            return "ytdlp"
        if ext in sniff.MEDIA_EXT or ext in localres.MEDIA_EXTS:
            return "direct"
        try:
            pr = await self.probe(value, headers)
        except CONNECT_ERRORS as exc:
            # nothing (webpage, yt-dlp) can work on a host we can't reach: say so plainly
            raise _connect_failed(value, exc) from exc
        except httpx.HTTPError:
            return "ytdlp" if ytdlp.extractor_matches(value) else "webpage"
        if pr.is_m3u:
            return "m3u" if m3u.looks_like_m3u_list(pr.text) else "direct"
        if sniff.classify(pr.url, pr.content_type) or pr.sniffed_mime:
            return "direct"
        if ytdlp.extractor_matches(value):
            return "ytdlp"
        return "webpage"

    # ------------------------------------------------------------ public API
    async def resolve(self, value: str, kind: SourceKind | None = None) -> MediaResult | PlaylistResult:
        value = value.strip()
        url, headers = split_input(value)  # Kodi-style "url|Referer=...&User-Agent=..."
        validate_url(url)
        kind = kind or await self.detect_kind(value)
        if kind == "m3u":
            name, channels, is_hls = await self.load_m3u(url=url, headers=headers)
            if not is_hls:
                return PlaylistResult(name=name, channels=channels)
            kind = "direct"
        cand = await self._candidate(url, kind)
        if headers:
            cand.original_input = value  # keep the headers for history/queue replays
            cand.headers = {**headers, **cand.headers}
            cand.pinned_user_agent = any(k.lower() == "user-agent" for k in headers)
        return MediaResult(media=await self.finalize(cand))

    async def resolve_media(
        self, value: str, kind: SourceKind | None = None, title: str | None = None
    ) -> ResolvedMedia:
        res = await self.resolve(value, kind)
        if isinstance(res, PlaylistResult):
            raise AppError(
                400,
                "This is an M3U playlist: import it and pick a channel",
                "unsupported_source",
                reason="is_playlist",
            )
        if title:
            res.media.title = title
        return res.media

    async def load_m3u(
        self, url: str | None = None, content: str | None = None, headers: dict[str, str] | None = None
    ) -> tuple[str, list[Channel], bool]:
        """Returns (name, channels, is_actually_hls)."""
        name = None
        if content is None:
            if not url:
                raise AppError(400, "Either url or content is required", "validation_error")
            url, extra = split_input(url)
            content, _ = await self.fetch_text(url, {**extra, **(headers or {})})
            name = title_from_url(url)
        if hls.is_hls_playlist(content):
            return name or "HLS", [], True
        has_header = content.lstrip("\ufeff \r\n\t").startswith("#EXTM3U") or "#EXTINF" in content
        if not has_header and not any(is_url(line.strip()) for line in content.splitlines()):
            raise AppError(400, "Not an M3U playlist", "resolve_failed", reason="not_m3u")
        parsed = m3u.parse_m3u(content)
        name = parsed.attrs.get("x-tvg-name") or parsed.attrs.get("name") or name or "Playlist"
        return name, m3u.to_channels(parsed), False

    async def _candidate(self, value: str, kind: SourceKind) -> Candidate:
        if kind == "local":
            return self._local(value)
        if kind == "ytdlp":
            return await self._ytdlp(value)
        if kind == "webpage":
            return await self._webpage(value)
        if kind == "direct":
            return Candidate(url=value, source_kind="direct", original_input=value, title=title_from_url(value))
        raise AppError(400, f"Unsupported kind {kind}", "unsupported_source")

    def _local(self, value: str) -> Candidate:
        p = self._local_candidate(value)
        if p is None:
            localres.require_root(self.media_root)
            raise AppError(404, "Local file not found", "resolve_failed", reason="local_file_not_found")
        return Candidate(
            url=p.as_uri(),
            source_kind="local",
            original_input=value,
            title=p.stem,
            mime_type=localres.guess_mime(p.name) or "video/mp4",
            stream_type="BUFFERED",
            local_path=p,
        )

    async def _ytdlp(self, value: str) -> Candidate:
        try:
            r = await ytdlp.resolve_ytdlp(value, self.ytdlp_extractor)
        except Exception as exc:
            raise AppError(
                422, f"yt-dlp could not extract a stream: {exc}", "resolve_failed", reason="extract_failed"
            ) from exc
        mime = None
        if "m3u8" in r.protocol:
            mime = HLS_MIME
        elif r.ext:
            mime = sniff.MIME_BY_EXT.get("." + r.ext)
        return Candidate(
            url=r.url,
            source_kind="ytdlp",
            original_input=value,
            title=r.title,
            thumbnail=r.thumbnail,
            mime_type=mime,
            stream_type="LIVE" if r.is_live else "BUFFERED",
            headers=r.headers,
            subtitles=r.subtitles,
        )

    async def _webpage(self, value: str) -> Candidate:
        """Real Chromium only (JS-built players, nested iframes): never regex the static HTML."""
        if self.enable_playwright and self.browser is not None:
            try:
                found = await webpage.browser_extract(
                    self.browser,
                    value,
                    self.webpage_timeout,
                    filters=self.filters if self.adblock_enabled(value) else None,
                )
            except Exception as exc:
                log.info("browser extraction failed: %s", exc)
                found = None
            if found:
                live = found.is_live
                return Candidate(
                    url=found.url,
                    source_kind="webpage",
                    original_input=value,
                    title=found.title,
                    thumbnail=found.thumbnail,
                    mime_type=found.mime_type,
                    headers=found.headers,
                    stream_type=None if live is None else ("LIVE" if live else "BUFFERED"),
                )
        # last resort: yt-dlp's generic extractor
        try:
            cand = await self._ytdlp(value)
            cand.source_kind = "webpage"
            return cand
        except AppError:
            pass
        raise AppError(422, webpage.NO_STREAM_HINT, "resolve_failed", reason="no_stream_on_page")

    # ------------------------------------------------------------ finalize
    async def finalize(self, cand: Candidate) -> ResolvedMedia:
        """Pick mime/stream type and decide proxy/restream; build cast & preview URLs."""
        base = self.base_url().rstrip("/")
        headers = clean_headers(cand.headers)
        if cand.local_path is not None:
            rel = localres.relative(self.media_root.resolve(), cand.local_path)  # type: ignore[union-attr]
            local_url = f"/local/{quote(rel)}"
            cand.subtitles = self._local_subtitles(cand.local_path, base)
            if cand.local_path.suffix.lower() in localres.NEEDS_RESTREAM:
                job = self.restream.register(str(cand.local_path), live=False)
                path = f"/restream/{job.token}/index.m3u8"
                return self._media(cand, base + path, path, HLS_MIME, "BUFFERED", proxied=True)
            return self._media(cand, base + local_url, local_url, cand.mime_type or "video/mp4", "BUFFERED", False)

        url = cand.url
        scheme = urlsplit(url).scheme.lower()
        mime = cand.mime_type
        kind = sniff.classify(url, mime) if mime else sniff.classify(url)
        if scheme in RESTREAM_SCHEMES:
            stream_type = cand.stream_type or "LIVE"
            job = self.restream.register(url, headers, live=stream_type == "LIVE")
            path = f"/restream/{job.token}/index.m3u8"
            return self._media(cand, base + path, path, HLS_MIME, stream_type, True)

        pr: Probe | None = None
        direct_http = cand.source_kind == "direct" and is_url(url)
        if not mime and direct_http and kind is None:
            # Unknown extension: look at the content type, then at the body bytes
            pr = await self.probe_reachable(url, headers)
            if pr is not None:
                if pr.is_m3u:
                    kind, mime = "hls", HLS_MIME
                elif pr.sniffed_mime:
                    mime = pr.sniffed_mime
                    kind = sniff.classify(pr.url, mime)
                else:
                    kind = sniff.classify(pr.url, pr.content_type)
                    mime = sniff.mime_for(pr.url, kind, pr.content_type) if kind else None
        mime = mime or sniff.mime_for(url, kind)
        if mime.lower() in ("application/x-mpegurl", "application/vnd.apple.mpegurl", "audio/mpegurl"):
            mime, kind = HLS_MIME, "hls"
        stream_type = cand.stream_type
        no_cors = False
        mixed_variants = False
        segment_format: str | None = None
        video_segment_format: str | None = None
        if kind == "hls":
            info = await self.hls_info(url, headers)
            no_cors = info.cors is not True  # the Cast receiver needs CORS for HLS: proxy unless verified
            segment_format = info.segment_format
            video_segment_format = info.video_segment_format
            mixed_variants = info.mixed_variants
            if stream_type is None:
                stream_type = "BUFFERED" if info.is_live is False else "LIVE"
        elif kind == "dash":
            dinfo = await self.dash_info(url, headers)
            no_cors = dinfo.cors is not True  # MSE on the receiver needs CORS too
            if stream_type is None and dinfo.is_live is not None:
                stream_type = "LIVE" if dinfo.is_live else "BUFFERED"
        elif direct_http and pr is None:
            # progressive/raw URL typed or picked by the user: fail now on a dead host
            # instead of "casting" something the TV can only fail to load
            pr = await self.probe_reachable(url, headers)
        if stream_type is None and mime in RESTREAM_MIMES:
            # raw TS/FLV over HTTP: a file has a length, a live feed doesn't
            if pr is None:
                with contextlib.suppress(Exception):
                    pr = await self.probe(url, headers)
            stream_type = "BUFFERED" if pr is not None and pr.content_length else "LIVE"
        if stream_type is None:
            stream_type = "BUFFERED"

        # Raw MPEG-TS / FLV / AVI over HTTP: Chromecast can't play it → ffmpeg to HLS
        if mime in RESTREAM_MIMES:
            job = self.restream.register(url, headers, live=stream_type == "LIVE")
            path = f"/restream/{job.token}/index.m3u8"
            return self._media(cand, base + path, path, HLS_MIME, stream_type, True)

        cand.subtitles = [self._proxied_subtitle(sub, headers, base) for sub in cand.subtitles]
        pinned_ua = cand.pinned_user_agent and any(k.lower() == "user-agent" for k in headers)
        must_proxy = self.force_proxy() or needs_header_proxy(headers) or pinned_ua or no_cors or mixed_variants
        if must_proxy or kind in ("hls", "dash"):
            # Always register: the browser preview needs a same-origin (CORS-free) path.
            target = self.tokens.register(url, headers)
            path = f"/proxy/{target.token}/{target.filename}"
            cast_url = base + path if must_proxy else url
            media = self._media(cand, cast_url, path, mime, stream_type, must_proxy)
            media.hls_segment_format = segment_format  # type: ignore[assignment]
            media.hls_video_segment_format = video_segment_format  # type: ignore[assignment]
            return media
        return self._media(cand, url, url, mime, stream_type, False)

    def _local_subtitles(self, video: Path, base: str) -> list[Subtitle]:
        """Sidecar ``.vtt``/``.srt`` files next to a local video (SRT is converted by ``/local``)."""
        root = self.media_root.resolve()  # type: ignore[union-attr]
        subs: list[Subtitle] = []
        for p, lang in localres.sidecar_subtitles(video):
            url = f"{base}/local/{quote(localres.relative(root, p))}"
            if p.suffix.lower() == ".srt":
                url += "?as=vtt"
            subs.append(Subtitle(url=url, lang=lang, label=lang or p.name))
        return subs

    def _proxied_subtitle(self, sub: Subtitle, headers: dict[str, str], base: str) -> Subtitle:
        """Cast receivers require CORS on text tracks: always serve them via the proxy."""
        if not is_url(sub.url):
            return sub
        target = self.tokens.register(sub.url, headers)
        return sub.model_copy(update={"url": f"{base}/proxy/{target.token}/{target.filename}"})

    @staticmethod
    def _media(
        cand: Candidate,
        cast_url: str,
        preview_url: str,
        mime: str,
        stream_type: StreamType,
        proxied: bool,
    ) -> ResolvedMedia:
        return ResolvedMedia(
            url=cand.url,
            cast_url=cast_url,
            preview_url=preview_url,
            title=cand.title or title_from_url(cand.url),
            mime_type=CAST_MIME_ALIASES.get(mime.lower(), mime),
            stream_type=stream_type,
            thumbnail=cand.thumbnail,
            source_kind=cand.source_kind,
            original_input=cand.original_input,
            proxied=proxied,
            subtitles=cand.subtitles,
        )
