"""
Repository layer for ephemeral sandbox household leases, row inspection, and SQLite backup operations.
Delegates core lease table, ID allocation, and lease lifecycle operations to `hvl_common.security.sandbox`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hvl_common.db import get_db_connection
from hvl_common.security.sandbox import (
    allocate_unique_sandbox_id,
    count_active_sandbox_leases as _shared_count_active_sandbox_leases,
    delete_sandbox_lease_row,
    ensure_sandbox_leases_table as _shared_ensure_sandbox_leases_table,
    get_sandbox_lease_row as _shared_get_sandbox_lease_row,
    insert_sandbox_lease,
    list_all_sandbox_leases as _shared_list_all_sandbox_leases,
    update_sandbox_lease_expiry,
)

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
    """Ensures the `sandbox_leases` tracking table exists in `global.db`."""
    _shared_ensure_sandbox_leases_table(conn)


def list_all_sandbox_leases(glob_db: Path) -> list[Any]:
    """Returns `(family_id, created_at, expires_at, extended_7d)` rows for all tracked sandbox leases."""
    return [
        (r["family_id"], r["created_at"], r["expires_at"], r["extended_7d"])
        for r in _shared_list_all_sandbox_leases(glob_db)
    ]


def count_active_sandbox_leases(glob_db: Path) -> int:
    """Returns the count of active sandbox leases in `glob_db`."""
    return _shared_count_active_sandbox_leases(glob_db)


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
    row = _shared_get_sandbox_lease_row(glob_db, family_id)
    if not row:
        return None
    return (row["created_at"], row["expires_at"], row["extended_7d"], row["seed_mode"])


def allocate_unique_sandbox_fid(glob_db: Path) -> int:
    """Generates a unique 6-digit sandbox `family_id` not currently leased in `glob_db`."""
    return allocate_unique_sandbox_id(glob_db, tenant_table="families")


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
            conn.commit()
    insert_sandbox_lease(
        glob_db,
        family_id,
        expires_at=expires_at,
        seed_mode=seed_mode,
        created_at=now_ts,
        session_hash=session_hash,
    )


def extend_sandbox_lease_in_db(glob_db: Path, family_id: int, new_expires_at: int) -> None:
    """Extends an existing sandbox lease in `glob_db`, raising `ValueError` if not found."""
    update_sandbox_lease_expiry(glob_db, family_id, expires_at=new_expires_at, extended_7d=1)


def delete_sandbox_lease_in_db(glob_db: Path, family_id: int) -> None:
    """Deletes the sandbox lease row for `family_id` from `glob_db`."""
    delete_sandbox_lease_row(glob_db, family_id)


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
        gconn.commit()
    insert_sandbox_lease(
        glob_db,
        family_id,
        expires_at=expires_at,
        seed_mode="fovault_restore",
        created_at=now_ts,
        session_hash=session_hash,
    )
