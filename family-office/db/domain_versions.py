"""
db/domain_versions.py: SQLite persistence for per-family reactive domain version counters.
Powered by shared `hvl_common.db.domain_versions`.
"""

from __future__ import annotations
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Optional, Tuple
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


def raise_rows_above(state_db: Path, family_id: int, floor: Optional[Tuple[int, Dict[str, int]]]) -> None:
    """
    Moves every counter for `family_id` strictly above `floor` (a `load_domain_versions_row` result taken before the
    database was overwritten) and above its own current value. A restore replaces this table with the backup's
    older counters; each process keeps the highest counters it has seen, so counters that went back down would let
    other workers keep serving pre-restore cached data. Leaving them all above every earlier value makes each
    process see a change.
    """
    floor_state, floor_domains = floor if floor else (1, {})
    loaded = load_domain_versions_row(state_db, family_id)
    cur_state, cur_domains = loaded if loaded else (1, {})
    names = set(floor_domains) | set(cur_domains)
    raised = {d: max(int(floor_domains.get(d, 1)), int(cur_domains.get(d, 1))) + 1 for d in names}
    save_domain_versions_row(state_db, family_id, max(int(floor_state), int(cur_state)) + 1, raised)


def delete_all_domain_versions(state_db: Path) -> None:
    delete_all_json_domain_versions(state_db, table_name="family_domain_versions")


def bump_rows_in_transaction(
    conn: sqlite3.Connection, family_id: int, domains: Iterable[str], *, state_version: Optional[int] = None
) -> Dict[str, int]:
    """
    Increments `domains` for `family_id` on `conn`, inside the transaction the caller already holds, and returns the
    new domain map. The caller owns the transaction: a write session's own unit of work (the write lock its flush
    took keeps another process from interleaving) or `bump_domain_rows`' `BEGIN IMMEDIATE`. `state_version` only
    ever moves forward.
    """
    targets = [str(d) for d in domains if d]
    row = conn.execute(
        "SELECT state_version, domains_json FROM family_domain_versions WHERE family_id = ?", (int(family_id),)
    ).fetchone()
    cur_state = int(row[0] or 1) if row else 1
    parsed = json.loads(row[1] or "{}") if row else {}
    domain_map: Dict[str, int] = {str(k): int(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}
    for dom in targets:
        domain_map[dom] = int(domain_map.get(dom, 1)) + 1
    new_state = max(cur_state, int(state_version)) if state_version is not None else cur_state
    conn.execute(
        "INSERT INTO family_domain_versions (family_id, state_version, domains_json, updated_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(family_id) DO UPDATE SET "
        "state_version = excluded.state_version, domains_json = excluded.domains_json, "
        "updated_at = CURRENT_TIMESTAMP",
        (int(family_id), new_state, json.dumps(domain_map, separators=(",", ":"))),
    )
    return domain_map


def bump_domain_rows(
    state_db: Path, family_id: int, domains: Iterable[str], *, state_version: Optional[int] = None
) -> Dict[str, int]:
    """
    Atomically increments `domains` for `family_id` in one `BEGIN IMMEDIATE` transaction, so concurrent workers
    (separate processes) serialize on the SQLite write lock and never lose a bump. Errors propagate: a bump that
    cannot be persisted must not look like success. For a bump with no write of its own; a write's bump travels
    in its own transaction (`db.session`, `before_commit`).
    """
    ensure_domain_versions_schema(state_db)
    conn = sqlite3.connect(str(state_db), timeout=10.0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            domain_map = bump_rows_in_transaction(conn, family_id, domains, state_version=state_version)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return domain_map


def raise_state_version(state_db: Path, family_id: int, state_version: int) -> None:
    """Moves the stored `state_version` forward to at least `state_version`; one atomic statement, no domain changes."""
    conn = sqlite3.connect(str(state_db), timeout=10.0)
    try:
        conn.execute(
            "UPDATE family_domain_versions SET state_version = MAX(state_version, ?) WHERE family_id = ?",
            (int(state_version), int(family_id)),
        )
        conn.commit()
    finally:
        conn.close()


def bump_domains(
    family_id: int = 0,
    *domains: Any,
    db_path: Optional[Path] = None,
    state_db: Optional[Path] = None,
) -> Dict[str, int]:
    """Increments specific domain version counters for `family_id` without purging forecast cache."""
    from forecast.cache import bump_domain_versions

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

