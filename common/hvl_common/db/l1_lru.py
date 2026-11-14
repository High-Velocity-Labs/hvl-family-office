"""
L1 In-Memory Byte-Bounded LRU Cache and Single-Flight Deduplication.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import json
import logging
import sys
import threading
import time
from typing import Any, Dict, Iterator, Optional, Tuple

import cachetools

logger = logging.getLogger(__name__)

READ_THROUGH_SCOPE = "read_through"  # L1 key scope of `read_through.py`'s objects: no tenant, any key, no L2 row


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
        except (TypeError, ValueError):
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
    except TypeError:
        return 256


def _estimate_payload_bytes(val: Any) -> int:
    """Fast byte-size estimator for L1 cache entries."""
    if isinstance(val, dict) and "size_bytes" in val:
        return max(64, int(val["size_bytes"]))
    return max(64, _estimate_object_bytes(val))


class L1LRUMixin:
    """
    Mixin providing L1 `cachetools.LRUCache` storage and single-flight stampede protection. Entries carry the
    caller's `state_version` (e.g. derived from its domain versions); nothing here bumps or purges a tenant.
    """

    max_l1_entries: int
    max_l1_bytes: int
    _lock: threading.RLock
    _l1: cachetools.LRUCache[Tuple[str, int, str, str], Dict[str, Any]]
    _flight_meta_lock: threading.Lock
    _flight_locks: OrderedDict[str, list]  # composite key -> [RLock, threads holding or waiting on it]
    _max_flight_locks: int
    _init_dbs_lock: threading.Lock

    def _init_l1_state(self, max_l1_entries: int, max_l1_bytes: int) -> None:
        self.max_l1_entries = max(1, int(max_l1_entries))
        self.max_l1_bytes = max(4096, int(max_l1_bytes))
        self._lock = threading.RLock()
        self._l1 = cachetools.LRUCache(
            maxsize=self.max_l1_bytes,
            getsizeof=_estimate_payload_bytes,
        )
        self._flight_meta_lock = threading.Lock()
        self._flight_locks = OrderedDict()
        self._max_flight_locks = 1024

    @contextmanager
    def single_flight(self, *key_parts: Any) -> Iterator[None]:
        """
        Per-key re-entrant lock context manager to prevent concurrent cache stampedes
        when multiple threads request the same uncached calculation simultaneously.
        """
        composite_key = ":".join(str(p) for p in key_parts)
        with self._flight_meta_lock:
            slot = self._flight_locks.get(composite_key)
            if slot is None:
                slot = [threading.RLock(), 0]
                self._flight_locks[composite_key] = slot
                if len(self._flight_locks) > self._max_flight_locks:
                    # Only a lock no thread holds or waits on may go: a later caller would get a second lock.
                    idle = next((k for k, s in self._flight_locks.items() if s[1] == 0 and s is not slot), None)
                    if idle is not None:
                        del self._flight_locks[idle]
            else:
                self._flight_locks.move_to_end(composite_key)
            slot[1] += 1
        try:
            with slot[0]:
                yield
        finally:
            with self._flight_meta_lock:
                slot[1] -= 1

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
            current = self._l1.get(l1_key)
            if current is not None and current.get("state_version", 0) > int(state_version):
                return  # a write computed at an older version never replaces a newer entry
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
                if entry.get("state_version", 0) < int(state_version):
                    self._l1.pop(l1_key, None)  # only an older entry goes: a lagging reader leaves a newer one
        return False, None

    def clear_l1(self) -> None:
        """Clears only the in-memory L1 LRU cache while preserving L2 SQLite entries."""
        with self._lock:
            self._l1.clear()
