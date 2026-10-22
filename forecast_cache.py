"""
forecast_cache.py: Two-Tier Encrypted Cache (L1 In-Memory LRU + L2 SQLite `computed_cache`)
for Scenarios, Monte Carlo Simulations, Financial Snapshots, and Estate Profiles.
Delegates lifecycle and stampede protection to `hvl_common.db.TwoTierCache`.
"""

from __future__ import annotations
import copy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import cachetools
from hvl_common.db import TwoTierCache
from hvl_common.db.sqlite import _resolve_db_key
from forecast_cache_helpers import (
    CANONICAL_DOMAINS,
    CANONICAL_SIMULATION_KEYS,
    SLIDER_OVERRIDE_KEYS,
    _has_custom_db_override,
    _resolve_state_db_path,
    _resolve_cache_db_path,
    _resolve_active_universe,
    _make_encrypt_fn,
    _make_decrypt_fn,
    _parse_cache_key,
    bump_domain_versions,
    clear_domain_versions,
    get_domain_versions,
    make_cache_key,
    is_canonical_simulation_params,
    is_canonical_monte_carlo_params,
)

CACHE = TwoTierCache(
    max_l1_entries=256,
    max_l1_bytes=32 * 1024 * 1024,
    max_l2_bytes=256 * 1024 * 1024,
    max_l2_per_tenant_ns=12,
    cache_db_path_fn=_resolve_cache_db_path,
    db_path_fn=_resolve_state_db_path,
)


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


def invalidate_family_cache(
    family_id: int = 0, domains: Optional[Iterable[str]] = None, *, db_path: Optional[Path] = None
) -> None:
    """
    Increments state version for a family in SQLite, bumps affected domain versions,
    and purges all L1 & L2 cached entries.
    """
    if not family_id or int(family_id) <= 0:
        return
    fid = int(family_id)
    state_db = _resolve_state_db_path(family_id=fid)
    cache_db = _resolve_cache_db_path(family_id=fid)
    new_v = CACHE.bump_version(fid, db_path=state_db, cache_db_path=cache_db)
    bump_domain_versions(fid, domains=domains, state_version=new_v)
    if db_path is not None:
        p = Path(db_path)
        if _resolve_db_key(p) != _resolve_db_key(state_db):
            bump_domain_versions(fid, domains=domains, state_version=new_v, state_db=p)
    try:
        import db
        db.store.invalidate_family(fid)
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


def get_cached_snapshot(
    family_id: int = 0,
    params: Optional[Dict[str, Any]] = None,
    *,
    universe: Optional[str] = None,
    share_price: Optional[float] = None,
    include_wa_tax: bool = False,
    prior_w2_income: float = 500000.0,
    company_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a cached financial snapshot for `family_id`, or None if miss."""
    if not family_id or int(family_id) <= 0:
        return None
    uni = universe or _resolve_active_universe()
    if isinstance(params, dict):
        eff_params = dict(params)
    else:
        eff_params = {
            "share_price": round(float(share_price), 4) if share_price is not None else None,
            "include_wa_tax": bool(include_wa_tax),
            "prior_w2_income": round(float(prior_w2_income), 2),
            "company_id": int(company_id) if company_id is not None else None,
        }
    key = make_cache_key(int(family_id), uni, eff_params)
    res = _get_namespaced("snapshot", key, check_l2=True)
    return copy.deepcopy(res) if res is not None else None


def set_cached_snapshot(
    family_id: int,
    data: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    *,
    universe: Optional[str] = None,
    share_price: Optional[float] = None,
    include_wa_tax: bool = False,
    prior_w2_income: float = 500000.0,
    company_id: Optional[int] = None,
    persist_l2: bool = True,
) -> None:
    """Stores a financial snapshot in L1 RAM and optionally L2 encrypted SQLite."""
    if not family_id or int(family_id) <= 0 or not isinstance(data, dict):
        return
    uni = universe or _resolve_active_universe()
    eff_params = dict(params) if isinstance(params, dict) else {
        "share_price": round(float(share_price), 4) if share_price is not None else None,
        "include_wa_tax": bool(include_wa_tax), "prior_w2_income": round(float(prior_w2_income), 2),
        "company_id": int(company_id) if company_id is not None else None,
    }
    _set_namespaced("snapshot", make_cache_key(int(family_id), uni, eff_params), copy.deepcopy(data), persist_l2=persist_l2)


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
