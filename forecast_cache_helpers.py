"""
forecast_cache_helpers.py: Helper utilities, parameter checkers, and path resolvers for forecast_cache.
Handles database path resolution, Fernet encryption lambdas, and canonical parameter detection.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, Iterable, Optional, Set, Tuple
import threading
from hvl_common.db.sqlite import _resolve_db_key
from db.domain_versions import (
    delete_all_domain_versions,
    load_domain_versions_row,
    save_domain_versions_row,
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


def get_domain_versions(
    family_id: int = 0, *, sync_db: bool = False, _ignore_live_state_bump: bool = False, state_db: Optional[Path] = None
) -> Dict[str, int]:
    if not family_id or int(family_id) <= 0:
        return _default_domain_map(1)
    fid = int(family_id)
    resolved_db = Path(state_db) if state_db is not None else _resolve_state_db_path()
    scope = _resolve_db_key(resolved_db)
    import forecast_cache
    scope_key = forecast_cache.CACHE._scope_key(db_path=resolved_db)
    has_mem_ver = (scope_key, fid) in forecast_cache.CACHE._tenant_versions
    live_ver = (
        forecast_cache.CACHE.get_version(fid, db_path=resolved_db, cache_db_path=_resolve_cache_db_path())
        if (sync_db or not has_mem_ver)
        else forecast_cache.CACHE._tenant_versions.get((scope_key, fid), 1)
    )
    with _DOMAIN_LOCK:
        mem = _DOMAIN_VERSIONS_MEM.get((scope, fid))
        if mem is not None and not sync_db and (_ignore_live_state_bump or mem[0] >= live_ver):
            return dict(mem[1])
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
                if vers.get(d, 1) < live_ver:
                    vers[d] = live_ver
        _DOMAIN_VERSIONS_MEM[(scope, fid)] = (eff_state_v, dict(vers))
        return dict(vers)


def bump_domain_versions(
    family_id: int = 0,
    domains: Optional[Iterable[str]] = None,
    *,
    state_version: Optional[int] = None,
    state_db: Optional[Path] = None,
) -> Dict[str, int]:
    if not family_id or int(family_id) <= 0:
        return _default_domain_map(1)
    fid = int(family_id)
    resolved_db = Path(state_db) if state_db is not None else _resolve_state_db_path()
    scope = _resolve_db_key(resolved_db)
    target_domains = [str(d) for d in (domains or ()) if str(d) in CANONICAL_DOMAINS]
    if target_domains:
        record_request_domains(fid, target_domains)
    elif get_request_domains(fid):
        with _DOMAIN_LOCK:
            cur_map = get_domain_versions(fid, _ignore_live_state_bump=True, state_db=resolved_db)
            if state_version is not None:
                _DOMAIN_VERSIONS_MEM[(scope, fid)] = (int(state_version), dict(cur_map))
                save_domain_versions_row(resolved_db, fid, int(state_version), cur_map)
            return dict(cur_map)
    else:
        target_domains = list(CANONICAL_DOMAINS)

    with _DOMAIN_LOCK:
        cur_map = get_domain_versions(fid, _ignore_live_state_bump=True, state_db=resolved_db)
        mem_v = _DOMAIN_VERSIONS_MEM.get((scope, fid), (1, cur_map))[0]
        eff_state_v = int(state_version) if state_version is not None else mem_v
        for d in target_domains:
            cur_map[d] = int(cur_map.get(d, 1)) + 1
        _DOMAIN_VERSIONS_MEM[(scope, fid)] = (eff_state_v, dict(cur_map))
        save_domain_versions_row(resolved_db, fid, eff_state_v, cur_map)
        return dict(cur_map)


def clear_domain_versions(state_db: Optional[Path] = None) -> None:
    with _DOMAIN_LOCK:
        _DOMAIN_VERSIONS_MEM.clear()
        target_db = state_db or _resolve_state_db_path()
        if target_db is not None:
            delete_all_domain_versions(target_db)


CANONICAL_SIMULATION_KEYS = frozenset({
    "scenario_id", "target_scenario_id", "view_mode", "equity_growth_preset",
})

SLIDER_OVERRIDE_KEYS = frozenset({
    "annual_living_spend", "annual_savings", "primary_retirement_age", "retirement_age",
    "spouse_retirement_age", "inflation_rate", "ss_claim_age", "primary_ss_claim_age",
    "spouse_ss_claim_age", "custom_equity_growth_rate", "equity_growth_presets",
})


def _has_custom_db_override() -> Optional[Path]:
    try:
        fe = sys.modules.get("forecast_engine")
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


def _resolve_state_db_path(universe: Optional[str] = None) -> Path:
    override = _has_custom_db_override()
    if override is not None:
        return override
    u = (universe or "").strip().lower()
    if u and not (os.getenv("APP_UNIVERSE", "").strip().lower() == "test" and u in ("public", "test")):
        from config import get_db_path_for_universe
        return get_db_path_for_universe(u)
    try:
        from forecast.storage import get_db_path
        return Path(get_db_path())
    except Exception:
        from config import get_db_path_for_universe
        return get_db_path_for_universe()


def _resolve_cache_db_path(universe: Optional[str] = None) -> Path:
    override = _has_custom_db_override()
    if override is not None:
        return override.parent / f"{override.stem}_cache.db"
    u = (universe or "").strip().lower()
    if u and not (os.getenv("APP_UNIVERSE", "").strip().lower() == "test" and u in ("public", "test")):
        from config import get_cache_db_path_for_universe
        return get_cache_db_path_for_universe(u)
    try:
        from routes.helpers import get_current_cache_db_path
        return get_current_cache_db_path()
    except Exception:
        from config import get_cache_db_path_for_universe
        return get_cache_db_path_for_universe()


def _resolve_active_universe() -> str:
    try:
        from routes.helpers import get_current_universe
        return get_current_universe()
    except Exception:
        from config import APP_UNIVERSE
        return APP_UNIVERSE


def _make_encrypt_fn(family_id: int, state_db: Optional[Path] = None) -> Callable[[bytes], bytes]:
    def _encrypt(raw: bytes) -> bytes:
        db_p = state_db or _resolve_state_db_path()
        key = security.get_family_key(db_p, int(family_id))
        return security._get_fernet(key).encrypt(raw)
    return _encrypt


def _make_decrypt_fn(family_id: int, state_db: Optional[Path] = None) -> Callable[[bytes], bytes]:
    def _decrypt(cipher: bytes) -> bytes:
        db_p = state_db or _resolve_state_db_path()
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


CACHE_SCHEMA_VERSION = "v5"


def make_cache_key(family_id: int = 0, universe: str = "public", params: Optional[Dict[str, Any]] = None) -> str:
    """
    Generates a deterministic cache key binding family_id, database universe, state version,
    CACHE_SCHEMA_VERSION, and a SHA-256 digest of sorted simulation parameters.
    """
    if params is None:
        params = {}
    import forecast_cache
    version = forecast_cache.get_state_version(family_id)
    payload = {"_schema": CACHE_SCHEMA_VERSION, **params}
    raw_params = json.dumps(payload, sort_keys=True, default=str)
    param_hash = hashlib.sha256(raw_params.encode("utf-8")).hexdigest()[:16]
    return f"{family_id}:{universe}:v{version}:{param_hash}"
