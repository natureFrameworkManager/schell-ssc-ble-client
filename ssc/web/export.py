"""Export recorder statistics as CSV, JSON or XLSX."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import zipfile
from collections.abc import Iterable
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from pydantic import BaseModel
from sqlmodel import Session

from ssc.db.models import utcnow
from ssc.web.queries import (
    config_changes,
    counter_history,
    current_state,
    daily_stats_history,
    event_history,
    list_snapshots,
    presence_history,
    telemetry_history,
)
from ssc.web.schemas import DeviceSummary

EXPORT_DATASETS = (
    "summary",
    "presence",
    "telemetry",
    "counters",
    "daily",
    "events",
    "config",
    "config_changes",
    "snapshots",
)

DATASET_LABELS = {
    "summary": "Device summary",
    "presence": "Online/off history",
    "telemetry": "Telemetry",
    "counters": "Consumption counters",
    "daily": "Daily statistics",
    "events": "Event logs",
    "config": "Current configuration",
    "config_changes": "Configuration changes",
    "snapshots": "Snapshot metadata",
}

DATASET_COLUMNS: dict[str, list[str]] = {
    "summary": [
        "id",
        "address",
        "identifier",
        "serial",
        "display_name",
        "product",
        "state",
        "recorder_running",
        "online_since",
        "offline_since",
        "current_interval_s",
        "last_seen_at",
        "observation_gap",
        "latest_snapshot_at",
        "latest_query_status",
        "latest_battery_level",
        "latest_battery_voltage_v",
        "state_age_s",
    ],
    "presence": [
        "kind",
        "started_at",
        "ended_at",
        "duration_s",
        "open",
        "clipped_start",
        "clipped_end",
        "fully_observed",
        "start_accuracy",
        "query_status",
        "scan_count",
    ],
    "telemetry": [
        "captured_at",
        "device_datetime",
        "battery_voltage_v",
        "battery_level",
        "vcc_v",
        "temperature_raw",
        "rail_33_raw",
        "samples",
    ],
    "counters": [
        "captured_at",
        "device_datetime",
        "count_normal",
        "runtime_normal",
        "count_stagnation",
        "runtime_stagnation",
        "consumption_normal_l",
        "consumption_stagnation_l",
        "count_restart",
        "count_lifetime",
    ],
    "daily": [
        "date",
        "count_normal",
        "runtime_normal",
        "count_stagnation",
        "runtime_stagnation",
        "aerator_lpm",
        "consumption_normal_l",
        "consumption_stagnation_l",
        "first_seen_at",
        "last_seen_at",
        "last_snapshot_id",
    ],
    "events": [
        "id",
        "log_type",
        "slot_index",
        "occurred_at",
        "status",
        "duration_s",
        "entry_sha256",
        "raw_hex",
        "first_seen_at",
        "last_seen_at",
        "last_snapshot_id",
    ],
    "config": [
        "name",
        "address",
        "length",
        "value_type",
        "value_text",
        "value_number",
        "value_bool",
        "first_seen_at",
        "last_seen_at",
        "last_snapshot_id",
    ],
    "config_changes": [
        "id",
        "name",
        "changed_at",
        "old_value_text",
        "new_value_text",
        "old_value_number",
        "new_value_number",
        "snapshot_id",
    ],
    "snapshots": [
        "id",
        "online_period_id",
        "captured_at",
        "completed_at",
        "device_datetime",
        "query_status",
        "coverage",
        "missing_ranges",
        "error",
        "eeprom.sha256",
        "eeprom.start_address",
        "eeprom.length",
        "eeprom.coverage",
        "eeprom.codec",
        "eeprom.first_seen_at",
        "eeprom.last_seen_at",
        "eeprom.seen_count",
    ],
}

DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t"}

PDF_COLUMNS: dict[str, list[str]] = {
    "presence": [
        "kind",
        "started_at",
        "ended_at",
        "duration_s",
        "open",
        "fully_observed",
        "query_status",
    ],
    "telemetry": [
        "captured_at",
        "device_datetime",
        "battery_voltage_v",
        "battery_level",
        "vcc_v",
        "temperature_raw",
    ],
    "counters": [
        "captured_at",
        "count_normal",
        "runtime_normal",
        "count_stagnation",
        "count_lifetime",
    ],
    "daily": [
        "date",
        "count_normal",
        "runtime_normal",
        "consumption_normal_l",
        "count_stagnation",
    ],
    "events": ["occurred_at", "log_type", "status", "duration_s"],
    "config": ["name", "value_text", "value_type", "last_seen_at"],
    "config_changes": [
        "changed_at",
        "name",
        "old_value_text",
        "new_value_text",
    ],
    "snapshots": [
        "captured_at",
        "query_status",
        "coverage",
        "missing_ranges",
        "error",
        "eeprom.sha256",
    ],
}

PDF_HEADERS = {
    "kind": "Kind",
    "started_at": "Started",
    "ended_at": "Ended",
    "duration_s": "Duration",
    "open": "Open",
    "fully_observed": "Observed",
    "query_status": "Query",
    "captured_at": "Captured",
    "device_datetime": "Device time",
    "battery_voltage_v": "Battery V",
    "battery_level": "Battery %",
    "vcc_v": "VCC V",
    "temperature_raw": "Temperature",
    "count_normal": "Count",
    "runtime_normal": "Runtime",
    "count_stagnation": "Stagnation",
    "count_lifetime": "Lifetime",
    "date": "Date",
    "consumption_normal_l": "Litres",
    "occurred_at": "Occurred",
    "log_type": "Log",
    "status": "Status",
    "name": "Field",
    "value_text": "Value",
    "value_type": "Type",
    "last_seen_at": "Last seen",
    "changed_at": "Changed",
    "old_value_text": "Old",
    "new_value_text": "New",
    "coverage": "Coverage",
    "missing_ranges": "Missing ranges",
    "error": "Error",
    "eeprom.sha256": "EEPROM SHA-256",
}

PDF_SUMMARY_FIELDS = [
    ("Name", "display_name"),
    ("Address", "address"),
    ("Serial", "serial"),
    ("Product", "product"),
    ("State", "state"),
    ("Recorder running", "recorder_running"),
    ("Online since", "online_since"),
    ("Offline since", "offline_since"),
    ("Current interval", "current_interval_s"),
    ("Last seen", "last_seen_at"),
    ("Latest snapshot", "latest_snapshot_at"),
    ("Latest query", "latest_query_status"),
    ("Battery", "latest_battery_level"),
    ("State age", "state_age_s"),
]


def parse_datasets(value: str | None) -> list[str]:
    if not value:
        return list(EXPORT_DATASETS)
    selected = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in selected if item not in EXPORT_DATASETS]
    if unknown:
        raise ValueError(f"unknown dataset(s): {', '.join(unknown)}")
    if not selected:
        raise ValueError("select at least one dataset")
    return selected


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def collect_export_data(
    session: Session,
    device: DeviceSummary,
    *,
    from_at: dt.datetime,
    to_at: dt.datetime,
    datasets: Iterable[str],
    max_rows: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Collect all selected datasets into flat row dictionaries."""
    data: dict[str, list[dict[str, Any]]] = {}
    truncated: dict[str, int] = {}

    for dataset in datasets:
        rows: list[Any]
        if dataset == "summary":
            rows = [_dump(device)]
        elif dataset == "presence":
            rows = [
                _dump(item)
                for item in presence_history(
                    session, device.id, from_at, to_at, limit=max_rows
                ).intervals
            ]
        elif dataset == "telemetry":
            try:
                rows = [
                    _dump(item)
                    for item in telemetry_history(
                        session,
                        device.id,
                        from_at,
                        to_at,
                        bucket="raw",
                        limit=max_rows,
                    ).points
                ]
            except ValueError as exc:
                raise ValueError(
                    "telemetry range contains too many points; narrow the range"
                ) from exc
        elif dataset == "counters":
            rows = [
                _dump(item)
                for item in counter_history(session, device.id, from_at, to_at).points
            ]
        elif dataset == "daily":
            rows = [
                _dump(item)
                for item in daily_stats_history(
                    session,
                    device.id,
                    from_date=from_at.date(),
                    to_date=to_at.date(),
                ).items
            ]
        elif dataset == "events":
            history = event_history(
                session,
                device.id,
                log_type=None,
                from_at=from_at,
                to_at=to_at,
                limit=max_rows,
                offset=0,
            )
            rows = [_dump(item) for item in history.items]
            if history.total > len(rows):
                truncated[dataset] = history.total
        elif dataset == "config":
            state = current_state(session, device.id)
            rows = [_dump(item) for item in state.config] if state else []
        elif dataset == "config_changes":
            rows = [
                _dump(item)
                for item in config_changes(
                    session,
                    device.id,
                    name=None,
                    from_at=from_at,
                    to_at=to_at,
                    limit=max_rows,
                )
            ]
        elif dataset == "snapshots":
            snapshots = list_snapshots(
                session,
                device.id,
                from_at=from_at,
                to_at=to_at,
                limit=max_rows,
                offset=0,
            )
            rows = [_dump(item) for item in snapshots.items]
            if snapshots.total > len(rows):
                truncated[dataset] = snapshots.total
        else:
            raise ValueError(f"unknown dataset: {dataset}")
        data[dataset] = rows

    metadata = {
        "generated_at": utcnow().isoformat(),
        "device": _dump(device),
        "from": from_at.isoformat(),
        "to": to_at.isoformat(),
        "datasets": list(datasets),
        "row_counts": {name: len(rows) for name, rows in data.items()},
        "truncated": truncated,
        "max_rows": max_rows,
    }
    return data, metadata


