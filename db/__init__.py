"""
Database repository package, SQLAlchemy 2.0 ORM models/session, and schema migration runner.
Built on shared `hvl_common.db` for SQLAlchemy `QueuePool` connection pooling, WAL mode, and migrations.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from hvl_common.db import get_db_connection, get_engine, run_migrations

from routes.helpers import DB_PATH

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run_project_migrations(db_path: Optional[Union[str, Path]] = None) -> List[str]:
    """
    Executes pending schema migrations against the target database (or active DB_PATH)
    and idempotently migrates any legacy `family_encrypted_store` domain blobs into
    normalized relational tables.
    Returns list of newly applied migration file names.
    """
    target = db_path if db_path is not None else DB_PATH
    applied = run_migrations(target, MIGRATIONS_DIR)
    try:
        from db import data_migration

        data_migration.migrate_encrypted_store_to_relational(target)
    except Exception:
        pass
    return applied


from db import (
    accounts,
    bugs,
    compensation,
    conversations,
    data_migration,
    education,
    equity,
    estate,
    families,
    gifting,
    models,
    notifications,
    philanthropy,
    scenarios,
    schemas,
    session,
    store,
    telemetry,
    transcripts,
    types,
)
from db.session import get_orm_session

__all__ = [
    "get_db_connection",
    "get_engine",
    "get_orm_session",
    "run_migrations",
    "run_project_migrations",
    "MIGRATIONS_DIR",
    "accounts",
    "bugs",
    "compensation",
    "conversations",
    "data_migration",
    "education",
    "equity",
    "estate",
    "families",
    "gifting",
    "models",
    "notifications",
    "philanthropy",
    "scenarios",
    "schemas",
    "session",
    "store",
    "telemetry",
    "transcripts",
    "types",
]
