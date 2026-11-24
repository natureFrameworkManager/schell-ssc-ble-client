"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ssc.db.engine import SCHEMA_VERSION
from ssc.db.models import Device, PresenceSample, RecorderRun
from ssc.web.db import database_path, schema_version, table_names
from ssc.web.schemas import HealthResponse, RecorderRunDTO

router = APIRouter(tags=["health"])

EXPECTED_TABLES = {
    "device",
    "online_period",
    "off_period",
    "presence_sample",
    "state_snapshot",
    "eeprom_image",
    "recorder_run",
}


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse | JSONResponse:
    config = request.app.state.config
    engine = request.app.state.engine
    path = database_path(config.database)
    exists = path is None or path.exists()
    if not exists:
        response = HealthResponse(
            status="unavailable",
            database=config.database,
            database_exists=False,
            expected_schema_version=SCHEMA_VERSION,
            detail=f"Database does not exist: {path}",
        )
        return JSONResponse(
            status_code=503,
            content=response.model_dump(mode="json"),
        )

    tables = table_names(engine)
    tables_ok = EXPECTED_TABLES.issubset(tables)
    version = schema_version(engine)
    latest_run = None
    device_count = 0
    latest_scan = None
    detail = None

    try:
        with Session(engine) as session:
            device_count = (
                session.exec(select(func.count()).select_from(Device)).one() or 0
            )
            run = session.exec(
                select(RecorderRun)
                .order_by(RecorderRun.started_at.desc())
                .limit(1)
            ).first()
            if run is not None:
                latest_run = RecorderRunDTO(
                    id=run.id,
                    started_at=run.started_at,
                    stopped_at=run.stopped_at,
                    host=run.host,
                    version=run.version,
                    stop_reason=run.stop_reason,
                )
            latest_scan = session.exec(
                select(func.max(PresenceSample.observed_at))
            ).first()
    except Exception as exc:  # noqa: BLE001 - health reports the failure
        detail = str(exc)

    recorder_running = bool(latest_run and latest_run.stopped_at is None)
    status = "ok" if tables_ok and version == SCHEMA_VERSION else "degraded"
    if detail:
        status = "unavailable"
    response = HealthResponse(
        status=status,  # type: ignore[arg-type]
        database=config.database,
        database_exists=exists,
        schema_version=version,
        expected_schema_version=SCHEMA_VERSION,
        tables_ok=tables_ok,
        device_count=int(device_count),
        recorder_running=recorder_running,
        latest_run=latest_run,
        latest_scan_at=latest_scan,
        detail=detail,
    )
    if detail:
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))
    return response