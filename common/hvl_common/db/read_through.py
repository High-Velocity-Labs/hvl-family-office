"""
Read-through and write-through objects in `TwoTierCache`'s L1 memory (`hvl_common/db/read_through.py`).

In-memory <=> database. A read looks in memory first; on a miss it loads from the database through the caller's loader
(one loader per key, concurrent callers wait for it) and keeps the object. A write runs the database write and, only
once it has committed, applies the same change to each object it touches in memory (an aggregate such as a list gets
the delta, it is not rebuilt). A write never drops or re-reads an object; a failed write leaves memory as it was.

Keys are any hashable primary key under a namespace; tenant scoping, where an app needs it, is part of its key (and so
is the database file, when one process serves several). Each object is stamped with `stamp_fn()`, the caller's
versions (a tuple of ints) for the domains the object depends on, served from memory (e.g. a `DomainVersionTracker`
with a backstop): a read whose stamp differs reloads, which is how writes from other processes are seen. The stamp is
read BEFORE the loader runs, so a write landing mid-load leaves the object stamped with the old versions and the next
read reloads. A single-process owner with no versions passes `stamp_fn=lambda: ()`.

Objects are dicts, lists and plain values (their size estimate bounds L1's bytes; an object over `max_l1_bytes` is
returned but not kept). They stay in this process's memory only (never in L2 on disk), so decrypted data never leaves
the process. A loader runs under its key's lock: it must not read a key whose own loader reads this one.
"""

from __future__ import annotations

import logging
import threading
from contextlib import AbstractContextManager
from typing import Any, Callable, Hashable, NamedTuple, Sequence, TypeVar

import cachetools

from hvl_common.db.l1_lru import READ_THROUGH_SCOPE, _estimate_object_bytes

logger = logging.getLogger(__name__)

R = TypeVar("R")

class WriteThrough(NamedTuple):
    """One kept object a write changes: `patch_fn(kept, write_result)` is the same change applied in memory."""

    namespace: str
    key: Hashable
    patch_fn: Callable[[Any, Any], Any]
    stamp_fn: Callable[[], tuple[int, ...]]
    bumps: tuple[int, ...]


