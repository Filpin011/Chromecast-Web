"""Upstream fetching for ``/proxy/{token}/{path}``: HLS rewrite or streaming passthrough."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from urllib.parse import urljoin

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from app.errors import AppError
from app.services.net import DESKTOP_UA
from app.services.proxy import dash
from app.services.proxy.hls import (
    DISGUISE_EXTS,
    decode_url,
    filter_variants,
    harmonize_audio_defaults,
    is_master_playlist,
    media_filename,
    rewrite_playlist,
    url_filename,
)
from app.services.proxy.tokens import ProxyTarget, TokenRegistry

log = logging.getLogger(__name__)

PLAYLIST_MAX_BYTES = 8 * 1024 * 1024
SNIFF_BYTES = 512
PASS_HEADERS = ("content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag")
HLS_CT = ("mpegurl",)
DASH_CT = ("dash+xml",)
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "Content-Length, Content-Range"}


def upstream_url(target: ProxyTarget, path: str, query: str = "") -> str:
    """Map a proxy sub-path (+ the request's query string) to the upstream URL.

    - ``u/<b64>/<name>`` is what rewritten HLS playlists contain. If a player resolved a
      relative URI against such a path (``u/<b64>/seg.ts``), ``seg.ts`` is resolved
      against the encoded URL instead of refetching the encoded resource.
    - ``a/<scheme>/<host>/<path>`` is what rewritten DASH manifests contain (clear, so
      segment templates and relative paths work); the query string is the upstream's.
    - anything else is relative to the token's URL.

    Raises AppError(404, token_not_found) for a path that can't be decoded.
    """
    path = path.lstrip("/")
    if path.startswith("u/"):
        encoded, _, rest = path[2:].partition("/")
        try:
            base = decode_url(encoded)
        except (ValueError, UnicodeDecodeError) as exc:  # binascii.Error is a ValueError
            raise AppError(404, "Malformed proxy path", "token_not_found") from exc
        if not base.startswith(("http://", "https://")):
            raise AppError(404, "Malformed proxy path", "token_not_found")
        if not rest or rest == url_filename(base) or rest in {media_filename(base, e) for e in DISGUISE_EXTS}:
            return base
        return urljoin(base, rest)
    if path.startswith("a/"):
        scheme, _, rest = path[2:].partition("/")
        if scheme not in ("http", "https") or not rest or rest.startswith("/"):
            raise AppError(404, "Malformed proxy path", "token_not_found")
        url = f"{scheme}://{rest}"
        return f"{url}?{query}" if query else url
    if not path or path == target.filename:
        return target.url
    url = urljoin(target.url, path)
    return f"{url.split('?', 1)[0]}?{query}" if query else url


def _looks_like_playlist(url: str, content_type: str) -> bool:
    ct = content_type.lower()
    if any(h in ct for h in HLS_CT):
        return True
    path = url.split("?", 1)[0].lower()
    return path.endswith((".m3u8", ".m3u"))


def _looks_like_mpd(url: str, content_type: str) -> bool:
    if any(h in content_type.lower() for h in DASH_CT):
        return True
    return url.split("?", 1)[0].lower().endswith(".mpd")


def _may_be_playlist(content_type: str) -> bool:
    """Bodies worth sniffing for ``#EXTM3U``: CDNs disguise playlists as text/plain,
    application/octet-stream, ``stream.php?id=``, ``index.txt``... Media types are not."""
    ct = content_type.lower()
    return not ct.startswith(("video/", "audio/", "image/"))


def _is_playlist_body(head: bytes) -> bool:
    return head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"#EXTM3U")


# --- disguised media segments -------------------------------------------------------
# Some CDNs serve HLS segments as text/html or image/* (sometimes with a fake PNG/JPEG
# header in front of the MPEG-TS data). hls.js copes; the Cast receiver does not.
MEDIA_SNIFF_BYTES = 64 * 1024
IMAGE_SIGNATURES = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM")
EXT_TYPES = {
    ".ts": "video/mp2t", ".m4s": "video/mp4", ".mp4": "video/mp4", ".aac": "audio/aac",
    ".vtt": "text/vtt",
}


def _is_media_type(content_type: str) -> bool:
    ct = content_type.lower()
    return ct.startswith(("video/", "audio/")) or "mpegurl" in ct or "dash+xml" in ct or ct.startswith("text/vtt")


def _ts_sync_offset(data: bytes, limit: int = MEDIA_SNIFF_BYTES) -> int | None:
    """First offset with three MPEG-TS sync bytes 188 bytes apart."""
    end = min(len(data) - 376, limit)
    i = data.find(b"\x47", 0, max(end, 0))
    while 0 <= i < end:
        if data[i + 188] == 0x47 and data[i + 376] == 0x47:
            return i
        i = data.find(b"\x47", i + 1, end)
    return None


def sniff_media(head: bytes) -> tuple[str | None, int]:
    """(content type, bytes of junk to strip) for the start of a media segment."""
    if head.startswith(b"WEBVTT") or head.startswith(b"\xef\xbb\xbfWEBVTT"):
        return "text/vtt", 0
    if len(head) > 376 and head[0] == 0x47 and head[188] == 0x47:
        return "video/mp2t", 0
    if head[4:8] in (b"ftyp", b"styp", b"moof", b"moov", b"sidx"):
        return "video/mp4", 0
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0):
        return "audio/aac", 0
    if head.startswith(b"\x0b\x77"):
        return "audio/ac3", 0
    if head.startswith(IMAGE_SIGNATURES):
        off = _ts_sync_offset(head)
        if off is not None:
            return "video/mp2t", off
        for box in (b"ftyp", b"styp", b"moof"):
            pos = head.find(box, 8)
            if pos >= 4:
                return "video/mp4", pos - 4
    return None, 0


class ProxyService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: TokenRegistry,
        prefix: str = "/proxy",
        *,
        audio_language: str | None = None,
    ) -> None:
        self.audio_language = audio_language or None
        self.client = client
        self.tokens = tokens
        self.prefix = prefix

    async def handle(self, target: ProxyTarget, path: str, request: Request) -> Response:
        url = upstream_url(target, path, request.url.query)
        headers = dict(target.headers)
        if not any(k.lower() == "user-agent" for k in headers):
            # same UA the resolver probed with; never python-httpx (403 on many panels/CDNs)
            headers["User-Agent"] = DESKTOP_UA
        for h in ("range", "if-range"):
            if h in request.headers:
                headers[h.title()] = request.headers[h]
        method = "HEAD" if request.method == "HEAD" else "GET"
        try:
            upstream = await self.client.send(
                self.client.build_request(method, url, headers=headers), stream=True
            )
        except httpx.HTTPError as exc:
            log.info("proxy upstream error %s: %s", url, exc)
            return Response(f"Upstream error: {exc}", status_code=502, headers=CORS)

        ct = upstream.headers.get("content-type", "")
        if upstream.status_code < 400 and method == "GET" and _looks_like_playlist(url, ct):
            try:
                body = await self._read_limited(upstream.aiter_bytes())
            finally:
                await upstream.aclose()
            if _is_playlist_body(body):
                return self._playlist_response(body, str(upstream.url), target)
            return Response(body, status_code=upstream.status_code, media_type=ct or None, headers=CORS)
        if upstream.status_code < 400 and method == "GET" and _looks_like_mpd(url, ct):
            try:
                body = await self._read_limited(upstream.aiter_bytes())
            finally:
                await upstream.aclose()
            mpd = self._mpd_response(body, str(upstream.url), target)
            if mpd is not None:
                return mpd
            return Response(body, status_code=upstream.status_code, media_type=ct or None, headers=CORS)

        out_headers = dict(CORS)
        encoded = "content-encoding" in upstream.headers
        for h in PASS_HEADERS:
            if h in upstream.headers and not (encoded and h == "content-length"):
                out_headers[h] = upstream.headers[h]
        # media type implied by the (possibly rewritten) file name, e.g. ``0001.ts``
        dot = path.rfind(".")
        path_type = EXT_TYPES.get(path[dot:].lower()) if dot > path.rfind("/") else None
        disguised = upstream.status_code < 400 and not _is_media_type(ct)
        if method == "HEAD":
            await upstream.aclose()
            if disguised and path_type:
                out_headers["content-type"] = path_type
            return Response(status_code=upstream.status_code, headers=out_headers)

        chunks = upstream.aiter_bytes(64 * 1024)
        head = b""
        if upstream.status_code in (200, 206) and (_may_be_playlist(ct) or disguised):
            # Peek: a playlist served with a non-HLS type/URL must still be rewritten,
            # otherwise the receiver fetches segments directly (no Referer/Cookie → 403);
            # a media segment served as text/html or image/* gets its real type.
            want = MEDIA_SNIFF_BYTES if disguised else SNIFF_BYTES
            try:
                async for chunk in chunks:
                    head += chunk
                    if len(head) >= want:
                        break
            except httpx.HTTPError as exc:
                await upstream.aclose()
                return Response(f"Upstream error: {exc}", status_code=502, headers=CORS)
            if upstream.status_code == 200 and _is_playlist_body(head):
                try:
                    body = await self._read_limited(chunks, head)
                finally:
                    await upstream.aclose()
                return self._playlist_response(body, str(upstream.url), target)
            if upstream.status_code == 200 and b"<MPD" in head:  # DASH served as text/xml, octet-stream, ...
                try:
                    body = await self._read_limited(chunks, head)
                finally:
                    await upstream.aclose()
                mpd = self._mpd_response(body, str(upstream.url), target)
                return mpd or Response(body, status_code=upstream.status_code, media_type=ct or None, headers=CORS)
            if disguised:
                real_type, junk = sniff_media(head) if upstream.status_code == 200 else (None, 0)
                real_type = real_type or path_type
                if real_type:
                    out_headers["content-type"] = real_type
                if junk:
                    log.info("proxy: stripped %d-byte fake header from %s segment", junk, real_type)
                    head = head[junk:]
                    out_headers.pop("content-length", None)
                    out_headers.pop("content-range", None)

        async def body_iter() -> AsyncIterator[bytes]:
            try:
                if head:
                    yield head
                async for chunk in chunks:
                    yield chunk
            except httpx.HTTPError as exc:  # pragma: no cover - mid-stream failure
                log.info("proxy stream aborted %s: %s", url, exc)
            finally:
                await upstream.aclose()

        return StreamingResponse(body_iter(), status_code=upstream.status_code, headers=out_headers)

    def _playlist_response(self, body: bytes, final_url: str, target: ProxyTarget) -> Response:
        text = body.decode("utf-8", errors="replace")
        if is_master_playlist(text):
            text = filter_variants(text)  # one container for the whole LOAD (see filter_variants)
            # one audio language across groups, so variant switches don't change it
            text = harmonize_audio_defaults(text, self.audio_language)
        rewritten = rewrite_playlist(text, final_url, target.token, self.prefix)
        return Response(
            rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={**CORS, "Cache-Control": "no-cache"},
        )

    def _mpd_response(self, body: bytes, final_url: str, target: ProxyTarget) -> Response | None:
        text = body.decode("utf-8", errors="replace")
        if not dash.is_mpd(text):
            return None
        rewritten = dash.rewrite_mpd(text, final_url, target.token, self.prefix)
        return Response(rewritten, media_type="application/dash+xml", headers={**CORS, "Cache-Control": "no-cache"})

    @staticmethod
    async def _read_limited(chunks: AsyncIterator[bytes], head: bytes = b"") -> bytes:
        buf = bytearray(head)
        async for chunk in chunks:
            buf.extend(chunk)
            if len(buf) > PLAYLIST_MAX_BYTES:
                break
        return bytes(buf)
