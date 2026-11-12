"""Devices, connection, playback control and per-device queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app import models as m
from app.api.deps import services
from app.services.container import Services
from app.services.resolver.inputs import join_input

router = APIRouter(prefix="/api/devices")


@router.get("", response_model=list[m.Device])
async def list_devices(s: Services = Depends(services)) -> list[m.Device]:
    return s.cast.driver.devices()


@router.post("/discover", response_model=list[m.Device])
async def discover(s: Services = Depends(services)) -> list[m.Device]:
    return await s.cast.discover()


@router.post("/manual", response_model=m.Device, status_code=201)
async def add_manual(body: m.ManualDeviceIn, s: Services = Depends(services)) -> m.Device:
    return await s.cast.add_manual(body.host.strip(), body.port, body.name)


@router.delete("/{device_id}", status_code=204)
async def remove_device(device_id: str, s: Services = Depends(services)) -> Response:
    await s.cast.remove_device(device_id)
    return Response(status_code=204)


@router.post("/{device_id}/connect", response_model=m.PlayerState)
async def connect(device_id: str, s: Services = Depends(services)) -> m.PlayerState:
    return await s.cast.connect(device_id)


@router.post("/{device_id}/disconnect", status_code=204)
async def disconnect(device_id: str, s: Services = Depends(services)) -> Response:
    await s.cast.disconnect(device_id)
    return Response(status_code=204)


@router.post("/{device_id}/play", response_model=m.PlayerState)
async def play(device_id: str, body: m.PlayIn, s: Services = Depends(services)) -> m.PlayerState:
    return await s.cast.play(device_id, join_input(body.input, body.headers), body.kind, body.title, body.enqueue)


@router.post("/{device_id}/control", response_model=m.PlayerState)
async def control(device_id: str, body: m.ControlIn, s: Services = Depends(services)) -> m.PlayerState:
    return await s.cast.control(device_id, body.action, body.value)


@router.post("/{device_id}/tracks", response_model=m.PlayerState)
async def tracks(device_id: str, body: m.TracksIn, s: Services = Depends(services)) -> m.PlayerState:
    return await s.cast.set_tracks(device_id, body.active_track_ids)


@router.post("/{device_id}/idle", response_model=m.PlayerState)
async def idle(device_id: str, s: Services = Depends(services)) -> m.PlayerState:
    return await s.cast.show_idle(device_id)


@router.post("/{device_id}/queue", response_model=m.PlayerState)
async def enqueue(device_id: str, body: m.QueueIn, s: Services = Depends(services)) -> m.PlayerState:
    return await s.cast.enqueue(device_id, join_input(body.input, body.headers), body.kind, body.title)


@router.delete("/{device_id}/queue/{item_id}", response_model=m.PlayerState)
async def dequeue(device_id: str, item_id: str, s: Services = Depends(services)) -> m.PlayerState:
    return s.cast.remove_from_queue(device_id, item_id)


@router.put("/{device_id}/queue", response_model=m.PlayerState)
async def reorder(device_id: str, body: m.QueueReorderIn, s: Services = Depends(services)) -> m.PlayerState:
    return s.cast.reorder_queue(device_id, body.item_ids)
