"""
db/domain_versions.py: SQLite persistence for per-family reactive domain version counters.
Powered by shared `hvl_common.db.domain_versions`.
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional, Tuple
from hvl_common.db import (
    delete_all_json_domain_versions,
    ensure_json_domain_versions_schema,
    load_json_domain_versions_row,
    save_json_domain_versions_row,
)


def ensure_domain_versions_schema(state_db: Path) -> None:
    ensure_json_domain_versions_schema(state_db, table_name="family_domain_versions", id_col="family_id")


def load_domain_versions_row(state_db: Path, family_id: int) -> Optional[Tuple[int, Dict[str, int]]]:
    return load_json_domain_versions_row(state_db, family_id, table_name="family_domain_versions", id_col="family_id")


def save_domain_versions_row(state_db: Path, family_id: int, state_version: int, domain_map: Dict[str, int]) -> None:
    save_json_domain_versions_row(
        state_db, family_id, state_version, domain_map, table_name="family_domain_versions", id_col="family_id"
    )


def delete_all_domain_versions(state_db: Path) -> None:
    delete_all_json_domain_versions(state_db, table_name="family_domain_versions")
