"""DASH (MPD) rewriting so every segment request goes back through ``/proxy/{token}/...``.

HLS URIs are rewritten one by one (``u/<b64>``), but DASH segment URLs are built by
the player from templates (``media="seg_$Number%05d$.m4s"``) and BaseURL chains, so
they can't be base64-encoded. Instead upstream URLs are mapped to a *clear* proxy
path, ``/proxy/{token}/a/{scheme}/{host}{path}``, which keeps templates intact and
keeps relative resolution (``../x``, ``video/``) inside the token:

- every MPD-level ``<BaseURL>`` is made absolute against the manifest URL and mapped;
  when there is none, one pointing at the manifest is inserted, so relative URLs never
  resolve against the bare proxy path (where ``../`` would escape the token);
- deeper ``<BaseURL>`` and URL attributes (``media``, ``initialization``, ``index``,
  ``sourceURL``) are only touched when absolute or host-relative; relative ones keep
  resolving against their (now proxied) parent base on the receiver;
- ``<Location>`` (manifest refresh URL) is mapped too.

The document is edited textually (no XML round-trip), so namespace prefixes,
comments and formatting are preserved exactly.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

TAG_RE = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!.*?>|<(/?)([A-Za-z_][\w.:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>",
    re.S,
)
ATTR_RE = re.compile(r"""(\s)([\w.:-]+)(\s*=\s*)(["'])(.*?)\4""", re.S)
URL_ATTRS = ("media", "initialization", "index", "sourceURL")
TEXT_URL_ELEMENTS = ("BaseURL", "Location")


def _local(name: str) -> str:
    return name.rsplit(":", 1)[-1]


def is_mpd(text: str) -> bool:
    return mpd_attrs(text) is not None


def mpd_attrs(text: str) -> dict[str, str] | None:
    """Attributes of the root ``<MPD>`` element, or None when ``text`` isn't an MPD."""
    for mt in TAG_RE.finditer(text[:65536]):
        if mt.group(2) is None:
            continue
        if mt.group(1) or _local(mt.group(2)) != "MPD":
            return None
        return {_local(a.group(2)): html.unescape(a.group(5)) for a in ATTR_RE.finditer(mt.group(3))}
    return None


def clear_path(token: str, absolute_url: str, prefix: str = "/proxy") -> str:
    """Root-relative proxy path that keeps the upstream URL readable (templates survive)."""
    parts = urlsplit(absolute_url)
    path = parts.path or "/"
    out = f"{prefix}/{token}/a/{parts.scheme.lower()}/{parts.netloc}{path}"
    return f"{out}?{parts.query}" if parts.query else out


def _needs_mapping(uri: str) -> bool:
    """Absolute (``http://``), protocol-relative (``//``) or host-relative (``/x``) URIs."""
    return uri.startswith("/") or urlsplit(uri).scheme.lower() in ("http", "https")


def _map(uri: str, base: str, token: str, prefix: str) -> str:
    return clear_path(token, urljoin(base, uri), prefix)


def rewrite_mpd(text: str, manifest_url: str, token: str, prefix: str = "/proxy") -> str:
    out: list[str] = []
    pos = 0
    # (local element name, absolute base for its children)
    stack: list[tuple[str, str]] = []
    pending_text: str | None = None  # element whose text content is a URL (BaseURL/Location)
    first_base: dict[int, bool] = {}  # depth -> a BaseURL already set the base at this level

    def base() -> str:
        return stack[-1][1] if stack else manifest_url

    for mt in TAG_RE.finditer(text):
        start, end = mt.span()
        chunk = text[pos:start]
        if pending_text is not None and chunk.strip():
            uri = html.unescape(chunk.strip())
            # the BaseURL's parent is stack[-2] (stack[-1] is the BaseURL element itself)
            parent_base = stack[-2][1] if len(stack) >= 2 else manifest_url
            depth = len(stack) - 1
            mpd_level = depth == 1
            absolute = urljoin(parent_base, uri)
            if pending_text == "BaseURL":
                if mpd_level or _needs_mapping(uri):
                    lead = chunk[: len(chunk) - len(chunk.lstrip())]
                    trail = chunk[len(chunk.rstrip()) :]
                    chunk = lead + html.escape(clear_path(token, absolute, prefix), quote=False) + trail
                if not first_base.get(depth):
                    first_base[depth] = True
                    name, _ = stack[-2]
                    stack[-2] = (name, absolute)
            else:  # Location: always absolute against the manifest
                chunk = html.escape(_map(uri, manifest_url, token, prefix), quote=False)
        out.append(chunk)
        pos = end
        tag = mt.group(0)
        name = mt.group(2)
        if name is None:  # comment / PI / CDATA / doctype
            out.append(tag)
            continue
        local = _local(name)
        closing, selfclosing = bool(mt.group(1)), bool(mt.group(4))
        if closing:
            if local in TEXT_URL_ELEMENTS:
                pending_text = None
            while stack:
                popped, _ = stack.pop()
                first_base.pop(len(stack) + 1, None)
                if popped == local:
                    break
            out.append(tag)
            continue
        attrs = mt.group(3)
        if any(a in attrs for a in URL_ATTRS):
            cur = base()

            def _attr(am: re.Match[str], cur: str = cur) -> str:
                key = _local(am.group(2))
                value = html.unescape(am.group(5))
                if key not in URL_ATTRS or not _needs_mapping(value):
                    return am.group(0)
                new = html.escape(_map(value, cur, token, prefix), quote=True)
                return f"{am.group(1)}{am.group(2)}{am.group(3)}{am.group(4)}{new}{am.group(4)}"

            tag = tag[: mt.start(3) - start] + ATTR_RE.sub(_attr, attrs) + tag[mt.end(3) - start :]
        out.append(tag)
        if selfclosing:
            continue
        stack.append((local, base()))
        if local in TEXT_URL_ELEMENTS:
            pending_text = local
        if local == "MPD" and len(stack) == 1 and not _has_mpd_base_url(text, end):
            # no MPD-level BaseURL: pin relative resolution to the manifest's own URL
            out.append(f"<BaseURL>{html.escape(clear_path(token, manifest_url, prefix), quote=False)}</BaseURL>")
    out.append(text[pos:])
    return "".join(out)


def _has_mpd_base_url(text: str, after: int) -> bool:
    """True when the MPD element (whose start tag ends at ``after``) has a direct BaseURL child."""
    depth = 0
    for mt in TAG_RE.finditer(text, after):
        name = mt.group(2)
        if name is None:
            continue
        local = _local(name)
        if mt.group(1):
            if depth == 0:
                return False  # </MPD>
            depth -= 1
        elif mt.group(4):
            continue
        else:
            if depth == 0 and local == "BaseURL":
                return True
            depth += 1
    return False
