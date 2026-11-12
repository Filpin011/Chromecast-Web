"""Source resolution."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import models as m
from app.api.deps import services
from app.services.container import Services
from app.services.resolver.inputs import join_input

router = APIRouter(prefix="/api")


@router.post("/resolve", response_model=m.ResolveResult)
async def resolve(body: m.ResolveIn, s: Services = Depends(services)) -> m.MediaResult | m.PlaylistResult:
    return await s.resolver.resolve(join_input(body.input, body.headers), body.kind)
