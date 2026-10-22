"""
Repository layer for ephemeral sandbox household leases, row inspection, and SQLite backup operations.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any

from hvl_common.db import get_db_connection

logger = logging.getLogger(__name__)

_SANDBOX_DATA_TABLES = (
    "monarch_accounts",
    "monarch_holdings",
    "equity_companies",
    "equity_grants",
    "compensation",
    "forecast_scenarios",
    "family_encrypted_store",
    "estate_profiles",
    "philanthropy_donations",
    "gift_recipients",
)


def ensure_sandbox_leases_table(conn: Any) -> None:
    """Ensures the `sandbox_leases` tracking table exists in global_sandbox.db."""
    from db.schemas import SANDBOX_LEASES_DDL
    conn.execute(SANDBOX_LEASES_DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sandbox_leases_exp ON sandbox_leases (expires_at)")


def list_all_sandbox_leases(glob_db: Path) -> list[Any]:
    """Returns `(family_id, created_at, expires_at, extended_7d)` rows for all tracked sandbox leases."""
    try:
        with get_db_connection(glob_db) as conn:
            ensure_sandbox_leases_table(conn)
            return conn.execute(
                "SELECT family_id, created_at, expires_at, extended_7d FROM sandbox_leases"
            ).fetchall()
    except Exception as exc:
        logger.warning("Error querying sandbox leases: %s", exc)
        return []


def count_active_sandbox_leases(glob_db: Path) -> int:
    """Returns the count of active sandbox leases in `glob_db`."""
    try:
        with get_db_connection(glob_db) as conn:
            ensure_sandbox_leases_table(conn)
            row = conn.execute("SELECT COUNT(*) FROM sandbox_leases").fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def has_sandbox_user_data_in_db(fam_db: Path, family_id: int) -> bool:
    """Returns True if the sandbox household database contains user-entered domain records."""
    if not fam_db.exists():
        return False
    try:
        with get_db_connection(fam_db) as conn:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            total = 0
            for tbl in _SANDBOX_DATA_TABLES:
                if tbl in tables:
                    try:
                        r = conn.execute(f'SELECT COUNT(*) FROM "{tbl}" WHERE family_id = ?', (family_id,)).fetchone()
                        total += int(r[0] or 0) if r else 0
                    except Exception:
                        pass
            if "users" in tables:
                try:
                    u_rows = conn.execute("SELECT name FROM users WHERE family_id = ?", (family_id,)).fetchall()
                    if len(u_rows) > 1:
                        total += len(u_rows)
                    elif len(u_rows) == 1 and str(u_rows[0][0] or "") not in ("", "Sandbox Guest"):
                        total += 1
                except Exception:
                    pass
            if "household_profile" in tables:
                try:
                    hp = conn.execute(
                        "SELECT annual_spending, annual_savings, assumptions_json FROM household_profile WHERE family_id = ?",
                        (family_id,),
                    ).fetchone()
                    if hp and (
                        float(hp[0] or 0) > 0
                        or float(hp[1] or 0) > 0
                        or str(hp[2] or "{}") not in ("", "{}")
                    ):
                        total += 1
                except Exception:
                    pass
            if "families" in tables:
                try:
                    fn = conn.execute("SELECT name FROM families WHERE family_id = ?", (family_id,)).fetchone()
                    if fn and str(fn[0] or "") not in ("", "Sandbox Household", "Family Office"):
                        total += 1
                except Exception:
                    pass
            return total > 0
    except Exception:
        return False


def get_sandbox_lease_row(glob_db: Path, family_id: int) -> Any | None:
    """Fetches `(created_at, expires_at, extended_7d, seed_mode)` for `family_id` or None."""
    if not glob_db.exists():
        return None
    try:
        with get_db_connection(glob_db) as conn:
            ensure_sandbox_leases_table(conn)
            return conn.execute(
                "SELECT created_at, expires_at, extended_7d, seed_mode FROM sandbox_leases WHERE family_id = ?",
                (family_id,),
            ).fetchone()
    except Exception:
        return None


def allocate_unique_sandbox_fid(glob_db: Path) -> int:
    """Generates a unique 6-digit sandbox `family_id` not currently leased in `glob_db`."""
    fid = secrets.randbelow(899999) + 100000
    with get_db_connection(glob_db) as conn:
        ensure_sandbox_leases_table(conn)
        while conn.execute("SELECT 1 FROM sandbox_leases WHERE family_id = ?", (fid,)).fetchone():
            fid = secrets.randbelow(899999) + 100000
    return fid


def insert_sandbox_household_and_lease(
    glob_db: Path,
    fam_db: Path,
    family_id: int,
    now_ts: int,
    expires_at: int,
    seed_mode: str,
    session_hash: str,
    household_name: str = "Sandbox Household",
) -> None:
    """Inserts sandbox household/owner rows into `glob_db` and `fam_db` plus lease row in `glob_db`."""
    for target_db in (glob_db, fam_db):
        with get_db_connection(target_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (?, ?, NULL, 0)",
                (family_id, household_name),
            )
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, family_id, role, name, email) VALUES (?, ?, 'owner', 'Sandbox Guest', '')",
                (family_id, family_id),
            )
            if target_db == glob_db:
                ensure_sandbox_leases_table(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO sandbox_leases (family_id, created_at, expires_at, extended_7d, seed_mode, session_hash) VALUES (?, ?, ?, 0, ?, ?)",
                    (family_id, now_ts, expires_at, seed_mode, session_hash),
                )
            conn.commit()


def extend_sandbox_lease_in_db(glob_db: Path, family_id: int, new_expires_at: int) -> None:
    """Extends an existing sandbox lease in `glob_db`, raising `ValueError` if not found."""
    with get_db_connection(glob_db) as conn:
        ensure_sandbox_leases_table(conn)
        row = conn.execute("SELECT 1 FROM sandbox_leases WHERE family_id = ?", (family_id,)).fetchone()
        if not row:
            raise ValueError("Sandbox lease not found or already expired.")
        conn.execute(
            "UPDATE sandbox_leases SET expires_at = ?, extended_7d = 1 WHERE family_id = ?",
            (new_expires_at, family_id),
        )
        conn.commit()


def delete_sandbox_lease_in_db(glob_db: Path, family_id: int) -> None:
    """Deletes the sandbox lease row for `family_id` from `glob_db`."""
    try:
        with get_db_connection(glob_db) as conn:
            ensure_sandbox_leases_table(conn)
            conn.execute("DELETE FROM sandbox_leases WHERE family_id = ?", (family_id,))
            conn.commit()
    except Exception:
        pass


def copy_fovault_to_sandbox_db(src_path: Path, dst_path: Path) -> None:
    """Copies SQLite database pages from `src_path` into `dst_path` using SQLite backup API."""
    with get_db_connection(src_path) as s_conn, get_db_connection(dst_path) as d_conn:
        s_conn.backup(d_conn)


def register_restored_sandbox_in_global_db(
    glob_db: Path,
    family_id: int,
    now_ts: int,
    expires_at: int,
    session_hash: str,
) -> None:
    """Registers a restored `.fovault` sandbox household and lease in `glob_db`."""
    with get_db_connection(glob_db) as gconn:
        ensure_sandbox_leases_table(gconn)
        gconn.execute(
            "INSERT OR REPLACE INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (?, ?, NULL, 0)",
            (family_id, "Restored Sandbox Household"),
        )
        gconn.execute(
            "INSERT OR REPLACE INTO users (user_id, family_id, role, name, email) VALUES (?, ?, 'owner', 'Sandbox Guest', '')",
            (family_id, family_id),
        )
        gconn.execute(
            "INSERT OR REPLACE INTO sandbox_leases (family_id, created_at, expires_at, extended_7d, seed_mode, session_hash) VALUES (?, ?, ?, 0, 'fovault_restore', ?)",
            (family_id, now_ts, expires_at, session_hash),
        )
        gconn.commit()
