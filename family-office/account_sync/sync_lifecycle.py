"""
account_sync/sync_lifecycle.py: explicit per-provider sync lifecycle (a validated FSM with a lease).

States: idle -> running -> succeeded | partial | failed, and any finished state -> running again. A `running`
record carries a lease; a crashed worker's lease expires and the next sync may take over, while a live lease
makes an overlapping sync fail fast (`SyncInProgress`) instead of racing. The record lives at
`providers[provider]["run"]` of `last_sync_metadata`, written inside the same `BEGIN IMMEDIATE` transaction
as every other sync-metadata write, so provider entries never clobber each other.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Union
from pathlib import Path
import uuid

from account_sync.sync_outcome import result_status
from db.sync_metadata import RUN_KEY, load_provider_sync_entry, update_provider_sync_entry

IDLE, RUNNING, SUCCEEDED, PARTIAL, FAILED = "idle", "running", "succeeded", "partial", "failed"
FINISHED = (SUCCEEDED, PARTIAL, FAILED)
TRANSITIONS: Dict[str, tuple[str, ...]] = {
    IDLE: (RUNNING,),
    RUNNING: (IDLE, SUCCEEDED, PARTIAL, FAILED),
    SUCCEEDED: (RUNNING,),
    PARTIAL: (RUNNING,),
    FAILED: (RUNNING,),
}
DEFAULT_LEASE_SECONDS = 15 * 60
_RESULT_TO_STATE = {"success": SUCCEEDED, "partial": PARTIAL, "failed": FAILED}


class SyncTransitionError(RuntimeError):
    """An illegal lifecycle transition (including finishing a run whose lease was lost)."""


class SyncInProgress(SyncTransitionError):
    """Another sync for the same provider holds a live lease."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _lease_expired(run: Dict[str, Any], now: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(run["lease_expires_at"])) <= now
    except (KeyError, ValueError):
        return True


def state_of(run: Optional[Dict[str, Any]]) -> str:
    return str((run or {}).get("state") or IDLE)


def start_run(run: Optional[Dict[str, Any]], *, now: datetime, lease_seconds: int) -> Dict[str, Any]:
    """Pure: returns the `running` record for a new run, or raises `SyncInProgress` while a live lease exists."""
    current = state_of(run)
    if current == RUNNING and not _lease_expired(run or {}, now):
        raise SyncInProgress(f"A sync is already running (run {(run or {}).get('run_id')}).")
    if current != RUNNING and RUNNING not in TRANSITIONS.get(current, ()):
        raise SyncTransitionError(f"Illegal sync transition {current} -> {RUNNING}.")
    return {
        "state": RUNNING,
        "run_id": uuid.uuid4().hex,
        "started_at": _iso(now),
        "lease_expires_at": _iso(now + timedelta(seconds=lease_seconds)),
        "finished_at": None,
        "error": None,
        "took_over_from": (run or {}).get("run_id") if current == RUNNING else None,
    }


def finish_run(
    run: Optional[Dict[str, Any]], run_id: str, to_state: str, *, now: datetime, error: Optional[str] = None
) -> Dict[str, Any]:
    """Pure: returns the finished record, or raises if `run_id` no longer owns a `running` record."""
    current = state_of(run)
    if to_state not in TRANSITIONS.get(current, ()):
        raise SyncTransitionError(f"Illegal sync transition {current} -> {to_state}.")
    if (run or {}).get("run_id") != run_id:
        raise SyncTransitionError(f"Sync run {run_id} lost its lease to {(run or {}).get('run_id')}.")
    return {**(run or {}), "state": to_state, "finished_at": _iso(now), "lease_expires_at": None, "error": error}


def begin_sync(
    db_path: Union[str, Path], family_id: int, provider: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: Optional[datetime] = None,
) -> str:
    """Atomically acquires the provider's lease and returns the new `run_id` (raises `SyncInProgress`)."""
    started: Dict[str, Any] = {}

    def _mutate(entry: Dict[str, Any]) -> Dict[str, Any]:
        started.update(start_run(entry.get(RUN_KEY), now=now or _now(), lease_seconds=lease_seconds))
        return {**entry, RUN_KEY: dict(started)}

    update_provider_sync_entry(db_path, family_id, provider, _mutate, notify=False)
    return str(started["run_id"])


def finish_sync(
    db_path: Union[str, Path], family_id: int, provider: str, run_id: str, to_state: str,
    *, error: Optional[str] = None, now: Optional[datetime] = None,
) -> None:
    """Atomically records the outcome of `run_id`; raises `SyncTransitionError` when the lease was lost."""

    def _mutate(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {**entry, RUN_KEY: finish_run(entry.get(RUN_KEY), run_id, to_state, now=now or _now(), error=error)}

    update_provider_sync_entry(db_path, family_id, provider, _mutate, notify=to_state != IDLE)


def current_sync_run(db_path: Union[str, Path], family_id: int, provider: str) -> Dict[str, Any]:
    """Returns the provider's lifecycle record (`{"state": "idle"}` when it has never synced)."""
    run = load_provider_sync_entry(db_path, family_id, provider).get(RUN_KEY)
    return dict(run) if isinstance(run, dict) else {"state": IDLE}


def run_provider_sync(
    db_path: Union[str, Path], family_id: int, provider: str, sync_fn: Callable[[], Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Runs `sync_fn` inside the provider's lease: overlapping syncs fail fast, the outcome (success / partial /
    failed) is recorded, a provider that is not connected releases back to idle, and exceptions record `failed`.
    """
    if not Path(db_path).exists():
        return sync_fn()  # nothing to record the lifecycle in yet (never create a database just to track a sync)
    try:
        run_id = begin_sync(db_path, family_id, provider)
    except SyncInProgress as exc:
        return {"success": False, "status": "failed", "provider": provider, "error": str(exc), "in_progress": True}
    try:
        result = sync_fn()
    except BaseException as exc:
        finish_sync(db_path, family_id, provider, run_id, FAILED, error=f"{type(exc).__name__}")
        raise
    if result.get("status") == "not_connected":
        finish_sync(db_path, family_id, provider, run_id, IDLE)
    else:
        outcome = result_status(result)
        finish_sync(db_path, family_id, provider, run_id, _RESULT_TO_STATE[outcome], error=result.get("error"))
    return result
