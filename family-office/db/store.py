"""
db/store.py: Layer 1 Unified In-Memory Domain Entity Cache.
Decrypted domain entities, read through `hvl_common.db.TwoTierCache` (L1 memory only: decrypted data never reaches
disk) under `(db_key, family_id)` per entity and stamped with the versions of the entity's domains.
Eliminates N+1 SQLite query loops and redundant Fernet decryptions during simulation and SSR rendering.
A write bumps only the domains it touched (forecast/cache.py), which moves the stamp of exactly the entities that
read them: nothing is dropped on a write, and a plan edit leaves accounts, holdings and the rest cached.
"""

from __future__ import annotations
import sqlite3
import copy
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from hvl_common.db import TwoTierCache
from hvl_common.db.sqlite import _resolve_db_key
import security

logger = logging.getLogger(__name__)

# Namespace: entity_name; key: (db_key, family_id); stamp: the entity's domain versions (`_entity_version`).
_ENTITIES = TwoTierCache(max_l1_entries=256, max_l1_bytes=64 * 1024 * 1024)

# The domains whose writes can change each entity (the tables and encrypted keys forecast/cache.py maps to them).
# An entity not listed here is keyed by the household state version, which every write bumps.
ENTITY_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "tuition_ledger": ("college",),
    "tuition_labels": ("college",),
    "family_members": ("household.members",),
    "deletion_status": ("household.identity",),
    "household_profile": ("household.identity",),
    "household_assumptions": ("household.identity",),
    "accounts": ("accounts",),
    "holdings_by_account": ("holdings",),
    "account_roles": ("accounts",),
    "balance_history": ("balance_sheet.history",),
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
    Fetches a decrypted domain entity kept for `(db_key, family_id)` at the entity's current domain versions, or
    loads it once via `loader_fn(resolved_path)` (concurrent callers wait for that load) and keeps it.
    """
    fid = int(family_id or 0)
    resolved_path = _resolve_active_db_path(db_path)
    if fid <= 0 or not resolved_path.exists():
        return loader_fn(resolved_path)

    try:
        ver = _entity_version(fid, str(entity_name))
    except sqlite3.Error as exc:
        # Without a version the entry could outlive a write; load it uncached.
        logger.warning("No version for %s of family %s: %s", entity_name, fid, exc)
        return loader_fn(resolved_path)

    val = _ENTITIES.get_or_load(
        str(entity_name),
        (_resolve_db_key(resolved_path), fid),
        lambda: loader_fn(resolved_path),
        stamp_fn=lambda: ver,
    )
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


def forget_family(family_id: int = 0) -> None:
    """Forgets every decrypted entity kept for `family_id` (its deletion, shred, or a write of unknown scope)."""
    fid = int(family_id or 0)
    if fid <= 0:
        return
    _ENTITIES.drop_where(lambda _entity, key: key[1] == fid)


def clear() -> None:
    """Clears the entire in-memory domain entity cache."""
    _ENTITIES.clear_l1()


def notify_family_mutation(
    family_id: int = 0,
    domains: Optional[Any] = None,
    db_path: Optional[Union[str, Path]] = None,
    *,
    domains_persisted: bool = False,
) -> None:
    """
    Universal mutation hook called by `db/*` and `security.py` after any state-changing write.
    Skips it during the initial `init_db` data migration, otherwise bumps the domains the write changed
    (`forecast_cache.invalidate_family_cache`), which moves the stamps of the entities and forecasts that read them.
    """
    fid = int(family_id or 0)
    if fid <= 0:
        return
    from db import data_migration
    if data_migration.is_in_initial_migration():
        return
    if domains is None:
        # A write of unknown scope (a vault lock, a deletion cancel, an import) bumps only what the request recorded,
        # so it forgets every decrypted entity of the household: none may outlive a lock unstamped.
        forget_family(fid)
    from forecast import cache as forecast_cache
    forecast_cache.invalidate_family_cache(
        fid, domains=domains, db_path=db_path, domains_persisted=domains_persisted
    )

