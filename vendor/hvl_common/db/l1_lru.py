"""
L1 In-Memory Byte-Bounded LRU Cache, Single-Flight Deduplication, and Multi-Worker State Version Sync.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, Iterator, Optional, Set, Tuple, Union

import cachetools

from hvl_common.db.sqlite import _resolve_db_key, get_db_connection

logger = logging.getLogger(__name__)


def _estimate_object_bytes(obj: Any, _depth: int = 0) -> int:
    """Fast recursive byte-size estimator for nested dicts, lists, and strings."""
    if obj is None:
        return 16
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return len(obj) + 32
    if isinstance(obj, str):
        return len(obj) + 48
    if isinstance(obj, (int, float, bool)):
        return 28
    if _depth > 3:
        try:
            return len(json.dumps(obj, default=str))
        except Exception:
            return 256
    if isinstance(obj, dict):
        return 64 + sum(
            _estimate_object_bytes(k, _depth + 1) + _estimate_object_bytes(v, _depth + 1)
            for k, v in obj.items()
        )
    if isinstance(obj, (list, tuple, set, frozenset)):
        return 64 + sum(_estimate_object_bytes(x, _depth + 1) for x in obj)
    try:
        return max(64, sys.getsizeof(obj))
    except Exception:
        return 256


def _estimate_payload_bytes(val: Any) -> int:
    """Fast byte-size estimator for L1 cache entries."""
    if isinstance(val, dict) and "size_bytes" in val:
        return max(64, int(val["size_bytes"]))
    return max(64, _estimate_object_bytes(val))


class L1LRUMixin:
    """
    Mixin providing L1 `cachetools.LRUCache` storage, single-flight stampede protection,
    and cross-worker state version tracking (`family_state_versions`).
    """

    max_l1_entries: int
    max_l1_bytes: int
    _lock: threading.RLock
    _l1: cachetools.LRUCache[Tuple[str, int, str, str], Dict[str, Any]]
    _tenant_versions: Dict[Tuple[str, int], int]
    _flight_meta_lock: threading.Lock
    _flight_locks: OrderedDict[str, threading.RLock]
    _max_flight_locks: int
    _init_dbs_lock: threading.Lock
    _initialized_state_dbs: Set[str]

    def _init_l1_state(self, max_l1_entries: int, max_l1_bytes: int) -> None:
        self.max_l1_entries = max(1, int(max_l1_entries))
        self.max_l1_bytes = max(4096, int(max_l1_bytes))
        self._lock = threading.RLock()
        self._l1 = cachetools.LRUCache(
            maxsize=self.max_l1_bytes,
            getsizeof=_estimate_payload_bytes,
        )
        self._tenant_versions = {}
        self._flight_meta_lock = threading.Lock()
        self._flight_locks = OrderedDict()
        self._max_flight_locks = 1024
        self._initialized_state_dbs = set()

    def _ensure_state_version_schema(self, state_db: Path) -> None:
        db_key = _resolve_db_key(state_db)
        if db_key in self._initialized_state_dbs and state_db.exists():
            return
        with self._init_dbs_lock:
            if db_key in self._initialized_state_dbs and state_db.exists():
                return
            conn = get_db_connection(state_db, timeout=5.0)
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS family_state_versions (
                            family_id INTEGER PRIMARY KEY,
                            version INTEGER NOT NULL DEFAULT 1,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        """
                    )
                self._initialized_state_dbs.add(db_key)
            finally:
                conn.close()

    @contextmanager
    def single_flight(self, *key_parts: Any) -> Iterator[None]:
        """
        Per-key re-entrant lock context manager to prevent concurrent cache stampedes
        when multiple threads request the same uncached calculation simultaneously.
        """
        composite_key = ":".join(str(p) for p in key_parts)
        with self._flight_meta_lock:
            lock = self._flight_locks.get(composite_key)
            if lock is None:
                lock = threading.RLock()
                self._flight_locks[composite_key] = lock
                if len(self._flight_locks) > self._max_flight_locks:
                    self._flight_locks.popitem(last=False)
            else:
                self._flight_locks.move_to_end(composite_key)

        with lock:
            yield

    def _put_l1(
        self,
        scope: str,
        tenant_id: int,
        namespace: str,
        key: str,
        state_version: int,
        data: Any,
        now: Optional[float] = None,
        size_bytes: Optional[int] = None,
    ) -> None:
        l1_key = (scope, int(tenant_id), str(namespace), str(key))
        ts = now if now is not None else time.time()
        est_size = (
            max(64, int(size_bytes))
            if size_bytes is not None
            else max(64, _estimate_object_bytes(data))
        )
        with self._lock:
            self._l1[l1_key] = {
                "state_version": int(state_version),
                "data": data,
                "updated_at": ts,
                "size_bytes": est_size,
            }
            while len(self._l1) > self.max_l1_entries:
                self._l1.popitem()

    def _get_l1(
        self,
        scope: str,
        tenant_id: int,
        namespace: str,
        key: str,
        state_version: int,
    ) -> Tuple[bool, Optional[Any]]:
        l1_key = (scope, int(tenant_id), str(namespace), str(key))
        with self._lock:
            entry = self._l1.get(l1_key)
            if entry is not None:
                if entry.get("state_version") == int(state_version):
                    return True, entry.get("data")
                self._l1.pop(l1_key, None)
        return False, None

    def _purge_l1_tenant_locked(
        self, tenant_id: int, scope: Optional[str] = None
    ) -> None:
        tid = int(tenant_id)
        to_remove = [
            k
            for k in list(self._l1.keys())
            if k[1] == tid and (scope is None or k[0] == scope)
        ]
        for k in to_remove:
            self._l1.pop(k, None)

        prefix = f"{tid}:"
        prefix_remove = [
            k
            for k in list(self._l1.keys())
            if k[3].startswith(prefix) and (scope is None or k[0] == scope)
        ]
        for k in prefix_remove:
            self._l1.pop(k, None)

    def _sync_state_version_from_db(
        self, tid: int, ver_key: Tuple[str, int], state_db: Optional[Path]
    ) -> int:
        if state_db is not None and state_db.parent.exists():
            try:
                self._ensure_state_version_schema(state_db)
                conn = get_db_connection(state_db, timeout=5.0)
                try:
                    cur = conn.execute(
                        "SELECT version FROM family_state_versions WHERE family_id = ?",
                        (tid,),
                    )
                    row = cur.fetchone()
                    if row is not None and row[0] is not None:
                        db_version = int(row[0])
                        with self._lock:
                            local_version = self._tenant_versions.get(ver_key, 1)
                            if db_version > local_version:
                                self._purge_l1_tenant_locked(tid)
                            eff_v = max(db_version, local_version)
                            self._tenant_versions[ver_key] = eff_v
                            return eff_v
                    else:
                        with self._lock:
                            cur_v = self._tenant_versions.get(ver_key, 1)
                        with conn:
                            conn.execute(
                                """
                                INSERT INTO family_state_versions (family_id, version, updated_at)
                                VALUES (?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(family_id) DO NOTHING
                                """,
                                (tid, cur_v),
                            )
                        return cur_v
                finally:
                    conn.close()
            except Exception as exc:
                logger.debug("State version lookup fallback for tenant %s: %s", tid, exc)

        with self._lock:
            return self._tenant_versions.get(ver_key, 1)

    def _bump_state_version_in_db(
        self, tid: int, ver_key: Tuple[str, int], state_db: Optional[Path]
    ) -> int:
        with self._lock:
            current_v = self._tenant_versions.get(ver_key, 1)
            new_v = current_v + 1

            if state_db is not None and state_db.parent.exists():
                try:
                    self._ensure_state_version_schema(state_db)
                    conn = get_db_connection(state_db, timeout=10.0)
                    try:
                        cur = conn.execute(
                            "SELECT version FROM family_state_versions WHERE family_id = ?",
                            (tid,),
                        )
                        row = cur.fetchone()
                        db_v = int(row[0]) if (row is not None and row[0] is not None) else 1
                        target_v = max(db_v, current_v) + 1
                        with conn:
                            conn.execute(
                                """
                                INSERT INTO family_state_versions (family_id, version, updated_at)
                                VALUES (?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(family_id) DO UPDATE SET
                                    version = excluded.version,
                                    updated_at = CURRENT_TIMESTAMP
                                """,
                                (tid, target_v),
                            )
                        new_v = target_v
                    finally:
                        conn.close()
                except Exception as exc:
                    logger.debug("State version bump DB fallback for tenant %s: %s", tid, exc)

            self._tenant_versions[ver_key] = new_v
            self._purge_l1_tenant_locked(tid)
            return new_v

    def clear_l1(self) -> None:
        """Clears only the in-memory L1 LRU cache while preserving L2 SQLite entries."""
        with self._lock:
            self._l1.clear()
