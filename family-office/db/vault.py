"""
SQLite persistence and DDL helpers for household encryption keys, schema initialization,
encrypted key-value store, server support-access escrow, and local passphrase vault records.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from cryptography.fernet import InvalidToken
from hvl_common.db import close_all_pools, get_db_connection
from hvl_common.db.sqlite import quote_ident

from db.vault_archive_schema import archive_schema_error
from db.vault_support_access import read_family_support_flag

logger = logging.getLogger(__name__)


def check_household_vault_initialized(conn: Any, family_id: int, fam_name: Any) -> bool:
    """Checks whether a household has already initialized encrypted records or user vault state."""
    if isinstance(fam_name, str) and fam_name.startswith("gAAAAA"):
        return True
    fid = int(family_id)
    queries = (
        "SELECT 1 FROM users WHERE family_id = ? LIMIT 1",
        "SELECT 1 FROM family_encrypted_store WHERE family_id = ? LIMIT 1",
        "SELECT 1 FROM monarch_accounts WHERE family_id = ? LIMIT 1",
        "SELECT 1 FROM equity_companies WHERE family_id = ? LIMIT 1",
        "SELECT 1 FROM compensation WHERE family_id = ? LIMIT 1",
        "SELECT 1 FROM forecast_scenarios WHERE family_id = ? LIMIT 1",
        "SELECT 1 FROM household_profile WHERE family_id = ? AND assumptions_json IS NOT NULL AND assumptions_json != '' AND assumptions_json != '{}' LIMIT 1",
    )
    # A query that fails is never read as "empty": that answer lets the caller mint a fresh key over a vault.
    return any(conn.execute(q, (fid,)).fetchone() for q in queries)


def check_initial_vault_setup(conn: Any, family_id: int) -> bool:
    """Returns True if the household has not completed Google Drive vault sync (`google_vault_synced == 0` for all members)."""
    synced_row = conn.execute(
        "SELECT 1 FROM users WHERE family_id = ? AND COALESCE(google_vault_synced, 0) = 1 LIMIT 1",
        (int(family_id),),
    ).fetchone()
    return synced_row is None


def is_alembic_at_head(path_obj: Path, head_revision: str) -> bool:
    """Returns True if the SQLite database is already at the expected Alembic head revision with required columns."""
    if not path_obj.exists():
        return False
    try:
        with get_db_connection(path_obj, timeout=30.0) as conn:
            ver_row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
            if ver_row and ver_row[0] == head_revision:
                fam_cols = {r[1] for r in conn.execute("PRAGMA table_info(families)").fetchall()}
                user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
                if "support_access_enabled" in fam_cols and "pending_fek_enc" in user_cols:
                    return True
    except sqlite3.Error:
        pass  # no readable alembic_version table: the database is not at head
    return False


def validate_vault_snapshot_sqlite(tmp_path: Union[str, Path]) -> Tuple[bool, str]:
    """Validates that an uploaded .fovault SQLite snapshot passes integrity check and contains families table."""
    try:
        with get_db_connection(tmp_path) as chk_conn:
            integrity = chk_conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                return False, "Uploaded .fovault file failed SQLite integrity check."
            tbl = chk_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='families'"
            ).fetchone()
            if not tbl:
                return False, "Uploaded file is not an HVL Family Office vault."
            schema_err = archive_schema_error(chk_conn)
            if schema_err:
                return False, schema_err
        return True, ""
    except sqlite3.Error:
        return False, "Invalid .fovault file: not a valid SQLite vault archive."
    finally:
        close_all_pools(tmp_path)


def fetch_pending_user_fek_enc(conn: Any, fid: int, uid: Optional[int]) -> Optional[str]:
    """Fetches a non-empty `users.pending_fek_enc` token for `uid` or any user in `fid`."""
    p_row = (
        conn.execute(
            "SELECT pending_fek_enc FROM users WHERE user_id = ? AND family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != ''",
            (int(uid), fid),
        ).fetchone()
        if uid
        else None
    )
    if not p_row:
        p_row = conn.execute(
            "SELECT pending_fek_enc FROM users WHERE family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1",
            (fid,),
        ).fetchone()
    if p_row and p_row[0]:
        return str(p_row[0])
    return None


def update_family_escrowed_fek(conn: Any, fid: int, enc_dek: str, support_enabled: int = 1) -> None:
    """Updates `families.encryption_key_enc` and `support_access_enabled` on an active connection."""
    was_in_tx = conn.in_transaction
    conn.execute(
        "UPDATE families SET encryption_key_enc = ?, support_access_enabled = ? WHERE family_id = ?",
        (enc_dek, int(support_enabled), fid),
    )
    if not was_in_tx:
        conn.commit()


def fetch_family_key_row(conn: Any, fid: int) -> Optional[Tuple[Any, Any, Any]]:
    """Fetches `(encryption_key_enc, support_access_enabled, name)` for `fid` from `families`."""
    row = conn.execute(
        "SELECT encryption_key_enc, support_access_enabled, name FROM families WHERE family_id = ?",
        (fid,),
    ).fetchone()
    if not row:
        return None
    return row[0], (row[1] if len(row) > 1 else 0), (row[2] if len(row) > 2 else "")


def insert_default_family_row(conn: Any, fid: int) -> None:
    """Inserts a placeholder `families` row if missing."""
    was_in_tx = conn.in_transaction
    conn.execute(
        "INSERT INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (?, ?, NULL, 0) ON CONFLICT(family_id) DO NOTHING",
        (fid, f"Family {fid}"),
    )
    if not was_in_tx:
        conn.commit()


def ensure_family_row_for_write(db_path: Path, fid: int) -> None:
    """Creates the household's `families` row (the parent of every FK) when a write session needs it and it is missing.
    Reads and bare key lookups never call this, so they cannot leave an unclaimed placeholder behind."""
    with get_db_connection(db_path, timeout=30.0) as conn:
        if conn.execute("SELECT 1 FROM families WHERE family_id = ?", (int(fid),)).fetchone() is None:
            insert_default_family_row(conn, int(fid))


def upsert_family_key_row(conn: Any, fid: int, enc_dek: str, support_enabled: int) -> None:
    """Upserts `families` row with encrypted DEK and support access flag."""
    was_in_tx = conn.in_transaction
    conn.execute(
        "INSERT INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (?, ?, ?, ?) ON CONFLICT(family_id) DO UPDATE SET encryption_key_enc = excluded.encryption_key_enc, support_access_enabled = excluded.support_access_enabled",
        (fid, f"Family {fid}", enc_dek, int(support_enabled)),
    )
    if not was_in_tx:
        conn.commit()


def is_sqlite_connection(db_or_conn: Any) -> bool:
    """Returns True if `db_or_conn` is a raw `sqlite3.Connection` or pooled SQLite connection."""
    return isinstance(db_or_conn, sqlite3.Connection) or hasattr(db_or_conn, "raw_connection")


def resolve_family_key_on_sqlite_conn(
    conn: Any,
    fid: int,
    root_kek: bytes,
    cache: Dict[Tuple[str, int], bytes],
    resolve_fn: Callable[..., bytes],
    cache_valid_fn: Callable[[Optional[bool], str], bool],
) -> bytes:
    """Resolves a family encryption key against an already-open SQLite connection."""
    db_list = conn.execute("PRAGMA database_list").fetchone()
    db_file = str(db_list[2]) if db_list and len(db_list) > 2 and db_list[2] else ""
    c_key = (db_file, fid) if db_file else None
    if c_key and c_key in cache:
        if cache_valid_fn(read_family_support_flag(conn, fid), db_file):
            return cache[c_key]
        cache.pop(c_key, None)
    return resolve_fn(conn, fid, root_kek, c_key)


def resolve_family_key_on_db_path(
    db_path: Any,
    fid: int,
    root_kek: bytes,
    cache_key: Tuple[str, int],
    resolve_fn: Callable[..., bytes],
) -> bytes:
    """
    Opens a pooled SQLite connection to `db_path` and delegates FEK resolution.
    The connection is returned to the pool explicitly: leaving `with` does not release it, and a
    raised PermissionError (locked vault) would otherwise keep it checked out via its traceback.
    """
    conn = get_db_connection(db_path, timeout=30.0)
    try:
        with conn:
            return resolve_fn(conn, fid, root_kek, cache_key)
    finally:
        conn.close()


def rotate_family_keys_in_db(path_obj: Path, multi: Any) -> List[int]:
    """Re-encrypts `families.encryption_key_enc`, `families.name`, and `users.pending_fek_enc` under `multi`."""
    rotated_family_ids: List[int] = []
    with get_db_connection(path_obj, timeout=30.0) as conn:
        rows = conn.execute(
            "SELECT family_id, encryption_key_enc, name FROM families ORDER BY family_id ASC"
        ).fetchall()
        for row in rows:
            fid = int(row[0])
            enc_dek = row[1]
            fam_name = row[2]
            if not enc_dek:
                continue
            rotated_dek = multi.rotate(str(enc_dek).encode("utf-8")).decode("utf-8")
            new_name = fam_name
            if isinstance(fam_name, str) and fam_name.startswith("gAAAAA"):
                try:
                    new_name = multi.rotate(fam_name.encode("utf-8")).decode("utf-8")
                except InvalidToken:
                    new_name = fam_name  # a name the ring cannot open stays as stored
            conn.execute(
                "UPDATE families SET encryption_key_enc = ?, name = ? WHERE family_id = ?",
                (rotated_dek, new_name, fid),
            )
            rotated_family_ids.append(fid)

        u_rows = conn.execute(
            "SELECT user_id, pending_fek_enc FROM users WHERE pending_fek_enc IS NOT NULL AND pending_fek_enc != ''"
        ).fetchall()
        for u_row in u_rows:
            uid = int(u_row[0])
            p_fek = str(u_row[1])
            try:
                rot_p_fek = multi.rotate(p_fek.encode("utf-8")).decode("utf-8")
            except InvalidToken:
                logger.warning("Pending FEK of user %s was not rotated: the key ring cannot open it", uid)
                continue
            conn.execute("UPDATE users SET pending_fek_enc = ? WHERE user_id = ?", (rot_p_fek, uid))
        conn.commit()
    return rotated_family_ids


def upsert_encrypted_store_payload(
    path_obj: Path, family_id: int, key: str, category: str, ciphertext: str
) -> None:
    """Upserts an encrypted payload into `family_encrypted_store`."""
    with get_db_connection(path_obj, timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO family_encrypted_store (family_id, key, category, updated_at, encrypted_payload)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(family_id, key) DO UPDATE SET
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP,
                encrypted_payload = excluded.encrypted_payload
            """,
            (family_id, key, category, ciphertext),
        )
        conn.commit()


