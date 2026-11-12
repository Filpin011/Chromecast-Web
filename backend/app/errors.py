"""Uniform API errors: ``{detail, code}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


Params = dict[str, str | int]


class AppError(Exception):
    """An API error. ``detail`` is English, for logs/developers; clients translate by ``code``
    (stable, coarse) and, when set, ``reason`` (stable, finer-grained) with ``params``."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        *,
        reason: str | None = None,
        params: Params | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.reason = reason
        self.params = params

    def body(self) -> dict[str, object]:
        body: dict[str, object] = {"detail": self.detail}
        if self.code:
            body["code"] = self.code
        if self.reason:
            body["reason"] = self.reason
        if self.params:
            body["params"] = self.params
        return body


def not_found(detail: str, code: str) -> AppError:
    return AppError(404, detail, code)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return JSONResponse(
            {"detail": "; ".join(parts) or "Invalid request", "code": "validation_error"},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Last resort: keep the {detail, code} contract instead of a plain-text 500.
        log.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        body = {"detail": f"Internal error: {type(exc).__name__}", "code": "internal_error"}
        return JSONResponse(body, status_code=500)
