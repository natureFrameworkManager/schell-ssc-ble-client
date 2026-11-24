"""Device list and detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from ssc.web.db import get_session
from ssc.web.queries import get_device_summary, list_device_summaries
from ssc.web.schemas import DeviceSummary

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceSummary])
def devices(
    online_only: bool = False,
    search: str | None = Query(default=None, max_length=128),
    session: Session = Depends(get_session),
) -> list[DeviceSummary]:
    items = list_device_summaries(session)
    if search:
        needle = search.strip().lower()
        items = [
            item
            for item in items
            if needle
            in " ".join(
                filter(
                    None,
                    [
                        item.display_name,
                        item.address,
                        item.serial,
                        item.product,
                    ],
                )
            ).lower()
        ]
    if online_only:
        items = [item for item in items if item.state == "online"]
    return items


@router.get("/{device_id}", response_model=DeviceSummary)
def device_detail(
    device_id: int,
    session: Session = Depends(get_session),
) -> DeviceSummary:
    device = get_device_summary(session, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device