"""Presence and availability endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from ssc.web.db import get_session
from ssc.web.queries import (
    availability_history,
    date_range,
    get_device_summary,
    presence_history,
    presence_samples,
)
from ssc.web.schemas import (
    AvailabilityResponse,
    PresenceResponse,
    PresenceSamplesResponse,
)

router = APIRouter(prefix="/devices", tags=["presence"])


def _require_device(session: Session, device_id: int) -> None:
    if get_device_summary(session, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")


def _range(
    request: Request,
    from_at: dt.datetime | None,
    to_at: dt.datetime | None,
) -> tuple[dt.datetime, dt.datetime]:
    start, end = date_range(
        from_at,
        to_at,
        default_days=request.app.state.config.default_range_days,
    )
    if start >= end:
        raise HTTPException(status_code=422, detail="from must be before to")
    return start, end


@router.get("/{device_id}/presence", response_model=PresenceResponse)
def device_presence(
    device_id: int,
    request: Request,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=5000, ge=1, le=20000),
    session: Session = Depends(get_session),
) -> PresenceResponse:
    _require_device(session, device_id)
    start, end = _range(request, from_at, to_at)
    return presence_history(
        session,
        device_id,
        start,
        end,
        limit=min(limit, request.app.state.config.max_presence_intervals),
    )


@router.get(
    "/{device_id}/presence/samples", response_model=PresenceSamplesResponse
)
def device_presence_samples(
    device_id: int,
    request: Request,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> PresenceSamplesResponse:
    _require_device(session, device_id)
    start, end = _range(request, from_at, to_at)
    return presence_samples(
        session, device_id, start, end, limit=limit, offset=offset
    )


@router.get("/{device_id}/availability", response_model=AvailabilityResponse)
def device_availability(
    device_id: int,
    request: Request,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    bucket: str = Query(default="day", pattern="^(hour|day|week)$"),
    session: Session = Depends(get_session),
) -> AvailabilityResponse:
    _require_device(session, device_id)
    start, end = _range(request, from_at, to_at)
    try:
        return availability_history(
            session,
            device_id,
            start,
            end,
            bucket=bucket,
            max_points=request.app.state.config.max_history_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc