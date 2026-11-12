"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request
from starlette.requests import HTTPConnection

from app.services.container import Services


def services(request: Request) -> Services:
    return request.app.state.services


def ws_services(conn: HTTPConnection) -> Services:
    return conn.app.state.services
