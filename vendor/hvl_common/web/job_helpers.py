"""
Helper functions for background job execution policy, cross-worker SQLite lookup,
and terminal job pruning in `hvl_common.web.jobs`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional, Union

from hvl_common.db.jobs import SQLiteJobPool
from hvl_common.db.sqlite import get_db_connection

logger = logging.getLogger(__name__)


def _parse_bool_flag(val: Any) -> Optional[bool]:
    """Parses a boolean value or boolean string representation."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def _is_test_or_sync_env() -> bool:
    """Returns True ONLY when running in Flask TESTING mode, pytest, or explicit HVL_ASYNC_JOBS_SYNC=1."""
    if os.getenv("HVL_ASYNC_JOBS_SYNC") == "1" or bool(os.getenv("PYTEST_CURRENT_TEST")):
        return True
    try:
        from flask import current_app, has_app_context

        if has_app_context() and bool(current_app.config.get("TESTING")):
            return True
    except ImportError:
        pass
    return False


def should_run_synchronously(
    payload: Optional[Dict[str, Any]] = None,
    *,
    sync_param: Any = None,
    async_param: Any = None,
) -> bool:
    """
    Determines whether a request should execute synchronously or in the background pool.
    - NEVER honors client-supplied `sync` / `async` flags outside `TESTING` / pytest / `HVL_ASYNC_JOBS_SYNC=1`.
    - Inside `TESTING` / pytest / `HVL_ASYNC_JOBS_SYNC=1`, defaults to `True` unless `async=true` or `sync=false`.
    """
    if not _is_test_or_sync_env():
        return False

    s_flag = _parse_bool_flag(sync_param)
    a_flag = _parse_bool_flag(async_param)

    if isinstance(payload, dict):
        if s_flag is None and "sync" in payload:
            s_flag = _parse_bool_flag(payload.get("sync"))
        if a_flag is None and "async" in payload:
            a_flag = _parse_bool_flag(payload.get("async"))

    if a_flag is True or s_flag is False:
        return False
    return True


def lookup_unisolated_job(
    pool: SQLiteJobPool,
    clean_id: str,
    cache_db_path: Optional[Union[str, Path]] = None,
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    extra_filters: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Looks up a job by `clean_id` across in-memory cache and SQLite without tenant_id restriction."""
    filters = extra_filters or {}
    now = time.time()
    with pool._lock:
        pool._prune_memory_locked(now)
        local = pool._jobs.get(clean_id)
        if local is not None:
            rec = dict(local)
            for k, expected_v in filters.items():
                if rec.get(k) != expected_v:
                    return None
            return rec

    resolved_db = pool._resolve_db_path(cache_db_path)
    if resolved_db is not None and resolved_db.exists():
        try:
            pool._ensure_schema(resolved_db)
            conn = get_db_connection(resolved_db, timeout=5.0)
            try:
                cur = conn.execute(
                    """
                    SELECT job_id, job_type, tenant_id, universe, status,
                           created_at, updated_at, meta_blob, result_blob, error
                    FROM background_jobs
                    WHERE job_id = ?
                    """,
                    (clean_id,),
                )
                row = cur.fetchone()
            finally:
                conn.close()

            if row is not None:
                updated_at = float(row["updated_at"])
                status = str(row["status"])
                if status in ("completed", "failed") and (now - updated_at) > pool.ttl_seconds:
                    return None

                meta = pool._decode_blob(row["meta_blob"], decrypt_fn=decrypt_fn)
                result = pool._decode_blob(row["result_blob"], decrypt_fn=decrypt_fn)
                rec = {
                    "job_id": str(row["job_id"]),
                    "job_type": str(row["job_type"]),
                    "tenant_id": int(row["tenant_id"]),
                    "family_id": int(row["tenant_id"]),
                    "universe": str(row["universe"]),
                    "status": status,
                    "created_at": float(row["created_at"]),
                    "updated_at": updated_at,
                    "result": result,
                    "error": row["error"],
                }
                if isinstance(meta, dict):
                    for k, v in meta.items():
                        if k not in rec:
                            rec[k] = v

                with pool._lock:
                    pool._jobs[clean_id] = dict(rec)

                for k, expected_v in filters.items():
                    if rec.get(k) != expected_v:
                        return None
                return rec
        except Exception as exc:
            logger.debug("JobManager SQLite lookup failed for %s: %s", clean_id, exc)

    return None


def prune_expired_jobs(
    pool: SQLiteJobPool,
    max_age_seconds: Optional[float] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Prunes terminal (completed or failed) jobs older than max_age_seconds from RAM and SQLite."""
    max_age = float(max_age_seconds if max_age_seconds is not None else pool.ttl_seconds)
    cutoff = time.time() - max_age
    purged = 0

    with pool._lock:
        expired_keys = [
            jid
            for jid, rec in pool._jobs.items()
            if rec.get("status") in ("completed", "failed")
            and float(rec.get("updated_at", 0.0)) < cutoff
        ]
        for jid in expired_keys:
            pool._jobs.pop(jid, None)
            pool._futures.pop(jid, None)
        purged += len(expired_keys)

    resolved_db = pool._resolve_db_path(cache_db_path)
    if resolved_db is not None and resolved_db.exists():
        try:
            pool._ensure_schema(resolved_db)
            conn = get_db_connection(resolved_db, timeout=5.0)
            try:
                with conn:
                    cur = conn.execute(
                        """
                        DELETE FROM background_jobs
                        WHERE status IN ('completed', 'failed') AND updated_at < ?
                        """,
                        (cutoff,),
                    )
                    purged += int(cur.rowcount or 0)
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("JobManager cleanup_old_jobs DB error: %s", exc)

    return purged