def _flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(f"{prefix}.{key}" if prefix else str(key), nested)
            return
        if isinstance(value, list):
            flat[prefix] = json.dumps(value, default=str, ensure_ascii=False)
            return
        flat[prefix] = value

    for key, value in row.items():
        walk(str(key), value)
    return flat


def _columns(dataset: str, rows: list[dict[str, Any]]) -> list[str]:
    columns = list(DATASET_COLUMNS.get(dataset, []))
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "device"


def _csv_bytes(
    dataset: str,
    rows: list[dict[str, Any]],
    *,
    delimiter: str,
    bom: bool,
) -> bytes:
    flat_rows = [_flatten_row(row) for row in rows]
    columns = _columns(dataset, flat_rows)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=columns,
        delimiter=delimiter,
        extrasaction="ignore",
        lineterminator="\n",
    )
    if columns:
        writer.writeheader()
        writer.writerows(flat_rows)
    text = buffer.getvalue()
    if bom:
        text = "\ufeff" + text
    return text.encode("utf-8")


def _json_bytes(payload: Any, *, pretty: bool) -> bytes:
    return json.dumps(
        payload,
        indent=2 if pretty else None,
        default=str,
        ensure_ascii=False,
        separators=None if pretty else (",", ":"),
    ).encode("utf-8")


def _excel_value(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            return value.astimezone(dt.UTC).replace(tzinfo=None)
        return value
    if isinstance(value, (dt.date, dt.time)):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return value


def _xlsx_bytes(
    data: dict[str, list[dict[str, Any]]],
    metadata: dict[str, Any],
    *,
    include_metadata: bool,
) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - dependency is in requirements-web
        raise RuntimeError(
            "XLSX export requires the openpyxl package"
        ) from exc

    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)

    if include_metadata:
        sheet = workbook.create_sheet("metadata")
        sheet.append(["key", "value"])
        for key, value in metadata.items():
            sheet.append([key, _excel_value(value)])
        sheet.freeze_panes = "A2"

    for dataset in metadata.get("datasets", []):
        rows = data.get(dataset, [])
        flat_rows = [_flatten_row(row) for row in rows]
        columns = _columns(dataset, flat_rows)
        title = dataset[:31]
        sheet = workbook.create_sheet(title)
        sheet.append(columns)
        for row in flat_rows:
            sheet.append([_excel_value(row.get(column)) for column in columns])
        sheet.freeze_panes = "A2"
        for index, column in enumerate(columns, start=1):
            width = min(60, max(12, len(column) + 2))
            sheet.column_dimensions[
                sheet.cell(row=1, column=index).column_letter
            ].width = width

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pdf_text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def _pdf_paragraph(text: Any, style: Any) -> Any:
    from reportlab.platypus import Paragraph

    escaped = xml_escape(_pdf_text(text)).replace("\n", "<br/>")
    return Paragraph(escaped, style)


