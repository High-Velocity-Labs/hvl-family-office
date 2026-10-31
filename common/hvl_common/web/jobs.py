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
from typing import Any, Callable, Dict, Optional, Union

from hvl_common.db.jobs import SQLiteJobPool, current_job_progress_publisher

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


def prune_expired_jobs(
    pool: SQLiteJobPool,
    max_age_seconds: Optional[float] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Prunes terminal (completed or failed) jobs older than max_age_seconds from RAM and SQLite."""
    return pool.prune_terminal(max_age_seconds=max_age_seconds, cache_db_path=cache_db_path)


class JobManager:
    """
    Generic, reusable background job manager for High Velocity Labs web applications.
    Wraps an underlying SQLiteJobPool to offer both fast in-memory execution and
    cross-worker SQLite persistence, with flexible metadata support (team_id, week, etc.).
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
        eff_tid = int(tenant_id if tenant_id is not None else 0)
        meta = dict(initial_meta) if initial_meta else {}
        if tenant_id is not None and "tenant_id" not in meta:
            meta["tenant_id"] = tenant_id

        return self.pool.submit_job(
            fn,
            *args,
            tenant_id=eff_tid,
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
        tenant_id: Optional[int] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        **extra_filters: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves job status and payload by `job_id`.
        Always verifies tenant isolation: there is no cross-tenant lookup. When no `tenant_id`
        is given the lookup is for tenant 0, the tenant `submit_job` assigns when it is
        also called without one (single-tenant apps). Optionally filters by arbitrary metadata
        matching extra_filters (e.g. team_id, week).
        """
        if not job_id:
            return None

        eff_tid = int(tenant_id if tenant_id is not None else 0)
        rec = self.pool.get_job(
            str(job_id).strip(),
            tenant_id=eff_tid,
            cache_db_path=cache_db_path,
            decrypt_fn=decrypt_fn,
        )
        if rec is None:
            return None
        for k, expected_v in extra_filters.items():
            if rec.get(k) != expected_v:
                return None
        return rec

    def cancel_job(
        self,
        job_id: str,
        tenant_id: Optional[int] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
        reason: str = "Cancelled",
    ) -> bool:
        """Tenant-checked cancel of an active job (see `SQLiteJobPool.cancel_job`). True if it was cancelled."""
        eff_tid = int(tenant_id if tenant_id is not None else 0)
        return self.pool.cancel_job(str(job_id or "").strip(), tenant_id=eff_tid, cache_db_path=cache_db_path, reason=reason)

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
        return prune_expired_jobs(self.pool, max_age_seconds=max_age_seconds, cache_db_path=cache_db_path)

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
        tenant_id=tenant_id,
        universe=universe,
        initial_meta=initial_meta,
        cache_db_path=cache_db_path,
        encrypt_fn=encrypt_fn,
        **kwargs,
    )


def get_job(
    job_id: str,
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
        tenant_id=tenant_id,
        cache_db_path=cache_db_path,
        decrypt_fn=decrypt_fn,
        **extra_filters,
    )


def cancel_job(
    job_id: str,
    tenant_id: Optional[int] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
    reason: str = "Cancelled",
    manager: Optional[JobManager] = None,
) -> bool:
    """Convenience module function to cancel an active job for a tenant."""
    mgr = manager or get_default_job_manager()
    return mgr.cancel_job(job_id, tenant_id=tenant_id, cache_db_path=cache_db_path, reason=reason)


def cleanup_old_jobs(
    max_age_seconds: Optional[float] = None,
    cache_db_path: Optional[Union[str, Path]] = None,
    manager: Optional[JobManager] = None,
) -> int:
    """Convenience module function to prune old jobs."""
    mgr = manager or get_default_job_manager()
    return mgr.cleanup_old_jobs(max_age_seconds=max_age_seconds, cache_db_path=cache_db_path)


__all__ = [
    "JobManager",
    "_parse_bool_flag",
    "cancel_job",
    "cleanup_old_jobs",
    "current_job_progress_publisher",
    "get_default_job_manager",
    "get_job",
    "prune_expired_jobs",
    "should_run_synchronously",
    "submit_job",
]
