from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.services.cast.fake import FakeCastDriver
from tests.fakes import FakeProvider, ytdlp_info

BASE = "http://cast.test:8000"


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    (root / "Movies").mkdir(parents=True)
    (root / "Movies" / "film.mp4").write_bytes(b"\x00" * 2048)
    (root / "Movies" / "old.avi").write_bytes(b"\x00" * 16)
    (root / "notes.txt").write_text("not media")
    (root / ".hidden.mp4").write_bytes(b"")
    return root


@pytest.fixture
def config(tmp_path: Path, media_root: Path) -> AppConfig:
    front = tmp_path / "front"
    front.mkdir()
    return AppConfig(
        cast_driver="fake",
        public_base_url=BASE,
        data_dir=tmp_path / "data",
        media_root=media_root,
        frontend_dir=front,
        enable_playwright=True,
        tick_interval=0.1,
        discovery_seconds=0.01,
        fake_delay=0.02,
        webpage_timeout=2.0,
        browser_idle_timeout=600,
        filters_auto_update=False,
    )


@pytest.fixture
def driver() -> FakeCastDriver:
    return FakeCastDriver(delay=0.02)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def mock_http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(config: AppConfig, driver: FakeCastDriver, provider: FakeProvider,
           mock_http: respx.MockRouter) -> Iterator[TestClient]:
    app = create_app(config, driver=driver, browser_provider=provider, ytdlp_extractor=ytdlp_info)
    with TestClient(app) as c:
        yield c


def wait_for(fn: Callable[[], Any], timeout: float = 3.0, interval: float = 0.02) -> Any:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met in {timeout}s (last={last!r})")


def player(client: TestClient, device_id: str) -> dict[str, Any] | None:
    return client.get("/api/state").json()["players"].get(device_id)
