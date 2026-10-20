"""
Repository functions for User entities and auth directory queries.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Union

from hvl_common.db import get_db_connection


def clear_pending_vault_and_sync(
    db_paths: Union[str, Path, Iterable[Union[str, Path]]],
    user_id: int,
    family_id: int,
) -> None:
    """
    Clears pending_fek_enc and sets google_vault_synced = 1 for a user,
    and nulls encryption_key_enc on families when support access is disabled.
    """
    if isinstance(db_paths, (str, Path)):
        paths = [Path(db_paths)]
    else:
        paths = [Path(p) for p in db_paths]

    for p in paths:
        if not p.exists():
            continue
        try:
            with get_db_connection(p) as conn:
                conn.execute(
                    "UPDATE users SET pending_fek_enc = NULL, google_vault_synced = 1 WHERE user_id = ?",
                    (user_id,),
                )
                conn.execute(
                    "UPDATE families SET encryption_key_enc = NULL WHERE family_id = ? AND (support_access_enabled IS NULL OR support_access_enabled = 0)",
                    (family_id,),
                )
                conn.commit()
        except Exception:
            pass


def _self_heal_global_auth_from_family_db(global_db: Path, family_db: Path, family_id: int) -> None:
    """Restores missing `families`, `users`, and `account_roles` rows for `family_id` from `family_db` into `global_db`."""
    from db.session import _upsert_sql

    try:
        with get_db_connection(family_db) as fconn, get_db_connection(global_db) as gconn:
            f_row = fconn.execute("SELECT * FROM families WHERE family_id = ?", (family_id,)).fetchone()
            if f_row:
                fcols = [c[1] for c in fconn.execute("PRAGMA table_info(families)").fetchall()]
                gconn.execute(_upsert_sql("families", fcols, ("family_id",)), tuple(f_row))

            u_rows = fconn.execute("SELECT * FROM users WHERE family_id = ?", (family_id,)).fetchall()
            if u_rows:
                ucols = [c[1] for c in fconn.execute("PRAGMA table_info(users)").fetchall()]
                gconn.executemany(_upsert_sql("users", ucols, ("user_id",)), [tuple(r) for r in u_rows])

            ar_rows = fconn.execute("SELECT * FROM account_roles WHERE family_id = ?", (family_id,)).fetchall()
            if ar_rows:
                ar_cols = [c[1] for c in fconn.execute("PRAGMA table_info(account_roles)").fetchall()]
                upsert_cols = [c for c in ar_cols if c != "role_id"]
                col_indices = [ar_cols.index(c) for c in upsert_cols]
                gconn.executemany(
                    _upsert_sql("account_roles", upsert_cols, ("family_id", "monarch_account_id")),
                    [tuple(r[i] for i in col_indices) for r in ar_rows],
                )
            gconn.commit()
    except Exception:
        pass


def get_user_by_email_hash(
    db_path: Union[str, Path],
    email_hash: str,
) -> Optional[Dict[str, Any]]:
    """Retrieves user row matching given email_hash, self-healing global.db from per-family DBs if needed."""
    path = Path(db_path)
    if not path.exists() or not email_hash:
        return None
    try:
        with get_db_connection(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE email_hash = ?",
                (email_hash,),
            ).fetchone()
            if row is not None:
                return dict(row)
    except Exception:
        pass

    fam_dir = path.parent / "families"
    if path.name == "global.db" and fam_dir.is_dir():
        cand_files = sorted(
            [p for p in fam_dir.glob("*.db") if not p.name.endswith("_cache.db") and p.stem.isdigit()],
            key=lambda p: (0 if p.stem == "1" else 1, int(p.stem)),
        )
        for fam_db in cand_files:
            try:
                with get_db_connection(fam_db) as fconn:
                    fconn.row_factory = sqlite3.Row
                    row = fconn.execute(
                        "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE email_hash = ?",
                        (email_hash,),
                    ).fetchone()
                    if row is not None:
                        res = dict(row)
                        _self_heal_global_auth_from_family_db(path, fam_db, int(res.get("family_id") or int(fam_db.stem)))
                        return res
            except Exception:
                continue
    return None


def get_all_users_with_email(
    db_path: Union[str, Path],
) -> List[Dict[str, Any]]:
    """Retrieves all users having non-null and non-empty email addresses."""
    path = Path(db_path)
    if not path.exists():
        return []
    try:
        with get_db_connection(path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE email IS NOT NULL AND email != ''"
            )
            rows = [dict(r) for r in cur.fetchall()]
            if rows:
                return rows
    except Exception:
        pass

    fam1_db = path.parent / "families" / "1.db"
    if path.name == "global.db" and fam1_db.exists():
        _self_heal_global_auth_from_family_db(path, fam1_db, 1)
        try:
            with get_db_connection(path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE email IS NOT NULL AND email != ''"
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
    return []


def get_user_by_id(
    db_path: Union[str, Path],
    user_id: int,
) -> Optional[Dict[str, Any]]:
    """Retrieves user row matching given user_id."""
    path = Path(db_path)
    if not path.exists() or not user_id:
        return None
    try:
        with get_db_connection(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is not None:
                return dict(row)
    except Exception:
        pass
    return None
