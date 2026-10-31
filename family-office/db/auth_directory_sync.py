"""
Guarded writes of `users` rows into an auth directory DB (`global.db` or a per-household DB peer).

A directory row is owned by exactly one household. A write may create or refresh rows of the household it is
syncing, but it can never move another household's row (`user_id` collision) nor claim another household's
login (`email_hash` already registered elsewhere), whatever the source DB contains.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Optional

from db.vault_archive_schema import quote_ident


def _guarded_users_upsert_sql(cols: list[str], preserve_identity: bool) -> str:
    frozen = {"user_id", "family_id"} | ({"email_hash"} if preserve_identity else set())
    col_str = ", ".join(quote_ident(c) for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    update_cols = [c for c in cols if c not in frozen]
    head = f'INSERT INTO "users" ({col_str}) VALUES ({placeholders}) ON CONFLICT("user_id") '
    if not update_cols:
        return head + "DO NOTHING"
    update_str = ", ".join(f'{quote_ident(c)} = excluded.{quote_ident(c)}' for c in update_cols)
    return head + f'DO UPDATE SET {update_str} WHERE "users"."family_id" = excluded."family_id"'


def write_users_guarded(
    conn: sqlite3.Connection,
    cols: list[str],
    rows: Iterable[Any],
    family_id: int,
    *,
    preserve_identity: bool = False,
    allowed_email_hashes: Optional[set[str]] = None,
) -> int:
    """
    Upserts `rows` (tuples ordered as `cols`) into `conn.users` for `family_id` only; returns rows written.
    A row is skipped when it names another household, its `user_id` already belongs to another household, or
    its `email_hash` is registered to another household. `preserve_identity` also freezes `email_hash` on
    conflict; `allowed_email_hashes` (when given) is the complete set of logins this write may carry.
    """
    fid = int(family_id)
    idx = {c: i for i, c in enumerate(cols)}
    sql = _guarded_users_upsert_sql(cols, preserve_identity)
    written = 0
    for row in rows:
        if int(row[idx["family_id"]] or 0) != fid:
            continue
        owner = conn.execute(
            "SELECT family_id FROM users WHERE user_id = ?", (row[idx["user_id"]],)
        ).fetchone()
        if owner is not None and int(owner[0]) != fid:
            continue
        email_hash = str(row[idx["email_hash"]] or "") if "email_hash" in idx else ""
        if email_hash:
            if allowed_email_hashes is not None and email_hash not in allowed_email_hashes:
                continue
            taken = conn.execute(
                "SELECT 1 FROM users WHERE email_hash = ? AND family_id != ? LIMIT 1", (email_hash, fid)
            ).fetchone()
            if taken is not None:
                continue
        conn.execute(sql, tuple(row))
        written += 1
    return written
