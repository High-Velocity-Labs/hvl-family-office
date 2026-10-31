"""
forecast/cache.py: Two-Tier Encrypted Cache (L1 In-Memory LRU + L2 SQLite `computed_cache`)
for Scenarios, Monte Carlo Simulations, Financial Snapshots, and Estate Profiles.
Delegates lifecycle and stampede protection to `hvl_common.db.TwoTierCache`.
"""

from __future__ import annotations

import copy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

import cachetools
from hvl_common.db import TwoTierCache
from hvl_common.db.sqlite import _resolve_db_key
from db.domain_versions import (
    bump_domain_rows,
    delete_all_domain_versions,
    load_domain_versions_row,
    raise_state_version,
)
import security

CANONICAL_DOMAINS: Tuple[str, ...] = (
    "balance_sheet", "accounts", "holdings", "holdings.policy", "equity",
    "tax_profile", "compensation", "household.members", "household.identity",
    "scenarios", "college", "philanthropy", "gifting", "estate",
    "onboarding.checklist", "settings.invites", "advisor.threads", "notifications",
)

TABLE_DOMAIN_MAP: Dict[str, Tuple[str, ...]] = {
    "monarch_accounts": ("accounts", "balance_sheet", "onboarding.checklist"),
    "monarch_holdings": ("holdings", "accounts", "balance_sheet"),
    "account_roles": ("accounts", "balance_sheet", "college", "estate"),
    "equity_companies": ("equity", "balance_sheet"),
    "equity_grants": ("equity", "balance_sheet", "onboarding.checklist"),
    "fmv_history": ("equity", "balance_sheet"),
    "compensation": ("compensation", "tax_profile"),
    "tax_transcript_meta": ("tax_profile", "compensation", "onboarding.checklist"),
    "tax_transcript_records": ("tax_profile", "compensation", "onboarding.checklist"),
    "users": ("household.members", "college", "estate", "gifting", "onboarding.checklist"),
    "families": ("household.identity", "household.members", "tax_profile", "onboarding.checklist"),
    "household_profile": ("household.identity", "tax_profile", "scenarios", "balance_sheet", "estate", "onboarding.checklist"),
    "forecast_scenarios": ("scenarios",), "forecast_events": ("scenarios",), "forecast_settings": ("scenarios",),
    "tuition": ("college",), "tuition_year_records": ("college",),
    "philanthropy_budgets": ("philanthropy",), "philanthropy_donations": ("philanthropy",),
    "gift_recipients": ("gifting", "estate"), "gifts": ("gifting", "estate"),
    "estate_profiles": ("estate", "onboarding.checklist"),
    "invite_tokens": ("settings.invites",),
    "advisor_conversations": ("advisor.threads",), "advisor_messages": ("advisor.threads",),
    "household_notifications": ("notifications",), "push_subscriptions": ("notifications",),
}

ENCRYPTED_KEY_DOMAIN_MAP: Dict[str, Tuple[str, ...]] = {
    "accounts": ("accounts", "balance_sheet", "onboarding.checklist"),
    "monarch_credentials": ("accounts", "balance_sheet", "onboarding.checklist"),
    "simplefin_credentials": ("accounts", "balance_sheet", "onboarding.checklist"),
    "simplefin_access_url": ("accounts", "balance_sheet", "onboarding.checklist"),
    "holdings": ("holdings", "accounts", "balance_sheet"),
    "investment_policy": ("holdings.policy", "holdings"),
    "holdings_policy": ("holdings.policy", "holdings"),
    "target_allocation": ("holdings.policy", "holdings"),
    "company_equity_grants": ("equity", "balance_sheet", "onboarding.checklist"),
    "career_compensation": ("compensation", "tax_profile"),
    "tax_transcripts": ("tax_profile", "compensation", "onboarding.checklist"),
    "estate_profile": ("estate", "onboarding.checklist"),
    "private_school_tuition": ("college",), "college_529_settings": ("college",),
    "scenario_system_state": ("scenarios",), "scenarios": ("scenarios",),
    "annual_donations": ("philanthropy",), "family_gifts": ("gifting", "estate"),
    "onboarding_checklist": ("onboarding.checklist",), "onboarding_dismissed": ("onboarding.checklist",),
}

