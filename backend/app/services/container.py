"""Wires every service together; stored on ``app.state.services``."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import AppConfig
from app.db import Database
from app.services import net
from app.services.adblock import FilterManager, host_in, hostname
from app.services.browser.launcher import BrowserProvider, PlaywrightProvider
from app.services.browser.session import BrowserManager
from app.services.cast.base import CastDriver
from app.services.cast.service import CastService
from app.services.proxy.restream import RestreamManager
from app.services.proxy.stream import ProxyService
from app.services.proxy.tokens import TokenRegistry
from app.services.resolver import ytdlp
from app.services.resolver.service import Resolver
from app.services.state import StateHub

log = logging.getLogger(__name__)


def make_driver(config: AppConfig) -> CastDriver:
    if config.cast_driver == "fake":
        from app.services.cast.fake import FakeCastDriver

        return FakeCastDriver(delay=config.fake_delay)
    from app.services.cast.pychromecast_driver import PyChromecastDriver

    return PyChromecastDriver()


@dataclass
class Services:
    config: AppConfig
    db: Database
    hub: StateHub
    http: httpx.AsyncClient
    tokens: TokenRegistry
    proxy: ProxyService
    restream: RestreamManager
    resolver: Resolver
    cast: CastService
    browser: BrowserManager
    browser_provider: BrowserProvider | None
    filters: FilterManager

    def base_url(self) -> str:
        return net.public_base_url(
            self.db.get_settings().public_base_url, self.config.public_base_url, self.config.port
        )

    async def start(self) -> None:
        self.hub.start()
        self.filters.start()
        await self.cast.start()
        self.restream.start_reaper()
        self.browser.start_reaper()

    async def stop(self) -> None:
        for step in (self.browser.shutdown, self.cast.stop, self.restream.shutdown, self.filters.stop, self.hub.stop):
            try:
                await step()
            except Exception:  # pragma: no cover
                log.exception("shutdown step failed")
        if self.browser_provider is not None:
            try:
                await self.browser_provider.close()
            except Exception:  # pragma: no cover
                log.exception("browser close failed")
        await self.http.aclose()
        self.db.close()


def build_services(
    config: AppConfig,
    *,
    driver: CastDriver | None = None,
    browser_provider: BrowserProvider | None = None,
    http_client: httpx.AsyncClient | None = None,
    ytdlp_extractor: Callable[[str], dict[str, Any]] | None = None,
    in_memory_db: bool = False,
) -> Services:
    db = Database(None if in_memory_db else config.db_path)
    hub = StateHub(tick_interval=config.tick_interval)
    http = http_client or httpx.AsyncClient(
        headers={"User-Agent": net.DESKTOP_UA},
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    tokens = TokenRegistry()
    restream = RestreamManager(
        config.restream_dir, config.ffmpeg_path, config.restream_idle_timeout, ffprobe=config.ffprobe_path
    )
    if browser_provider is None and config.enable_playwright:
        browser_provider = PlaywrightProvider()

    holder: dict[str, Services] = {}
    filters = FilterManager(None if in_memory_db else config.data_dir, http, auto_update=config.filters_auto_update)

    def adblock_for(url: str) -> bool:
        st = db.get_settings()
        return st.adblock_enabled and not host_in(hostname(url), st.adblock_disabled_hosts)

    def base_url() -> str:
        return holder["s"].base_url()

    resolver = Resolver(
        http,
        tokens,
        restream,
        media_root=config.media_root,
        browser=browser_provider,
        enable_playwright=config.enable_playwright,
        webpage_timeout=config.webpage_timeout,
        ytdlp_extractor=ytdlp_extractor or ytdlp.extract_info,
        base_url=base_url,
        force_proxy=lambda: db.get_settings().force_proxy,
        filters=filters,
        adblock_enabled=adblock_for,
    )

    def preview(url: str, headers: dict[str, str]) -> str:
        target = tokens.register(url, headers)
        return f"/proxy/{target.token}/{target.filename}"

    browser = BrowserManager(
        browser_provider if config.enable_playwright else None,
        max_sessions=config.browser_max_sessions,
        idle_timeout=config.browser_idle_timeout,
        hls_probe=resolver.hls_info,
        preview=preview,
        filters=filters,
        settings=db.get_settings,
        update_settings=db.update_settings,
    )
    cast = CastService(
        driver or make_driver(config),
        hub,
        db,
        resolver,
        base_url,
        discovery_seconds=config.discovery_seconds,
    )
    # a paused receiver stops fetching: keep the restream job of media still loaded
    restream.in_use = lambda job: any(f"/restream/{job.token}/" in u for u in cast.loaded_urls())
    services = Services(
        config=config,
        db=db,
        hub=hub,
        http=http,
        tokens=tokens,
        proxy=ProxyService(http, tokens),
        restream=restream,
        resolver=resolver,
        cast=cast,
        browser=browser,
        browser_provider=browser_provider,
        filters=filters,
    )
    holder["s"] = services
    return services