def _pdf_table(
    dataset: str,
    rows: list[dict[str, Any]],
    *,
    available_width: float,
    styles: dict[str, Any],
) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import LongTable, Paragraph, TableStyle

    columns = list(PDF_COLUMNS.get(dataset, []))
    flat_rows = [_flatten_row(row) for row in rows]
    for row in flat_rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns or not flat_rows:
        return _pdf_paragraph("No data in the selected range.", styles["body"])

    data = [
        [
            Paragraph(xml_escape(PDF_HEADERS.get(column, column)), styles["header"])
            for column in columns
        ]
    ]
    for row in flat_rows:
        data.append(
            [
                _pdf_paragraph(row.get(column), styles["cell"])
                for column in columns
            ]
        )

    table = LongTable(
        data,
        colWidths=[available_width / len(columns)] * len(columns),
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c2cf")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _pdf_bytes(
    data: dict[str, list[dict[str, Any]]],
    metadata: dict[str, Any],
    device: DeviceSummary,
    *,
    page_size_name: str,
    orientation: str,
    include_metadata: bool,
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, LETTER, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - dependency is in requirements-web
        raise RuntimeError("PDF export requires the reportlab package") from exc

    base_size = A4 if page_size_name == "a4" else LETTER
    page_size = landscape(base_size) if orientation == "landscape" else base_size
    margin = 34
    available_width = page_size[0] - 2 * margin

    styles = {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=19,
            textColor=colors.HexColor("#17202a"),
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#5f6b7a"),
            spaceAfter=10,
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=colors.HexColor("#17202a"),
            spaceBefore=10,
            spaceAfter=5,
        ),
        "header": ParagraphStyle(
            "header",
            fontName="Helvetica-Bold",
            fontSize=6.8,
            leading=8,
            textColor=colors.HexColor("#1f2937"),
        ),
        "cell": ParagraphStyle(
            "cell",
            fontName="Helvetica",
            fontSize=6.5,
            leading=7.8,
            textColor=colors.HexColor("#17202a"),
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#5f6b7a"),
        ),
    }

    name = device.display_name or device.serial or device.address
    story: list[Any] = [
        Paragraph(xml_escape(f"{name} — SSC statistics"), styles["title"]),
        Paragraph(
            xml_escape(
                f"Range {metadata.get('from')} to {metadata.get('to')} · "
                f"generated {metadata.get('generated_at')} · "
                f"{page_size_name.upper()} {orientation}"
            ),
            styles["subtitle"],
        ),
    ]

    if include_metadata:
        meta_rows = [
            ["Generated", metadata.get("generated_at")],
            ["Device", f"{name} [{device.address}]"],
            ["Range from", metadata.get("from")],
            ["Range to", metadata.get("to")],
            ["Datasets", ", ".join(metadata.get("datasets", []))],
            [
                "Row counts",
                json.dumps(metadata.get("row_counts", {}), ensure_ascii=False),
            ],
            [
                "Truncated",
                json.dumps(metadata.get("truncated", {}), ensure_ascii=False),
            ],
        ]
        story.append(Paragraph("Export metadata", styles["heading"]))
        meta_table = Table(
            [
                [
                    _pdf_paragraph(label, styles["header"]),
                    _pdf_paragraph(value, styles["cell"]),
                ]
                for label, value in meta_rows
            ],
            colWidths=[available_width * 0.2, available_width * 0.8],
        )
        meta_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c2cf")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef1f5")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(meta_table)

    for dataset in metadata.get("datasets", []):
        rows = data.get(dataset, [])
        story.append(
            Paragraph(
                xml_escape(DATASET_LABELS.get(dataset, dataset)),
                styles["heading"],
            )
        )
        if dataset == "summary":
            summary_row = _flatten_row(rows[0]) if rows else {}
            summary_data = [
                [
                    _pdf_paragraph(label, styles["header"]),
                    _pdf_paragraph(summary_row.get(key), styles["cell"]),
                ]
                for label, key in PDF_SUMMARY_FIELDS
            ]
            table = Table(
                summary_data,
                colWidths=[available_width * 0.22, available_width * 0.78],
            )
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c2cf")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef1f5")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 3),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            story.append(table)
        else:
            story.append(
                _pdf_table(
                    dataset,
                    rows,
                    available_width=available_width,
                    styles=styles,
                )
            )
        story.append(Spacer(1, 8))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"SSC export {name}",
        author="SSC Recorder",
    )

    def footer(canvas, doc) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(margin, 18, f"SSC Recorder · {device.address}")
        canvas.drawRightString(page_size[0] - margin, 18, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def build_export(
    session: Session,
    device: DeviceSummary,
    *,
    from_at: dt.datetime,
    to_at: dt.datetime,
    datasets: list[str],
    export_format: str,
    delimiter_name: str,
    pretty: bool,
    include_metadata: bool,
    bom: bool,
    max_rows: int,
    pdf_page_size: str = "a4",
    pdf_orientation: str = "landscape",
) -> tuple[bytes, str, str]:
    """Return ``(content, media_type, filename)`` for the requested export."""
    data, metadata = collect_export_data(
        session,
        device,
        from_at=from_at,
        to_at=to_at,
        datasets=datasets,
        max_rows=max_rows,
    )
    timestamp = utcnow().strftime("%Y%m%d-%H%M%S")
    safe_name = _safe_name(device.display_name or device.address)
    base = f"ssc-{device.id}-{safe_name}-{timestamp}"

    if export_format == "json":
        payload = (
            {"metadata": metadata, "datasets": data}
            if include_metadata
            else data
        )
        return _json_bytes(payload, pretty=pretty), "application/json", f"{base}.json"

    if export_format == "xlsx":
        content = _xlsx_bytes(
            data, metadata, include_metadata=include_metadata
        )
        return (
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{base}.xlsx",
        )

    if export_format == "pdf":
        if pdf_page_size not in {"a4", "letter"}:
            raise ValueError("pdf_page_size must be a4 or letter")
        if pdf_orientation not in {"portrait", "landscape"}:
            raise ValueError("pdf_orientation must be portrait or landscape")
        content = _pdf_bytes(
            data,
            metadata,
            device,
            page_size_name=pdf_page_size,
            orientation=pdf_orientation,
            include_metadata=include_metadata,
        )
        return content, "application/pdf", f"{base}.pdf"

    if export_format != "csv":
        raise ValueError("format must be csv, json, xlsx or pdf")
    if delimiter_name not in DELIMITERS:
        raise ValueError("delimiter must be comma, semicolon or tab")
    delimiter = DELIMITERS[delimiter_name]

    if len(datasets) == 1:
        dataset = datasets[0]
        content = _csv_bytes(
            dataset,
            data[dataset],
            delimiter=delimiter,
            bom=bom,
        )
        return content, "text/csv; charset=utf-8", f"{base}-{dataset}.csv"

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for dataset in datasets:
            zipped.writestr(
                f"{dataset}.csv",
                _csv_bytes(
                    dataset,
                    data[dataset],
                    delimiter=delimiter,
                    bom=bom,
                ),
            )
        if include_metadata:
            zipped.writestr(
                "metadata.json",
                _json_bytes(metadata, pretty=True),
            )
    return archive.getvalue(), "application/zip", f"{base}.zip"