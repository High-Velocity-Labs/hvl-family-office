"""
Repository functions for User entities and auth directory queries.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from hvl_common.db import get_db_connection

from db.auth_directory_sync import write_users_guarded


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


def _local_household_db(global_db: Path) -> Optional[Path]:
    """Local Desktop only: the single local household's DB beside `global.db`; never any other household."""
    import config

    if not config.is_local_mode() or global_db.name != "global.db":
        return None
    fam_db = global_db.parent / "families" / f"{config.LOCAL_HOUSEHOLD_FAMILY_ID}.db"
    return fam_db if fam_db.exists() else None


def _self_heal_local_household_auth(global_db: Path, family_db: Path) -> None:
    """
    Local Desktop only: restores the local household's `families`, `users` and `account_roles` rows into
    `global_db` from its own DB. Writes only the local `family_id`, through the guarded writer (no other
    household's row is touched, `email_hash` is never changed on conflict).
    """
    import config
    from db.session import _upsert_sql

    fid = int(config.LOCAL_HOUSEHOLD_FAMILY_ID)
    try:
        with get_db_connection(family_db) as fconn, get_db_connection(global_db) as gconn:
            f_row = fconn.execute("SELECT * FROM families WHERE family_id = ?", (fid,)).fetchone()
            if f_row:
                fcols = [c[1] for c in fconn.execute("PRAGMA table_info(families)").fetchall()]
                gconn.execute(_upsert_sql("families", fcols, ("family_id",)), tuple(f_row))

            u_rows = fconn.execute("SELECT * FROM users WHERE family_id = ?", (fid,)).fetchall()
            if u_rows:
                ucols = [c[1] for c in fconn.execute("PRAGMA table_info(users)").fetchall()]
                write_users_guarded(gconn, ucols, [tuple(r) for r in u_rows], fid, preserve_identity=True)

            ar_rows = fconn.execute("SELECT * FROM account_roles WHERE family_id = ?", (fid,)).fetchall()
            if ar_rows:
                ar_cols = [c[1] for c in fconn.execute("PRAGMA table_info(account_roles)").fetchall()]
                upsert_cols = [c for c in ar_cols if c != "role_id"]
                col_indices = [ar_cols.index(c) for c in upsert_cols]
                gconn.executemany(
                    _upsert_sql("account_roles", upsert_cols, ("family_id", "monarch_account_id")),
                    [tuple(r[i] for i in col_indices) for r in ar_rows],
                )
            gconn.commit()
    except sqlite3.Error:
        pass


def get_user_by_email_hash(
    db_path: Union[str, Path],
    email_hash: Union[str, Sequence[str]],
) -> Optional[Dict[str, Any]]:
    """
    Retrieves the user row matching `email_hash` from `db_path` only. `email_hash` is one hash or the ordered
    forms from `security.email_hash_candidates` (current keyed hash first); a row found under a later (legacy
    unsalted) form is rewritten to the first one, so each login migrates its own row.

    The auth directory is the sole source of logins: a user row found in some per-household DB is never copied
    into `global.db` (that would let any household DB mint a global login). The one exception is Local
    Desktop mode, which re-syncs its single local household's own rows into `global.db`.
    """
    path = Path(db_path)
    hashes = [email_hash] if isinstance(email_hash, str) else list(email_hash)
    hashes = [h for h in hashes if h]
    if not path.exists() or not hashes:
        return None
    query = "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE email_hash = ?"
    for attempt in (0, 1):
        try:
            with get_db_connection(path) as conn:
                conn.row_factory = sqlite3.Row
                for rank, candidate in enumerate(hashes):
                    row = conn.execute(query, (candidate,)).fetchone()
                    if row is None:
                        continue
                    if rank > 0:
                        conn.execute(
                            "UPDATE users SET email_hash = ? WHERE user_id = ? AND email_hash = ?",
                            (hashes[0], row["user_id"], candidate),
                        )
                        conn.commit()
                    return dict(row)
        except sqlite3.Error:
            pass
        local_db = _local_household_db(path) if attempt == 0 else None
        if local_db is None:
            return None
        _self_heal_local_household_auth(path, local_db)
    return None


def get_all_users_with_email(
    db_path: Union[str, Path],
) -> List[Dict[str, Any]]:
    """Retrieves all users having non-null and non-empty email addresses (Local Desktop re-syncs its own household first if empty)."""
    path = Path(db_path)
    if not path.exists():
        return []
    query = "SELECT user_id, family_id, name, email, role, pending_fek_enc, google_vault_synced FROM users WHERE email IS NOT NULL AND email != ''"
    for attempt in (0, 1):
        try:
            with get_db_connection(path) as conn:
                conn.row_factory = sqlite3.Row
                rows = [dict(r) for r in conn.execute(query).fetchall()]
                if rows:
                    return rows
        except sqlite3.Error:
            pass
        local_db = _local_household_db(path) if attempt == 0 else None
        if local_db is None:
            return []
        _self_heal_local_household_auth(path, local_db)
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
