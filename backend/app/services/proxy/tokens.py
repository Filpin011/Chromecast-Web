"""Token registry: opaque token → upstream URL + headers to use."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# Headers worth forwarding to the upstream when proxying.
FORWARD_HEADERS = ("referer", "origin", "user-agent", "cookie", "authorization", "accept-language")

TOKEN_TTL = 48 * 3600


def clean_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Keep only the request headers that matter for upstream access."""
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        lk = k.lower()
        if lk in FORWARD_HEADERS and v:
            canonical = "-".join(p.capitalize() for p in lk.split("-"))
            out[canonical] = v
    return out


@dataclass
class ProxyTarget:
    token: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    @property
    def filename(self) -> str:
        name = urlsplit(self.url).path.rsplit("/", 1)[-1]
        return name or "index"


class TokenRegistry:
    def __init__(self, ttl: float = TOKEN_TTL) -> None:
        self.ttl = ttl
        self._targets: dict[str, ProxyTarget] = {}

    def register(self, url: str, headers: dict[str, str] | None = None) -> ProxyTarget:
        hdrs = clean_headers(headers)
        # deterministic → re-registering the same source reuses its token
        digest = hashlib.sha256(json.dumps([url, sorted(hdrs.items())]).encode()).hexdigest()[:24]
        target = self._targets.get(digest)
        if target is None:
            target = ProxyTarget(token=digest, url=url, headers=hdrs)
            self._targets[digest] = target
        target.last_used = time.time()
        self._gc()
        return target

    def get(self, token: str) -> ProxyTarget | None:
        t = self._targets.get(token)
        if t:
            t.last_used = time.time()
        return t

    def _gc(self) -> None:
        cutoff = time.time() - self.ttl
        for tok in [k for k, v in self._targets.items() if v.last_used < cutoff]:
            self._targets.pop(tok, None)

    def __len__(self) -> int:
        return len(self._targets)