class ReadThroughMixin:
    """`get_or_load`, `update`, `drop` and `drop_where` over `L1LRUMixin`'s byte-bounded LRU (`TwoTierCache`)."""

    max_l1_entries: int
    max_l1_bytes: int
    _lock: threading.RLock
    _l1: cachetools.LRUCache

    single_flight: Callable[..., AbstractContextManager[None]]

    def _rt_lookup(self, namespace: str, key: Hashable, stamp: Any) -> tuple[bool, Any]:
        l1_key = (READ_THROUGH_SCOPE, 0, str(namespace), key)
        with self._lock:
            entry = self._l1.get(l1_key)
            if entry is None:
                return False, None
            if entry["state_version"] == stamp:
                return True, entry["data"]
            self._l1.pop(l1_key, None)
        return False, None

    def _rt_store(self, namespace: str, key: Hashable, stamp: Any, data: Any) -> None:
        l1_key = (READ_THROUGH_SCOPE, 0, str(namespace), key)
        size = max(64, _estimate_object_bytes(data))
        with self._lock:
            if size > self.max_l1_bytes:
                self._l1.pop(l1_key, None)
                logger.warning(
                    "Read-through object (%s, %r) is %d bytes, over L1's bound; not kept", namespace, key, size
                )
                return
            self._l1[l1_key] = {"state_version": stamp, "data": data, "size_bytes": size}
            while len(self._l1) > self.max_l1_entries:
                self._l1.popitem()

    def get_or_load(
        self,
        namespace: str,
        key: Hashable,
        loader: Callable[[], Any],
        *,
        stamp_fn: Callable[[], tuple[int, ...]],
    ) -> Any:
        """The object kept for `(namespace, key)` at the current `stamp_fn()`, else `loader()`'s result, kept (None
        too). Returns the kept object itself, shared with every reader: a caller that hands it on to code that changes
        it copies it first."""
        hit, data = self._rt_lookup(namespace, key, stamp_fn())
        if hit:
            return data
        with self.single_flight(READ_THROUGH_SCOPE, namespace, key):
            stamp = stamp_fn()  # read again under the lock: an update may have stored newer versions meanwhile
            hit, data = self._rt_lookup(namespace, key, stamp)
            if hit:
                return data
            data = loader()
            self._rt_store(namespace, key, stamp, data)
            return data

    def update(
        self,
        namespace: str,
        key: Hashable,
        write_fn: Callable[[], R],
        patch_fn: Callable[[Any, R], Any],
        *,
        stamp_fn: Callable[[], tuple[int, ...]],
        bumps: Sequence[int],
    ) -> R:
        """Write-through of one kept object: `update_many(write_fn, [WriteThrough(namespace, key, ...)])`."""
        return self.update_many(write_fn, [WriteThrough(namespace, key, patch_fn, stamp_fn, tuple(bumps))])

    def update_many(self, write_fn: Callable[[], R], targets: Sequence["WriteThrough"]) -> R:
        """Write-through: runs `write_fn()` (the database write; it commits or raises) and returns its result. Then
        each target's kept object becomes `patch_fn(kept, result)`, the same change applied in memory: a new object,
        or `kept` itself when the write changed nothing in it (`kept` is never changed in place: readers hold it).
        A write that commits and patches never drops or re-reads.

        `bumps` says how far the write moves each version in the target's stamp (e.g. `(1, 0)`: one bump of the first
        domain); the patched object is stamped `pre + bumps`, the versions it reflects. When another process wrote the
        same domains meanwhile, the versions are past that stamp and the next read reloads (the backstop). `bumps` must
        be exact: a declared bump the write does not make could be hidden by another writer's. A target with nothing
        kept before the write, or one a concurrent load replaced, is left for its next read. A raising `write_fn` leaves
        memory as it was. After the commit, a bump that did not land drops that one object
        (the result still returns); a `patch_fn` that raises drops it and raises (a bug in the patch, not the write:
        the targets after it are left for their next read)."""
        befores = []
        for target in targets:
            with self.single_flight(READ_THROUGH_SCOPE, target.namespace, target.key):
                pre = target.stamp_fn()
                hit, _kept = self._rt_lookup(target.namespace, target.key, pre)
                befores.append((pre, self._rt_entry(target.namespace, target.key) if hit else None))
        result = write_fn()  # outside the keys' locks: the write may read other keys (its commit hooks too)
        for target, (pre, before) in zip(targets, befores):
            if before is None:
                continue
            with self.single_flight(READ_THROUGH_SCOPE, target.namespace, target.key):
                if self._rt_entry(target.namespace, target.key) is not before:
                    # A load kept a new object meanwhile (it may already hold this write): its stamp predates the
                    # write, so the next read reloads; patching it would apply the write twice.
                    continue
                stamp = tuple(int(a) + int(d) for a, d in zip(pre, target.bumps))
                if len(target.bumps) != len(pre) or any(b < s for b, s in zip(target.stamp_fn(), stamp)):
                    # The database has the write but the versions do not show it: nothing would reload the object.
                    logger.warning(
                        "Write-through of (%s, %r): the write's bumps %r did not land; object dropped",
                        target.namespace, target.key, target.bumps,
                    )
                    self.drop(target.namespace, target.key)
                    continue
                try:
                    patched = target.patch_fn(before["data"], result)
                except Exception:
                    self.drop(target.namespace, target.key)  # the write committed; the patch's bug goes to the caller
                    raise
                self._rt_store(target.namespace, target.key, stamp, patched)
        return result

    def _rt_entry(self, namespace: str, key: Hashable) -> Any:
        with self._lock:
            return self._l1.get((READ_THROUGH_SCOPE, 0, str(namespace), key))

    def drop(self, namespace: str, key: Hashable) -> None:
        """Forgets the object kept for `(namespace, key)`."""
        with self._lock:
            self._l1.pop((READ_THROUGH_SCOPE, 0, str(namespace), key), None)

    def drop_where(self, match: Callable[[str, Hashable], bool]) -> None:
        """Forgets every kept object whose `(namespace, key)` matches, e.g. a household's when its vault locks."""
        with self._lock:
            for l1_key in [k for k in list(self._l1.keys()) if k[0] == READ_THROUGH_SCOPE and match(k[2], k[3])]:
                self._l1.pop(l1_key, None)


__all__ = ["ReadThroughMixin", "WriteThrough"]
