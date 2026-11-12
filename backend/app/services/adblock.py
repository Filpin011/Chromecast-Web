"""uBlock-Origin-style ad blocking for the Playwright browser contexts.

Network filtering uses Brave's ``adblock`` engine (Rust, uBO/ABP syntax) fed with the default
lists uBO ships (downloaded to ``DATA_DIR/filters``, refreshed every 24h) plus a small bundled
fallback list (``app/static/filters/fallback.txt``) that is always loaded, so it works offline
and in tests.

``FilterManager`` owns the engines; :func:`install` hooks one browser context:
every request goes through ``context.route("**/*")`` → stream sniffer first (the real stream
is never blocked) → engine check with request type + source frame URL → abort / redirect
resource / continue. Cosmetic filters are injected in every frame through an init script that
asks the engine (via ``context.expose_binding``) for the hide selectors of the frame URL and the
generic selectors matching the frame's classes/ids.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models import FilterListInfo

log = logging.getLogger(__name__)

REFRESH_SECONDS = 24 * 3600

# Same defaults as uBlock Origin (assets.json).
DEFAULT_LISTS: list[tuple[str, str, str, str]] = [
    # (id, display name, url, format)
    ("ublock-filters", "uBlock filters", "https://ublockorigin.github.io/uAssets/filters/filters.min.txt", "standard"),
    ("ublock-badware", "uBlock filters - Badware risks",
     "https://ublockorigin.github.io/uAssets/filters/badware.min.txt", "standard"),
    ("ublock-privacy", "uBlock filters - Privacy",
     "https://ublockorigin.github.io/uAssets/filters/privacy.min.txt", "standard"),
    ("ublock-unbreak", "uBlock filters - Unbreak",
     "https://ublockorigin.github.io/uAssets/filters/unbreak.min.txt", "standard"),
    ("ublock-quick-fixes", "uBlock filters - Quick fixes",
     "https://ublockorigin.github.io/uAssets/filters/quick-fixes.min.txt", "standard"),
    ("easylist", "EasyList", "https://ublockorigin.github.io/uAssets/thirdparties/easylist.txt", "standard"),
    ("easyprivacy", "EasyPrivacy", "https://ublockorigin.github.io/uAssets/thirdparties/easyprivacy.txt", "standard"),
    ("plowe", "Peter Lowe's Ad and tracking server list",
     "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=1&mimetype=plaintext", "hosts"),
    ("easylist-italy", "EasyList Italy", "https://easylist-downloads.adblockplus.org/easylistitaly.txt", "standard"),
]
FALLBACK_NAME = "Bundled fallback"

# Minimal uBO redirect resources (name, aliases, mime, body).
REDIRECT_RESOURCES: list[tuple[str, list[str], str, bytes]] = [
    ("noop.js", ["noopjs"], "application/javascript", b"(function(){})();"),
    ("noop.txt", ["nooptext"], "text/plain", b""),
    ("noop.html", ["noopframe"], "text/html", b"<!DOCTYPE html><html><head></head><body></body></html>"),
    ("noop.css", ["noopcss"], "text/css", b""),
    ("noop.json", ["noopjson"], "application/json", b"{}"),
    ("1x1.gif", ["1x1-transparent.gif"], "image/gif",
     base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")),
    ("2x2.png", ["2x2-transparent.png"], "image/png",
     base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAC0lEQVQI12NgQAcAABIAAe+JVKQAAAAASUVORK5CYII=")),
    ("google-ima.js", ["google-ima3"], "application/javascript", b"(function(){})();"),
]

# Playwright resource_type → adblock-rust request type.
REQUEST_TYPES = {
    "document": "document",
    "stylesheet": "stylesheet",
    "image": "image",
    "media": "media",
    "font": "font",
    "script": "script",
    "texttrack": "other",
    "xhr": "xmlhttprequest",
    "fetch": "xmlhttprequest",
    "eventsource": "other",
    "websocket": "websocket",
    "manifest": "other",
    "ping": "ping",
    "beacon": "ping",
    "other": "other",
}

_POPUP_OPT = re.compile(r"(?:^|,)(?:popup|popunder)(?:,|$)")


def hostname(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def site(url_or_host: str) -> str:
    """Rough registrable domain (last two labels; good enough for same-site checks)."""
    host = hostname(url_or_host) if "/" in url_or_host else url_or_host.lower()
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "net", "org", "gov", "ac"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def host_in(host: str, hosts: list[str] | set[str]) -> bool:
    """``host`` or one of its parent domains is listed."""
    host = host.lower()
    hs = {h.lower().removeprefix("www.") for h in hosts}
    parts = host.split(".")
    return any(".".join(parts[i:]) in hs for i in range(len(parts)))


def popup_rules(text: str) -> list[str]:
    """Extract ``$popup`` network filters, rewritten without the option (uBO popup semantics)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("!", "[")) or "##" in line or "#@#" in line or "$" not in line:
            continue
        pattern, _, opts = line.rpartition("$")
        if not pattern or not _POPUP_OPT.search(opts):
            continue
        rest = [o for o in opts.split(",") if o not in ("popup", "popunder")]
        # options irrelevant for a top-level popup document
        rest = [o for o in rest if not o.startswith(("domain=", "~"))] if rest else rest
        out.append(pattern + ("$" + ",".join(rest) if rest else ""))
    return out