def fetch_encrypted_store_payload(path_obj: Path, family_id: int, key: str) -> Optional[str]:
    """Fetches `encrypted_payload` from `family_encrypted_store` for `(family_id, key)`."""
    with get_db_connection(path_obj, timeout=30.0) as conn:
        try:
            cur = conn.execute(
                "SELECT encrypted_payload FROM family_encrypted_store WHERE family_id = ? AND key = ?",
                (family_id, key),
            )
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.OperationalError:
            pass
    return None


def has_escrowed_family_key(path_obj: Path, fid: int) -> bool:
    """Returns True if `families.encryption_key_enc` is present and non-empty for `fid`."""
    with get_db_connection(path_obj, timeout=30.0) as conn:
        row = conn.execute(
            "SELECT encryption_key_enc FROM families WHERE family_id = ?",
            (fid,),
        ).fetchone()
        return bool(row and row[0])


def fetch_any_pending_user_fek(path_obj: Path, fid: int) -> Optional[str]:
    """Fetches any non-empty `pending_fek_enc` from `users` for `fid`."""
    with get_db_connection(path_obj, timeout=30.0) as conn:
        p_row = conn.execute(
            "SELECT pending_fek_enc FROM users WHERE family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1",
            (fid,),
        ).fetchone()
        return str(p_row[0]) if (p_row and p_row[0]) else None


