"""
SQLite-Backed Multi-Worker Background Job Pool (`SQLiteJobPool`).
Combines a local `ThreadPoolExecutor` with persistent, optionally encrypted SQLite job state
in the shared cache database so any Gunicorn worker process can submit or poll jobs seamlessly.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Union
import uuid
import zlib

from hvl_common.db.job_liveness import (
    ensure_liveness_columns,
    fail_job_if_orphaned,
    fail_orphaned_jobs,
    touch_heartbeats,
)
from hvl_common.db.job_state import (
    ACTIVE_STATES,
    COMPLETED,
    FAILED,
    PROCESSING,
    QUEUED,
    TERMINAL_STATES,
    process_boot_id,
    public_status,
    require_transition,
)
from hvl_common.db.sqlite import _resolve_db_key, get_db_connection

logger = logging.getLogger(__name__)

_JOB_SCHEMA_SQL = (
    "CREATE TABLE IF NOT EXISTS background_jobs ("
    "job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, tenant_id INTEGER NOT NULL, "
    "universe TEXT NOT NULL DEFAULT 'public', status TEXT NOT NULL, "
    "created_at REAL NOT NULL, updated_at REAL NOT NULL, "
    "meta_blob BLOB, result_blob BLOB, error TEXT, "
    "owner_pid INTEGER, owner_boot_id TEXT, heartbeat_at REAL);"
)
_JOB_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_background_jobs_tenant_updated "
    "ON background_jobs (tenant_id, updated_at);"
)
_JOB_UPSERT_SQL = (
    "INSERT INTO background_jobs ("
    "job_id, job_type, tenant_id, universe, status, created_at, updated_at, meta_blob, result_blob, error, "
    "owner_pid, owner_boot_id, heartbeat_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(job_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at, "
    "meta_blob = COALESCE(excluded.meta_blob, background_jobs.meta_blob), "
    "result_blob = excluded.result_blob, error = excluded.error, heartbeat_at = excluded.heartbeat_at "
    "WHERE background_jobs.status IN ('queued', 'processing')"
)
_JOB_SELECT_SQL = (
    "SELECT job_id, job_type, tenant_id, universe, status, created_at, updated_at, meta_blob, result_blob, error "
    "FROM background_jobs WHERE job_id = ?"
)

# Set while a job's callable runs: publishes a partial result any worker's `get_job` returns as `progress`.
_current_progress_publisher: ContextVar[Optional[Callable[[Dict[str, Any]], bool]]] = ContextVar(
    "hvl_job_progress_publisher", default=None
)


def current_job_progress_publisher() -> Optional[Callable[[Dict[str, Any]], bool]]:
    """The running job's progress publisher, or None outside a background job (sync mode, tests, scripts).

    Capture it on the job's own thread: threads the job starts do not inherit it. Calling it after the
    job finished is a no-op that returns False, so a late progress update never overwrites the result."""
    return _current_progress_publisher.get()


class SQLiteJobPool:
    """
    Multi-worker safe background job execution pool backed by a shared SQLite `background_jobs` table.
    - Executes background callables on a bounded `ThreadPoolExecutor(max_workers=...)`.
    - Persists job metadata, lifecycle state (`queued` -> `processing` -> `completed` | `failed`, see
      `hvl_common.db.job_state`), compressed + optionally encrypted `result_blob`, and `error` in SQLite
      so any worker in a multi-worker deployment can poll `get_job(job_id, tenant_id)`.
    - Records the owning process (`owner_pid`, `owner_boot_id`) and refreshes `heartbeat_at` while a job
      runs. Active rows whose owner died (restart/deploy) are marked `failed` on worker boot and on poll.
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
        service_name: str = "generic",
        telemetry_db_path: Optional[Union[str, Path]] = None,
        heartbeat_interval: float = 10.0,
        stale_after: float = 60.0,
        boot_id: Optional[str] = None,
    ) -> None:
        self.heartbeat_interval = max(0.01, float(heartbeat_interval))
        self.stale_after = float(stale_after)
        self._boot_id_override = boot_id
        self.max_workers = max(1, int(max_workers))
        self.ttl_seconds = float(ttl_seconds)
        self.max_memory_jobs = max(16, int(max_memory_jobs))
        self._cache_db_path_fn = cache_db_path_fn
        self._encrypt_fn = encrypt_fn
        self._decrypt_fn = decrypt_fn
        self._context_setup_fn = context_setup_fn
        self._context_reset_fn = context_reset_fn
        self._service_name = str(service_name or "generic")
        self._telemetry_db_path = telemetry_db_path

        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._local_active_jobs: Set[str] = set()
        self._futures: Dict[str, Future[Any]] = {}
        self._cancelled: Set[str] = set()
        self._active_dbs: Dict[str, Path] = {}
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._init_dbs_lock = threading.Lock()
        self._initialized_dbs: Set[str] = set()

    @property
    def boot_id(self) -> str:
        return self._boot_id_override or process_boot_id()

    def _resolve_db_path(self, cache_db_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
        target = cache_db_path
        if target is None and self._cache_db_path_fn is not None:
            target = self._cache_db_path_fn()
        return Path(target) if target is not None else None

    def _ensure_schema(self, db_path: Path) -> None:
        db_key = _resolve_db_key(db_path)
        if db_key in self._initialized_dbs and db_path.exists():
            return
        with self._init_dbs_lock:
            if db_key in self._initialized_dbs and db_path.exists():
                return
            with get_db_connection(db_path, timeout=5.0) as conn:
                with conn:
                    conn.execute(_JOB_SCHEMA_SQL)
                    conn.execute(_JOB_INDEX_SQL)
                    ensure_liveness_columns(conn)
                # Worker boot: rows left active by a dead incarnation can never finish.
                failed = fail_orphaned_jobs(
                    conn, own_boot_id=self.boot_id, now=time.time(), stale_after=self.stale_after
                )
                if failed:
                    logger.warning("Marked %d orphaned background job(s) failed on boot: %s", len(failed), failed)
            self._initialized_dbs.add(db_key)

    def _encode_blob(self, payload: Any, encrypt_fn: Optional[Callable[[bytes], bytes]] = None) -> Optional[bytes]:
        if payload is None:
            return None
        compressed = zlib.compress(json.dumps(payload, default=str).encode("utf-8"), level=6)
        eff_encrypt = encrypt_fn if encrypt_fn is not None else self._encrypt_fn
        return eff_encrypt(compressed) if eff_encrypt is not None else compressed

    def _decode_blob(self, blob: Optional[bytes], decrypt_fn: Optional[Callable[[bytes], bytes]] = None) -> Any:
        if blob is None:
            return None
        raw_blob = bytes(blob)
        eff_decrypt = decrypt_fn if decrypt_fn is not None else self._decrypt_fn
        compressed = eff_decrypt(raw_blob) if eff_decrypt is not None else raw_blob
        return json.loads(zlib.decompress(compressed).decode("utf-8"))

    def _prune_memory_locked(self, now: float) -> None:
        expired = [
            jid
            for jid, j in self._jobs.items()
            if j.get("status") in TERMINAL_STATES
            and (now - float(j.get("updated_at", now))) > self.ttl_seconds
        ]
        for jid in expired:
            self._jobs.pop(jid, None)
            self._futures.pop(jid, None)
            self._cancelled.discard(jid)

        if len(self._jobs) > self.max_memory_jobs:
            terminal = sorted(
                ((float(j.get("updated_at", 0.0)), jid) for jid, j in self._jobs.items() if j.get("status") in TERMINAL_STATES),
                key=lambda x: x[0],
            )
            for _, jid in terminal[: len(self._jobs) - self.max_memory_jobs]:
                self._jobs.pop(jid, None)
                self._futures.pop(jid, None)
                self._cancelled.discard(jid)

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
                    cur = conn.execute(
                        _JOB_UPSERT_SQL,
                        (
                            job_record["job_id"],
                            job_record["job_type"],
                            int(job_record["tenant_id"]),
                            str(job_record["universe"]),
                            str(job_record["phase"]),
                            float(job_record["created_at"]),
                            float(job_record["updated_at"]),
                            meta_blob,
                            result_blob,
                            job_record.get("error"),
                            job_record.get("owner_pid"),
                            job_record.get("owner_boot_id"),
                            job_record.get("heartbeat_at"),
                        ),
                    )
                    if cur.rowcount == 0:
                        logger.warning(
                            "Job %s -> %s ignored: its row is already terminal (marked failed by orphan recovery)",
                            job_record["job_id"],
                            job_record["phase"],
                        )
                    if prune_now is not None:
                        conn.execute(
                            "DELETE FROM background_jobs WHERE status IN ('completed', 'failed') AND updated_at < ?",
                            (prune_now - self.ttl_seconds,),
                        )
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            # Only the SQLite write is best-effort (the in-memory record stays authoritative for this process).
            # An unserializable result or a failing encrypt_fn is a bug and fails the job.
            logger.warning("SQLiteJobPool persistence skipped for %s: %s", job_record.get("job_id"), exc)

    def _advance(
        self, job_id: str, base: Dict[str, Any], new_state: str, **fields: Any
    ) -> Optional[Dict[str, Any]]:
        """Validated in-memory lifecycle transition. Returns a snapshot of the updated record, or None when
        the job was cancelled (`cancel_job` already made it terminal, so the worker must stop reporting)."""
        with self._lock:
            if job_id in self._cancelled:
                return None
            rec = self._jobs.get(job_id, dict(base))
            require_transition(job_id, str(rec["phase"]), new_state)
            now = time.time()
            rec.update(phase=new_state, status=public_status(new_state), updated_at=now, heartbeat_at=now, **fields)
            self._jobs[job_id] = rec
            if new_state in TERMINAL_STATES:
                self._local_active_jobs.discard(job_id)
                self._active_dbs.pop(job_id, None)
            return dict(rec)

    def _ensure_heartbeat_locked(self) -> None:
        thread = self._heartbeat_thread
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=self._heartbeat_loop, name="hvl_job_heartbeat", daemon=True)
            self._heartbeat_thread = thread
            thread.start()

    def _heartbeat_loop(self) -> None:
        """Refreshes `heartbeat_at` for locally running jobs; exits once none are active."""
        while not self._heartbeat_stop.wait(self.heartbeat_interval):
            with self._lock:
                by_db: Dict[Path, list] = {}
                for jid, db in self._active_dbs.items():
                    by_db.setdefault(db, []).append(jid)
                if not by_db:
                    self._heartbeat_thread = None
                    return
            for db, ids in by_db.items():
                try:
                    with get_db_connection(db, timeout=5.0) as conn:
                        touch_heartbeats(conn, ids, time.time())
                except sqlite3.Error as exc:
                    logger.warning("Job heartbeat write failed for %s: %s", db, exc)

    def submit_job(
        self,
        fn: Callable[..., Any],
        *args: Any,
        tenant_id: Optional[int] = None,
        universe: str = "public",
        job_type: str = "generic",
        initial_meta: Optional[Dict[str, Any]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        **kwargs: Any,
    ) -> str:
        """Registers a `queued` job ticket, persists it to SQLite, and submits `fn(*args, **kwargs)` to the executor."""
        eff_tid = int(tenant_id if tenant_id is not None else 0)
        eff_universe = str(universe or "public")
        job_id = uuid.uuid4().hex[:16]
        now = time.time()

        job_record: Dict[str, Any] = {
            "job_id": job_id,
            "job_type": str(job_type),
            "tenant_id": eff_tid,
            "universe": eff_universe,
            "phase": QUEUED,
            "status": public_status(QUEUED),
            "created_at": now,
            "updated_at": now,
            "heartbeat_at": now,
            "owner_pid": os.getpid(),
            "owner_boot_id": self.boot_id,
            "result": None,
            "error": None,
        }
        meta_copy = dict(initial_meta) if initial_meta else None
        if meta_copy:
            # Caller meta never overrides the ticket's own fields: the in-memory tenant check reads tenant_id.
            job_record = {**meta_copy, **job_record}

        resolved_db = self._resolve_db_path(cache_db_path)
        with self._lock:
            self._prune_memory_locked(now)
            self._jobs[job_id] = dict(job_record)
            self._local_active_jobs.add(job_id)
            if resolved_db is not None:
                self._active_dbs[job_id] = resolved_db
                self._ensure_heartbeat_locked()

        self._persist_job_row(resolved_db, job_record, initial_meta=meta_copy, encrypt_fn=encrypt_fn, prune_now=now)

        def _publish_progress(progress: Dict[str, Any]) -> bool:
            with self._lock:
                rec = self._jobs.get(job_id)
                if rec is None or rec.get("phase") != PROCESSING:
                    return False
                rec.update({"progress": dict(progress), "updated_at": time.time()})
                snapshot = dict(rec)
            self._persist_job_row(
                resolved_db, snapshot, initial_meta={**(meta_copy or {}), "progress": dict(progress)}, encrypt_fn=encrypt_fn,
            )
            return True

        def _worker() -> None:
            tokens = None
            job_start = time.perf_counter()
            running = self._advance(job_id, job_record, PROCESSING)
            if running is None:
                return
            self._persist_job_row(resolved_db, running, initial_meta=meta_copy, encrypt_fn=encrypt_fn)
            publisher_token = _current_progress_publisher.set(_publish_progress)
            try:
                if self._context_setup_fn is not None:
                    tokens = self._context_setup_fn(eff_tid, eff_universe)
                res = fn(*args, **kwargs)
                snapshot = self._advance(job_id, job_record, COMPLETED, result=res)
                if snapshot is not None:
                    self._persist_job_row(resolved_db, snapshot, initial_meta=meta_copy, encrypt_fn=encrypt_fn)
            except Exception as exc:
                logger.warning("Background job %s (%s) failed: %s", job_id, job_type, exc)
                duration_ms = (time.perf_counter() - job_start) * 1000.0
                snapshot = self._advance(job_id, job_record, FAILED, error=str(exc))
                if snapshot is None:
                    return
                self._persist_job_row(resolved_db, snapshot, initial_meta=meta_copy, encrypt_fn=encrypt_fn)
                try:
                    from hvl_common.telemetry.store import EVENT_JOB_ERROR, record_telemetry_event

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
                except (sqlite3.Error, OSError) as tel_exc:
                    logger.warning("Job error telemetry for %s not recorded: %s", job_id, tel_exc)
            finally:
                _current_progress_publisher.reset(publisher_token)
                if self._context_reset_fn is not None and tokens is not None:
                    self._context_reset_fn(tokens)

        fut = self.executor.submit(_worker)
        with self._lock:
            self._futures[job_id] = fut
        return job_id

    def _record_from_row(self, row: sqlite3.Row, decrypt_fn: Optional[Callable[[bytes], bytes]]) -> Dict[str, Any]:
        state = str(row["status"])
        meta = self._decode_blob(row["meta_blob"], decrypt_fn=decrypt_fn)
        record: Dict[str, Any] = {
            "job_id": str(row["job_id"]),
            "job_type": str(row["job_type"]),
            "tenant_id": int(row["tenant_id"]),
            "universe": str(row["universe"]),
            "phase": state,
            "status": public_status(state),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "result": self._decode_blob(row["result_blob"], decrypt_fn=decrypt_fn),
            "error": row["error"],
        }
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k not in record:
                    record[k] = v
        return record

    def get_job(
        self,
        job_id: str,
        tenant_id: Optional[int] = None,
        *,
        cache_db_path: Optional[Union[str, Path]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Thread-safe and multi-worker-safe lookup of a background job by ID with strict tenant isolation.
        An active row whose owning worker is gone is marked `failed` here so pollers stop waiting.
        """
        if not job_id:
            return None
        eff_tid = int(tenant_id if tenant_id is not None else 0)
        now = time.time()

        with self._lock:
            self._prune_memory_locked(now)
            local_job = self._jobs.get(job_id)
            is_local_active = job_id in self._local_active_jobs
            if local_job is not None:
                job_tid = int(local_job.get("tenant_id", -1))
                if job_tid != eff_tid:
                    return None
                if local_job.get("status") in TERMINAL_STATES or is_local_active:
                    return dict(local_job)

        resolved_db = self._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            try:
                self._ensure_schema(resolved_db)
                with get_db_connection(resolved_db, timeout=5.0) as conn:
                    fail_job_if_orphaned(
                        conn, str(job_id), own_boot_id=self.boot_id, now=now, stale_after=self.stale_after
                    )
                    row = conn.execute(_JOB_SELECT_SQL, (str(job_id),)).fetchone()

                if row is not None:
                    if int(row["tenant_id"]) != eff_tid:
                        return None
                    record = self._record_from_row(row, decrypt_fn)
                    if record["status"] in TERMINAL_STATES and (now - record["updated_at"]) > self.ttl_seconds:
                        return None
                    with self._lock:
                        self._jobs[job_id] = dict(record)
                    return record
            except (sqlite3.Error, OSError) as exc:
                logger.warning("SQLiteJobPool DB lookup failed for %s; using the in-memory record: %s", job_id, exc)

        with self._lock:
            return dict(local_job) if local_job is not None else None

    def cancel_job(
        self,
        job_id: str,
        tenant_id: Optional[int] = None,
        *,
        cache_db_path: Optional[Union[str, Path]] = None,
        reason: str = "Cancelled",
    ) -> bool:
        """
        Cancels an active (`queued` | `processing`) job owned by `tenant_id`; another tenant's job is never touched.
        The SQLite row is marked `failed` with `error=reason` so every worker's poller sees it. When the job runs
        in this process its future is cancelled if still queued, and a running callable's late result is
        discarded (a Python thread cannot be killed; the callable should poll for interruption itself).
        Returns True when this call made an active job terminal.
        """
        if not job_id:
            return False
        eff_tid = int(tenant_id if tenant_id is not None else 0)
        jid = str(job_id).strip()
        cancelled = False
        with self._lock:
            rec = self._jobs.get(jid)
            if rec is not None:
                if int(rec.get("tenant_id", -1)) != eff_tid:
                    return False
                if rec.get("phase") in ACTIVE_STATES:
                    require_transition(jid, str(rec["phase"]), FAILED)
                    self._cancelled.add(jid)
                    fut = self._futures.get(jid)
                    if fut is not None:
                        fut.cancel()
                    now = time.time()
                    rec.update(phase=FAILED, status=public_status(FAILED), updated_at=now, heartbeat_at=now, error=reason)
                    self._local_active_jobs.discard(jid)
                    self._active_dbs.pop(jid, None)
                    cancelled = True
        resolved_db = self._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            self._ensure_schema(resolved_db)
            with get_db_connection(resolved_db, timeout=5.0) as conn:
                with conn:
                    cur = conn.execute(
                        "UPDATE background_jobs SET status = ?, error = ?, updated_at = ? "
                        "WHERE job_id = ? AND tenant_id = ? AND status IN ('queued', 'processing')",
                        (FAILED, reason, time.time(), jid, eff_tid),
                    )
            cancelled = cancelled or cur.rowcount > 0
        return cancelled

    def shutdown(self, wait: bool = False) -> None:
        """Stops the heartbeat thread and the executor (idempotent)."""
        self._heartbeat_stop.set()
        self.executor.shutdown(wait=wait)

    def list_local_jobs(
        self, *, status: Optional[str] = None, job_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Snapshot of jobs this process knows about, optionally filtered by public `status` and `job_type`."""
        with self._lock:
            return [
                dict(rec)
                for rec in self._jobs.values()
                if (status is None or rec.get("status") == status)
                and (job_type is None or rec.get("job_type") == job_type)
            ]

    def prune_terminal(
        self,
        max_age_seconds: Optional[float] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> int:
        """Removes completed/failed jobs older than `max_age_seconds` from RAM and SQLite. Returns the count."""
        max_age = float(max_age_seconds if max_age_seconds is not None else self.ttl_seconds)
        cutoff = time.time() - max_age
        with self._lock:
            expired = [
                jid
                for jid, rec in self._jobs.items()
                if rec.get("status") in TERMINAL_STATES and float(rec.get("updated_at", 0.0)) < cutoff
            ]
            for jid in expired:
                self._jobs.pop(jid, None)
                self._futures.pop(jid, None)
                self._cancelled.discard(jid)
        purged = len(expired)

        resolved_db = self._resolve_db_path(cache_db_path)
        if resolved_db is not None and resolved_db.exists():
            try:
                self._ensure_schema(resolved_db)
                with get_db_connection(resolved_db, timeout=5.0) as conn:
                    cur = conn.execute(
                        "DELETE FROM background_jobs WHERE status IN ('completed', 'failed') AND updated_at < ?",
                        (cutoff,),
                    )
                    purged += int(cur.rowcount or 0)
            except (sqlite3.Error, OSError) as exc:
                logger.warning("SQLiteJobPool prune_terminal DB error: %s", exc)
        return purged

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
            self._cancelled.clear()

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
            except (sqlite3.Error, OSError) as exc:
                logger.warning("SQLiteJobPool clear DB error: %s", exc)
