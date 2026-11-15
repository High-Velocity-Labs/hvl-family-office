"""
L2 Encrypted SQLite Disk Cache (`SQLiteFileDiskCache` and `L2DiskMixin`).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union
import zlib

import cachetools
import diskcache
from cryptography.fernet import InvalidToken

from hvl_common.db.l1_lru import entry_is_fresh
from hvl_common.db.sqlite import _resolve_db_key
from hvl_common.security.crypto import DecryptionError

logger = logging.getLogger(__name__)

# What the L2 disk store itself raises: a locked/missing/corrupt SQLite file or a diskcache lock timeout.
L2_STORAGE_ERRORS = (sqlite3.Error, OSError, diskcache.Timeout)
# What a stored L2 blob raises when it no longer decodes (cache entry from another key, truncated, not JSON).
L2_BLOB_ERRORS = (zlib.error, ValueError, InvalidToken, DecryptionError)


class SQLiteFileDiskCache(diskcache.Cache):
    """
    `diskcache.Cache` subclass backed by a specific SQLite database file path
    with `disk_min_file_size = 2**31 - 1` so 100% of encrypted blobs remain inside
    the SQLite `Cache` table rather than spilling loose files onto the filesystem.
    """

    def __init__(
        self,
        db_file: Union[str, Path],
        *,
        size_limit: int = 256 * 1024 * 1024,
        timeout: float = 10.0,
    ) -> None:
        resolved = Path(db_file).resolve()
        self._db_file = str(resolved)
        parent_dir = str(resolved.parent)
        os.makedirs(parent_dir, exist_ok=True)
        super().__init__(
            directory=parent_dir,
            timeout=timeout,
            disk_min_file_size=2**31 - 1,
            size_limit=int(size_limit),
            tag_index=True,
            eviction_policy="least-recently-stored",
            statistics=0,
        )

    @property
    def _con(self) -> sqlite3.Connection:
        local_pid = getattr(self._local, "pid", None)
        pid = os.getpid()
        if local_pid != pid:
            self.close()
            self._local.pid = pid

        con = getattr(self._local, "con", None)
        if con is None:
            os.makedirs(os.path.dirname(self._db_file), exist_ok=True)
            con = self._local.con = sqlite3.connect(
                self._db_file,
                timeout=self._timeout,
                isolation_level=None,
            )
            try:
                settings = con.execute("SELECT key, value FROM Settings").fetchall()
            except sqlite3.OperationalError:
                pass
            else:
                for key, value in settings:
                    if str(key).startswith("sqlite_"):
                        self.reset(key, value, update=False)
        return con

    def get_fresh(
        self, key: str, *, max_age_seconds: Optional[float] = None, include_expired: bool = False
    ) -> Optional[Tuple[Any, float, Optional[float]]]:
        """
        `(value, store_time, expire_time)` for `key`, or None when it is absent or not fresh: past its write-time TTL
        (`expire_time`) or stored more than `max_age_seconds` ago (`store_time`), unless `include_expired` (an offline
        fallback that wants the last copy). One SELECT; freshness comes from the row's own columns, so a stale row is
        never decrypted or unpickled. diskcache's `get` would hide an expired row from a fallback reader.
        """
        row = self._sql(
            "SELECT store_time, expire_time, mode, filename, value FROM Cache WHERE key = ? AND raw = 1", (key,)
        ).fetchone()
        if row is None:
            return None
        store_time, expire_time, mode, filename, value = row
        if not include_expired and not entry_is_fresh(store_time, expire_time, max_age_seconds, time.time()):
            return None
        return self._disk.fetch(mode, filename, value, False), float(store_time), expire_time


class L2DiskMixin:
    """
    Mixin providing L2 `SQLiteFileDiskCache` lifecycle management, out-of-lock
    JSON + zlib + Fernet serialization, write-time TTL in diskcache's `expire_time`, and one-DELETE pruning of a
    namespace's older state versions. diskcache's `size_limit` (`max_l2_bytes`) evicts the least recently stored rows.
    """

    max_l2_bytes: int
    _encrypt_fn: Optional[Callable[[bytes], bytes]]
    _decrypt_fn: Optional[Callable[[bytes], bytes]]
    _init_dbs_lock: threading.Lock
    _l2_caches: Dict[str, SQLiteFileDiskCache]
    _l2_pruned_lock: threading.Lock
    _l2_pruned: cachetools.LRUCache[Tuple[str, int, str], int]  # (cache file, tenant, namespace) -> version pruned to

    def _init_l2_state(
        self,
        max_l2_bytes: int,
        encrypt_fn: Optional[Callable[[bytes], bytes]],
        decrypt_fn: Optional[Callable[[bytes], bytes]],
    ) -> None:
        self.max_l2_bytes = max(1024 * 1024, int(max_l2_bytes))
        self._encrypt_fn = encrypt_fn
        self._decrypt_fn = decrypt_fn
        self._l2_caches = {}
        # The state version this process last pruned each namespace to, so the prune's DELETE runs once per version
        # bump, not on every write. Rows an older-version writer adds later go at the next bump.
        self._l2_pruned_lock = threading.Lock()
        self._l2_pruned = cachetools.LRUCache(maxsize=4096)

    @staticmethod
    def _make_l2_key(tenant_id: int, namespace: str, state_version: int, key: str) -> str:
        return f"{int(tenant_id)}:{namespace}:v{int(state_version)}:{key}"

    @staticmethod
    def _make_tenant_tag(tenant_id: int) -> str:
        return f"tenant:{int(tenant_id)}"

    def _get_l2_cache(
        self, cache_db: Path, *, create_if_missing: bool = True
    ) -> Optional[SQLiteFileDiskCache]:
        if not create_if_missing and not cache_db.exists():
            return None
        db_key = _resolve_db_key(cache_db)
        with self._init_dbs_lock:
            existing = self._l2_caches.get(db_key)
            if existing is not None:
                if cache_db.exists():
                    return existing
                try:
                    existing.close()
                except L2_STORAGE_ERRORS as exc:
                    logger.warning("Closing stale L2 cache %s failed: %s", db_key, exc)
                self._l2_caches.pop(db_key, None)

            if not create_if_missing and not cache_db.exists():
                return None

            l2 = SQLiteFileDiskCache(
                cache_db,
                size_limit=self.max_l2_bytes,
                timeout=10.0,
            )
            self._l2_caches[db_key] = l2
            return l2

    def close_l2_caches(self, cache_db_path: Optional[Union[str, Path]] = None) -> None:
        """Closes pooled diskcache SQLite connections."""
        with self._init_dbs_lock:
            if cache_db_path is not None:
                key = _resolve_db_key(cache_db_path)
                c = self._l2_caches.pop(key, None)
                if c is not None:
                    try:
                        c.close()
                    except L2_STORAGE_ERRORS as exc:
                        logger.warning("Closing L2 cache %s failed: %s", key, exc)
            else:
                caches = list(self._l2_caches.values())
                self._l2_caches.clear()
                for c in caches:
                    try:
                        c.close()
                    except L2_STORAGE_ERRORS as exc:
                        logger.warning("Closing an L2 cache failed: %s", exc)

    def _write_l2_entry(
        self,
        cache_db: Path,
        tid: int,
        namespace: str,
        ver: int,
        key: str,
        data: Any,
        *,
        raw_bytes: Optional[bytes] = None,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        try:
            if raw_bytes is None:
                raw_bytes = json.dumps(data, default=str).encode("utf-8")
            compressed_bytes = zlib.compress(raw_bytes, level=6)
            eff_encrypt = encrypt_fn if encrypt_fn is not None else self._encrypt_fn
            payload_blob = (
                eff_encrypt(compressed_bytes)
                if eff_encrypt is not None
                else compressed_bytes
            )

            l2 = self._get_l2_cache(cache_db, create_if_missing=True)
            if l2 is None:
                return

            l2_key = self._make_l2_key(tid, namespace, ver, key)
            tag = self._make_tenant_tag(tid)
            l2.set(l2_key, payload_blob, tag=tag, expire=ttl_seconds)

            pruned_key = (_resolve_db_key(cache_db), int(tid), str(namespace))
            with self._l2_pruned_lock:
                if self._l2_pruned.get(pruned_key, -1) >= ver:
                    return
            self._prune_older_versions(l2, tid, namespace, ver)
            with self._l2_pruned_lock:
                self._l2_pruned[pruned_key] = max(ver, self._l2_pruned.get(pruned_key, -1))
        except L2_STORAGE_ERRORS as exc:
            logger.warning("L2 diskcache write skipped for (%s, %s): %s", namespace, key, exc)

    def _prune_older_versions(self, l2: SQLiteFileDiskCache, tid: int, namespace: str, ver: int) -> None:
        """One DELETE of this exact (tenant, namespace)'s rows at versions below `ver`, never newer ones (a slow writer
        must not drop a restamped row). The key range `{tid}:{namespace}:v` .. `{tid}:{namespace}:w` walks the key
        index and matches the namespace exactly (`sim` never takes `simulation`'s rows); SQLite's CAST reads the
        version digits up to the next `:`."""
        prefix = f"{int(tid)}:{namespace}:v"
        l2._sql(
            "DELETE FROM Cache WHERE key >= ? AND key < ? AND raw = 1 AND CAST(substr(key, ?) AS INTEGER) < ?",
            (prefix, prefix[:-1] + "w", len(prefix) + 1, int(ver)),
        )

    def _read_l2_entry(
        self,
        cache_db: Path,
        tid: int,
        namespace: str,
        ver: int,
        key: str,
        *,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        max_age_seconds: Optional[float] = None,
        include_expired: bool = False,
    ) -> Optional[Tuple[Any, int, float, Optional[float]]]:
        """`(data, raw JSON bytes, store_time, expire_time)`, or None for a miss or a row that is not fresh."""
        try:
            l2 = self._get_l2_cache(cache_db, create_if_missing=False)
            if l2 is None:
                return None

            l2_key = self._make_l2_key(tid, namespace, ver, key)
            row = l2.get_fresh(l2_key, max_age_seconds=max_age_seconds, include_expired=include_expired)
            if row is None:
                return None
            raw_val, store_time, expire_time = row

            blob = bytes(raw_val)
            eff_decrypt = decrypt_fn if decrypt_fn is not None else self._decrypt_fn
            compressed_bytes = eff_decrypt(blob) if eff_decrypt is not None else blob
            raw_bytes = zlib.decompress(compressed_bytes)
            data = json.loads(raw_bytes.decode("utf-8"))
            return data, len(raw_bytes), store_time, expire_time
        except (*L2_STORAGE_ERRORS, *L2_BLOB_ERRORS) as exc:
            logger.warning("L2 diskcache read treated as a miss for (%s, %s): %s", namespace, key, exc)
            return None

    def _restamp_l2_namespace(
        self,
        cache_db: Path,
        tid: int,
        namespace: str,
        from_version: int,
        to_version: int,
        mutator_fn: Callable[[Any], None],
        *,
        encrypt_fn: Optional[Callable[[bytes], bytes]] = None,
        decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
    ) -> None:
        try:
            l2 = self._get_l2_cache(cache_db, create_if_missing=False)
            if l2 is None:
                return
            tag = self._make_tenant_tag(tid)
            from_prefix = self._make_l2_key(tid, namespace, from_version, "")
            to_prefix = self._make_l2_key(tid, namespace, to_version, "")
            rows = l2._sql(
                "SELECT key, value, expire_time FROM Cache WHERE tag = ? AND substr(key, 1, ?) = ?",
                (tag, len(from_prefix), from_prefix),
            ).fetchall()

            eff_decrypt = decrypt_fn if decrypt_fn is not None else self._decrypt_fn
            eff_encrypt = encrypt_fn if encrypt_fn is not None else self._encrypt_fn
            now = time.time()
            for l2_key, raw_val, expire_time in rows:
                if raw_val is None:
                    continue
                if expire_time is not None and expire_time <= now:
                    l2.delete(str(l2_key))  # already past its TTL: nothing to carry to the new version
                    continue
                blob = bytes(raw_val)
                comp = eff_decrypt(blob) if eff_decrypt is not None else blob
                data = json.loads(zlib.decompress(comp).decode("utf-8"))
                mutator_fn(data)
                new_comp = zlib.compress(
                    json.dumps(data, default=str).encode("utf-8"), level=6
                )
                new_blob = eff_encrypt(new_comp) if eff_encrypt is not None else new_comp
                expire = expire_time - now if expire_time is not None else None  # the row keeps its TTL
                l2.set(to_prefix + str(l2_key)[len(from_prefix):], new_blob, tag=tag, expire=expire)
                l2.delete(str(l2_key))
        except (*L2_STORAGE_ERRORS, *L2_BLOB_ERRORS) as exc:
            logger.warning("L2 restamp skipped for (%s, %s): %s", tid, namespace, exc)
