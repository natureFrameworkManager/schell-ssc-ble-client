"""SQLite engine setup for the recorder database."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, create_engine

from ssc.db import models as _models  # noqa: F401 - register table metadata

SCHEMA_VERSION = 1


def create_db_engine(path: str | Path, *, echo: bool = False) -> Engine:
    """Create a SQLite engine and apply the recorder PRAGMAs.

    ``path`` may also be a SQLAlchemy URL such as ``sqlite://`` (used by
    tooling and smoke tests).
    """
    if isinstance(path, Path) or ":" not in str(path):
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{database_path}"
    else:
        url = str(path)

    engine = create_engine(url, echo=echo, connect_args={"timeout": 30})
    _install_pragmas(engine)
    return engine


def _install_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA temp_store=MEMORY")
        finally:
            cursor.close()


def init_db(engine: Engine) -> None:
    """Create all tables if they do not exist yet."""
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")