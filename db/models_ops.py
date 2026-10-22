"""
Operational, Telemetry, Sandbox Lease, and Bug Report SQLAlchemy 2.0 ORM Models for HVL Family Office.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Float, Index, Integer, Text, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable

from db.models_core import Base


class BugReport(Base):
    __tablename__ = "bug_reports"
    __table_args__ = (
        Index("idx_bug_reports_created", text("created_at DESC")),
        Index("idx_bug_reports_status", "status"),
        Index("idx_bug_reports_project", "project"),
    )

    bug_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(
        Text, nullable=False, default="finances", server_default=text("'finances'")
    )
    app_version: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="open", server_default=text("'open'")
    )
    universe: Mapped[str] = mapped_column(
        Text, nullable=False, default="public", server_default=text("'public'")
    )
    family_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    user_role: Mapped[str] = mapped_column(
        Text, nullable=False, default="viewer", server_default=text("'viewer'")
    )
    user_ref: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    support_access_enabled: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    pane: Mapped[str] = mapped_column(
        Text, nullable=False, default="overview", server_default=text("'overview'")
    )
    category: Mapped[str] = mapped_column(
        Text, nullable=False, default="math", server_default=text("'math'")
    )
    scrubbed_description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    scrubbed_followup: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    ai_explanation: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    suspected_module: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    invariant_summary: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    scale_factor: Mapped[Optional[float]] = mapped_column(
        Float, default=1.0, server_default=text("1.0")
    )
    anonymization_mode: Mapped[Optional[str]] = mapped_column(
        Text, default="scaled", server_default=text("'scaled'")
    )
    sanitized_snapshot_json: Mapped[Optional[str]] = mapped_column(
        Text, default="{}", server_default=text("'{}'")
    )
    admin_notes: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )


class SandboxLease(Base):
    __tablename__ = "sandbox_leases"
    __table_args__ = (Index("idx_sandbox_leases_exp", "expires_at"),)

    family_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    extended_7d: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    seed_mode: Mapped[Optional[str]] = mapped_column(
        Text, default="blank", server_default=text("'blank'")
    )
    session_hash: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )


class DownloadEvent(Base):
    __tablename__ = "download_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    app_version: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    referrer: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class PortalTelemetryEvent(Base):
    __tablename__ = "portal_telemetry_events"
    __table_args__ = (
        Index("idx_portal_telemetry_created", "created_at"),
        Index("idx_portal_telemetry_uni_evt", "universe", "event_type"),
        Index("idx_portal_telemetry_tab", "universe", "tab"),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    universe: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    feature_key: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    session_hash: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    meta_json: Mapped[Optional[str]] = mapped_column(
        Text, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    tab: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    action: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )
    modal: Mapped[Optional[str]] = mapped_column(
        Text, default="", server_default=text("''")
    )


def ensure_orm_table_on_conn(conn: Any, model_cls: Any) -> None:
    """Compiles and executes SQLAlchemy 2.0 `CreateTable`/`CreateIndex` statements on `conn`."""
    dialect = sqlite.dialect()
    table = model_cls.__table__
    conn.execute(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)))
    for idx in table.indexes:
        conn.execute(str(CreateIndex(idx, if_not_exists=True).compile(dialect=dialect)))


__all__ = [
    "BugReport",
    "SandboxLease",
    "DownloadEvent",
    "PortalTelemetryEvent",
    "ensure_orm_table_on_conn",
]
