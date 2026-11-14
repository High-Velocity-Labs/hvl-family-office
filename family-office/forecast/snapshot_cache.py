"""
forecast/snapshot_cache.py: The household balance-sheet snapshot (account_sync/snapshot.py), cached against the
data it is built from.

It used to share the forecast cache's household state version, which every save bumps, so a plan edit (which
cannot change a balance) rebuilt it. It is now keyed by the versions of the domains it can read (everything but
plans and the UI-only domains; a write to data outside the domain map bumps every domain), the snapshot's own
parameters, and today's date (vesting moves with the calendar). Entries live in `hvl_common.db.TwoTierCache`'s
L1 memory only (the snapshot is decrypted data), bounded by count and bytes, stamped with the sum of those domains'
versions: it moves exactly when one of them is bumped and never goes back, so an entry built before a write never
replaces one built after it.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Dict, Mapping, Optional, Tuple

from hvl_common.db import TwoTierCache

from forecast.cache import CANONICAL_DOMAINS, _resolve_active_universe, get_domain_versions

# Domains no snapshot input lives in: plans, and state the balance sheet never reads.
_UNREAD_DOMAINS = frozenset({
    "scenarios", "advisor.threads", "notifications", "settings.invites", "onboarding.checklist",
})
SNAPSHOT_DOMAINS: Tuple[str, ...] = tuple(d for d in CANONICAL_DOMAINS if d not in _UNREAD_DOMAINS)

_SNAPSHOTS = TwoTierCache(max_l1_entries=64, max_l1_bytes=32 * 1024 * 1024)


def key(family_id: int, params: Mapping[str, Any]) -> Tuple[Any, ...]:
    """The cache key for these parameters and the household's data as of now. Take it before building a snapshot
    and store the snapshot under it: a write that lands during the build then leaves it under the older versions."""
    versions = get_domain_versions(family_id)
    entry_key = repr((
        _resolve_active_universe(),
        tuple(sorted((str(k), repr(v)) for k, v in params.items())),
        date.today().isoformat(),
    ))
    return int(family_id), entry_key, sum(int(versions.get(d, 1)) for d in SNAPSHOT_DOMAINS)


def get(snapshot_key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    """A private copy of the snapshot cached under `snapshot_key`, or None."""
    fid, entry_key, stamp = snapshot_key
    snap = _SNAPSHOTS.get("snapshot", entry_key, tenant_id=fid, state_version=stamp, check_l2=False)
    return copy.deepcopy(snap) if snap is not None else None


def put(snapshot_key: Tuple[Any, ...], snapshot: Dict[str, Any]) -> None:
    """Caches a copy of `snapshot` under `snapshot_key` (taken before the build); the caller keeps its own."""
    if not isinstance(snapshot, dict):
        return
    fid, entry_key, stamp = snapshot_key
    _SNAPSHOTS.set("snapshot", entry_key, copy.deepcopy(snapshot), tenant_id=fid, state_version=stamp, persist_l2=False)


def clear() -> None:
    """Empties the cache (tests, full cache resets)."""
    _SNAPSHOTS.clear_l1()
