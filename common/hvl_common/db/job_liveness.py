"""
Cross-process liveness for `background_jobs`: ownership columns, heartbeats, and orphan recovery.

SQLite is the only state shared between gunicorn workers, so a job's owner is recorded as
(`owner_pid`, `owner_boot_id`) and kept fresh through `heartbeat_at`. A job still `queued` or
`processing` whose owner is another incarnation that is dead (pid gone, pid reused by this very
process, or heartbeat stale) can never finish and is marked `failed`.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from hvl_common.db.job_state import ACTIVE_STATES, FAILED

LIVENESS_COLUMNS: Dict[str, str] = {
    "owner_pid": "INTEGER",
    "owner_boot_id": "TEXT",
    "heartbeat_at": "REAL",
}

_ACTIVE_SQL = "(" + ", ".join(f"'{s}'" for s in sorted(ACTIVE_STATES)) + ")"


def ensure_liveness_columns(conn: sqlite3.Connection) -> None:
    """Idempotently adds ownership/heartbeat columns to a `background_jobs` table created before them."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(background_jobs)").fetchall()}
    for name, decl in LIVENESS_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE background_jobs ADD COLUMN {name} {decl}")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_orphaned(
    *,
    owner_pid: Optional[int],
    owner_boot_id: Optional[str],
    heartbeat_at: Optional[float],
    updated_at: float,
    own_boot_id: str,
    now: float,
    stale_after: float,
) -> bool:
    """True when an active job's owner is another incarnation that can no longer finish it."""
    if owner_boot_id == own_boot_id:
        return False
    if owner_pid is not None and int(owner_pid) == os.getpid():
        return True  # same pid, different boot: the previous incarnation of this worker
    if owner_pid is not None and not pid_alive(int(owner_pid)):
        return True
    last_seen = heartbeat_at if heartbeat_at is not None else updated_at
    return (now - float(last_seen)) > stale_after


def orphan_error(owner_pid: Optional[int], owner_boot_id: Optional[str]) -> str:
    return (
        "Background job was lost: the worker that owned it "
        f"(pid {owner_pid if owner_pid is not None else 'unknown'}, "
        f"boot {(owner_boot_id or 'unknown')[:8]}) stopped before it finished. Please retry."
    )


def fail_job_if_orphaned(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    own_boot_id: str,
    now: float,
    stale_after: float,
) -> bool:
    """Fails one active row whose owner is gone. Returns True if this call marked it failed."""
    row = conn.execute(
        "SELECT owner_pid, owner_boot_id, heartbeat_at, updated_at FROM background_jobs "
        f"WHERE job_id = ? AND status IN {_ACTIVE_SQL}",
        (job_id,),
    ).fetchone()
    if row is None or not is_orphaned(
        owner_pid=row["owner_pid"],
        owner_boot_id=row["owner_boot_id"],
        heartbeat_at=row["heartbeat_at"],
        updated_at=float(row["updated_at"]),
        own_boot_id=own_boot_id,
        now=now,
        stale_after=stale_after,
    ):
        return False
    with conn:
        cur = conn.execute(
            "UPDATE background_jobs SET status = ?, error = ?, updated_at = ? "
            f"WHERE job_id = ? AND status IN {_ACTIVE_SQL}",
            (FAILED, orphan_error(row["owner_pid"], row["owner_boot_id"]), now, job_id),
        )
    return cur.rowcount > 0


def fail_orphaned_jobs(
    conn: sqlite3.Connection,
    *,
    own_boot_id: str,
    now: float,
    stale_after: float,
) -> List[str]:
    """Worker-boot sweep: fails every active row whose owner is gone. Returns the failed job ids."""
    ids = [r["job_id"] for r in conn.execute(f"SELECT job_id FROM background_jobs WHERE status IN {_ACTIVE_SQL}").fetchall()]
    return [
        jid
        for jid in ids
        if fail_job_if_orphaned(conn, jid, own_boot_id=own_boot_id, now=now, stale_after=stale_after)
    ]


def touch_heartbeats(conn: sqlite3.Connection, job_ids: Iterable[str], now: float) -> None:
    ids = list(job_ids)
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    with conn:
        conn.execute(
            f"UPDATE background_jobs SET heartbeat_at = ? WHERE job_id IN ({marks}) AND status IN {_ACTIVE_SQL}",
            (now, *ids),
        )


__all__ = [
    "LIVENESS_COLUMNS",
    "ensure_liveness_columns",
    "fail_job_if_orphaned",
    "fail_orphaned_jobs",
    "is_orphaned",
    "orphan_error",
    "pid_alive",
    "touch_heartbeats",
]
