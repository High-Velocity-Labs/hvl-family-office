"""
Cross-Worker SQLite WAL Event Bus for Real-Time Pub/Sub & WebSocket Wakeups.
Combines an in-process `threading.Condition` fast-path (<1ms intra-process wakeup)
with shared SQLite WAL monotonic sequence polling (<25ms cross-process wakeup).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Optional, Union

from hvl_common.db.sqlite import get_db_connection

logger = logging.getLogger(__name__)

_COND = threading.Condition()
_SCHEMA_LOCK = threading.Lock()
_ENSURED_DBS: set[str] = set()

# Keyed by (db_scope_key, tenant_id, channel) -> {"seq": int, "payload": Any, "updated_at": float}
_RAM_EVENTS: dict[tuple[str, int, str], dict[str, Any]] = {}


def _db_scope_key(db_path: Optional[Union[str, Path]]) -> str:
    if db_path is None:
        return "__memory__"
    raw = str(db_path).strip()
    if not raw or raw == ":memory:":
        return "__memory__"
    if raw.startswith("file:"):
        return raw
    try:
        return str(Path(raw).resolve())
    except (OSError, RuntimeError):
        return raw


def _normalize_channel(channel: Optional[str]) -> str:
    clean = str(channel or "default").strip()
    return clean or "default"


def _ensure_pubsub_schema(db_path: Union[str, Path]) -> None:
    scope_key = _db_scope_key(db_path)
    if scope_key == "__memory__":
        return
    with _SCHEMA_LOCK:
        if scope_key in _ENSURED_DBS and (
            scope_key.startswith("file:") or Path(scope_key).exists()
        ):
            return
        conn = get_db_connection(db_path, timeout=5.0)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tenant_events (
                        tenant_id INTEGER NOT NULL,
                        channel TEXT NOT NULL DEFAULT 'default',
                        seq INTEGER NOT NULL,
                        updated_at REAL NOT NULL,
                        payload_json TEXT,
                        PRIMARY KEY (tenant_id, channel)
                    );
                    """
                )
            _ENSURED_DBS.add(scope_key)
        finally:
            conn.close()


