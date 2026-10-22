"""
db/domain_versions.py: SQLite persistence for per-family reactive domain version counters.
Powered by shared `hvl_common.db.domain_versions`.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
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


def bump_domains(
    family_id: int = 0,
    *domains: Any,
    db_path: Optional[Path] = None,
    state_db: Optional[Path] = None,
) -> Dict[str, int]:
    """Increments specific domain version counters for `family_id` without purging forecast cache."""
    from forecast_cache_helpers import bump_domain_versions

    fid = int(family_id or 0)
    if fid <= 0:
        return {}
    flat: list[str] = []
    for item in domains:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, (list, tuple, set, frozenset)):
            flat.extend(str(x) for x in item if x)
    return bump_domain_versions(fid, domains=flat or ("notifications",), state_db=state_db or db_path)

