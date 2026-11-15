"""
L1 In-Memory Byte-Bounded LRU Cache and Single-Flight Deduplication.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import json
import logging
import sqlite3
import sys
import threading
import time
from typing import Any, Dict, Iterator, Optional, Tuple

import cachetools

logger = logging.getLogger(__name__)

READ_THROUGH_SCOPE = "read_through"  # L1 key scope of `read_through.py`'s objects: no tenant, any key, no L2 row
# An entry over L1's whole budget is a sizing bug (budgets are set from the largest real entry, #2338): it is logged
# as an error every time, counted per namespace, and recorded as a CACHE_OVERSIZE telemetry event on the admin page
# at most once per namespace in this window, so a hot oversized key can't flood the 1,000-row telemetry ring.
OVERSIZE_TELEMETRY_INTERVAL_S = 600.0


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


def entry_is_fresh(
    stored_at: Optional[float], expires_at: Optional[float], max_age_seconds: Optional[float], now: float
) -> bool:
    """Whether an entry stored at `stored_at` with write-time expiry `expires_at` (epoch seconds; None: never) is
    still fresh at `now` for a reader that accepts at most `max_age_seconds` (None: any age)."""
    if expires_at is not None and float(expires_at) <= now:
        return False
    if max_age_seconds is not None and (stored_at is None or now - float(stored_at) > float(max_age_seconds)):
        return False
    return True


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
    oversize_counts: Dict[str, int]  # namespace -> entries refused for being over L1's budget, since start
    # namespace -> last CACHE_OVERSIZE telemetry event (namespaces are constants)
    _oversize_reported_at: Dict[str, float]

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
        self.oversize_counts = {}
        self._oversize_reported_at = {}

    def _report_oversize(self, namespace: str, key: Any, size_bytes: int) -> None:
        """An entry too big for L1's whole budget: loud, counted, and on the admin page. Call outside `_lock`."""
        namespace = str(namespace)
        now = time.time()
        with self._lock:
            self.oversize_counts[namespace] = self.oversize_counts.get(namespace, 0) + 1
            last = self._oversize_reported_at.get(namespace)
            send = last is None or now - last >= OVERSIZE_TELEMETRY_INTERVAL_S
            if send:
                self._oversize_reported_at[namespace] = now
            count = self.oversize_counts[namespace]
        # One error per namespace per interval: an entry never kept in memory comes back on every read.
        logger.log(
            logging.ERROR if send else logging.DEBUG,
            "Cache entry (%s, %r) is %d bytes, over L1's %d-byte budget; not kept in memory. Raise this cache's "
            "max_l1_bytes (python3 common/scripts/cache_sizes.py measures the largest entries).",
            namespace,
            key,
            size_bytes,
            self.max_l1_bytes,
        )
        if not send:
            return
        try:
            from flask import current_app, has_app_context

            from hvl_common.telemetry.store import EVENT_CACHE_OVERSIZE, record_telemetry_event

            service = str(current_app.config.get("HVL_SERVICE_NAME") or "app") if has_app_context() else "app"
            record_telemetry_event(
                service=service,
                event_type=EVENT_CACHE_OVERSIZE,
                method="CACHE",
                path=f"cache:{namespace}",
                error_type="CacheOversize",
                detail=f"Entry of {size_bytes} bytes over the {self.max_l1_bytes}-byte L1 budget ({count} so far)",
            )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Cache oversize telemetry for %s not recorded: %s", namespace, exc)

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
        expires_at: Optional[float] = None,
    ) -> None:
        """Keeps `data` in L1. `now` is when it was stored (an L2 row's `store_time` when loaded from L2), and
        `expires_at` its write-time TTL as an epoch time (None: never), checked by `_get_l1`."""
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
            oversize = est_size > self.max_l1_bytes
            if oversize:
                # cachetools would raise. The older entry goes too, or a read at the same version would serve it in
                # place of this write.
                self._l1.pop(l1_key, None)
            else:
                self._l1[l1_key] = {
                    "state_version": int(state_version),
                    "data": data,
                    "updated_at": ts,
                    "expires_at": expires_at,
                    "size_bytes": est_size,
                }
                while len(self._l1) > self.max_l1_entries:
                    self._l1.popitem()
        if oversize:
            self._report_oversize(namespace, key, est_size)

    def _get_l1(
        self,
        scope: str,
        tenant_id: int,
        namespace: str,
        key: str,
        state_version: int,
        *,
        max_age_seconds: Optional[float] = None,
        include_expired: bool = False,
    ) -> Tuple[bool, Optional[Any]]:
        """(hit, data) for the entry at `state_version`. An entry past its write-time TTL, or stored more than
        `max_age_seconds` ago, is a miss unless `include_expired` (an offline fallback); it is left in place."""
        l1_key = (scope, int(tenant_id), str(namespace), str(key))
        now = time.time()
        with self._lock:
            entry = self._l1.get(l1_key)
            if entry is not None:
                if entry.get("state_version") == int(state_version):
                    if include_expired or entry_is_fresh(
                        entry.get("updated_at"), entry.get("expires_at"), max_age_seconds, now
                    ):
                        return True, entry.get("data")
                    return False, None
                if entry.get("state_version", 0) < int(state_version):
                    self._l1.pop(l1_key, None)  # only an older entry goes: a lagging reader leaves a newer one
        return False, None

    def clear_l1(self) -> None:
        """Clears only the in-memory L1 LRU cache while preserving L2 SQLite entries."""
        with self._lock:
            self._l1.clear()
