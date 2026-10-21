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
        if "families" in existing_tables and not conn.execute(
            "SELECT family_id FROM families WHERE family_id = 1"
        ).fetchone():
            conn.execute(
                "INSERT INTO families (family_id, name, settings) VALUES (1, 'Primary Family Office', '{\"primary_state\": \"WA\", \"tax_filing_status\": \"MFJ\"}')"
            )
        if "household_profile" in existing_tables and not conn.execute(
            "SELECT family_id FROM household_profile WHERE family_id = 1"
        ).fetchone():
            conn.execute(
                "INSERT INTO household_profile (family_id, state, filing_status, annual_spending, annual_savings) VALUES (1, 'WA', 'MFJ', 350000.0, 250000.0)"
            )
        if "encrypted_store" in existing_tables and "family_encrypted_store" in existing_tables:
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
