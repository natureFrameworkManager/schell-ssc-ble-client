"""Read-only database access for the web service."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine


def database_path(database: str) -> Path | None:
    """Return the on-disk path for a file database, or ``None`` for a URL."""
    if database.startswith("sqlite:///"):
        return Path(database[len("sqlite:///") :])
    if ":" not in database:
        return Path(database)
    return None


def create_readonly_engine(database: str) -> Engine:
    """Create an engine whose SQL connections are query-only.

    The connection is intentionally not switched to SQLite URI ``mode=ro``:
    WAL databases may require access to the ``-shm`` index even for read-only
    work.  ``PRAGMA query_only=ON`` prevents application-level writes while
    leaving WAL access functional.
    """
    path = database_path(database)
    url = f"sqlite:///{path}" if path is not None else database
    engine = create_engine(
        url,
        connect_args={"timeout": 30, "check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _readonly_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA query_only=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def ensure_database_exists(database: str) -> None:
    path = database_path(database)
    if path is not None and not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Recorder database is not available: {path}",
        )


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a read-only SQLModel session."""
    config = request.app.state.config
    ensure_database_exists(config.database)
    engine: Engine = request.app.state.engine
    with Session(engine) as session:
        yield session


def schema_version(engine: Engine) -> int | None:
    try:
        with engine.connect() as connection:
            value = connection.exec_driver_sql("PRAGMA user_version").scalar()
            return int(value) if value is not None else None
    except Exception:  # noqa: BLE001 - reported by the health endpoint
        return None


def table_names(engine: Engine) -> set[str]:
    try:
        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return {str(row[0]) for row in rows}
    except Exception:  # noqa: BLE001
        return set()