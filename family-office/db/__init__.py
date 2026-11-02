"""
Database repository package, SQLAlchemy 2.0 ORM models/session, and schema migration runner.
Built on shared `hvl_common.db` for SQLAlchemy `QueuePool` connection pooling, WAL mode, and migrations.
"""

from __future__ import annotations

from hvl_common.db import get_db_connection, get_engine

from services.request_context import DB_PATH

from db import (
    account_roles,
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
    household,
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
    "account_roles",
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
    "household",
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
