"""
hvl_common.web.jobs: Generic, Reusable Background Job Manager & Polling Service.
Provides asynchronous job dispatch, thread-safe in-memory caching, multi-worker SQLite
persistence via SQLiteJobPool, optional tenant isolation, and synchronous execution bypasses.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
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


def should_run_synchronously(
    payload: Optional[Dict[str, Any]] = None,
    *,
    sync_param: Any = None,
    async_param: Any = None,
) -> bool:
    """
    Determines whether a request should execute synchronously or in the background pool.
    - If payload/params explicitly pass `async=true` or `sync=false`, runs asynchronously in background pool.
    - If payload/params explicitly pass `sync=true` or `async=false`, runs synchronously.
    - When Flask `TESTING=True` or `PYTEST_CURRENT_TEST` is active (and not overridden by `async=true`),
      falls back to synchronous execution so unit tests remain deterministic.
    - Otherwise (production / live web requests), runs asynchronously in the background pool.
    """
    s_flag = _parse_bool_flag(sync_param)
    a_flag = _parse_bool_flag(async_param)

    if isinstance(payload, dict):
        if s_flag is None and "sync" in payload:
            s_flag = _parse_bool_flag(payload.get("sync"))
        if a_flag is None and "async" in payload:
            a_flag = _parse_bool_flag(payload.get("async"))

    if a_flag is True or s_flag is False:
        return False
    if s_flag is True or a_flag is False:
        return True

    try:
        from flask import current_app, has_app_context

        if has_app_context() and current_app.config.get("TESTING"):
            return True
    except ImportError:
        pass

    if os.getenv("PYTEST_CURRENT_TEST"):
        return True

    return False


class JobManager:
    """
    Generic, reusable background job manager for High Velocity Labs web applications.
    Wraps an underlying SQLiteJobPool to offer both fast in-memory execution and
    cross-worker SQLite persistence, with flexible metadata support (family_id, team_id, week, etc.).
    """

    def __init__(
        self,
        *,
        max_workers: int = 4,
        thread_name_prefix: str = "hvl_bg_worker",
        ttl_seconds: float = 3600.0,
        max_memory_jobs: int = 500,
        cache_db_path_fn: Optional[Callable[[], Optional[Union[str, Path]]]] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        context_setup_fn: Optional[Callable[..., Any]] = None,
        context_reset_fn: Optional[Callable[[Any], None]] = None,
        service_name: str = "generic",
        telemetry_db_path: Optional[Union[str, Path]] = None,
        pool: Optional[SQLiteJobPool] = None,
    ) -> None:
        if pool is not None:
            self.pool = pool
        else:
            self.pool = SQLiteJobPool(
                max_workers=max_workers,
                thread_name_prefix=thread_name_prefix,
                ttl_seconds=ttl_seconds,
                max_memory_jobs=max_memory_jobs,
                cache_db_path_fn=cache_db_path_fn,
                encrypt_fn=encrypt_fn,
                decrypt_fn=decrypt_fn,
                context_setup_fn=context_setup_fn,
                context_reset_fn=context_reset_fn,
                service_name=service_name,
                telemetry_db_path=telemetry_db_path,
            )

        self.executor = self.pool.executor
        self.ttl_seconds = self.pool.ttl_seconds

    def submit_job(
        self,
        fn: Callable[..., Any],
        *args: Any,
        job_type: str = "generic",
        family_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
        universe: Optional[str] = "public",
        initial_meta: Optional[Dict[str, Any]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Submits `fn(*args, **kwargs)` to the background pool.
        Returns a unique `job_id` string (<1ms).
        """
        eff_tid = int(tenant_id if tenant_id is not None else (family_id if family_id is not None else 0))
        meta = dict(initial_meta) if initial_meta else {}
        if family_id is not None and "family_id" not in meta:
            meta["family_id"] = family_id
        if tenant_id is not None and "tenant_id" not in meta:
            meta["tenant_id"] = tenant_id

        return self.pool.submit_job(
            fn,
            *args,
            tenant_id=eff_tid,
            family_id=eff_tid,
            universe=str(universe or "public"),
            job_type=str(job_type or "generic"),
            initial_meta=meta,
            cache_db_path=cache_db_path,
            encrypt_fn=encrypt_fn,
            **kwargs,
        )

    def get_job(
        self,
        job_id: str,
        family_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        **extra_filters: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves job status and payload by `job_id`.
        If tenant_id or family_id is specified, strictly verifies tenant isolation.
        If neither is specified, allows global lookup by job_id across the worker or shared database.
        Optionally filters by arbitrary metadata matching extra_filters (e.g. team_id, week).
        """
        if not job_id:
            return None

        clean_id = str(job_id).strip()

        # If tenant isolation is explicitly requested
        if tenant_id is not None or family_id is not None:
            eff_tid = int(tenant_id if tenant_id is not None else family_id)
            rec = self.pool.get_job(
                clean_id,
                tenant_id=eff_tid,
                family_id=eff_tid,
                cache_db_path=cache_db_path,
                decrypt_fn=decrypt_fn,
            )
            if rec is None:
                return None
            for k, expected_v in extra_filters.items():
                if rec.get(k) != expected_v:
                    return None
            return rec

        # Un-isolated lookup (e.g. fantasy-assistant without family_id)
        now = time.time()
        with self.pool._lock:
            self.pool._prune_memory_locked(now)
            local = self.pool._jobs.get(clean_id)
            if local is not None:
                rec = dict(local)
                for k, expected_v in extra_filters.items():
                    if rec.get(k) != expected_v:
                        return None
                return rec

        # Cross-worker SQLite lookup
        resolved_db = self.pool._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            try:
                self.pool._ensure_schema(resolved_db)
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
                    if status in ("completed", "failed") and (now - updated_at) > self.pool.ttl_seconds:
                        return None

                    meta = self.pool._decode_blob(row["meta_blob"], decrypt_fn=decrypt_fn)
                    result = self.pool._decode_blob(row["result_blob"], decrypt_fn=decrypt_fn)
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

                    with self.pool._lock:
                        self.pool._jobs[clean_id] = dict(rec)

                    for k, expected_v in extra_filters.items():
                        if rec.get(k) != expected_v:
                            return None
                    return rec
            except Exception as exc:
                logger.debug("JobManager SQLite lookup failed for %s: %s", clean_id, exc)

        return None

    def cleanup_old_jobs(
        self,
        max_age_seconds: Optional[float] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> int:
        """
        Prunes terminal (completed or failed) jobs older than max_age_seconds.
        Removes them from both memory and persistent SQLite database.
        Returns the number of pruned jobs.
        """
        max_age = float(max_age_seconds if max_age_seconds is not None else self.ttl_seconds)
        cutoff = time.time() - max_age
        purged = 0

        with self.pool._lock:
            expired_keys = [
                jid
                for jid, rec in self.pool._jobs.items()
                if rec.get("status") in ("completed", "failed")
                and float(rec.get("updated_at", 0.0)) < cutoff
            ]
            for jid in expired_keys:
                self.pool._jobs.pop(jid, None)
                self.pool._futures.pop(jid, None)
            purged += len(expired_keys)

        resolved_db = self.pool._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            try:
                self.pool._ensure_schema(resolved_db)
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

    def wait_for_job(self, job_id: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Waits synchronously for a local job to complete (primarily for testing)."""
        return self.pool.wait_for_job(job_id, timeout=timeout)

    def clear(self, cache_db_path: Optional[Union[str, Path]] = None) -> None:
        """Clears memory and SQLite state."""
        self.pool.clear(cache_db_path=cache_db_path)


_DEFAULT_MANAGER: Optional[JobManager] = None
_DEFAULT_MANAGER_LOCK = threading.Lock()


def get_default_job_manager() -> JobManager:
    """Returns the process-wide default JobManager singleton."""
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        with _DEFAULT_MANAGER_LOCK:
            if _DEFAULT_MANAGER is None:
                _DEFAULT_MANAGER = JobManager()
    return _DEFAULT_MANAGER


def submit_job(
    fn: Callable[..., Any],
    *args: Any,
    job_type: str = "generic",
    family_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    universe: Optional[str] = "public",
    initial_meta: Optional[Dict[str, Any]] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
    encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    manager: Optional[JobManager] = None,
    **kwargs: Any,
) -> str:
    """Convenience module function to submit a background job."""
    mgr = manager or get_default_job_manager()
    return mgr.submit_job(
        fn,
        *args,
        job_type=job_type,
        family_id=family_id,
        tenant_id=tenant_id,
        universe=universe,
        initial_meta=initial_meta,
        cache_db_path=cache_db_path,
        encrypt_fn=encrypt_fn,
        **kwargs,
    )


def get_job(
    job_id: str,
    family_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    manager: Optional[JobManager] = None,
    **extra_filters: Any,
) -> Optional[Dict[str, Any]]:
    """Convenience module function to retrieve a background job by ID."""
    mgr = manager or get_default_job_manager()
    return mgr.get_job(
        job_id,
        family_id=family_id,
        tenant_id=tenant_id,
        cache_db_path=cache_db_path,
        decrypt_fn=decrypt_fn,
        **extra_filters,
    )


def cleanup_old_jobs(
    max_age_seconds: Optional[float] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
    manager: Optional[JobManager] = None,
) -> int:
    """Convenience module function to prune old jobs."""
    mgr = manager or get_default_job_manager()
    return mgr.cleanup_old_jobs(max_age_seconds=max_age_seconds, cache_db_path=cache_db_path)
