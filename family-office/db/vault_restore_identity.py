"""
Identity handling for `.fovault` restores.

An uploaded archive is untrusted input. Its `users` rows may carry any `user_id`, `email_hash`, `role` or
`family_id`, so none of them is ever believed. A restore keeps the household members' names and relationships
as login-less rows under freshly allocated ids, and the only logins that survive are the restoring household's
own verified members, captured from the live directory BEFORE the archive is copied in.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

from hvl_common.db import get_db_connection

from db.auth_directory_sync import write_users_guarded
from db.vault_archive_schema import quote_ident

logger = logging.getLogger(__name__)

_OWNER_RELATIONSHIPS = ("primary", "owner", "")


def peer_global_db(db_path: Path) -> Optional[Path]:
    """The `global.db` beside a per-household DB (`<universe>/families/<id>.db`), if there is one."""
    if db_path.parent.name == "families":
        return db_path.parent.parent / "global.db"
    return None


def collect_verified_members(global_db: Path, family_db: Path, family_id: int) -> list[dict[str, Any]]:
    """
    The restoring household's existing login rows (`users` with an `email_hash`) as recorded in the live
    directory (`global.db` first, then the household DB). Must run before the archive is copied over `family_db`.
    """
    for candidate in (global_db, family_db):
        if not candidate.exists():
            continue
        try:
            with get_db_connection(candidate) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM users WHERE family_id = ? AND email_hash IS NOT NULL AND email_hash != ''",
                    (int(family_id),),
                ).fetchall()
        except sqlite3.Error:
            continue
        if rows:
            return [dict(r) for r in rows]
    return []


def _max_user_id(db_path: Optional[Path]) -> int:
    if db_path is None or not db_path.exists():
        return 0
    try:
        with get_db_connection(db_path) as conn:
            return int(conn.execute("SELECT COALESCE(MAX(user_id), 0) FROM users").fetchone()[0])
    except sqlite3.Error:
        return 0


def _user_reference_columns(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(table, column) pairs that foreign-key to `users.user_id`, discovered from the schema."""
    refs: list[tuple[str, str]] = []
    for (tbl,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        for fk in conn.execute("PRAGMA foreign_key_list(" + quote_ident(tbl) + ")").fetchall():
            if fk[2] == "users" and fk[4] == "user_id":
                refs.append((tbl, fk[3]))
    return refs


def strip_archive_identities(
    conn: sqlite3.Connection,
    family_id: int,
    *,
    global_db: Optional[Path],
    reserved_user_ids: tuple[int, ...] = (),
    fold_owner_into: Optional[int] = None,
) -> None:
    """
    Re-keys every `users` row of the restored household to a new id above anything in the directory and wipes
    its login material (`email`, `email_hash`, `pending_fek_enc`, `google_vault_synced`) and archive role (viewer). When `fold_owner_into`
    is given (the restoring caller's real `user_id`), the archive's owner rows are removed and everything that
    referenced them (compensation, tuition, account beneficiaries) is repointed at the caller instead.
    """
    fid = int(family_id)
    conn.commit()  # PRAGMA foreign_keys is a no-op inside a transaction
    fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        _rekey_and_wipe(conn, fid, global_db, reserved_user_ids, fold_owner_into)
        conn.commit()
    finally:
        if fk_was_on:
            conn.execute("PRAGMA foreign_keys = ON")


def _rekey_and_wipe(
    conn: sqlite3.Connection,
    fid: int,
    global_db: Optional[Path],
    reserved_user_ids: tuple[int, ...],
    fold_owner_into: Optional[int],
) -> None:
    local_max = int(conn.execute("SELECT COALESCE(MAX(user_id), 0) FROM users").fetchone()[0])
    next_id = max([local_max, _max_user_id(global_db), *reserved_user_ids]) + 1
    refs = _user_reference_columns(conn)

    def _repoint(old: int, new: int) -> None:
        for tbl, col in refs:
            conn.execute(
                "UPDATE " + quote_ident(tbl) + " SET " + quote_ident(col) + " = ? WHERE " + quote_ident(col) + " = ?",
                (new, old),
            )

    for uid, rel in conn.execute("SELECT user_id, relationship FROM users WHERE family_id = ?", (fid,)).fetchall():
        if fold_owner_into is not None and str(rel or "").lower() in _OWNER_RELATIONSHIPS:
            _repoint(uid, int(fold_owner_into))
            conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
            continue
        conn.execute(
            "UPDATE users SET user_id = ?, email = NULL, email_hash = NULL, pending_fek_enc = NULL, "
            "google_vault_synced = 0, role = 'viewer' WHERE user_id = ?",
            (next_id, uid),
        )
        _repoint(uid, next_id)
        next_id += 1


def reinstate_verified_members(conn: sqlite3.Connection, family_id: int, members: list[dict[str, Any]]) -> None:
    """Writes the household's pre-restore verified members back, replacing any row with their id or login."""
    if not members:
        return
    cols = {c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()}
    for member in members:
        row = dict(member)
        row["family_id"] = int(family_id)
        keys = [k for k in row if k in cols]
        conn.execute(
            "DELETE FROM users WHERE user_id = ? OR (email_hash = ? AND email_hash != '')",
            (row["user_id"], row.get("email_hash") or ""),
        )
        conn.execute(
            "INSERT INTO users (" + ", ".join(quote_ident(k) for k in keys) + ") VALUES ("
            + ", ".join("?" for _ in keys) + ")",
            [row[k] for k in keys],
        )
    conn.commit()


def quarantine_restored_users(
    db_path: Path,
    family_id: int,
    verified_members: Optional[list[dict[str, Any]]] = None,
    global_db: Optional[Path] = None,
) -> None:
    """
    Makes the `users` table of a freshly restored household safe: archive identities are wiped and re-keyed,
    and only `verified_members` (captured before the restore) come back as logins. Idempotent per restore.
    """
    members = list(verified_members or [])
    peer = global_db if global_db is not None else peer_global_db(Path(db_path))
    with get_db_connection(db_path) as conn:
        strip_archive_identities(
            conn,
            family_id,
            global_db=peer,
            reserved_user_ids=tuple(int(m["user_id"]) for m in members),
            fold_owner_into=int(members[0]["user_id"]) if members else None,
        )
        reinstate_verified_members(conn, family_id, members)


def sync_restored_household_to_global(
    global_db: Path, family_db: Path, family_id: int, verified_members: list[dict[str, Any]]
) -> None:
    """
    Mirrors the restored household's `families`, `users` and `account_roles` rows into `global.db`.

    Rule: a restore may only write rows of the restoring `family_id`; a `users` row may carry a login only if
    its `email_hash` is one of `verified_members` (the household's own members before the restore); no row
    belonging to another household is touched and `email_hash` is never changed on conflict.
    """
    from db.session import _upsert_sql

    fid = int(family_id)
    allowed = {str(m.get("email_hash")) for m in verified_members if m.get("email_hash")}
    with get_db_connection(family_db) as sconn, get_db_connection(global_db) as gconn:
        for tbl, conflict in (("families", ("family_id",)), ("users", ("user_id",)), ("account_roles", ("family_id", "monarch_account_id"))):
            qtbl = quote_ident(tbl)
            rows = sconn.execute("SELECT * FROM " + qtbl + " WHERE family_id = ?", (fid,)).fetchall()
            s_cols = [c[1] for c in sconn.execute("PRAGMA table_info(" + qtbl + ")").fetchall()]
            g_cols = {c[1] for c in gconn.execute("PRAGMA table_info(" + qtbl + ")").fetchall()}
            shared = [c for c in s_cols if c in g_cols and (tbl != "account_roles" or c != "role_id")]
            picked = [tuple(r[s_cols.index(c)] for c in shared) for r in rows]
            if tbl == "users":
                gconn.execute("DELETE FROM users WHERE family_id = ?", (fid,))
                write_users_guarded(gconn, shared, picked, fid, preserve_identity=True, allowed_email_hashes=allowed)
                continue
            if tbl == "account_roles":
                gconn.execute("DELETE FROM account_roles WHERE family_id = ?", (fid,))
            for values in picked:
                gconn.execute(_upsert_sql(tbl, shared, conflict), values)
        gconn.commit()
