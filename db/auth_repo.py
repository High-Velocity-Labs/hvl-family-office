"""
Repository functions for authentication, vault sync, database backups,
and isolated queries extracted from auth and engine modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union

from hvl_common.db import get_db_connection
from db.users import (
    clear_pending_vault_and_sync,
    get_all_users_with_email,
    get_user_by_email_hash,
    get_user_by_id,
)

__all__ = [
    "backup_sqlite_database",
    "clear_pending_vault_and_sync",
    "get_all_users_with_email",
    "get_equity_company_fmvs",
    "get_family_children_for_estate",
    "get_household_profile_for_estate",
    "get_user_by_email_hash",
    "get_user_by_id",
]


def backup_sqlite_database(
    src_path: Union[str, Path],
    dst_path: Union[str, Path],
) -> None:
    """Creates a point-in-time online backup of a SQLite database."""
    with sqlite3.connect(str(src_path)) as src_conn:
        with sqlite3.connect(str(dst_path)) as dst_conn:
            src_conn.backup(dst_conn)


def get_equity_company_fmvs(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[int, float]:
    """Returns mapping of company_id to current_fmv for a household."""
    if not family_id:
        return {}
    if db_path is None:
        from equity.models import get_db_path
        path = get_db_path()
    else:
        path = Path(db_path)
    if not path.exists():
        return {}
    fmvs: Dict[int, float] = {}
    try:
        with get_db_connection(path) as conn:
            cur = conn.execute(
                "SELECT company_id, current_fmv FROM equity_companies WHERE family_id = ?",
                (family_id,),
            )
            for r in cur.fetchall():
                if r[0] is not None and r[1] is not None:
                    fmvs[int(r[0])] = float(r[1])
    except Exception:
        pass
    return fmvs


def get_household_profile_for_estate(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves household state, filing_status, and assumptions_json for estate engine."""
    if not family_id:
        return None
    path = Path(db_path) if db_path is not None else None
    if path is None or not path.exists():
        from db.session import resolve_db_path
        path = resolve_db_path(None, family_id=family_id)
    if not path.exists():
        return None
    try:
        with get_db_connection(path) as conn:
            row = conn.execute(
                "SELECT state, filing_status, assumptions_json FROM household_profile WHERE family_id = ?",
                (family_id,),
            ).fetchone()
            if row:
                return {
                    "state": str(row[0] or "WA"),
                    "filing_status": str(row[1] or "MFJ"),
                    "assumptions_json": row[2],
                }
    except Exception:
        pass
    return None


def get_family_children_for_estate(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Retrieves children members for estate calculations."""
    if not family_id:
        return []
    path = Path(db_path) if db_path is not None else None
    if path is None or not path.exists():
        from db.session import resolve_db_path
        path = resolve_db_path(None, family_id=family_id)
    if not path.exists():
        return []
    import security
    children = []
    try:
        with get_db_connection(path) as conn:
            cur = conn.execute(
                "SELECT user_id, name, relationship, birthdate FROM users WHERE family_id = ?",
                (family_id,),
            )
            for urow in cur.fetchall():
                rel = str(urow[2] or "").lower()
                if rel == "child":
                    c_name = security.decrypt_field(urow[1]) if urow[1] else f"Child {urow[0]}"
                    c_byear = 2015
                    if urow[3]:
                        try:
                            c_byear = int(str(urow[3])[:4])
                        except Exception:
                            pass
                    children.append({
                        "user_id": urow[0],
                        "name": c_name,
                        "birth_year": c_byear,
                        "age": max(0, datetime.now(timezone.utc).year - c_byear),
                    })
    except Exception:
        pass
    return children
