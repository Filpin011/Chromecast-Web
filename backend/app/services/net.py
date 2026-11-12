"""Network helpers: LAN IP detection and public base URL."""

from __future__ import annotations

import socket

# Browser User-Agent for every upstream request (probes, proxy, restream): many IPTV
# panels and CDN WAFs answer python-httpx / Lavf with 403.
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


def detect_lan_ip() -> str:
    """Return the LAN IP of the default route (no packets are actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def public_base_url(override: str | None, env_value: str | None, port: int) -> str:
    """Base URL the Chromecast uses to reach this server (no trailing slash)."""
    for value in (override, env_value):
        if value and value.strip():
            return value.strip().rstrip("/")
    return f"http://{detect_lan_ip()}:{port}"