def check_local_vault_unclaimed_in_db(target_db: Path) -> bool:
    """Checks SQLite tables in `target_db` (and `families/1.db`) to determine if local vault is unclaimed."""
    with get_db_connection(target_db) as conn:
        u_row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        if int(u_row[0] if u_row else 0) > 0:
            return False

        fam1_cand = target_db.parent / "families" / "1.db"
        if fam1_cand.exists():
            # An unreadable families/1.db raises: never read as "no users" (that reports the vault unclaimed).
            with get_db_connection(fam1_cand) as fconn:
                fu_row = fconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()
                if int(fu_row[0] if fu_row else 0) > 0:
                    u_records = fconn.execute("SELECT * FROM users WHERE family_id = 1").fetchall()
                    cols = [c[1] for c in fconn.execute("PRAGMA table_info(users)").fetchall()]
                    if u_records and cols:
                        col_str = ", ".join(quote_ident(c) for c in cols)
                        placeholders = ", ".join("?" for _ in cols)
                        conn.execute("DELETE FROM users WHERE family_id = 1")
                        conn.executemany(
                            f"INSERT OR REPLACE INTO users ({col_str}) VALUES ({placeholders})",
                            [tuple(r) for r in u_records],
                        )
                        conn.commit()
                    return False

        for _, settings_str in conn.execute("SELECT family_id, settings FROM families WHERE family_id > 0").fetchall():
            if settings_str:
                s = json.loads(settings_str) if isinstance(settings_str, str) else {}
                if s.get("local_passphrase_fek_enc") or s.get("onboarding_completed"):
                    return False
    return True