def _serialize_payload(payload: Any) -> Optional[str]:
    if payload is None:
        return None
    try:
        return json.dumps(payload, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return json.dumps(str(payload))


def _deserialize_payload(payload_json: Optional[str]) -> Any:
    if not payload_json:
        return None
    try:
        return json.loads(payload_json)
    except json.JSONDecodeError:
        return payload_json


def get_latest_tenant_event(
    db_path: Optional[Union[str, Path]],
    tenant_id: int,
    channel: str = "default",
) -> dict[str, Any]:
    """
    Returns the latest event metadata `{"seq": int, "payload": Any, "updated_at": float}`
    for `(tenant_id, channel)`, reading from SQLite WAL when `db_path` is provided
    and merging with the in-RAM cache.
    """
    tid = int(tenant_id or 0)
    ch = _normalize_channel(channel)
    scope_key = _db_scope_key(db_path)
    cache_key = (scope_key, tid, ch)

    with _COND:
        ram_entry = dict(_RAM_EVENTS.get(cache_key) or {"seq": 0, "payload": None, "updated_at": 0.0})

    if scope_key == "__memory__" or db_path is None:
        return ram_entry

    try:
        _ensure_pubsub_schema(db_path)
        conn = get_db_connection(db_path, timeout=5.0)
        try:
            row = conn.execute(
                "SELECT seq, updated_at, payload_json FROM tenant_events WHERE tenant_id = ? AND channel = ?",
                (tid, ch),
            ).fetchone()
        finally:
            conn.close()

        if row is not None:
            db_seq = int(row["seq"] or 0)
            db_updated = float(row["updated_at"] or 0.0)
            db_payload = _deserialize_payload(row["payload_json"])
            with _COND:
                cur_ram = _RAM_EVENTS.get(cache_key)
                if cur_ram is None or db_seq >= int(cur_ram.get("seq", 0)):
                    merged = {"seq": db_seq, "payload": db_payload, "updated_at": db_updated}
                    _RAM_EVENTS[cache_key] = merged
                    return dict(merged)
                return dict(cur_ram)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("SQLite pubsub read fell back to memory for tenant=%s channel=%s: %s", tid, ch, exc)

    return ram_entry


def get_tenant_event_seq(
    db_path: Optional[Union[str, Path]],
    tenant_id: int,
    channel: str = "default",
) -> int:
    """Returns the current monotonic sequence number for `(tenant_id, channel)`."""
    latest = get_latest_tenant_event(db_path, tenant_id, channel=channel)
    return int(latest.get("seq") or 0)


def notify_tenant_event(
    db_path: Optional[Union[str, Path]],
    tenant_id: int,
    channel: str = "default",
    payload: Any = None,
) -> int:
    """
    Atomically increments the monotonic event sequence for `(tenant_id, channel)` in
    SQLite WAL (when `db_path` is provided), updates the in-RAM cache, wakes all
    waiting threads in the current process immediately, and returns the new sequence.
    """
    tid = int(tenant_id or 0)
    ch = _normalize_channel(channel)
    scope_key = _db_scope_key(db_path)
    cache_key = (scope_key, tid, ch)
    now = time.time()
    payload_json = _serialize_payload(payload)
    new_seq: Optional[int] = None

    if scope_key != "__memory__" and db_path is not None:
        try:
            _ensure_pubsub_schema(db_path)
            conn = get_db_connection(db_path, timeout=5.0)
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO tenant_events (tenant_id, channel, seq, updated_at, payload_json)
                        VALUES (?, ?, 1, ?, ?)
                        ON CONFLICT(tenant_id, channel) DO UPDATE SET
                            seq = tenant_events.seq + 1,
                            updated_at = excluded.updated_at,
                            payload_json = excluded.payload_json
                        """,
                        (tid, ch, now, payload_json),
                    )
                    row = conn.execute(
                        "SELECT seq FROM tenant_events WHERE tenant_id = ? AND channel = ?",
                        (tid, ch),
                    ).fetchone()
                    if row is not None:
                        new_seq = int(row["seq"])
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("SQLite pubsub write fell back to memory for tenant=%s channel=%s: %s", tid, ch, exc)

    with _COND:
        prev_seq = int((_RAM_EVENTS.get(cache_key) or {}).get("seq") or 0)
        resolved_seq = max(new_seq or 0, prev_seq + 1) if new_seq is not None else (prev_seq + 1)
        _RAM_EVENTS[cache_key] = {
            "seq": resolved_seq,
            "payload": payload,
            "updated_at": now,
        }
        _COND.notify_all()
        return resolved_seq


def wait_for_tenant_event(
    db_path: Optional[Union[str, Path]],
    tenant_id: int,
    channel: str = "default",
    since_seq: Optional[int] = None,
    timeout_sec: float = 15.0,
    poll_interval_sec: float = 0.02,
) -> int:
    """
    Blocks until the monotonic sequence for `(tenant_id, channel)` exceeds `since_seq`
    or `timeout_sec` elapses. Wakes in <1ms for intra-process `notify_tenant_event`
    calls and polls SQLite WAL every `poll_interval_sec` (~20ms) for cross-process writes.
    """
    tid = int(tenant_id or 0)
    ch = _normalize_channel(channel)
    scope_key = _db_scope_key(db_path)
    cache_key = (scope_key, tid, ch)

    cur = get_tenant_event_seq(db_path, tid, channel=ch)
    target = cur if since_seq is None else int(since_seq)
    if cur > target or timeout_sec <= 0:
        return cur

    step = max(0.005, float(poll_interval_sec or 0.02))
    deadline = time.monotonic() + min(max(0.0, float(timeout_sec)), 30.0)

    while True:
        with _COND:
            ram_seq = int((_RAM_EVENTS.get(cache_key) or {}).get("seq") or 0)
            if ram_seq > target:
                return ram_seq
            rem = deadline - time.monotonic()
            if rem <= 0:
                break
            _COND.wait(timeout=min(rem, step))
            ram_seq = int((_RAM_EVENTS.get(cache_key) or {}).get("seq") or 0)
            if ram_seq > target:
                return ram_seq

        cur = get_tenant_event_seq(db_path, tid, channel=ch)
        if cur > target or time.monotonic() >= deadline:
            return cur

    return get_tenant_event_seq(db_path, tid, channel=ch)


__all__ = [
    "get_tenant_event_seq",
    "get_latest_tenant_event",
    "notify_tenant_event",
    "wait_for_tenant_event",
]