def count_rules(text: str, fmt: str = "standard") -> int:
    n = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or (line.startswith(("!", "[", "#")) and not line.startswith("##")):
            continue
        n += 1
    return n


@dataclass
class Decision:
    blocked: bool
    redirect: str | None = None  # data: URL of a redirect resource
    filter: str | None = None


@dataclass
class _List:
    id: str
    name: str
    text: str
    fmt: str
    updated_at: datetime | None


class FilterManager:
    def __init__(
        self,
        data_dir: Path | None,
        http: httpx.AsyncClient | None = None,
        *,
        auto_update: bool = True,
        lists: list[tuple[str, str, str, str]] | None = None,
    ) -> None:
        self.dir = data_dir / "filters" if data_dir else None
        self.http = http
        self.auto_update = auto_update
        self.sources = DEFAULT_LISTS if lists is None else lists
        self._lists: list[_List] = []
        self._engine: Any = None
        self._popup_engine: Any = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.load()

    # ------------------------------------------------------------ loading
    @staticmethod
    def fallback_text() -> str:
        return resources.files("app").joinpath("static/filters/fallback.txt").read_text(encoding="utf-8")

    def _meta_path(self) -> Path | None:
        return self.dir / "meta.json" if self.dir else None

    def _read_meta(self) -> dict[str, str]:
        p = self._meta_path()
        if p and p.is_file():
            with contextlib.suppress(Exception):
                return dict(json.loads(p.read_text()))
        return {}

    def load(self) -> None:
        """(Re)build the engines from the fallback list + whatever lists were downloaded."""
        lists = [_List("fallback", FALLBACK_NAME, self.fallback_text(), "standard", None)]
        meta = self._read_meta()
        if self.dir and self.dir.is_dir():
            for list_id, name, _url, fmt in self.sources:
                f = self.dir / f"{list_id}.txt"
                if f.is_file():
                    with contextlib.suppress(Exception):
                        updated = datetime.fromisoformat(meta[list_id]) if list_id in meta else None
                        text = f.read_text(encoding="utf-8", errors="replace")
                        lists.append(_List(list_id, name, text, fmt, updated))
        self._build(lists)

    def _build(self, lists: list[_List]) -> None:
        engine, popup_engine = self._compile(lists)
        self._lists, self._engine, self._popup_engine = lists, engine, popup_engine

    @staticmethod
    def _compile(lists: list[_List]) -> tuple[Any, Any]:
        import adblock

        fs = adblock.FilterSet(debug=False)
        popups: list[str] = []
        for lst in lists:
            try:
                fs.add_filter_list(lst.text, format=lst.fmt)
            except Exception:  # pragma: no cover - malformed list
                log.warning("filter list %s could not be parsed", lst.name)
            if lst.fmt == "standard":
                popups.extend(popup_rules(lst.text))
        engine = adblock.Engine(fs, optimize=True)
        for name, aliases, mime, body in REDIRECT_RESOURCES:
            encoded = base64.b64encode(body).decode()
            for n in (name, *aliases):
                with contextlib.suppress(Exception):
                    engine.add_resource(n, mime, encoded)
        pfs = adblock.FilterSet(debug=False)
        pfs.add_filter_list("\n".join(popups))
        return engine, adblock.Engine(pfs, optimize=True)

    # ------------------------------------------------------------ updating
    def info(self) -> list[FilterListInfo]:
        return [
            FilterListInfo(name=lst.name, rules=count_rules(lst.text, lst.fmt), updated_at=lst.updated_at)
            for lst in self._lists
        ]

    def needs_refresh(self) -> bool:
        meta = self._read_meta()
        now = datetime.now(UTC)
        for list_id, *_ in self.sources:
            ts = meta.get(list_id)
            if not ts:
                return True
            with contextlib.suppress(ValueError):
                if (now - datetime.fromisoformat(ts)).total_seconds() > REFRESH_SECONDS:
                    return True
        return False

    async def refresh(self) -> list[FilterListInfo]:
        """Download every default list (failures keep the previous copy), then rebuild."""
        if self.http is None or self.dir is None:
            return self.info()
        async with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            meta = self._read_meta()
            for list_id, name, url, _fmt in self.sources:
                try:
                    r = await self.http.get(url, timeout=30.0, follow_redirects=True)
                    r.raise_for_status()
                    text = r.text
                    if len(text) < 20:
                        raise ValueError("empty list")
                    (self.dir / f"{list_id}.txt").write_text(text, encoding="utf-8")
                    meta[list_id] = datetime.now(UTC).isoformat()
                except Exception as exc:
                    log.info("filter list %s not updated: %s", name, exc)
            p = self._meta_path()
            if p:
                p.write_text(json.dumps(meta))
            await asyncio.to_thread(self.load)
        log.info("ad-block engine rebuilt: %s", ", ".join(f"{i.name}={i.rules}" for i in self.info()))
        return self.info()

    def start(self) -> None:
        if self.auto_update and self._task is None and self.http is not None and self.dir is not None:
            self._task = asyncio.create_task(self._update_loop(), name="filters-update")

    async def _update_loop(self) -> None:
        while True:
            if self.needs_refresh():
                with contextlib.suppress(Exception):
                    await self.refresh()
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    # ------------------------------------------------------------ matching
    def check(self, url: str, source_url: str, request_type: str) -> Decision:
        if not url.startswith(("http://", "https://", "ws://", "wss://")):
            return Decision(False)
        try:
            r = self._engine.check_network_urls(url, source_url or url, request_type)
        except Exception:  # pragma: no cover
            return Decision(False)
        if r.matched and not r.exception:
            return Decision(True, r.redirect or None, r.filter)
        return Decision(False)

    def is_popup_ad(self, url: str, opener_url: str) -> bool:
        """uBO ``$popup`` semantics, plus ``$document``/badware hosts and known ad servers."""
        if not url.startswith(("http://", "https://")):
            return False
        src = opener_url or url
        with contextlib.suppress(Exception):
            r = self._popup_engine.check_network_urls(url, src, "document")
            if r.matched and not r.exception:
                return True
        with contextlib.suppress(Exception):
            r = self._engine.check_network_urls(url, src, "document")
            if r.matched and not r.exception:
                return True
        return False

    def cosmetic_css(self, url: str, classes: list[str], ids: list[str]) -> str:
        """Hide rules for one frame: host-specific selectors + generic ones matching its classes/ids."""
        selectors: set[str] = set()
        try:
            res = self._engine.url_cosmetic_resources(url)
            selectors |= set(res.hide_selectors)
            exceptions = set(res.exceptions)
            if not res.generichide and (classes or ids):
                selectors |= set(self._engine.hidden_class_id_selectors(classes[:4000], ids[:4000], exceptions))
            selectors -= exceptions
        except Exception:  # pragma: no cover
            return ""
        # one rule per selector: an invalid selector must not void the others
        return "\n".join(f"{s}{{display:none!important}}" for s in sorted(selectors) if "{" not in s)


