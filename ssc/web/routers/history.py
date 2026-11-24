"""History and analysis endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from ssc.web.db import get_session
from ssc.web.queries import (
    config_changes,
    counter_history,
    daily_stats_history,
    date_range,
    event_history,
    get_device_summary,
    recorder_runs,
    telemetry_history,
)
from ssc.web.schemas import (
    ConfigChangesResponse,
    CounterHistoryResponse,
    DailyStatsResponse,
    EventHistoryResponse,
    RecorderRunDTO,
    RecorderRunsResponse,
    TelemetryHistoryResponse,
)

router = APIRouter(tags=["history"])


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


@router.get(
    "/devices/{device_id}/history/telemetry",
    response_model=TelemetryHistoryResponse,
)
def device_telemetry_history(
    device_id: int,
    request: Request,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    bucket: str = Query(default="day", pattern="^(raw|hour|day|week)$"),
    session: Session = Depends(get_session),
) -> TelemetryHistoryResponse:
    _require_device(session, device_id)
    start, end = _range(request, from_at, to_at)
    try:
        return telemetry_history(
            session,
            device_id,
            start,
            end,
            bucket=bucket,
            limit=request.app.state.config.max_history_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/devices/{device_id}/history/counters",
    response_model=CounterHistoryResponse,
)
def device_counter_history(
    device_id: int,
    request: Request,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    session: Session = Depends(get_session),
) -> CounterHistoryResponse:
    _require_device(session, device_id)
    start, end = _range(request, from_at, to_at)
    return counter_history(session, device_id, start, end)


@router.get(
    "/devices/{device_id}/history/daily",
    response_model=DailyStatsResponse,
)
def device_daily_history(
    device_id: int,
    from_date: dt.date | None = Query(default=None, alias="from"),
    to_date: dt.date | None = Query(default=None, alias="to"),
    session: Session = Depends(get_session),
) -> DailyStatsResponse:
    _require_device(session, device_id)
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from must be before to")
    return daily_stats_history(
        session, device_id, from_date=from_date, to_date=to_date
    )


@router.get(
    "/devices/{device_id}/history/events",
    response_model=EventHistoryResponse,
)
def device_event_history(
    device_id: int,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    log_type: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> EventHistoryResponse:
    _require_device(session, device_id)
    if from_at is not None and to_at is not None and from_at >= to_at:
        raise HTTPException(status_code=422, detail="from must be before to")
    return event_history(
        session,
        device_id,
        log_type=log_type,
        from_at=from_at,
        to_at=to_at,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/devices/{device_id}/history/config-changes",
    response_model=ConfigChangesResponse,
)
def device_config_changes(
    device_id: int,
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    name: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ConfigChangesResponse:
    _require_device(session, device_id)
    if from_at is not None and to_at is not None and from_at >= to_at:
        raise HTTPException(status_code=422, detail="from must be before to")
    return ConfigChangesResponse(
        device_id=device_id,
        items=config_changes(
            session,
            device_id,
            name=name,
            from_at=from_at,
            to_at=to_at,
            limit=limit,
        ),
    )


@router.get("/recorder/runs", response_model=RecorderRunsResponse)
def recorder_run_history(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> RecorderRunsResponse:
    rows = recorder_runs(session, limit)
    return RecorderRunsResponse(
        items=[
            RecorderRunDTO(
                id=row.id,
                started_at=row.started_at,
                stopped_at=row.stopped_at,
                host=row.host,
                version=row.version,
                stop_reason=row.stop_reason,
            )
            for row in rows
        ]
    )