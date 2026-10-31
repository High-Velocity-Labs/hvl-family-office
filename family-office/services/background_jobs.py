"""
background_jobs.py: Dedicated non-blocking background execution pool.
Delegates to `hvl_common.web.jobs.JobManager` and `hvl_common.db.SQLiteJobPool` so any Gunicorn worker process (`--workers 3 --threads 4`)
can submit or poll background jobs (Gemini LLM tool-calling, Monarch GraphQL sync) via the
universe-isolated SQLite cache database (`global_cache.db` / `{family_id}_cache.db`)
with per-family Fernet encryption at rest.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import config
from config import get_cache_db_path_for_universe, get_family_db_path, get_global_db_path
from db.job_orphans import fail_orphaned_jobs_in_cache
from hvl_common.db import SQLiteJobPool
from hvl_common.web.jobs import JobManager, should_run_synchronously
from services.request_context import (
    can_mutate,
    get_current_cache_db_path,
    get_current_db_path,
    get_current_universe,
    reset_background_context,
    set_background_context,
)
import security

__all__ = ["should_run_synchronously"]

logger = logging.getLogger(__name__)


def _resolve_job_cache_db_path(universe: Optional[str] = None) -> Path:
    u = str(universe or "").strip().lower()
    if os.getenv("APP_UNIVERSE", "").strip().lower() == "test" and u in ("", "public", "test"):
        return get_cache_db_path_for_universe("test")
    try:
        active_univ = get_current_universe()
        if not u or u == str(active_univ).lower():
            return get_current_cache_db_path()
    except Exception:
        pass
    return get_cache_db_path_for_universe(u or "public")


def _resolve_job_primary_db_path(universe: Optional[str] = None, family_id: int = 0) -> Path:
    u = str(universe or "").strip().lower()
    if family_id and int(family_id) > 0:
        return get_family_db_path(int(family_id), universe=u or "public")
    if os.getenv("APP_UNIVERSE", "").strip().lower() == "test" and u in ("", "public", "test"):
        return get_global_db_path("test")
    try:
        active_univ = get_current_universe()
        if not u or u == str(active_univ).lower():
            return get_current_db_path()
    except Exception:
        pass
    return get_global_db_path(u or "public")


def _get_family_fernet(family_id: int, universe: Optional[str] = None, fek: Optional[bytes] = None):
    """Household jobs encrypt only under the household FEK (never the root key); tenantless jobs use the root key."""
    if fek:
        return security._get_fernet(fek)
    if not family_id or family_id <= 0:
        return security._get_fernet(None)
    primary_db = _resolve_job_primary_db_path(universe, family_id=family_id)
    if not primary_db.exists():
        raise FileNotFoundError(f"Household {family_id} database not found for background job encryption")
    return security._get_fernet(security.get_family_key(primary_db, int(family_id)))


def _make_job_encrypt_fn(
    family_id: int, universe: Optional[str] = None, fek: Optional[bytes] = None
) -> Callable[[bytes], bytes]:
    def _encrypt(data: bytes) -> bytes:
        f = _get_family_fernet(family_id, universe, fek=fek)
        return f.encrypt(data) if f is not None else data

    return _encrypt


def _make_job_decrypt_fn(family_id: int, universe: Optional[str] = None) -> Callable[[bytes], bytes]:
    def _decrypt(token: bytes) -> bytes:
        # The polling request's own FEK (cookie/session) opens a ticket; a sandbox household has no server escrow.
        fek = security.get_request_vault_fek(family_id) if family_id and int(family_id) > 0 else None
        return _get_family_fernet(family_id, universe, fek=fek).decrypt(token)

    return _decrypt


JOB_POOL = SQLiteJobPool(
    max_workers=4,
    thread_name_prefix="fo_bg_worker",
    ttl_seconds=3600.0,
    max_memory_jobs=500,
    cache_db_path_fn=get_current_cache_db_path,
    context_setup_fn=lambda tid, univ: set_background_context(family_id=tid, universe=univ),
    context_reset_fn=reset_background_context,
    service_name="finances",
)

JOB_MANAGER = JobManager(pool=JOB_POOL)

# Dedicated background pool completely separate from Gunicorn request threads
EXECUTOR = JOB_MANAGER.executor

_RECOVERY_LOCK = threading.Lock()
_recovered_in_this_process = False


def recover_orphaned_jobs() -> list[str]:
    """
    F-AI-7: marks every `queued`/`processing` ticket in every universe's job cache database `failed` when its
    owning worker is gone (restart, deploy, crash), using `hvl_common.db.job_liveness` (the pool's own rule).
    The pool also does this per database on first use and on each poll; this sweep makes it happen once per
    process for all of them, so a poller never waits on a ticket nobody is running. Returns the failed job ids.
    """
    failed: list[str] = []
    for universe in config.VALID_UNIVERSES:
        cache_db = get_cache_db_path_for_universe(universe)
        if not cache_db.exists():
            continue
        try:
            failed += fail_orphaned_jobs_in_cache(
                cache_db, own_boot_id=JOB_POOL.boot_id, stale_after=JOB_POOL.stale_after
            )
        except Exception as exc:
            logger.warning("Orphaned-job sweep skipped %s: %s", cache_db, exc)
    if failed:
        logger.warning("Marked %d orphaned background job(s) failed: %s", len(failed), failed)
    return failed


def _recover_once_per_process() -> None:
    global _recovered_in_this_process
    if _recovered_in_this_process:
        return
    with _RECOVERY_LOCK:
        if _recovered_in_this_process:
            return
        _recovered_in_this_process = True
        recover_orphaned_jobs()


def submit_job(
    fn: Callable[..., Any],
    *args: Any,
    family_id: int = 0,
    universe: str = "public",
    job_type: str = "generic",
    initial_meta: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> str:
    """
    Registers a background job ticket in `JobManager` and submits `fn(*args, **kwargs)`
    to the dedicated ThreadPoolExecutor while preserving `family_id`, `universe`, and
    any ephemeral request `vault_fek` context.
    Returns the `job_id` immediately (<1ms).
    """
    _recover_once_per_process()
    fid = int(family_id or 0)
    univ = str(universe or "public")
    cache_db = _resolve_job_cache_db_path(univ)
    captured_fek = security.get_request_vault_fek(fid) if fid > 0 else None
    # Resolve the ticket key now: a locked vault raises PermissionError to the caller (403) instead of the
    # job pool swallowing the encryption error later and leaving pollers on other workers with no ticket.
    _get_family_fernet(fid, univ, fek=captured_fek)
    captured_can_mutate = can_mutate()
    orig_fn = fn

    def _wrapped_fn(*w_args: Any, **w_kwargs: Any) -> Any:
        tok = set_background_context(
            family_id=fid, universe=univ, vault_fek=captured_fek, can_mutate=captured_can_mutate,
        )
        try:
            return orig_fn(*w_args, **w_kwargs)
        finally:
            reset_background_context(tok)

    target_fn: Callable[..., Any] = _wrapped_fn

    # FO keeps `family_id` in the ticket meta (pollers and tenant checks read it); the shared pool is tenant-keyed.
    return JOB_MANAGER.submit_job(
        target_fn,
        *args,
        tenant_id=fid,
        universe=univ,
        job_type=job_type,
        initial_meta={"family_id": fid, **(initial_meta or {})},
        cache_db_path=cache_db,
        encrypt_fn=_make_job_encrypt_fn(fid, univ, fek=captured_fek),
        **kwargs,
    )


def get_job(job_id: str, family_id: int = 0) -> Optional[Dict[str, Any]]:
    """
    Thread-safe and multi-worker-safe lookup of a background job by ID.
    Strictly enforces multi-tenant isolation by verifying `family_id`.
    """
    _recover_once_per_process()
    fid = int(family_id or 0)
    univ = get_current_universe()
    cache_db = _resolve_job_cache_db_path(univ)
    return JOB_MANAGER.get_job(
        job_id,
        tenant_id=fid,
        cache_db_path=cache_db,
        decrypt_fn=_make_job_decrypt_fn(fid, univ),
    )


def cleanup_old_jobs(max_age_seconds: Optional[float] = None) -> int:
    """Prunes expired jobs from memory and universe SQLite cache."""
    univ = get_current_universe()
    cache_db = _resolve_job_cache_db_path(univ)
    return JOB_MANAGER.cleanup_old_jobs(max_age_seconds=max_age_seconds, cache_db_path=cache_db)