# ---------------------------------------------------------------- browser hook

COSMETIC_JS = """
(() => {
  if (window.__cwCosmeticInstalled) return;
  window.__cwCosmeticInstalled = true;
  let style = null;
  const run = async () => {
    try {
      if (typeof window.__cwCosmetic !== 'function') return;
      const classes = new Set(), ids = new Set();
      for (const el of document.querySelectorAll('[class],[id]')) {
        if (el.id) ids.add(el.id);
        if (el.classList) for (const c of el.classList) classes.add(c);
        if (classes.size + ids.size > 6000) break;
      }
      const css = await window.__cwCosmetic(location.href, [...classes], [...ids]);
      if (!css) return;
      if (!style) { style = document.createElement('style'); style.setAttribute('data-cw', 'cosmetic'); }
      style.textContent = css;
      (document.head || document.documentElement).appendChild(style);
    } catch (e) {}
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, { once: true });
  else run();
  setTimeout(run, 2500);
  setTimeout(run, 8000);
})();
"""


# window.open / target=_blank are intercepted in every frame and reported to the backend instead of
# creating a real tab: the popup policy decides first (a real popup tab would also stall the opener's
# nested iframes while request interception is active). ``context.on("page")`` stays as a fallback.
POPUP_GUARD_JS = """
(() => {
  if (window.__cwPopupGuard) return;
  window.__cwPopupGuard = true;
  const report = (url) => {
    try {
      const href = new URL(url || 'about:blank', location.href).href;
      if (typeof window.__cwPopup === 'function') window.__cwPopup(href);
    } catch (e) {}
  };
  try {
    Object.defineProperty(window, 'open', {
      configurable: false, writable: false,
      value: function (url) { report(url); return null; },
    });
  } catch (e) { window.open = function (url) { report(url); return null; }; }
  document.addEventListener('click', (ev) => {
    const a = ev.target && ev.target.closest ? ev.target.closest('a[target]') : null;
    if (!a || !a.href) return;
    const t = (a.getAttribute('target') || '').toLowerCase();
    if (!t || t === '_self' || t === '_top' || t === '_parent') return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    report(a.href);
  }, true);
})();
"""


