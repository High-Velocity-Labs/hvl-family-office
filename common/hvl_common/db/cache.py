"""
Two-Tier Cache (L1 In-Memory `cachetools.LRUCache` + L2 Encrypted `diskcache.Cache`)
with Single-Flight Stampede Protection and Multi-Worker State Version Invalidation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable, Optional, Union

from hvl_common.db.l1_lru import (
    L1LRUMixin,
    _estimate_object_bytes,
    _estimate_payload_bytes,
)
from hvl_common.db.l2_disk import L2DiskMixin, SQLiteFileDiskCache
from hvl_common.db.sqlite import _resolve_db_key, get_db_connection

logger = logging.getLogger(__name__)

__all__ = [
    "TwoTierCache",
    "SQLiteFileDiskCache",
    "_estimate_object_bytes",
    "_estimate_payload_bytes",
]


class TwoTierCache(L1LRUMixin, L2DiskMixin):
    """
    Thread-safe Two-Tier Cache built on industry-standard libraries:
      - L1: `cachetools.LRUCache` bounded by both byte size (`max_l1_bytes`, default 32 MB)
            and entry count (`max_l1_entries`) for sub-0.1ms in-memory hits.
      - L2: `SQLiteFileDiskCache` (`diskcache.Cache` with `disk_min_file_size=2**31 - 1`,
            `tag_index=True`, and byte-bounded `size_limit`) with out-of-lock JSON
            serialization, zlib compression, and per-tenant Fernet encryption at rest.
      - Option A Canonical vs. Ephemeral (Slider) Support:
            `persist_l2=False` keeps exploratory slider runs strictly in L1 RAM without
            touching SQLite disk I/O, while `persist_l2=True` persists canonical runs to L2.
      - Pure SELECT on L2 reads (`eviction_policy='least-recently-stored'`, `statistics=0`).
      - Single-flight lock deduplication to prevent concurrent cache stampedes.
    """

    def __init__(
        self,
        *,
        max_l1_entries: int = 128,
        max_l1_bytes: int = 32 * 1024 * 1024,
        max_l2_bytes: int = 256 * 1024 * 1024,
        max_l2_per_tenant_ns: int = 16,
        cache_db_path_fn: Optional[Callable[[], Optional[Union[str, Path]]]] = None,
        db_path_fn: Optional[Callable[[], Optional[Union[str, Path]]]] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    ) -> None:
        self._cache_db_path_fn = cache_db_path_fn
        self._db_path_fn = db_path_fn
        self._init_dbs_lock = threading.Lock()
        self._init_l1_state(max_l1_entries=max_l1_entries, max_l1_bytes=max_l1_bytes)
        self._init_l2_state(
            max_l2_bytes=max_l2_bytes,
            max_l2_per_tenant_ns=max_l2_per_tenant_ns,
            encrypt_fn=encrypt_fn,
            decrypt_fn=decrypt_fn,
        )

    def _resolve_cache_db(
        self, cache_db_path: Optional[Union[str, Path]] = None
    ) -> Optional[Path]:
        target = cache_db_path
        if target is None and self._cache_db_path_fn is not None:
            try:
                target = self._cache_db_path_fn()
            except Exception:
                target = None
        return Path(target) if target is not None else None

    def _resolve_state_db(
        self, db_path: Optional[Union[str, Path]] = None
    ) -> Optional[Path]:
        target = db_path
        if target is None and self._db_path_fn is not None:
            try:
                target = self._db_path_fn()
            except Exception:
                target = None
        return Path(target) if target is not None else None

    def _scope_key(
        self,
        cache_db_path: Optional[Union[str, Path]] = None,
        db_path: Optional[Union[str, Path]] = None,
    ) -> str:
        c_path = self._resolve_cache_db(cache_db_path)
        if c_path is not None:
            return _resolve_db_key(c_path)
        s_path = self._resolve_state_db(db_path)
        if s_path is not None:
            return _resolve_db_key(s_path)
        return "default"

    def set(
        self,
        namespace: str,
        key: str,
        data: Any,
        *,
        tenant_id: int = 0,
        state_version: int = 1,
        persist_l2: bool = True,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        max_l2_per_tenant_ns: Optional[int] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """
        Stores `data` in L1 `cachetools.LRUCache` and optionally persists to L2 `diskcache.Cache`.
        Serialization, zlib compression, and Fernet encryption happen strictly outside the SQLite lock.
        """
        if data is None:
            return

        tid = int(tenant_id)
        ver = int(state_version)
        now = time.time()
        scope = self._scope_key(cache_db_path=cache_db_path)

        raw_bytes: Optional[bytes] = None
        if persist_l2 and tid > 0:
            try:
                raw_bytes = json.dumps(data, default=str).encode("utf-8")
            except Exception:
                raw_bytes = None

        self._put_l1(
            scope,
            tid,
            namespace,
            key,
            ver,
            data,
            now=now,
            size_bytes=len(raw_bytes) if raw_bytes is not None else None,
        )

        if not persist_l2 or tid <= 0:
            return

        cache_db = self._resolve_cache_db(cache_db_path)
        if cache_db is None:
            return

        self._write_l2_entry(
            cache_db,
            tid,
            namespace,
            ver,
            key,
            data,
            raw_bytes=raw_bytes,
            encrypt_fn=encrypt_fn,
            max_l2_per_tenant_ns=max_l2_per_tenant_ns,
        )

    def get(
        self,
        namespace: str,
        key: str,
        *,
        tenant_id: int = 0,
        state_version: int = 1,
        check_l2: bool = True,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> Optional[Any]:
        """
        Retrieves cached entry from L1 `cachetools.LRUCache` or L2 `diskcache.Cache`.
        L2 read is a 100% pure SELECT (zero write lock on read).
        """
        tid = int(tenant_id)
        ver = int(state_version)
        scope = self._scope_key(cache_db_path=cache_db_path)

        hit, l1_data = self._get_l1(scope, tid, namespace, key, ver)
        if hit:
            return l1_data

        if not check_l2 or tid <= 0:
            return None

        cache_db = self._resolve_cache_db(cache_db_path)
        if cache_db is None or not cache_db.exists():
            return None

        l2_res = self._read_l2_entry(
            cache_db, tid, namespace, ver, key, decrypt_fn=decrypt_fn
        )
        if l2_res is None:
            return None

        data, raw_len = l2_res
        self._put_l1(scope, tid, namespace, key, ver, data, size_bytes=raw_len)
        return data

    def get_or_compute(
        self,
        namespace: str,
        key: str,
        compute_fn: Callable[[], Any],
        *,
        tenant_id: int = 0,
        state_version: int = 1,
        persist_l2: bool = True,
        check_l2: bool = True,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        max_l2_per_tenant_ns: Optional[int] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> Any:
        """
        Retrieves from L1/L2 cache or computes once under a single-flight lock for `(tenant_id, namespace, key, state_version)`.
        """
        cached = self.get(
            namespace,
            key,
            tenant_id=tenant_id,
            state_version=state_version,
            check_l2=check_l2,
            decrypt_fn=decrypt_fn,
            cache_db_path=cache_db_path,
        )
        if cached is not None:
            return cached

        scope = self._scope_key(cache_db_path=cache_db_path)
        with self.single_flight(scope, int(tenant_id), namespace, key, int(state_version)):
            cached = self.get(
                namespace,
                key,
                tenant_id=tenant_id,
                state_version=state_version,
                check_l2=check_l2,
                decrypt_fn=decrypt_fn,
                cache_db_path=cache_db_path,
            )
            if cached is not None:
                return cached

            result = compute_fn()
            if result is not None:
                self.set(
                    namespace,
                    key,
                    result,
                    tenant_id=tenant_id,
                    state_version=state_version,
                    persist_l2=persist_l2,
                    encrypt_fn=encrypt_fn,
                    max_l2_per_tenant_ns=max_l2_per_tenant_ns,
                    cache_db_path=cache_db_path,
                )
            return result

    def get_version(
        self,
        tenant_id: int = 0,
        db_path: Optional[Union[str, Path]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> int:
        """
        Returns the current state version integer for `tenant_id` (`family_id`).
        Synchronizes against `family_state_versions` in `db_path` across Gunicorn workers
        and purges stale L1 entries when an out-of-band version bump is detected.
        """
        tid = int(tenant_id or 0)
        if tid <= 0:
            return 1
        state_db = self._resolve_state_db(db_path)
        scope = self._scope_key(cache_db_path=cache_db_path, db_path=state_db)
        return self._sync_state_version_from_db(tid, (scope, tid), state_db)

    def bump_version(
        self,
        tenant_id: int = 0,
        db_path: Optional[Union[str, Path]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> int:
        """
        Increments the state version for `tenant_id` in `family_state_versions`,
        purges all L1 entries for `tenant_id`, and evicts all L2 `diskcache` rows
        tagged for `tenant_id`.
        """
        tid = int(tenant_id or 0)
        if tid <= 0:
            return 1

        state_db = self._resolve_state_db(db_path)
        cache_db = self._resolve_cache_db(cache_db_path)
        scope = self._scope_key(cache_db_path=cache_db, db_path=state_db)
        new_v = self._bump_state_version_in_db(tid, (scope, tid), state_db)

        if cache_db is not None and cache_db.exists():
            try:
                l2 = self._get_l2_cache(cache_db, create_if_missing=False)
                if l2 is not None:
                    l2.evict(self._make_tenant_tag(tid))
            except Exception as exc:
                logger.debug("L2 diskcache evict error for tenant %s: %s", tid, exc)

        return new_v

    def mutate_tenant_namespace(
        self,
        tenant_id: int,
        namespace: str,
        mutator_fn: Callable[[Any], None],
        *,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """
        Applies `mutator_fn(data)` in-place to all cached entries for `(tenant_id, namespace)`
        in L1 (and updates L2 `diskcache` entries if present) without bumping `state_version`.
        """
        tid = int(tenant_id or 0)
        if tid <= 0:
            return
        prefix = f"{tid}:"
        with self._lock:
            for (_scope, k_tid, k_ns, k_key), entry in list(self._l1.items()):
                if k_ns == namespace and (k_tid == tid or k_key.startswith(prefix)):
                    data = entry.get("data")
                    if data is not None:
                        mutator_fn(data)

        cache_db = self._resolve_cache_db(cache_db_path)
        if cache_db is not None and cache_db.exists():
            self._mutate_l2_namespace(
                cache_db,
                tid,
                namespace,
                mutator_fn,
                encrypt_fn=encrypt_fn,
                decrypt_fn=decrypt_fn,
            )

    def clear(
        self,
        *,
        db_path: Optional[Union[str, Path]] = None,
        cache_db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """
        Clears L1 cache, in-memory state versions, and (if resolvable) L2 `diskcache`
        and `family_state_versions` tables.
        """
        with self._lock:
            self._l1.clear()
            self._tenant_versions.clear()

        state_db = self._resolve_state_db(db_path)
        if state_db is not None and state_db.exists():
            try:
                self._ensure_state_version_schema(state_db)
                conn = get_db_connection(state_db, timeout=5.0)
                try:
                    with conn:
                        conn.execute("DELETE FROM family_state_versions")
                finally:
                    conn.close()
            except Exception:
                pass

        cache_db = self._resolve_cache_db(cache_db_path)
        if cache_db is not None and cache_db.exists():
            try:
                l2 = self._get_l2_cache(cache_db, create_if_missing=False)
                if l2 is not None:
                    l2.clear()
                    l2._sql("DROP TABLE IF EXISTS computed_cache")
            except Exception:
                pass
