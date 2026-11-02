"""
db/store.py: Layer 1 Unified In-Memory Domain Entity Cache.
Caches decrypted domain entities per (db_path, family_id, versions of the entity's domains) with LRU bounding.
Eliminates N+1 SQLite query loops and redundant Fernet decryptions during simulation and SSR rendering.
A write bumps only the domains it touched (forecast/cache.py), so a plan edit leaves accounts, holdings and the
rest cached instead of reloading and decrypting them all.
"""

from __future__ import annotations
import sqlite3
from collections import OrderedDict
import copy
import logging
from pathlib import Path
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from hvl_common.db.sqlite import _resolve_db_key
import security

logger = logging.getLogger(__name__)

_STORE_LOCK = threading.RLock()
_MAX_STORE_ENTRIES = 256
# Key: (db_key, family_id, entity version, entity_name) -> value
_ENTITY_CACHE: OrderedDict[Tuple[str, int, Tuple[int, ...], str], Any] = OrderedDict()

# The domains whose writes can change each entity (the tables and encrypted keys forecast/cache.py maps to them).
# An entity not listed here is keyed by the household state version, which every write bumps.
ENTITY_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "tuition_ledger": ("college",),
    "tuition_labels": ("college",),
    "family_members": ("household.members",),
    "deletion_status": ("household.identity",),
    "household_profile": ("household.identity",),
    "accounts": ("accounts",),
    "holdings_by_account": ("holdings",),
    "account_roles": ("accounts",),
    "equity_grants": ("equity",),
    "equity_companies_summary": ("equity",),
}


def _resolve_active_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    from forecast.storage import get_db_path

    return Path(get_db_path())


def _entity_version(family_id: int, entity_name: str) -> Tuple[int, ...]:
    """The versions of the domains `entity_name` depends on (the state version for an unlisted entity)."""
    from forecast import cache as forecast_cache

    domains = ENTITY_DOMAINS.get(entity_name)
    if domains is None:
        return (forecast_cache.get_state_version(family_id),)
    versions = forecast_cache.get_domain_versions(family_id)
    return tuple(int(versions.get(d, 1)) for d in domains)


def get_or_load_entity(
    family_id: int,
    entity_name: str,
    loader_fn: Callable[[Path], Any],
    *,
    db_path: Optional[Union[str, Path]] = None,
    clone: bool = False,
) -> Any:
    """
    Fetches a decrypted domain entity from the bounded in-memory cache keyed by
    `(db_key, family_id, entity version, entity_name)` or loads it via `loader_fn(resolved_path)`.
    """
    fid = int(family_id or 0)
    resolved_path = _resolve_active_db_path(db_path)
    if fid <= 0 or not resolved_path.exists():
        return loader_fn(resolved_path)

    db_key = _resolve_db_key(resolved_path)
    try:
        ver = _entity_version(fid, str(entity_name))
    except sqlite3.Error as exc:
        # Without a version the entry could outlive a write; load it uncached.
        logger.warning("No version for %s of family %s: %s", entity_name, fid, exc)
        return loader_fn(resolved_path)
    cache_key = (db_key, fid, ver, str(entity_name))

    with _STORE_LOCK:
        if cache_key in _ENTITY_CACHE:
            _ENTITY_CACHE.move_to_end(cache_key)
            val = _ENTITY_CACHE[cache_key]
            return copy.deepcopy(val) if clone else val

    val = loader_fn(resolved_path)

    with _STORE_LOCK:
        # Evict other versions of the same (db_key, fid, entity_name)
        stale_keys = [
            k for k in _ENTITY_CACHE
            if k[0] == db_key and k[1] == fid and k[3] == entity_name and k[2] != ver
        ]
        for k in stale_keys:
            _ENTITY_CACHE.pop(k, None)

        _ENTITY_CACHE[cache_key] = val
        _ENTITY_CACHE.move_to_end(cache_key)
        while len(_ENTITY_CACHE) > _MAX_STORE_ENTRIES:
            _ENTITY_CACHE.popitem(last=False)

    return copy.deepcopy(val) if clone else val


def _tuition_rows(path: Path, fid: int) -> List[tuple]:
    """Returns `[(child_user_id, calendar_year, amount, label)]` for every tuition row with a parsable school year."""
    out: List[tuple] = []
    if not path.exists():
        return out
    from sqlalchemy import select
    from db.models import TuitionRecord
    from db.session import get_orm_session

    with get_orm_session(path, family_id=fid) as session:
        rows = session.scalars(
            select(TuitionRecord)
            .where(TuitionRecord.family_id == fid)
            .order_by(TuitionRecord.tuition_id.asc())
        ).all()
        for row in rows:
            if row.child_user_id is None:
                continue
            try:
                cid = int(row.child_user_id)
            except (ValueError, TypeError):
                continue
            yr_prefix = str(row.school_year or "").strip().split("-")[0].strip()
            if not yr_prefix.isdigit():
                continue
            label = f"{row.school_name or ''} {row.notes or ''}".strip()
            out.append((cid, int(yr_prefix), float(row.tuition_amount or 0.0), label))
    return out


