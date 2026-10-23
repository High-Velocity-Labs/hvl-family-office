"""
Database initialization, schema migration, and snapshot verification helpers for security store.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Tuple, Union
from hvl_common.db import close_all_pools, get_db_connection, run_migrations
from security_crypto import (
    ALEMBIC_DIR,
    ALEMBIC_HEAD_REVISION,
    ALEMBIC_INI_PATH,
    MIGRATIONS_DIR,
    _DB_INIT_CACHE,
    _FAMILY_KEY_CACHE,
)


def _is_household_vault_initialized(conn: Any, family_id: int, fam_name: Any) -> bool:
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
    for q in queries:
        try:
            if conn.execute(q, (fid,)).fetchone():
                return True
        except Exception:
            continue
    return False


def _is_initial_vault_setup(conn: Any, family_id: int) -> bool:
    """Returns True if the household has not completed Google Drive vault sync (`google_vault_synced == 0` for all members)."""
    try:
        synced_row = conn.execute(
            "SELECT 1 FROM users WHERE family_id = ? AND COALESCE(google_vault_synced, 0) = 1 LIMIT 1",
            (int(family_id),),
        ).fetchone()
        return synced_row is None
    except Exception:
        return True


def _is_non_public_db_path(db_file: str) -> bool:
    """Returns True if the database path belongs to a demo or sandbox universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return bool(parts.intersection({"demo", "sandbox", "families_beta", "families_sandbox"}))


def _is_demo_db_path(db_file: str) -> bool:
    """Returns True if the database path belongs to a read-only demo universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return bool(parts.intersection({"demo", "families_beta"}))


def _is_sandbox_db_path(db_file: str) -> bool:
    """Returns True if the database path belongs to an ephemeral sandbox universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return bool(parts.intersection({"sandbox", "families_sandbox"}))


def _is_public_db_path(db_file: str) -> bool:
    """Returns True if the database path explicitly belongs to the public universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return "public" in parts


def run_alembic_migrations(db_path: Path) -> None:
    """Runs Alembic schema migrations up to head for the specified SQLite database."""
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    if path_obj.exists():
        try:
            with get_db_connection(path_obj, timeout=30.0) as conn:
                ver_row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
                if ver_row and ver_row[0] == ALEMBIC_HEAD_REVISION:
                    fam_cols = {r[1] for r in conn.execute("PRAGMA table_info(families)").fetchall()}
                    user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
                    if "support_access_enabled" in fam_cols and "pending_fek_enc" in user_cols:
                        return
        except Exception:
            pass

    from alembic import command
    from alembic.config import Config
    from hvl_common.db import get_engine

    alembic_cfg = Config(str(ALEMBIC_INI_PATH) if ALEMBIC_INI_PATH.exists() else None)
    alembic_cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path_obj.resolve()}")
    alembic_cfg.attributes["skip_logging_config"] = True

    engine = get_engine(path_obj)
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")


def init_db(db_path: Path) -> None:
    """Initializes the multi-tenant SQLite schema via migrations and ensures default records."""
    path_obj = Path(db_path)
    p_str = str(path_obj)
    if p_str in _DB_INIT_CACHE and path_obj.exists():
        return

    for k in [k for k in _FAMILY_KEY_CACHE if k[0] == p_str]:
        _FAMILY_KEY_CACHE.pop(k, None)

    path_obj.parent.mkdir(parents=True, exist_ok=True)
    run_migrations(path_obj, MIGRATIONS_DIR)
    run_alembic_migrations(path_obj)

    with get_db_connection(path_obj, timeout=30.0) as conn:
        from db.models_ops import HouseholdNotification, PushSubscription, ensure_orm_table_on_conn
        ensure_orm_table_on_conn(conn, HouseholdNotification)
        ensure_orm_table_on_conn(conn, PushSubscription)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invite_tokens (
                invite_id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                created_by_family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
                created_by_email TEXT DEFAULT '',
                invite_type TEXT NOT NULL DEFAULT 'new_household',
                target_role TEXT NOT NULL DEFAULT 'editor',
                label TEXT DEFAULT '',
                max_uses INTEGER NOT NULL DEFAULT 1,
                uses_count INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS download_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                app_version TEXT DEFAULT '',
                referrer TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "encrypted_store" in existing_tables and "family_encrypted_store" in existing_tables:
            if conn.execute("SELECT 1 FROM encrypted_store LIMIT 1").fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO families (family_id, name, settings) VALUES (1, 'Primary Family Office', '{\"primary_state\": \"WA\", \"tax_filing_status\": \"MFJ\"}')"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO family_encrypted_store (family_id, key, category, updated_at, encrypted_payload) SELECT 1, key, category, updated_at, encrypted_payload FROM encrypted_store"
                )
            conn.execute("DELETE FROM encrypted_store")
        if "family_encrypted_store" in existing_tables:
            conn.execute("DELETE FROM family_encrypted_store WHERE family_id <= 0")
        conn.commit()

    _DB_INIT_CACHE.add(p_str)

    try:
        from db import data_migration
        data_migration.migrate_encrypted_store_to_relational(path_obj)
    except Exception:
        pass


def validate_vault_snapshot_file(tmp_path: Union[str, Path]) -> Tuple[bool, str]:
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
        return True, ""
    except Exception:
        return False, "Invalid .fovault file: not a valid SQLite vault archive."
    finally:
        close_all_pools(tmp_path)


def _resolve_pending_user_fek(
    conn: Any,
    fid: int,
    root_kek: bytes,
    cache_key: Optional[Tuple[str, int]],
    support_enabled: bool,
    is_local: bool,
    enc_key_str: str,
) -> Optional[bytes]:
    """Resolves a pending user FEK from users.pending_fek_enc when authenticated for the family."""
    from security_crypto import _FAMILY_KEY_CACHE, _get_fernet, stash_request_vault_fek

    try:
        from flask import session
        uid = session.get("user_id")
        p_row = conn.execute(
            "SELECT pending_fek_enc FROM users WHERE user_id = ? AND family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != ''",
            (int(uid), fid),
        ).fetchone() if uid else None
        if not p_row:
            p_row = conn.execute(
                "SELECT pending_fek_enc FROM users WHERE family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1",
                (fid,),
            ).fetchone()
        if p_row and p_row[0]:
            dek = _get_fernet(root_kek).decrypt(str(p_row[0]).encode("utf-8"))
            stash_request_vault_fek(fid, dek)
            if (support_enabled or is_local) and cache_key is not None:
                _FAMILY_KEY_CACHE[cache_key] = dek
            if is_local and (not enc_key_str or not support_enabled):
                enc_dek = _get_fernet(root_kek).encrypt(dek).decode("utf-8")
                was_in_tx = conn.in_transaction
                conn.execute(
                    "UPDATE families SET encryption_key_enc = ?, support_access_enabled = 1 WHERE family_id = ?",
                    (enc_dek, fid),
                )
                if not was_in_tx:
                    conn.commit()
            return dek
    except Exception:
        pass
    return None

