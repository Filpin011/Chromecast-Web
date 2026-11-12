"""Environment configuration (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Dev only (production is same-origin): a Next dev server opened from a phone on the
# LAN (http://192.168.x.y:3000) calls the backend cross-origin.
PRIVATE_ORIGIN_RE = (
    r"^https?://(localhost|127\.0\.0\.1|\[::1\]|10(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}"
    r"|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2}|[A-Za-z0-9-]+\.(local|lan|home|internal))(:\d+)?$"
)


class AppConfig(BaseSettings):
    """Process-level configuration from environment variables.

    User-editable runtime preferences live in the DB (see ``models.Settings``).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cast_driver: Literal["pychromecast", "fake"] = "pychromecast"
    public_base_url: str | None = None
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = Path("./data")
    media_root: Path | None = None
    frontend_dir: Path = Path("../frontend/out")
    enable_playwright: bool = True
    # download/refresh the uBO default filter lists every 24h (bundled fallback list is always used)
    filters_auto_update: bool = True
    log_level: str = "info"
    # CORS_ORIGINS: comma-separated extra origins; CORS_ORIGIN_REGEX: "" disables the LAN default
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    cors_origin_regex: str | None = PRIVATE_ORIGIN_RE

    # Tunables (mostly useful for tests)
    discovery_seconds: float = 5.0
    tick_interval: float = 1.0
    browser_max_sessions: int = 2
    browser_idle_timeout: float = 600.0
    webpage_timeout: float = 20.0
    restream_idle_timeout: float = 60.0
    fake_delay: float = 0.4
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str | None = None  # default: "ffprobe" next to ffmpeg_path

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def restream_dir(self) -> Path:
        return self.data_dir / "restream"


@lru_cache
def get_settings() -> AppConfig:
    return AppConfig()
