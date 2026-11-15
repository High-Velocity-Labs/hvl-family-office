"""
db/store.py: Layer 1 Unified In-Memory Domain Entity Cache.
Decrypted domain entities, read through `hvl_common.db.TwoTierCache` (L1 memory only: decrypted data never reaches
disk) under `(db_key, family_id)` per entity and stamped with the versions of the entity's domains.
Eliminates N+1 SQLite query loops and redundant Fernet decryptions during simulation and SSR rendering.
A write bumps only the domains it touched (forecast/cache.py). A repository write that runs through `write_through`
then applies the same change to each kept entity it changed and keeps the others at the new versions, so nothing is
reloaded; a write that does not (or another process's) moves the stamps, and the entities that read those domains
load again on their next read.
"""

from __future__ import annotations
import sqlite3
import copy
import json
import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar, Union

from hvl_common.db import TwoTierCache, WriteThrough
from hvl_common.db.sqlite import _resolve_db_key
import security

logger = logging.getLogger(__name__)

# The domains each commit bumped while a `write_through` write runs: `[(family_id, domains)]`.
_WRITE_BUMPS: ContextVar[Optional[List[Tuple[int, frozenset]]]] = ContextVar("_write_bumps", default=None)

R = TypeVar("R")

# Namespace: entity_name; key: (db_key, family_id); stamp: the entity's domain versions (`_entity_version`).
_ENTITIES = TwoTierCache(max_l1_entries=256, max_l1_bytes=64 * 1024 * 1024)

# The domains whose writes can change each entity (the tables and encrypted keys forecast/cache.py maps to them).
# An entity not listed here is keyed by the household state version, which every write bumps.
ENTITY_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "tuition_ledger": ("college",),
    "tuition_labels": ("college",),
    "family_members": ("household.members",),
    "deletion_status": ("household.identity",),
    "family_settings": ("household.identity",),
    "household_profile": ("household.identity",),
    "household_assumptions": ("household.identity",),
    "accounts": ("accounts",),
    "holdings_by_account": ("holdings",),
    "account_roles": ("accounts",),
    "balance_history": ("balance_sheet.history",),
    "equity_grants": ("equity",),
    "equity_companies_summary": ("equity",),
}

# The tables each entity is read from. A `write_through` write to one of them patches the entity (or, with no patch
# from the writer, leaves it to load on its next read); a write that bumps the entity's domains only through other
# tables leaves it as it is, kept at the new versions.
ENTITY_TABLES: Dict[str, Tuple[str, ...]] = {
    "tuition_ledger": ("tuition",),
    "tuition_labels": ("tuition",),
    "family_members": ("users",),
    "deletion_status": ("families",),
    "family_settings": ("families",),
    "household_profile": ("household_profile",),
    "household_assumptions": ("household_assumption_sections", "household_profile"),
    "accounts": ("monarch_accounts",),
    "holdings_by_account": ("monarch_holdings",),
    "account_roles": ("account_roles",),
    "balance_history": ("account_balance_snapshots",),
    "equity_grants": ("equity_grants", "equity_companies", "fmv_history"),
    "equity_companies_summary": ("equity_grants", "equity_companies", "fmv_history"),
}


def _resolve_active_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    from forecast.storage import get_db_path

    return Path(get_db_path())


def _entity_key(fid: int, path: Path) -> Tuple[str, int]:
    """The key of a household's entities: its own database, whichever root or family path the caller named, so a
    read through the active path and a write through the household's path keep and patch the same entry."""
    from db.session import resolve_db_path

    return (_resolve_db_key(resolve_db_path(path, family_id=fid)), fid)


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
        _entity_key(fid, resolved_path),
        lambda: loader_fn(resolved_path),
        stamp_fn=lambda: ver,
    )
    return copy.deepcopy(val) if clone else val


def unchanged(kept: Any, _result: Any) -> Any:
    """The patch of an entity read from a table the write touched only in columns the entity does not read."""
    return kept


def stored_json(value: Any) -> Any:
    """`value` as an encrypted JSON column reads it back, for a patch built from the values a write stored."""
    return json.loads(json.dumps(value, default=str))