_DOMAIN_LOCK = threading.RLock()
_DOMAIN_VERSIONS_MEM: Dict[Tuple[str, int], Tuple[int, Dict[str, int]]] = {}

CANONICAL_SIMULATION_KEYS = frozenset({
    "scenario_id", "target_scenario_id", "view_mode", "equity_growth_preset",
})

SLIDER_OVERRIDE_KEYS = frozenset({
    "annual_living_spend", "annual_savings", "primary_retirement_age", "retirement_age",
    "spouse_retirement_age", "inflation_rate", "ss_claim_age", "primary_ss_claim_age",
    "spouse_ss_claim_age", "custom_equity_growth_rate", "equity_growth_presets",
})

CACHE_SCHEMA_VERSION = "v11"


def resolve_domains_for_tables(tables: Optional[Iterable[str]]) -> Set[str]:
    out: Set[str] = set()
    for tbl in tables or ():
        out.update(TABLE_DOMAIN_MAP.get(str(tbl), ()))
    return out


def resolve_domains_for_encrypted_key(key: str, category: str = "") -> Tuple[str, ...]:
    k = str(key or "").strip().lower()
    if k in ENCRYPTED_KEY_DOMAIN_MAP:
        return ENCRYPTED_KEY_DOMAIN_MAP[k]
    cat = str(category or "").strip().lower()
    if cat in ("policy", "allocation"):
        return ("holdings.policy", "holdings")
    if cat in ("credentials", "accounts", "sync", "simplefin", "monarch"):
        return ("accounts", "balance_sheet", "onboarding.checklist")
    if cat == "onboarding":
        return ("onboarding.checklist",)
    return CANONICAL_DOMAINS


def _default_domain_map(base_ver: int = 1) -> Dict[str, int]:
    v = max(1, int(base_ver))
    return {d: v for d in CANONICAL_DOMAINS}


def record_request_domains(family_id: int, domains: Iterable[str]) -> None:
    try:
        from flask import g, has_request_context
        if has_request_context():
            req_map = getattr(g, "_request_mutated_domains", None)
            if req_map is None:
                req_map = {}
                g._request_mutated_domains = req_map
            req_map.setdefault(int(family_id), set()).update(domains)
    except Exception:
        pass


def get_request_domains(family_id: int) -> Optional[Set[str]]:
    try:
        from flask import g, has_request_context
        if has_request_context():
            req_map = getattr(g, "_request_mutated_domains", None)
            return req_map.get(int(family_id)) if isinstance(req_map, dict) else None
    except Exception:
        pass
    return None


def _has_custom_db_override() -> Optional[Path]:
    try:
        fe = sys.modules.get("forecast.engine") or sys.modules.get("forecast_engine")
        if fe is not None and hasattr(fe, "DB_PATH"):
            fe_db = fe.DB_PATH
            if type(fe_db).__name__ not in ("_DbPathProxy", "_ForecastDbPathProxy"):
                return Path(fe_db)
        fs = sys.modules.get("forecast.storage")
        if fs is not None and hasattr(fs, "DB_PATH") and getattr(fs.DB_PATH, "_override", None) is not None:
            return Path(fs.DB_PATH._override)
    except Exception:
        pass
    return None


def _resolve_state_db_path(universe: Optional[str] = None, family_id: Optional[int] = None) -> Path:
    override = _has_custom_db_override()
    if override is not None:
        return override
    eff_fid = int(family_id) if family_id is not None else 0
    if eff_fid <= 0:
        try:
            from services.request_context import get_current_family_id
            eff_fid = int(get_current_family_id() or 0)
        except Exception:
            eff_fid = 0
    u = (universe or "").strip().lower()
    if u and not (os.getenv("APP_UNIVERSE", "").strip().lower() == "test" and u in ("public", "test")):
        from config import get_family_db_path, get_global_db_path
        return get_family_db_path(eff_fid, universe=u) if eff_fid > 0 else get_global_db_path(u)
    if eff_fid > 0:
        try:
            from services.request_context import get_current_db_path
            return get_current_db_path(family_id=eff_fid)
        except Exception:
            from config import get_family_db_path
            return get_family_db_path(eff_fid)
    try:
        from forecast.storage import get_db_path
        return Path(get_db_path())
    except Exception:
        from config import get_global_db_path
        return get_global_db_path()


def _resolve_cache_db_path(universe: Optional[str] = None, family_id: Optional[int] = None) -> Path:
    override = _has_custom_db_override()
    if override is not None:
        return override.parent / f"{override.stem}_cache.db"
    eff_fid = int(family_id) if family_id is not None else 0
    if eff_fid <= 0:
        try:
            from services.request_context import get_current_family_id
            eff_fid = int(get_current_family_id() or 0)
        except Exception:
            eff_fid = 0
    fid_arg = eff_fid if eff_fid > 0 else None
    u = (universe or "").strip().lower()
    if u and not (os.getenv("APP_UNIVERSE", "").strip().lower() == "test" and u in ("public", "test")):
        from config import get_cache_db_path_for_universe
        return get_cache_db_path_for_universe(u, family_id=fid_arg)
    try:
        from services.request_context import get_current_cache_db_path
        return get_current_cache_db_path(family_id=fid_arg)
    except Exception:
        from config import get_cache_db_path_for_universe
        return get_cache_db_path_for_universe(family_id=fid_arg)


def _resolve_active_universe() -> str:
    try:
        from services.request_context import get_current_universe
        return get_current_universe()
    except Exception:
        from config import APP_UNIVERSE
        return APP_UNIVERSE


def _make_encrypt_fn(family_id: int, state_db: Optional[Path] = None) -> Callable[[bytes], bytes]:
    def _encrypt(raw: bytes) -> bytes:
        db_p = state_db or _resolve_state_db_path(family_id=family_id)
        key = security.get_family_key(db_p, int(family_id))
        return security._get_fernet(key).encrypt(raw)
    return _encrypt


def _make_decrypt_fn(family_id: int, state_db: Optional[Path] = None) -> Callable[[bytes], bytes]:
    def _decrypt(cipher: bytes) -> bytes:
        db_p = state_db or _resolve_state_db_path(family_id=family_id)
        key = security.get_family_key(db_p, int(family_id))
        return security._get_fernet(key).decrypt(cipher)
    return _decrypt


def _parse_cache_key(key: str) -> Tuple[int, str, Optional[int]]:
    """Extracts `(family_id, universe, version)` from `"{family_id}:{universe}:v{version}:{hash}"`."""
    parts = str(key or "").split(":")
    family_id = 0
    universe = "public"
    version: Optional[int] = None
    if len(parts) >= 1:
        try:
            family_id = int(parts[0])
        except (ValueError, TypeError):
            family_id = 0
    if len(parts) >= 2 and parts[1]:
        universe = parts[1]
    if len(parts) >= 3 and parts[2].startswith("v"):
        try:
            version = int(parts[2][1:])
        except (ValueError, TypeError):
            version = None
    return family_id, universe, version


def is_canonical_simulation_params(params: Optional[Dict[str, Any]] = None) -> bool:
    """
    Returns True if `params` represents a canonical saved-plan request (`persist_l2=True`),
    or False if `params` contains temporary exploratory slider overrides (`persist_l2=False`).
    """
    if not params:
        return True
    for k, v in params.items():
        if v in (None, "", "null", "undefined", "inherit"):
            continue
        k_str = str(k)
        if k_str in SLIDER_OVERRIDE_KEYS or k_str.startswith("growth_"):
            return False
        if k_str not in CANONICAL_SIMULATION_KEYS:
            return False
    return True


def is_canonical_monte_carlo_params(
    params: Optional[Dict[str, Any]] = None,
    *,
    spending: Any = None,
    retirement_age: Any = None,
    trials: int = 1000,
) -> bool:
    """Returns True if Monte Carlo parameters are canonical (no temporary overrides and 1,000 trials)."""
    sp = params.get("spending", spending) if isinstance(params, dict) else spending
    ra = params.get("retirement_age", retirement_age) if isinstance(params, dict) else retirement_age
    tr = params.get("trials", trials) if isinstance(params, dict) else trials
    if sp not in (None, "", "null", "undefined") or ra not in (None, "", "null", "undefined"):
        return False
    try:
        return int(tr if tr is not None else 1000) == 1000
    except (ValueError, TypeError):
        return False


CACHE = TwoTierCache(
    max_l1_entries=256,
    max_l1_bytes=32 * 1024 * 1024,
    max_l2_bytes=256 * 1024 * 1024,
    max_l2_per_tenant_ns=12,
    cache_db_path_fn=_resolve_cache_db_path,
    db_path_fn=_resolve_state_db_path,
)


def get_domain_versions(
    family_id: int = 0, *, sync_db: bool = False, _ignore_live_state_bump: bool = False, state_db: Optional[Path] = None
) -> Dict[str, int]:
    if not family_id or int(family_id) <= 0:
        return _default_domain_map(1)
    fid = int(family_id)
    resolved_db = Path(state_db) if state_db is not None else _resolve_state_db_path(family_id=fid)
    cache_db = _resolve_cache_db_path(family_id=fid)
    scope = _resolve_db_key(resolved_db)
    scope_key = CACHE._scope_key(cache_db_path=cache_db, db_path=resolved_db)
    live_ver = (
        CACHE._tenant_versions.get((scope_key, fid), 1)
        if _ignore_live_state_bump
        else CACHE.get_version(fid, db_path=resolved_db, cache_db_path=cache_db)
    )
    with _DOMAIN_LOCK:
        mem = _DOMAIN_VERSIONS_MEM.get((scope, fid))
        vers = dict(mem[1]) if mem is not None else _default_domain_map(1)
        db_state_v = mem[0] if mem is not None else 1
        loaded = load_domain_versions_row(resolved_db, fid)
        if loaded is not None:
            db_state_v, parsed = loaded
            for d in CANONICAL_DOMAINS:
                vers[d] = max(int(vers.get(d, 1)), int(parsed.get(d, 1)))
        eff_state_v = db_state_v if _ignore_live_state_bump else max(live_ver, db_state_v)
        if not _ignore_live_state_bump and live_ver > db_state_v:
            for d in CANONICAL_DOMAINS:
                vers[d] = max(int(vers.get(d, 1)), live_ver)
        _DOMAIN_VERSIONS_MEM[(scope, fid)] = (eff_state_v, dict(vers))
        return dict(vers)


def resolve_bump_targets(family_id: int, domains: Optional[Iterable[str]]) -> List[str]:
    """
    The domains one mutation bumps. Named domains are recorded for the request; a mutation with no named domains
    still changed something, so it bumps the union of what this request has already recorded, or every domain when
    nothing was recorded (unknown scope).
    """
    target_domains = [str(d) for d in (domains or ()) if str(d) in CANONICAL_DOMAINS]
    if target_domains:
        record_request_domains(family_id, target_domains)
        return target_domains
    return sorted(get_request_domains(family_id) or CANONICAL_DOMAINS)


def persists_to_state_db(family_id: int, db_path: Optional[Path]) -> bool:
    """True when `db_path` is the database that holds this family's domain versions."""
    if db_path is None:
        return False
    return _resolve_db_key(Path(db_path)) == _resolve_db_key(_resolve_state_db_path(family_id=int(family_id)))


def bump_domain_versions(
    family_id: int = 0,
    domains: Optional[Iterable[str]] = None,
    *,
    state_version: Optional[int] = None,
    state_db: Optional[Path] = None,
    already_persisted: bool = False,
) -> Dict[str, int]:
    """
    Bumps `domains` (see `resolve_bump_targets`) in the database and the in-process map. `already_persisted` means
    the committed write carried the increment in its own transaction (`db.session`): the rows are read back, not
    incremented a second time.
    """
    if not family_id or int(family_id) <= 0:
        return _default_domain_map(1)
    fid = int(family_id)
    resolved_db = Path(state_db) if state_db is not None else _resolve_state_db_path(family_id=fid)
    scope = _resolve_db_key(resolved_db)
    # The committed write already resolved (and recorded) its targets; resolving again would record a fallback
    # "every domain" set as if the request had named them.
    target_domains = (
        [str(d) for d in (domains or ()) if str(d) in CANONICAL_DOMAINS]
        if already_persisted
        else resolve_bump_targets(fid, domains)
    )

    with _DOMAIN_LOCK:
        mem_before = get_domain_versions(fid, _ignore_live_state_bump=True, state_db=resolved_db)
        if already_persisted:
            if state_version is not None:
                raise_state_version(resolved_db, fid, state_version)
            loaded = load_domain_versions_row(resolved_db, fid)
            persisted = dict(loaded[1]) if loaded is not None else dict(mem_before)
        elif resolved_db.parent.exists():
            persisted = bump_domain_rows(resolved_db, fid, target_domains, state_version=state_version)
        else:
            persisted = dict(mem_before)
            for d in target_domains:
                persisted[d] = int(persisted.get(d, 1)) + 1
        merged = {d: max(int(persisted.get(d, 1)), int(mem_before.get(d, 1))) for d in CANONICAL_DOMAINS}
        if not already_persisted:
            for d in target_domains:
                merged[d] = max(merged[d], int(mem_before.get(d, 1)) + 1)
        mem_v = _DOMAIN_VERSIONS_MEM.get((scope, fid), (1, merged))[0]
        eff_state_v = max(int(state_version), mem_v) if state_version is not None else mem_v
        _DOMAIN_VERSIONS_MEM[(scope, fid)] = (eff_state_v, dict(merged))
        return dict(merged)


def clear_domain_versions(state_db: Optional[Path] = None) -> None:
    with _DOMAIN_LOCK:
        _DOMAIN_VERSIONS_MEM.clear()
        target_db = state_db or _resolve_state_db_path()
        if target_db is not None:
            delete_all_domain_versions(target_db)


def get_state_version(family_id: int = 0) -> int:
    """
    Returns the current state version integer for a family.
    Persisted in SQLite `family_state_versions` for multi-worker consistency across Gunicorn processes.
    """
    if not family_id or int(family_id) <= 0:
        return 1
    fid = int(family_id)
    state_db = _resolve_state_db_path(family_id=fid)
    cache_db = _resolve_cache_db_path(family_id=fid)
    return CACHE.get_version(fid, db_path=state_db, cache_db_path=cache_db)


def make_cache_key(family_id: int = 0, universe: str = "public", params: Optional[Dict[str, Any]] = None) -> str:
    """
    Generates a deterministic cache key binding family_id, database universe, state version,
    CACHE_SCHEMA_VERSION, the projection start year, and a SHA-256 digest of sorted simulation parameters.
    """
    if params is None:
        params = {}
    version = get_state_version(family_id)
    payload = {"_schema": CACHE_SCHEMA_VERSION, "_as_of_year": date.today().year, **params}
    raw_params = json.dumps(payload, sort_keys=True, default=str)
    param_hash = hashlib.sha256(raw_params.encode("utf-8")).hexdigest()[:16]
    return f"{family_id}:{universe}:v{version}:{param_hash}"


def invalidate_family_cache(
    family_id: int = 0,
    domains: Optional[Iterable[str]] = None,
    *,
    db_path: Optional[Path] = None,
    domains_persisted: bool = False,
) -> None:
    """
    Increments state version for a family in SQLite, bumps affected domain versions,
    and purges all L1 & L2 cached entries. `domains_persisted`: the committed write already carried the domain
    increments in its own transaction, so only the in-process map is brought up to date.
    """
    if not family_id or int(family_id) <= 0:
        return
    fid = int(family_id)
    state_db = _resolve_state_db_path(family_id=fid)
    cache_db = _resolve_cache_db_path(family_id=fid)
    # The domains this mutation changed, resolved once: the version bump and the entity store both act on them.
    targets = (
        [str(d) for d in (domains or ()) if str(d) in CANONICAL_DOMAINS]
        if domains_persisted
        else resolve_bump_targets(fid, domains)
    )
    new_v = CACHE.bump_version(fid, db_path=state_db, cache_db_path=cache_db)
    bump_domain_versions(fid, domains=targets, state_version=new_v, already_persisted=domains_persisted)
    if db_path is not None:
        p = Path(db_path)
        if _resolve_db_key(p) != _resolve_db_key(state_db):
            bump_domain_versions(fid, domains=targets, state_version=new_v, state_db=p)
    try:
        import db
        # Entities outside the changed domains (accounts after a plan edit, say) stay cached.
        db.store.invalidate_family(fid, domains=targets or None)
    except Exception:
        pass


def update_active_scenario(family_id: int = 0, active_id: str = "") -> None:
    """
    Updates the active scenario ID in all cached simulations for the given family
    in place (both L1 and L2), without purging simulation math or incrementing the state version.
    """
    if not family_id or int(family_id) <= 0 or not active_id:
        return
    fid = int(family_id)
    state_db = _resolve_state_db_path(family_id=fid)
    cache_db = _resolve_cache_db_path(family_id=fid)
    bump_domain_versions(fid, domains=("scenarios",))

    def _mutate(sim: Any) -> None:
        if not isinstance(sim, dict):
            return
        sim["active_scenario_id"] = active_id
        for s in sim.get("scenarios", []):
            if isinstance(s, dict):
                s["is_active"] = (s.get("id") == active_id)

        active_readiness = None
        for sc in sim.get("scorecard", []):
            if isinstance(sc, dict):
                is_act = (sc.get("id") == active_id)
                sc["is_active"] = is_act
                if is_act:
                    active_readiness = sc.get("retirement_readiness")

        if active_readiness is not None:
            sim["active_retirement_readiness"] = active_readiness

        schedules = sim.get("scenario_schedules", {})
        if active_id in schedules:
            sim["active_schedule"] = schedules[active_id]

        cash_flows = sim.get("scenario_cash_flows", {})
        if active_id in cash_flows:
            sim["active_cash_flow_series"] = cash_flows[active_id]

        longevity = sim.get("scenario_longevity_breakdowns", {})
        if active_id in longevity:
            sim["active_longevity_breakdown"] = longevity[active_id]

    CACHE.mutate_tenant_namespace(
        fid,
        "simulation",
        _mutate,
        encrypt_fn=_make_encrypt_fn(fid, state_db),
        decrypt_fn=_make_decrypt_fn(fid, state_db),
        cache_db_path=cache_db,
    )


def _get_namespaced(namespace: str, key: str, *, check_l2: bool = True) -> Optional[Dict[str, Any]]:
    fid, universe, key_ver = _parse_cache_key(key)
    if fid <= 0:
        return None
    cache_db = _resolve_cache_db_path(universe, family_id=fid)
    state_db = _resolve_state_db_path(universe, family_id=fid)
    eff_ver = key_ver if key_ver is not None else get_state_version(fid)

    l1_hit = CACHE.get(
        namespace,
        key,
        tenant_id=fid,
        state_version=eff_ver,
        check_l2=False,
        cache_db_path=cache_db,
    )
    if l1_hit is not None:
        return l1_hit

    if not check_l2:
        return None

    live_ver = CACHE.get_version(fid, db_path=state_db, cache_db_path=cache_db)
    if key_ver is not None and key_ver != live_ver:
        return None

    return CACHE.get(
        namespace,
        key,
        tenant_id=fid,
        state_version=live_ver,
        check_l2=True,
        decrypt_fn=_make_decrypt_fn(fid, state_db),
        cache_db_path=cache_db,
    )


def _set_namespaced(
    namespace: str,
    key: str,
    data: Dict[str, Any],
    *,
    persist_l2: Optional[bool] = None,
) -> None:
    if not data or not isinstance(data, dict):
        return
    fid, universe, key_ver = _parse_cache_key(key)
    if fid <= 0:
        return
    cache_db = _resolve_cache_db_path(universe, family_id=fid)
    state_db = _resolve_state_db_path(universe, family_id=fid)
    eff_ver = key_ver if key_ver is not None else get_state_version(fid)
    do_persist = True if persist_l2 is None else bool(persist_l2)

    CACHE.set(
        namespace,
        key,
        data,
        tenant_id=fid,
        state_version=eff_ver,
        persist_l2=do_persist,
        encrypt_fn=_make_encrypt_fn(fid, state_db),
        cache_db_path=cache_db,
    )


def get_simulation(key: str, *, check_l2: bool = True) -> Optional[Dict[str, Any]]:
    """Retrieves a cached multi-scenario simulation output from L1 RAM or L2 SQLite, or None if miss."""
    return _get_namespaced("simulation", key, check_l2=check_l2)


def set_simulation(key: str, data: Dict[str, Any], *, persist_l2: Optional[bool] = None) -> None:
    """Caches a multi-scenario simulation output in L1 RAM and (when canonical) L2 encrypted SQLite."""
    _set_namespaced("simulation", key, data, persist_l2=persist_l2)


def get_monte_carlo(key: str, *, check_l2: bool = True) -> Optional[Dict[str, Any]]:
    """Retrieves a cached Monte Carlo simulation output from L1 RAM or L2 SQLite, or None if miss."""
    return _get_namespaced("monte_carlo", key, check_l2=check_l2)


def set_monte_carlo(key: str, data: Dict[str, Any], *, persist_l2: Optional[bool] = None) -> None:
    """Caches a Monte Carlo simulation output in L1 RAM and (when canonical) L2 encrypted SQLite."""
    _set_namespaced("monte_carlo", key, data, persist_l2=persist_l2)


def get_cached_estate(family_id: int = 0, params: Optional[Dict[str, Any]] = None, *, universe: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a cached family estate profile from L1 RAM or L2 encrypted SQLite."""
    if not family_id or int(family_id) <= 0:
        return None
    uni = universe or _resolve_active_universe()
    res = _get_namespaced("estate", make_cache_key(int(family_id), uni, dict(params) if isinstance(params, dict) else {"profile": "estate"}), check_l2=True)
    return copy.deepcopy(res) if res is not None else None


def set_cached_estate(family_id: int, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None, *, universe: Optional[str] = None, persist_l2: bool = True) -> None:
    """Stores a family estate profile in L1 RAM and L2 encrypted SQLite."""
    if not family_id or int(family_id) <= 0 or not isinstance(data, dict):
        return
    uni = universe or _resolve_active_universe()
    _set_namespaced("estate", make_cache_key(int(family_id), uni, dict(params) if isinstance(params, dict) else {"profile": "estate"}), copy.deepcopy(data), persist_l2=persist_l2)


def get_cached_dashboard_payload(family_id: int = 0) -> Optional[Dict[str, Any]]:
    """Retrieves cached dashboard balance sheet and valuation payload for family_id."""
    if not family_id or int(family_id) <= 0:
        return None
    res = _get_namespaced("dashboard_api", make_cache_key(int(family_id), _resolve_active_universe(), {"endpoint": "dashboard_api"}), check_l2=False)
    return copy.deepcopy(res) if res is not None else None


def set_cached_dashboard_payload(family_id: int, data: Dict[str, Any]) -> None:
    """Caches dashboard balance sheet and valuation payload in L1 memory."""
    if not family_id or int(family_id) <= 0 or not isinstance(data, dict):
        return
    _set_namespaced("dashboard_api", make_cache_key(int(family_id), _resolve_active_universe(), {"endpoint": "dashboard_api"}), copy.deepcopy(data), persist_l2=False)


_FRAGMENT_L1_CACHE: cachetools.LRUCache = cachetools.LRUCache(maxsize=256)


def _compute_fragment_domain_ver_token(family_id: int, fragment_name: str) -> str:
    """Computes a domain-scoped version token for a fragment based on FRAGMENT_ETAG_DOMAINS."""
    try:
        from ssr.dashboard import FRAGMENT_ETAG_DOMAINS
        domains = FRAGMENT_ETAG_DOMAINS.get(fragment_name)
    except Exception:
        domains = None
    if domains and family_id > 0:
        d_vers = get_domain_versions(family_id)
        return ",".join(f"{d}:{d_vers.get(d, 1)}" for d in domains)
    ver = get_state_version(family_id) if family_id > 0 else 0
    return f"v{ver}"


def _make_fragment_l1_key(family_id: int, universe: str, fragment_name: str, query_args: Optional[Any] = None) -> tuple:
    frag = str(fragment_name).strip().lower()
    query_tuple = ()
    if query_args:
        try:
            query_tuple = tuple(sorted((str(k), str(v)) for k, v in query_args.items() if v not in (None, "")))
        except Exception:
            pass
    return (int(family_id), universe, frag, query_tuple)


def get_cached_fragment(family_id: int, fragment_name: str, query_args: Optional[Any] = None, *, domain_ver_token: Optional[str] = None) -> Optional[str]:
    """Retrieves cached HTML fragment for family_id and query params from domain-scoped L1 memory."""
    if not family_id or int(family_id) <= 0 or not fragment_name:
        return None
    uni = _resolve_active_universe()
    key = _make_fragment_l1_key(family_id, uni, fragment_name, query_args)
    cached = _FRAGMENT_L1_CACHE.get(key)
    if cached is None:
        return None
    cached_token, html = cached
    cur_token = domain_ver_token if domain_ver_token is not None else _compute_fragment_domain_ver_token(family_id, fragment_name)
    if cached_token == cur_token:
        return html
    _FRAGMENT_L1_CACHE.pop(key, None)
    return None


def set_cached_fragment(family_id: int, fragment_name: str, html: str, query_args: Optional[Any] = None, *, domain_ver_token: Optional[str] = None) -> None:
    """Caches rendered HTML fragment in domain-scoped L1 memory."""
    if not family_id or int(family_id) <= 0 or not fragment_name or not html:
        return
    uni = _resolve_active_universe()
    key = _make_fragment_l1_key(family_id, uni, fragment_name, query_args)
    cur_token = domain_ver_token if domain_ver_token is not None else _compute_fragment_domain_ver_token(family_id, fragment_name)
    _FRAGMENT_L1_CACHE[key] = (cur_token, html)


def clear_l1_only() -> None:
    """Clears only in-memory L1 LRUCaches while preserving L2 SQLite entries."""
    CACHE.clear_l1()
    _FRAGMENT_L1_CACHE.clear()


def clear_all_caches() -> None:
    """Empties all L1 and L2 simulation, Monte Carlo, snapshot, estate, fragment, and domain store caches."""
    state_db, cache_db = _resolve_state_db_path(), _resolve_cache_db_path()
    CACHE.clear(db_path=state_db, cache_db_path=cache_db)
    _FRAGMENT_L1_CACHE.clear()
    clear_domain_versions(state_db)
    from forecast import snapshot_cache
    snapshot_cache.clear()
    for uni in ("beta", "test"):
        try:
            u_state, u_cache = _resolve_state_db_path(uni), _resolve_cache_db_path(uni)
            if u_cache.exists():
                CACHE.clear(db_path=u_state, cache_db_path=u_cache)
            fam_dir = u_state.parent / "families"
            if fam_dir.is_dir():
                for f_db in fam_dir.glob("*.db"):
                    if f_db.name.endswith("_cache.db"):
                        CACHE.clear(cache_db_path=f_db)
                    else:
                        CACHE.clear(db_path=f_db)
                        clear_domain_versions(f_db)
        except Exception:
            pass
    try:
        import db
        db.store.clear()
    except Exception:
        pass
