"""
Orphaned background-job recovery over a job cache database (F-AI-7), using `hvl_common.db.job_liveness`.
"""

from __future__ import annotations

import time
from pathlib import Path

from hvl_common.db import get_db_connection
from hvl_common.db.job_liveness import ensure_liveness_columns, fail_orphaned_jobs


def fail_orphaned_jobs_in_cache(cache_db: Path, *, own_boot_id: str, stale_after: float) -> list[str]:
    """Marks `queued`/`processing` tickets in `cache_db` failed when their owning worker is gone; returns their ids."""
    with get_db_connection(cache_db, timeout=5.0) as conn:
        has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='background_jobs'").fetchone()
        if not has_table:
            return []
        with conn:
            ensure_liveness_columns(conn)
        return fail_orphaned_jobs(conn, own_boot_id=own_boot_id, now=time.time(), stale_after=stale_after)
