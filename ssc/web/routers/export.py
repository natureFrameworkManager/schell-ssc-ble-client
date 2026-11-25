"""Export endpoint for device statistics."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlmodel import Session

from ssc.web.db import get_session
from ssc.web.export import build_export, parse_datasets
from ssc.web.queries import date_range, get_device_summary

router = APIRouter(prefix="/devices", tags=["export"])


@router.get("/{device_id}/export")
def export_device(
    device_id: int,
    request: Request,
    export_format: Literal["csv", "json", "xlsx", "pdf"] = Query(
        default="csv", alias="format"
    ),
    datasets: str | None = Query(default=None),
    from_at: dt.datetime | None = Query(default=None, alias="from"),
    to_at: dt.datetime | None = Query(default=None, alias="to"),
    delimiter: Literal["comma", "semicolon", "tab"] = "comma",
    pretty: bool = True,
    include_metadata: bool = True,
    bom: bool = False,
    pdf_page_size: Literal["a4", "letter"] = "a4",
    pdf_orientation: Literal["portrait", "landscape"] = "landscape",
    session: Session = Depends(get_session),
) -> Response:
    device = get_device_summary(session, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    start, end = date_range(
        from_at,
        to_at,
        default_days=request.app.state.config.default_range_days,
    )
    if start >= end:
        raise HTTPException(status_code=422, detail="from must be before to")

    try:
        selected = parse_datasets(datasets)
        content, media_type, filename = build_export(
            session,
            device,
            from_at=start,
            to_at=end,
            datasets=selected,
            export_format=export_format,
            delimiter_name=delimiter,
            pretty=pretty,
            include_metadata=include_metadata,
            bom=bom,
            max_rows=request.app.state.config.max_export_rows,
            pdf_page_size=pdf_page_size,
            pdf_orientation=pdf_orientation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )