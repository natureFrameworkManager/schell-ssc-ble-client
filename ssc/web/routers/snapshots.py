"""Current state, snapshot and raw EEPROM endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlmodel import Session

from ssc.web.db import get_session
from ssc.web.queries import (
    compare_snapshots,
    current_state,
    get_device_summary,
    get_snapshot,
    list_snapshots,
    load_raw_eeprom,
    load_snapshot_state,
)
from ssc.web.schemas import (
    CompareResponse,
    SnapshotListResponse,
    SnapshotStateResponse,
)

router = APIRouter(prefix="/devices", tags=["state"])


def _summary(session: Session, device_id: int):
    device = get_device_summary(session, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("/{device_id}/state/current", response_model=SnapshotStateResponse)
def device_current_state(
    device_id: int,
    session: Session = Depends(get_session),
) -> SnapshotStateResponse:
    state = current_state(session, device_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return state


@router.get("/{device_id}/snapshots", response_model=SnapshotListResponse)
def device_snapshots(
    device_id: int,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> SnapshotListResponse:
    _summary(session, device_id)
    return list_snapshots(
        session,
        device_id,
        from_at=from_at,
        to_at=to_at,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{device_id}/snapshots/{snapshot_id}",
    response_model=SnapshotStateResponse,
)
def device_snapshot(
    device_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> SnapshotStateResponse:
    device = _summary(session, device_id)
    snapshot = get_snapshot(session, device_id, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return load_snapshot_state(session, device, snapshot)


@router.get("/{device_id}/snapshots/{snapshot_id}/eeprom")
def device_snapshot_eeprom(
    device_id: int,
    snapshot_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    if not request.app.state.config.raw_eeprom_download:
        raise HTTPException(
            status_code=403, detail="Raw EEPROM download is disabled"
        )
    _summary(session, device_id)
    snapshot = get_snapshot(session, device_id, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    data = load_raw_eeprom(session, snapshot)
    if data is None:
        raise HTTPException(status_code=404, detail="EEPROM image not available")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="eeprom-{device_id}-{snapshot_id}.bin"'
            )
        },
    )


@router.get("/{device_id}/compare", response_model=CompareResponse)
def device_compare(
    device_id: int,
    base: int = Query(ge=1),
    target: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> CompareResponse:
    _summary(session, device_id)
    if base == target:
        raise HTTPException(
            status_code=422, detail="base and target must be different snapshots"
        )
    try:
        result = compare_snapshots(session, device_id, base, target)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return result