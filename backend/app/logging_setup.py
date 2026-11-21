"""Logging setup: one format for uvicorn and the app, short URLs, no per-request noise.

Conventions (see docs/ARCHITECTURE.md "Logging"): ``logging.getLogger(__name__)``, one
line per event, ``key=value`` details, devices as ``"<friendly name>" (<id[:8]>)``.
INFO = state changes a user cares about, WARNING = something went wrong, DEBUG =
per-request detail. ``LOG_LEVEL`` (default INFO) sets the level of the app loggers.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

FORMAT = "%(asctime)s %(levelname)-7s %(shortname)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARK = "_cw_handler"

# Reads of these never reach the log below DEBUG (failures always do): media the
# Chromecast fetches every few seconds, the frontend's assets, polling endpoints.
# Mutations (POST/PUT/DELETE/PATCH) and every 4xx/5xx are always logged.
QUIET_METHODS = ("GET", "HEAD", "OPTIONS")
# Third-party loggers that are chatty at INFO (one line per upstream request, volume
# changes, "app launched"): WARNING, or INFO when LOG_LEVEL=DEBUG.
VERBOSE_ONLY_LOGGERS = ("httpx", "pychromecast")
# Per-socket traces, mDNS internals, file watcher: WARNING at every level.
QUIET_LOGGERS = ("httpcore", "zeroconf", "watchfiles", "asyncio", "hpack")
_SEGMENT_MAX = 32
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def short_url(url: str | None) -> str:
    """``host/…/last-segment`` (query and fragment dropped, long segments cut).

    Never prints tokens, base64 ``/proxy/<token>/u/<b64>`` paths or query strings in full.
    Works for absolute URLs and bare paths (``/proxy/abc.../seg.ts``).
    """
    if not url:
        return "-"
    parts = urlsplit(url)
    host = parts.netloc.rsplit("@", 1)[-1]  # drop user:password@
    segments = [s for s in parts.path.split("/") if s]
    last = segments[-1] if segments else ""
    if len(last) > _SEGMENT_MAX:
        last = last[: _SEGMENT_MAX - 12] + "…"
    if len(segments) > 1:
        return f"{host}/…/{last}"
    return f"{host}/{last}"


def short_path(path: str) -> str:
    """Shorten a request path for the access log: media paths carry tokens/base64."""
    clean = path.split("?", 1)[0]
    if clean.startswith(("/proxy/", "/restream/")):
        prefix, token = clean.split("/")[1:3]
        return f"/{prefix}/{token[:6]}{short_url(clean)}"
    if len(clean) > 80:
        return short_url(clean)
    return clean


def shorten_urls(text: str) -> str:
    """Replace every absolute URL in free text (e.g. an exception message) by its short form."""
    return _URL_RE.sub(lambda m: short_url(m.group(0)), text)


def _short_name(name: str) -> str:
    for prefix in ("app.services.", "app."):
        if name.startswith(prefix):
            return name[len(prefix):]
    if name == "uvicorn.error":
        return "uvicorn"
    if name == "uvicorn.access":
        return "access"
    return name


class Formatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(FORMAT, DATEFMT)

    def format(self, record: logging.LogRecord) -> str:
        record.shortname = _short_name(record.name)
        return super().format(record)


class AccessFilter(logging.Filter):
    """uvicorn.access: drop successful reads unless verbose; shorten media paths always."""

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self.verbose = verbose

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        client, method, path, version, status = args
        try:
            code = int(status)
        except (TypeError, ValueError):
            return True
        if not self.verbose and code < 400 and method in QUIET_METHODS:
            return False
        if not self.verbose and str(path).startswith(("/proxy/", "/restream/")):
            return False  # media errors: the proxy / restream log them with more detail
        record.args = (client, method, short_path(str(path)), version, status)
        return True


class UvicornErrorFilter(logging.Filter):
    """uvicorn.error: websocket open/accept/close lines are per-connection noise."""

    QUIET = ("connection open", "connection closed")

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self.verbose = verbose

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.INFO:
            return True
        msg = str(record.msg)
        if msg in self.QUIET or msg.endswith("[accepted]"):
            if not self.verbose:
                return False
            if isinstance(record.args, tuple) and len(record.args) == 2:
                record.args = (record.args[0], short_path(str(record.args[1])))
        return True


class HttpxFilter(logging.Filter):
    """httpx "HTTP Request: GET <url> ..." lines (DEBUG only): print the URL short."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if str(record.msg).startswith("HTTP Request") and isinstance(args, tuple) and len(args) >= 2:
            record.args = (args[0], short_url(str(args[1])), *args[2:])
        return True


def _level(name: str | int | None) -> int:
    if isinstance(name, int):
        return name
    value = logging.getLevelName(str(name or "INFO").upper())
    return value if isinstance(value, int) else logging.INFO


def _replace_filter(logger: logging.Logger, flt: logging.Filter) -> None:
    for f in list(logger.filters):
        if type(f) is type(flt):
            logger.removeFilter(f)
    logger.addFilter(flt)


def configure_logging(level: str | int | None = "INFO") -> None:
    """Install the shared format and filters (idempotent; safe under pytest's caplog).

    Called by ``create_app`` (after uvicorn configured its own loggers), so it applies to
    ``python -m app`` and ``uvicorn app.main:app`` alike: uvicorn's loggers lose their
    own handlers and propagate to the root handler installed here.
    """
    lvl = _level(level)
    verbose = lvl <= logging.DEBUG
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]
    if not ours and not root.handlers:
        handler = logging.StreamHandler()
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)
        ours = [handler]
    for h in ours:  # no handler of ours: someone else (pytest) owns the root, leave it alone
        h.setFormatter(Formatter())
        root.setLevel(logging.INFO)
    logging.getLogger("app").setLevel(lvl)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(max(lvl, logging.INFO))
    _replace_filter(logging.getLogger("uvicorn.access"), AccessFilter(verbose))
    _replace_filter(logging.getLogger("uvicorn.error"), UvicornErrorFilter(verbose))
    _replace_filter(logging.getLogger("httpx"), HttpxFilter())
    for name in VERBOSE_ONLY_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO if verbose else max(lvl, logging.WARNING))
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(lvl, logging.WARNING))


def uvicorn_log_config(level: str | int | None = "INFO") -> dict[str, Any]:
    """dictConfig for ``uvicorn.run``: uvicorn's own startup lines in the shared format too
    (``configure_logging`` takes over once the app is imported)."""
    lvl = logging.getLevelName(max(_level(level), logging.INFO))
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"()": Formatter}},
        "handlers": {"default": {"class": "logging.StreamHandler", "formatter": "default"}},
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": lvl, "propagate": False},
            "uvicorn.error": {"level": lvl},
            "uvicorn.access": {"level": lvl},
        },
    }
