"""Entry point: ``python -m app``."""

import uvicorn

from app.config import get_settings
from app.logging_setup import uvicorn_log_config


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_config=uvicorn_log_config(settings.log_level),
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