def write_through(
    family_id: int,
    db_path: Union[str, Path],
    tables: Iterable[str],
    write_fn: Callable[[], R],
    patches: Optional[Dict[str, Callable[[Any, R], Any]]] = None,
    *,
    domains: Optional[Iterable[str]] = None,
) -> R:
    """
    Runs `write_fn()`, ONE committed transaction on `db_path` that writes exactly `tables` (their domains are the
    bumps it declares, or `domains` for a write whose notify names its own), and returns its result. Then, for the
    entities kept for the household: one read from a table in `tables` becomes `patches[entity](kept, result)`, the
    same change applied in memory (a new object; `kept` is shared with readers and never changed); one with no patch
    here is left to load on its next read; one whose domains the write bumps only through other tables is kept as it
    is at the new versions. Another process's write to the same domains meanwhile moves the versions past the patched
    stamp, so the next read loads (the backstop).
    """
    fid = int(family_id or 0)
    path = Path(db_path)
    if fid <= 0 or not path.exists():
        return write_fn()
    from forecast import cache as forecast_cache

    written = {str(t) for t in tables}
    bumped = (
        {str(d) for d in domains} if domains is not None else forecast_cache.resolve_domains_for_tables(written)
    )
    key = _entity_key(fid, path)
    targets = []
    for name, entity_domains in ENTITY_DOMAINS.items():
        bumps = tuple(1 if d in bumped else 0 for d in entity_domains)
        if not any(bumps):
            continue
        patch = (patches or {}).get(name)
        if patch is None:
            if set(ENTITY_TABLES[name]) & written:
                continue
            patch = unchanged
        targets.append(WriteThrough(name, key, patch, _stamp_fn(fid, name), bumps))

    def _write() -> R:
        seen: List[Tuple[int, frozenset]] = []
        token = _WRITE_BUMPS.set(seen)
        try:
            result = write_fn()
        finally:
            _WRITE_BUMPS.reset(token)
        if [b for b in seen if b[0] == fid] != [(fid, frozenset(bumped))]:
            # The write bumped other domains than it declared, or none, or twice (a no-op save, an early return): its
            # stamps would not say what the kept entities hold, so they load on their next read instead.
            for target in targets:
                _ENTITIES.drop(target.namespace, target.key)
        return result

    return _ENTITIES.update_many(_write, targets)


def _stamp_fn(fid: int, entity_name: str) -> Callable[[], Tuple[int, ...]]:
    def _stamp() -> Tuple[int, ...]:
        try:
            return _entity_version(fid, entity_name)
        except sqlite3.Error as exc:
            # No stamp matches a kept entity, so it is not patched before the write and is dropped after it.
            logger.warning("No version for %s of family %s: %s", entity_name, fid, exc)
            return ()

    return _stamp


def patch_rows(
    kept: List[Dict[str, Any]],
    rows: Iterable[Dict[str, Any]],
    key: str,
    *,
    drop: Callable[[Any], bool] = lambda _k: False,
) -> List[Dict[str, Any]]:
    """`kept` (rows in insertion order) without the rows whose `key` `drop` names, each of `rows` (as the write stored
    them) in place of the kept row with its `key`, and the rest of `rows` appended in the order they were inserted."""
    fresh = {r[key]: stored_json(r) for r in rows}
    out = [fresh.pop(r[key], r) for r in kept if not drop(r[key])]
    return out + list(fresh.values())


def patch_balance_history(
    kept: Dict[str, Dict[str, float]],
    written: Dict[str, Dict[str, float]],
    removed: Optional[Dict[str, Optional[Iterable[str]]]] = None,
) -> Dict[str, Dict[str, float]]:
    """`kept` (`{account_id: {date: balance}}`, accounts and dates ascending) with the days in `removed` deleted (all
    of an account's days for None) and the `written` days set."""
    out = {acc: dict(days) for acc, days in kept.items()}
    for acc, dates in (removed or {}).items():
        if dates is None:
            out.pop(acc, None)
            continue
        for d in dates:
            out.get(acc, {}).pop(str(d), None)
    for acc, days in written.items():
        out.setdefault(acc, {}).update({d: round(float(v), 2) for d, v in days.items()})
    return {acc: dict(sorted(out[acc].items())) for acc in sorted(out) if out[acc]}


