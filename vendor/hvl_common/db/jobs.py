"""
SQLite-Backed Multi-Worker Background Job Pool (`SQLiteJobPool`).
Combines a local `ThreadPoolExecutor` with persistent, optionally encrypted SQLite job state
in the shared cache database so any Gunicorn worker process can submit or poll jobs seamlessly.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Union
import uuid
import zlib

from hvl_common.db.sqlite import _resolve_db_key, get_db_connection

logger = logging.getLogger(__name__)


class SQLiteJobPool:
    """
    Multi-worker safe background job execution pool backed by a shared SQLite `background_jobs` table.
    - Executes background callables on a bounded `ThreadPoolExecutor(max_workers=...)`.
    - Persists job metadata, status (`processing`, `completed`, `failed`), compressed + optionally
      encrypted `result_blob`, and `error` in SQLite so any worker in a multi-worker deployment
      (`--workers 3 --threads 4`) can poll `get_job(job_id, tenant_id)` and retrieve the live state.
    - Maintains an in-memory fast path for local active and terminal jobs.
    - Automatically prunes completed/failed jobs older than `ttl_seconds`.
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
        context_setup_fn: Optional[Callable[[int, str], Any]] = None,
        context_reset_fn: Optional[Callable[[Any], None]] = None,
        service_name: str = "finances",
        telemetry_db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.ttl_seconds = float(ttl_seconds)
        self.max_memory_jobs = max(16, int(max_memory_jobs))
        self._cache_db_path_fn = cache_db_path_fn
        self._encrypt_fn = encrypt_fn
        self._decrypt_fn = decrypt_fn
        self._context_setup_fn = context_setup_fn
        self._context_reset_fn = context_reset_fn
        self._service_name = str(service_name or "finances")
        self._telemetry_db_path = telemetry_db_path

        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=thread_name_prefix,
        )

        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._local_active_jobs: Set[str] = set()
        self._futures: Dict[str, Future[Any]] = {}

        self._init_dbs_lock = threading.Lock()
        self._initialized_dbs: Set[str] = set()

    def _resolve_db_path(
        self, cache_db_path: Optional[Union[str, Path]] = None
    ) -> Optional[Path]:
        target = cache_db_path
        if target is None and self._cache_db_path_fn is not None:
            try:
                target = self._cache_db_path_fn()
            except Exception:
                target = None
        if target is None:
            return None
        return Path(target)

    def _ensure_schema(self, db_path: Path) -> None:
        db_key = _resolve_db_key(db_path)
        if db_key in self._initialized_dbs and db_path.exists():
            return
        with self._init_dbs_lock:
            if db_key in self._initialized_dbs and db_path.exists():
                return
            conn = get_db_connection(db_path, timeout=5.0)
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS background_jobs (
                            job_id TEXT PRIMARY KEY,
                            job_type TEXT NOT NULL,
                            tenant_id INTEGER NOT NULL,
                            universe TEXT NOT NULL DEFAULT 'public',
                            status TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            meta_blob BLOB,
                            result_blob BLOB,
                            error TEXT
                        );
                        """
                    )
                    conn.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_background_jobs_tenant_updated
                            ON background_jobs (tenant_id, updated_at);
                        """
                    )
                self._initialized_dbs.add(db_key)
            finally:
                conn.close()

    def _encode_blob(
        self,
        payload: Any,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    ) -> Optional[bytes]:
        if payload is None:
            return None
        raw = json.dumps(payload, default=str).encode("utf-8")
        compressed = zlib.compress(raw, level=6)
        eff_encrypt = encrypt_fn if encrypt_fn is not None else self._encrypt_fn
        return eff_encrypt(compressed) if eff_encrypt is not None else compressed

    def _decode_blob(
        self,
        blob: Optional[bytes],
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    ) -> Any:
        if blob is None:
            return None
        raw_blob = bytes(blob)
        eff_decrypt = decrypt_fn if decrypt_fn is not None else self._decrypt_fn
        compressed = eff_decrypt(raw_blob) if eff_decrypt is not None else raw_blob
        raw = zlib.decompress(compressed)
        return json.loads(raw.decode("utf-8"))

    def _prune_memory_locked(self, now: float) -> None:
        expired = [
            jid
            for jid, j in self._jobs.items()
            if j.get("status") in ("completed", "failed")
            and (now - float(j.get("updated_at", now))) > self.ttl_seconds
        ]
        for jid in expired:
            self._jobs.pop(jid, None)
            self._futures.pop(jid, None)

        if len(self._jobs) > self.max_memory_jobs:
            # Evict oldest terminal jobs if over capacity
            terminal = sorted(
                (
                    (float(j.get("updated_at", 0.0)), jid)
                    for jid, j in self._jobs.items()
                    if j.get("status") in ("completed", "failed")
                ),
                key=lambda x: x[0],
            )
            excess = len(self._jobs) - self.max_memory_jobs
            for _, jid in terminal[:excess]:
                self._jobs.pop(jid, None)
                self._futures.pop(jid, None)

    def _persist_job_row(
        self,
        db_path: Optional[Path],
        job_record: Dict[str, Any],
        *,
        initial_meta: Optional[Dict[str, Any]] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        prune_now: Optional[float] = None,
    ) -> None:
        if db_path is None:
            return
        try:
            meta_blob = self._encode_blob(initial_meta, encrypt_fn=encrypt_fn) if initial_meta else None
            result_blob = self._encode_blob(job_record.get("result"), encrypt_fn=encrypt_fn)
            self._ensure_schema(db_path)
            conn = get_db_connection(db_path, timeout=5.0)
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO background_jobs (
                            job_id, job_type, tenant_id, universe, status,
                            created_at, updated_at, meta_blob, result_blob, error
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(job_id) DO UPDATE SET
                            status = excluded.status,
                            updated_at = excluded.updated_at,
                            result_blob = excluded.result_blob,
                            error = excluded.error
                        """,
                        (
                            job_record["job_id"],
                            job_record["job_type"],
                            int(job_record["tenant_id"]),
                            str(job_record["universe"]),
                            str(job_record["status"]),
                            float(job_record["created_at"]),
                            float(job_record["updated_at"]),
                            meta_blob,
                            result_blob,
                            job_record.get("error"),
                        ),
                    )
                    if prune_now is not None:
                        cutoff = prune_now - self.ttl_seconds
                        conn.execute(
                            """
                            DELETE FROM background_jobs
                            WHERE status IN ('completed', 'failed') AND updated_at < ?
                            """,
                            (cutoff,),
                        )
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("SQLiteJobPool persistence skipped for %s: %s", job_record.get("job_id"), exc)

    def submit_job(
        self,
        fn: Callable[..., Any],
        *args: Any,
        tenant_id: Optional[int] = None,
        family_id: int = 0,
        universe: str = "public",
        job_type: str = "generic",
        initial_meta: Optional[Dict[str, Any]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Registers a background job ticket, persists it to SQLite `background_jobs`,
        and submits `fn(*args, **kwargs)` to the dedicated `ThreadPoolExecutor`.
        Accepts either `tenant_id` or `family_id` for multi-tenant isolation.
        """
        eff_tid = int(tenant_id if tenant_id is not None else family_id)
        eff_universe = str(universe or "public")
        job_id = uuid.uuid4().hex[:16]
        now = time.time()

        job_record: Dict[str, Any] = {
            "job_id": job_id,
            "job_type": str(job_type),
            "tenant_id": eff_tid,
            "family_id": eff_tid,
            "universe": eff_universe,
            "status": "processing",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None,
        }
        meta_copy = dict(initial_meta) if initial_meta else None
        if meta_copy:
            job_record.update(meta_copy)

        resolved_db = self._resolve_db_path(cache_db_path)

        with self._lock:
            self._prune_memory_locked(now)
            self._jobs[job_id] = dict(job_record)
            self._local_active_jobs.add(job_id)

        self._persist_job_row(
            resolved_db,
            job_record,
            initial_meta=meta_copy,
            encrypt_fn=encrypt_fn,
            prune_now=now,
        )

        def _worker() -> None:
            tokens = None
            job_start = time.perf_counter()
            if self._context_setup_fn is not None:
                try:
                    tokens = self._context_setup_fn(eff_tid, eff_universe)
                except Exception:
                    tokens = None
            try:
                res = fn(*args, **kwargs)
                done_ts = time.time()
                with self._lock:
                    rec = self._jobs.get(job_id, dict(job_record))
                    rec["status"] = "completed"
                    rec["result"] = res
                    rec["updated_at"] = done_ts
                    self._jobs[job_id] = rec
                    self._local_active_jobs.discard(job_id)
                    snapshot = dict(rec)
                self._persist_job_row(
                    resolved_db,
                    snapshot,
                    initial_meta=meta_copy,
                    encrypt_fn=encrypt_fn,
                )
            except Exception as exc:
                logger.warning("Background job %s (%s) failed: %s", job_id, job_type, exc)
                fail_ts = time.time()
                duration_ms = (time.perf_counter() - job_start) * 1000.0
                with self._lock:
                    rec = self._jobs.get(job_id, dict(job_record))
                    rec["status"] = "failed"
                    rec["error"] = str(exc)
                    rec["updated_at"] = fail_ts
                    self._jobs[job_id] = rec
                    self._local_active_jobs.discard(job_id)
                    snapshot = dict(rec)
                self._persist_job_row(
                    resolved_db,
                    snapshot,
                    initial_meta=meta_copy,
                    encrypt_fn=encrypt_fn,
                )
                try:
                    from hvl_common.telemetry.store import (
                        EVENT_JOB_ERROR,
                        record_telemetry_event,
                    )

                    record_telemetry_event(
                        service=self._service_name,
                        event_type=EVENT_JOB_ERROR,
                        method="JOB",
                        path=f"job:{job_type}",
                        status_code=500,
                        duration_ms=duration_ms,
                        error_type=type(exc).__name__,
                        detail=f"Background job '{job_type}' failed ({type(exc).__name__})",
                        db_path=self._telemetry_db_path,
                    )
                except Exception:
                    pass
            finally:
                if self._context_reset_fn is not None and tokens is not None:
                    try:
                        self._context_reset_fn(tokens)
                    except Exception:
                        pass

        fut = self.executor.submit(_worker)
        with self._lock:
            self._futures[job_id] = fut
        return job_id

    def get_job(
        self,
        job_id: str,
        tenant_id: Optional[int] = None,
        *,
        family_id: int = 0,
        cache_db_path: Optional[Union[str, Path]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Thread-safe and multi-worker-safe lookup of a background job by ID.
        Strictly enforces tenant isolation (`tenant_id` / `family_id`).
        Uses the local in-memory fast path when terminal or actively running on this worker,
        and transparently falls back to SQLite `background_jobs` when polled from another worker.
        """
        if not job_id:
            return None
        eff_tid = int(tenant_id if tenant_id is not None else family_id)
        now = time.time()

        with self._lock:
            self._prune_memory_locked(now)
            local_job = self._jobs.get(job_id)
            is_local_active = job_id in self._local_active_jobs
            if local_job is not None:
                job_tid = int(local_job.get("tenant_id", local_job.get("family_id", -1)))
                if job_tid != eff_tid:
                    return None
                if local_job.get("status") in ("completed", "failed") or is_local_active:
                    return dict(local_job)

        resolved_db = self._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            try:
                self._ensure_schema(resolved_db)
                conn = get_db_connection(resolved_db, timeout=5.0)
                try:
                    cur = conn.execute(
                        """
                        SELECT job_id, job_type, tenant_id, universe, status,
                               created_at, updated_at, meta_blob, result_blob, error
                        FROM background_jobs
                        WHERE job_id = ?
                        """,
                        (str(job_id),),
                    )
                    row = cur.fetchone()
                finally:
                    conn.close()

                if row is not None:
                    row_tid = int(row["tenant_id"])
                    if row_tid != eff_tid:
                        return None
                    updated_at = float(row["updated_at"])
                    status = str(row["status"])
                    if status in ("completed", "failed") and (now - updated_at) > self.ttl_seconds:
                        return None

                    meta = self._decode_blob(row["meta_blob"], decrypt_fn=decrypt_fn)
                    result = self._decode_blob(row["result_blob"], decrypt_fn=decrypt_fn)
                    record: Dict[str, Any] = {
                        "job_id": str(row["job_id"]),
                        "job_type": str(row["job_type"]),
                        "tenant_id": row_tid,
                        "family_id": row_tid,
                        "universe": str(row["universe"]),
                        "status": status,
                        "created_at": float(row["created_at"]),
                        "updated_at": updated_at,
                        "result": result,
                        "error": row["error"],
                    }
                    if isinstance(meta, dict):
                        for k, v in meta.items():
                            if k not in record:
                                record[k] = v

                    with self._lock:
                        self._jobs[job_id] = dict(record)
                    return record
            except Exception as exc:
                logger.debug("SQLiteJobPool DB lookup failed for %s: %s", job_id, exc)

        with self._lock:
            if local_job is not None:
                return dict(local_job)
        return None

    def wait_for_job(self, job_id: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Waits for a locally submitted job future to complete (useful in tests)."""
        with self._lock:
            fut = self._futures.get(job_id)
        if fut is not None:
            fut.result(timeout=timeout)
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def clear(self, cache_db_path: Optional[Union[str, Path]] = None) -> None:
        """Clears in-memory job records and SQLite `background_jobs` table."""
        with self._lock:
            self._jobs.clear()
            self._local_active_jobs.clear()
            self._futures.clear()

        resolved_db = self._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            try:
                self._ensure_schema(resolved_db)
                conn = get_db_connection(resolved_db, timeout=5.0)
                try:
                    with conn:
                        conn.execute("DELETE FROM background_jobs")
                finally:
                    conn.close()
            except Exception:
                pass
