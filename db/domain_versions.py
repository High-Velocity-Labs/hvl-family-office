"""
db/domain_versions.py: SQLite persistence for per-family reactive domain version counters.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Optional, Set, Tuple
import threading
from hvl_common.db import get_db_connection
from hvl_common.db.sqlite import _resolve_db_key

_DOMAIN_DB_LOCK = threading.RLock()
_DOMAIN_DB_INIT: Set[str] = set()


def ensure_domain_versions_schema(state_db: Path) -> None:
    db_key = _resolve_db_key(state_db)
    if db_key in _DOMAIN_DB_INIT and state_db.exists():
        return
    with _DOMAIN_DB_LOCK:
        if db_key in _DOMAIN_DB_INIT and state_db.exists():
            return
        with get_db_connection(state_db, timeout=5.0) as conn:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS family_domain_versions ("
                    "family_id INTEGER PRIMARY KEY, state_version INTEGER NOT NULL DEFAULT 1, "
                    "domains_json TEXT NOT NULL DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
                )
            _DOMAIN_DB_INIT.add(db_key)


def load_domain_versions_row(state_db: Path, family_id: int) -> Optional[Tuple[int, Dict[str, int]]]:
    if not state_db.parent.exists():
        return None
    try:
        ensure_domain_versions_schema(state_db)
        with get_db_connection(state_db, timeout=5.0) as conn:
            row = conn.execute(
                "SELECT state_version, domains_json FROM family_domain_versions WHERE family_id = ?",
                (int(family_id),),
            ).fetchone()
            if row is None:
                return None
            db_state_v = int(row[0] or 1)
            parsed = json.loads(row[1] or "{}")
            return db_state_v, (parsed if isinstance(parsed, dict) else {})
    except Exception:
        return None


def save_domain_versions_row(state_db: Path, family_id: int, state_version: int, domain_map: Dict[str, int]) -> None:
    if not state_db.parent.exists():
        return
    try:
        ensure_domain_versions_schema(state_db)
        with get_db_connection(state_db, timeout=5.0) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO family_domain_versions (family_id, state_version, domains_json, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(family_id) DO UPDATE SET "
                    "state_version = excluded.state_version, domains_json = excluded.domains_json, "
                    "updated_at = CURRENT_TIMESTAMP",
                    (int(family_id), int(state_version), json.dumps(domain_map, separators=(",", ":"))),
                )
    except Exception:
        pass


def delete_all_domain_versions(state_db: Path) -> None:
    if state_db is None or not state_db.exists():
        return
    try:
        ensure_domain_versions_schema(state_db)
        with get_db_connection(state_db, timeout=5.0) as conn:
            with conn:
                conn.execute("DELETE FROM family_domain_versions")
    except Exception:
        pass