def tuition_rows_in(session: Any, fid: int) -> List[tuple]:
    """`[(child_user_id, calendar_year, amount, label)]` for every tuition row with a parsable school year, in
    `session` (a write reads them back in its own transaction to patch the tuition entities)."""
    from sqlalchemy import select
    from db.models import TuitionRecord

    stmt = select(TuitionRecord).where(TuitionRecord.family_id == fid)
    out: List[tuple] = []
    for row in session.scalars(stmt.order_by(TuitionRecord.tuition_id.asc())).all():
        if row.child_user_id is None:
            continue
        try:
            cid = int(row.child_user_id)
        except (ValueError, TypeError):
            # A legacy row with a non-numeric child id belongs to no child the planner knows; the ledger omits it.
            continue
        yr_prefix = str(row.school_year or "").strip().split("-")[0].strip()
        if not yr_prefix.isdigit():
            continue
        label = f"{row.school_name or ''} {row.notes or ''}".strip()
        out.append((cid, int(yr_prefix), float(row.tuition_amount or 0.0), label))
    return out


def _tuition_rows(path: Path, fid: int) -> List[tuple]:
    """Returns `[(child_user_id, calendar_year, amount, label)]` for every tuition row with a parsable school year."""
    if not path.exists():
        return []
    from db.session import get_orm_session

    with get_orm_session(path, family_id=fid) as session:
        return tuition_rows_in(session, fid)


def tuition_cells(rows: Iterable[tuple], *, labels: bool) -> Dict[int, Dict[int, Any]]:
    """`{child_user_id: {calendar_year: amount (or label)}}` from `tuition_rows_in` rows, in their order."""
    out: Dict[int, Dict[int, Any]] = {}
    for cid, yr, amt, label in rows:
        out.setdefault(cid, {})[yr] = label if labels else amt
    return out


# A tuition write returns `(result, tuition_rows_in(...))`; both entities are rebuilt whole from the rows it read back.
TUITION_PATCHES = {
    "tuition_ledger": lambda _kept, res: tuition_cells(res[1], labels=False),
    "tuition_labels": lambda _kept, res: tuition_cells(res[1], labels=True),
}


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
        return tuition_cells(_tuition_rows(path, fid), labels=False)

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
        return tuition_cells(_tuition_rows(path, fid), labels=True)

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


# Every domain a kept entity reads: a vault lock moves them all, so no load racing it stays current.
_ENTITY_DOMAINS_ALL: Tuple[str, ...] = tuple(sorted({d for ds in ENTITY_DOMAINS.values() for d in ds}))


def forget_family(family_id: int, domains: Iterable[str]) -> None:
    """Forgets every decrypted entity kept for `family_id` (a vault lock, a deletion, a shred, a restore) after
    bumping `domains` (what the write changed) and every domain an entity reads. Bumping first: a load that read its
    stamp before the bump and keeps its entity after the forget holds the old versions, so the next read loads again
    instead of serving what it decrypted before the lock."""
    if domains is None:
        raise TypeError("forget_family needs the domains the write changed")
    fid = int(family_id or 0)
    if fid <= 0:
        return
    from forecast import cache as forecast_cache

    try:
        forecast_cache.invalidate_family_cache(fid, domains={str(d) for d in domains} | set(_ENTITY_DOMAINS_ALL))
    finally:
        _ENTITIES.drop_where(lambda _entity, key: key[1] == fid)  # a bump that raised still drops what was decrypted


def clear() -> None:
    """Clears the entire in-memory domain entity cache."""
    _ENTITIES.clear_l1()


def notify_family_mutation(
    family_id: int,
    domains: Iterable[str],
    db_path: Optional[Union[str, Path]] = None,
    *,
    domains_persisted: bool = False,
) -> None:
    """
    Universal mutation hook called by `db/*` and `security.py` after any state-changing write.
    Skips it during the initial `init_db` data migration, otherwise bumps the domains the write changed
    (`forecast_cache.invalidate_family_cache`), which moves the stamps of the entities and forecasts that read them.
    Every write names its domains (`CANONICAL_DOMAINS` for one that replaced the whole household); a write that must
    drop the household's decrypted entities (a vault lock, a restore) calls `forget_family` with them instead.
    """
    if domains is None:
        raise TypeError("notify_family_mutation needs the domains the write changed")
    fid = int(family_id or 0)
    if fid <= 0:
        return
    from db import data_migration
    if data_migration.is_in_initial_migration():
        return
    recorded = _WRITE_BUMPS.get()
    if recorded is not None:
        recorded.append((fid, frozenset(str(d) for d in domains)))
    from forecast import cache as forecast_cache
    forecast_cache.invalidate_family_cache(
        fid, domains=domains, db_path=db_path, domains_persisted=domains_persisted
    )

