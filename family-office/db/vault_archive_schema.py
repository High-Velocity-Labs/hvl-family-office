"""
Schema allowlist for uploaded `.fovault` archives.

Table and column names inside an uploaded SQLite file are attacker-controlled and are later spliced into
SQL (`PRAGMA table_info`, `DELETE FROM`, `UPDATE`), so an archive is refused unless every table is a known
schema table, every column is a plain identifier, and it carries no triggers or views.
"""

from __future__ import annotations

import re
import sqlite3

ALLOWED_ARCHIVE_TABLES = frozenset(
    {
        "_schema_migrations",
        "account_roles",
        "advisor_conversations",
        "advisor_messages",
        "alembic_version",
        "bug_reports",
        "compensation",
        "download_events",
        "encrypted_store",
        "equity_companies",
        "equity_grants",
        "estate_profiles",
        "families",
        "family_domain_versions",
        "family_encrypted_store",
        "family_id_allocator",
        "family_state_versions",
        "fmv_history",
        "forecast_events",
        "forecast_scenarios",
        "forecast_settings",
        "gift_recipients",
        "gifts",
        "household_notifications",
        "household_profile",
        "invite_tokens",
        "monarch_accounts",
        "monarch_holdings",
        "philanthropy_budgets",
        "philanthropy_donations",
        "portal_telemetry_events",
        "push_subscriptions",
        "sandbox_leases",
        "tax_transcript_meta",
        "tax_transcript_records",
        "tuition",
        "tuition_year_records",
        "users",
    }
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    """Returns `name` double-quoted for SQL, or raises `ValueError` if it is not a plain identifier."""
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier in vault archive: {name!r}")
    return '"' + name + '"'


def archive_schema_error(conn: sqlite3.Connection) -> str:
    """Returns a refusal message if the archive's schema is not the known HVL schema, else an empty string."""
    for obj_type, name in conn.execute("SELECT type, name FROM sqlite_master").fetchall():
        if obj_type in ("trigger", "view"):
            return f"Uploaded file contains a {obj_type}, which a vault backup never does."
        if obj_type == "table":
            if name.startswith("sqlite_"):
                continue
            if name not in ALLOWED_ARCHIVE_TABLES:
                return "Uploaded file contains a table that is not part of the HVL Family Office schema."
            for col in conn.execute("PRAGMA table_info(" + quote_ident(name) + ")").fetchall():
                if not _IDENT_RE.match(str(col[1])):
                    return "Uploaded file contains an invalid column name."
    return ""
