"""
forecast/snapshot_cache.py: The household balance-sheet snapshot (account_sync/snapshot.py), cached against the
data it is built from.

It used to share the forecast cache's household state version, which every save bumps, so a plan edit (which
cannot change a balance) rebuilt it. It is now keyed by the versions of the domains it can read (everything but
plans and the UI-only domains; a write to data outside the domain map bumps every domain), the snapshot's own
parameters, and today's date (vesting moves with the calendar). Entries live in process memory, bounded.
"""

from __future__ import annotations

import copy
import threading
from datetime import date
from typing import Any, Dict, Mapping, Optional, Tuple

import cachetools

from forecast.cache import CANONICAL_DOMAINS, _resolve_active_universe, get_domain_versions

# Domains no snapshot input lives in: plans, and state the balance sheet never reads.
_UNREAD_DOMAINS = frozenset({
    "scenarios", "advisor.threads", "notifications", "settings.invites", "onboarding.checklist",
})
SNAPSHOT_DOMAINS: Tuple[str, ...] = tuple(d for d in CANONICAL_DOMAINS if d not in _UNREAD_DOMAINS)

_SNAPSHOTS: cachetools.LRUCache = cachetools.LRUCache(maxsize=64)
_LOCK = threading.Lock()


def key(family_id: int, params: Mapping[str, Any]) -> Tuple[Any, ...]:
    """The cache key for these parameters and the household's data as of now. Take it before building a snapshot
    and store the snapshot under it: a write that lands during the build then leaves it under the older versions."""
    versions = get_domain_versions(family_id)
    return (
        int(family_id),
        _resolve_active_universe(),
        tuple(sorted((str(k), repr(v)) for k, v in params.items())),
        date.today().isoformat(),
        tuple(int(versions.get(d, 1)) for d in SNAPSHOT_DOMAINS),
    )


def get(snapshot_key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    """A private copy of the snapshot cached under `snapshot_key`, or None."""
    with _LOCK:
        snap = _SNAPSHOTS.get(snapshot_key)
    return copy.deepcopy(snap) if snap is not None else None


def put(snapshot_key: Tuple[Any, ...], snapshot: Dict[str, Any]) -> None:
    """Caches a copy of `snapshot` under `snapshot_key` (taken before the build); the caller keeps its own."""
    if not isinstance(snapshot, dict):
        return
    stored = copy.deepcopy(snapshot)
    with _LOCK:
        _SNAPSHOTS[snapshot_key] = stored


def clear() -> None:
    """Empties the cache (tests, full cache resets)."""
    with _LOCK:
        _SNAPSHOTS.clear()
