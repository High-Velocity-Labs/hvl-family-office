"""
One-off re-encryption of legacy root-KEK ciphertext in a household database (F-SEC-11).

Before household keys were mandatory, some columns (and JSON values inside them) were written under the server
root KEK. Every token that the household FEK cannot open but the root key can is rewritten under the FEK; tokens
the FEK already opens, and tokens neither opens, are left byte-for-byte alone, so the pass is idempotent and safe
to run from several workers at once. Columns that hold KEK-wrapped keys on purpose are never touched.
"""

from __future__ import annotations

import sqlite3
import logging
import re
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from hvl_common.db import get_db_connection

from hvl_common.db.sqlite import quote_ident

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"gAAAAA[A-Za-z0-9_\-=]+")
_FernetLike = Fernet | MultiFernet


def _is_key_wrapping_column(name: str) -> bool:
    lowered = name.lower()
    return "fek" in lowered or "key_enc" in lowered


def _opens(fernet: _FernetLike, token: bytes) -> bool:
    try:
        fernet.decrypt(token)
        return True
    except InvalidToken:
        return False


def _rekey_value(value: str, household: _FernetLike, root: _FernetLike) -> tuple[str, int]:
    changed = 0

    def _swap(match: re.Match[str]) -> str:
        nonlocal changed
        token = match.group(0).encode("utf-8")
        if _opens(household, token):
            return match.group(0)
        try:
            plain = root.decrypt(token)
        except InvalidToken:
            return match.group(0)
        changed += 1
        return household.encrypt(plain).decode("utf-8")

    return _TOKEN_RE.sub(_swap, value), changed


def is_household_only_db(db_path: Path, family_id: int) -> bool:
    """True for `families/{family_id}.db`, whose every row belongs to that household (unlike the shared global.db)."""
    path = Path(db_path)
    return path.parent.name.startswith("families") and path.stem == str(int(family_id))


def rekey_household_db(db_path: Path, family_id: int, household: _FernetLike, root: _FernetLike) -> int:
    """
    Rewrites root-KEK tokens under `household`. Returns the number rewritten. In a household's own database that
    is every table; in a shared one (global.db) only rows whose `family_id` is this household's, because the
    other rows belong to households whose keys this one must never be applied to.
    """
    total = 0
    own_db = is_household_only_db(db_path, family_id)
    fid = int(family_id)
    with get_db_connection(db_path, timeout=30.0) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "AND name NOT LIKE 'alembic_%'"
                ).fetchall()
            ]
            for tbl in tables:
                qtbl = quote_ident(tbl)
                all_cols = [c[1] for c in conn.execute(f"PRAGMA table_info({qtbl})").fetchall()]
                if not own_db and "family_id" not in all_cols:
                    continue
                cols = [c for c in all_cols if not _is_key_wrapping_column(c)]
                if not cols:
                    continue
                select = ", ".join(quote_ident(c) for c in cols)
                scope = "" if own_db else " WHERE family_id = ?"
                params = () if own_db else (fid,)
                for row in conn.execute(f"SELECT rowid, {select} FROM {qtbl}{scope}", params).fetchall():
                    updates: dict[str, str] = {}
                    for idx, col in enumerate(cols, start=1):
                        val = row[idx]
                        if isinstance(val, str) and "gAAAAA" in val:
                            new_val, n = _rekey_value(val, household, root)
                            if n:
                                updates[col] = new_val
                                total += n
                    if updates:
                        sets = ", ".join(f"{quote_ident(k)} = ?" for k in updates)
                        conn.execute(f"UPDATE {qtbl} SET {sets} WHERE rowid = ?", [*updates.values(), row[0]])
            _write_marker(conn, family_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return total


def is_rekeyed(db_path: Path, family_id: int) -> bool:
    """True when this household's `families.root_kek_rekeyed` records a completed pass."""
    try:
        with get_db_connection(db_path, timeout=10.0) as conn:
            row = conn.execute(
                "SELECT root_kek_rekeyed FROM families WHERE family_id = ?", (int(family_id),)
            ).fetchone()
    except sqlite3.Error:
        return False
    return bool(row) and bool(row[0])


def _write_marker(conn: Any, family_id: int) -> None:
    conn.execute("UPDATE families SET root_kek_rekeyed = 1 WHERE family_id = ?", (int(family_id),))