@dataclass
class Hooks:
    """Callbacks from the route handler to its owner (browser session or resolver)."""

    enabled: Callable[[], bool]
    # (request, url) -> True if the sniffer recognised it as a media stream (never blocked)
    on_stream: Callable[[Any, str], bool]
    on_blocked: Callable[[str], None]
    # (route, request) -> True if the navigation was handled (aborted/prompted) by the owner
    on_navigation: Callable[[Any, Any], Any] | None = None


async def install(context: Any, filters: FilterManager | None, hooks: Hooks) -> None:
    """Route every request of ``context`` through the engine and inject cosmetic filters.

    With ``filters=None`` only the stream sniffer and the navigation/popup policy hooks run.
    """

    async def handler(route: Any, request: Any) -> None:
        try:
            await _handle(route, request)
        except Exception as exc:  # never leave a request hanging
            log.debug("adblock route error: %s", exc)
            with contextlib.suppress(Exception):
                await route.continue_()

    async def _handle(route: Any, request: Any) -> None:
        url = request.url
        if not url.startswith(("http://", "https://")):
            await route.continue_()
            return
        # 1) stream detection runs before any abort decision: the real stream is never blocked
        if hooks.on_stream(request, url):
            await route.continue_()
            return
        rtype = getattr(request, "resource_type", "other") or "other"
        frame = None
        with contextlib.suppress(Exception):
            frame = request.frame
        is_main_doc = False
        with contextlib.suppress(Exception):
            is_main_doc = rtype == "document" and request.is_navigation_request() and frame.parent_frame is None
        # 2) top-level navigations: popup / redirect-ad policy lives in the owner
        if is_main_doc:
            if hooks.on_navigation is not None and await hooks.on_navigation(route, request):
                return
            await route.continue_()
            return
        if filters is None or not hooks.enabled():
            await route.continue_()
            return
        source = ""
        with contextlib.suppress(Exception):
            source = frame.url if frame is not None else ""
        if not source or not source.startswith("http"):
            with contextlib.suppress(Exception):
                source = frame.page.url
        req_type = "sub_frame" if rtype == "document" else REQUEST_TYPES.get(rtype, "other")
        d = filters.check(url, source, req_type)
        if not d.blocked:
            await route.continue_()
            return
        hooks.on_blocked(url)
        if d.redirect and d.redirect.startswith("data:"):
            head, _, data = d.redirect.partition(",")
            mime = head[5:].split(";")[0] or "text/plain"
            body = base64.b64decode(data) if ";base64" in head else data.encode()
            await route.fulfill(status=200, content_type=mime, body=body)
            return
        await route.abort("blockedbyclient")

    async def cosmetic(source: Any, url: str, classes: list[str], ids: list[str]) -> str:
        if filters is None or not hooks.enabled():
            return ""
        return await asyncio.to_thread(filters.cosmetic_css, url, list(classes or []), list(ids or []))

    route = getattr(context, "route", None)
    if route is not None:
        await route("**/*", handler)
    if filters is None:
        return
    with contextlib.suppress(Exception):
        await context.expose_binding("__cwCosmetic", cosmetic)
        await context.add_init_script(COSMETIC_JS)


class RateLimiter:
    """Coalesce frequent events (blocked-count updates) to at most one every ``interval`` s."""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self._last = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            return True
        return False