def get_tuition_ledger(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[int, Dict[int, float]]:
    """
    Batch-loads and decrypts the entire tuition ledger for `family_id` in a single SQLite query.
    Returns `{child_user_id: {calendar_year: verified_tuition_float}}`.
    """
    fid = int(family_id or 0)
    if fid <= 0:
        return {}

    def _load(path: Path) -> Dict[int, Dict[int, float]]:
        ledger: Dict[int, Dict[int, float]] = {}
        for cid, yr, amt, _label in _tuition_rows(path, fid):
            ledger.setdefault(cid, {})[yr] = amt
        return ledger

    return get_or_load_entity(fid, "tuition_ledger", _load, db_path=db_path, clone=False)


def get_tuition_labels(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[int, Dict[int, str]]:
    """Returns `{child_user_id: {calendar_year: "school name + notes"}}` for classifying ledger rows by level."""
    fid = int(family_id or 0)
    if fid <= 0:
        return {}

    def _load(path: Path) -> Dict[int, Dict[int, str]]:
        labels: Dict[int, Dict[int, str]] = {}
        for cid, yr, _amt, label in _tuition_rows(path, fid):
            labels.setdefault(cid, {})[yr] = label
        return labels

    return get_or_load_entity(fid, "tuition_labels", _load, db_path=db_path, clone=False)


def get_family_members(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns cached decrypted family members for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return []

    def _load(path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        return security.get_family_members(path, family_id=fid)

    return get_or_load_entity(fid, "family_members", _load, db_path=db_path, clone=True)


def get_deletion_status(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Returns L1-cached 30-day deletion quarantine status for `family_id`, or `None` if active."""
    fid = int(family_id or 0)
    if fid <= 0:
        return None

    def _load(path: Path) -> Optional[Dict[str, Any]]:
        return security.get_family_deletion_status(path, family_id=fid)

    return get_or_load_entity(fid, "deletion_status", _load, db_path=db_path, clone=True)


def get_household_profile(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Returns cached household profile for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return None

    def _load(path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        from db import household
        return household.get_household_profile(family_id=fid, db_path=path)

    return get_or_load_entity(fid, "household_profile", _load, db_path=db_path, clone=True)


def get_accounts(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns cached decrypted Monarch accounts for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return []

    def _load(path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        from db import accounts
        return accounts.list_accounts(family_id=fid, db_path=path)

    return get_or_load_entity(fid, "accounts", _load, db_path=db_path, clone=True)


def get_holdings_by_account(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Returns cached decrypted Monarch holdings by account for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return {}

    def _load(path: Path) -> Dict[str, List[Dict[str, Any]]]:
        if not path.exists():
            return {}
        from db import accounts
        return accounts.get_holdings_by_account(family_id=fid, db_path=path)

    return get_or_load_entity(fid, "holdings_by_account", _load, db_path=db_path, clone=True)


def get_account_roles(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns cached account role rows for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return []

    def _load(path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        from db import account_roles
        return account_roles.get_account_roles(family_id=fid, db_path=path)

    return get_or_load_entity(fid, "account_roles", _load, db_path=db_path, clone=True)


def get_equity_grants(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Any]:
    """Returns cached decrypted `EquityGrant` instances for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return []

    def _load(_path: Path) -> List[Any]:
        from services import equity_engine
        return equity_engine.load_equity_grants_from_db(family_id=fid)

    return get_or_load_entity(fid, "equity_grants", _load, db_path=db_path, clone=True)


def get_equity_companies_summary(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns cached decrypted equity companies summary for `family_id`."""
    fid = int(family_id or 0)
    if fid <= 0:
        return []

    def _load(_path: Path) -> List[Dict[str, Any]]:
        from services import equity_engine
        return equity_engine.load_equity_companies_summary(family_id=fid)

    return get_or_load_entity(fid, "equity_companies_summary", _load, db_path=db_path, clone=True)


def invalidate_family(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
    domains: Optional[Any] = None,
) -> None:
    """Purges the cached domain entities for `family_id` that depend on `domains` (all of them when None)."""
    fid = int(family_id or 0)
    if fid <= 0:
        return
    target_key = _resolve_db_key(db_path) if db_path is not None else None
    changed = None if domains is None else {str(d) for d in domains}

    def affected(entity_name: str) -> bool:
        entity_domains = ENTITY_DOMAINS.get(entity_name)
        return changed is None or entity_domains is None or bool(changed.intersection(entity_domains))

    with _STORE_LOCK:
        to_remove = [
            k for k in _ENTITY_CACHE
            if k[1] == fid and (target_key is None or k[0] == target_key) and affected(k[3])
        ]
        for k in to_remove:
            _ENTITY_CACHE.pop(k, None)


def clear() -> None:
    """Clears the entire in-memory domain entity cache."""
    with _STORE_LOCK:
        _ENTITY_CACHE.clear()


def notify_family_mutation(
    family_id: int = 0,
    domains: Optional[Any] = None,
    db_path: Optional[Union[str, Path]] = None,
    *,
    domains_persisted: bool = False,
) -> None:
    """
    Universal mutation hook called by `db/*` and `security.py` after any state-changing write.
    Skips invalidation during initial `init_db` data migration, otherwise atomically invalidates
    both L1/L2 `forecast_cache` and `db.store`.
    """
    fid = int(family_id or 0)
    if fid <= 0:
        return
    from db import data_migration
    if data_migration.is_in_initial_migration():
        return
    invalidate_family(fid, db_path=db_path, domains=domains)
    from forecast import cache as forecast_cache
    forecast_cache.invalidate_family_cache(
        fid, domains=domains, db_path=db_path, domains_persisted=domains_persisted
    )

