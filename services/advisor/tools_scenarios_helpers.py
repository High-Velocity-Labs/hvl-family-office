"""
Shared Scenario Resolution, Cloning, Equity Growth Override, and Schedule Extraction
Helpers for AI Financial Advisor Scenario Tools.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional, Tuple

import forecast_engine
from routes.helpers import sanitize_text
from services.scenario_clone_service import pick_unused_scenario_color
from ssr.scenarios import build_ssr_scenarios

_BENCHMARK_YEARS = (2026, 2027, 2028, 2030, 2032, 2036)

_INHERITABLE_SCENARIO_KEYS = (
    "primary_retirement_age", "spouse_retirement_age", "annual_living_spend", "annual_savings",
    "inflation_rate", "spending_guardrail_mode", "equity_growth_preset", "equity_growth_presets",
    "custom_equity_growth_rate", "ss_claim_age", "primary_ss_claim_age", "spouse_ss_claim_age",
    "growth_us_equity", "growth_intl_equity", "growth_bonds", "growth_cash",
    "growth_private_investments", "growth_real_estate",
)

_STATE_CODES = {
    "nevada": "NV", "texas": "TX", "florida": "FL", "wyoming": "WY", "washington": "WA",
    "california": "CA", "new hampshire": "NH", "tennessee": "TN", "south dakota": "SD",
    "alaska": "AK", "new york": "NY", "oregon": "OR",
}


def _resolve_state_code(raw_val: Optional[str], hint_text: str, default: str) -> str:
    """Resolves a 2-letter US state code from an explicit parameter or event title/description hint."""
    s = str(raw_val or "").strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    lower_hint = hint_text.lower()
    return (
        _STATE_CODES.get(s.lower())
        or next((code for name, code in _STATE_CODES.items() if name in lower_hint), default)
    )


def _exclude_conflicting_events(target_scen: Dict[str, Any], conflicting_ids: set) -> None:
    """Removes conflicting event IDs from target_scen and records them in excluded_event_ids when inherited."""
    if not conflicting_ids:
        return
    target_scen["event_ids"] = [
        eid for eid in target_scen.get("event_ids", []) if eid not in conflicting_ids
    ]
    if isinstance(target_scen.get("added_event_ids"), list):
        target_scen["added_event_ids"] = [
            eid for eid in target_scen["added_event_ids"] if eid not in conflicting_ids
        ]
    if target_scen.get("parent_id"):
        exc = target_scen.setdefault("excluded_event_ids", [])
        exc.extend(cid for cid in conflicting_ids if cid and cid not in exc)


def normalize_equity_action(raw_action: Optional[str]) -> str:
    """Normalizes company equity event action identifiers into canonical strategy keys."""
    act = str(raw_action or "").strip().lower()
    if act in ("exercise_and_hold_cash", "hold_cash_cover", "exercise_hold_cash", "hold_cash"):
        return "exercise_and_hold_cash"
    if act in ("exercise_and_hold_sell_to_cover", "hold_sell_to_cover", "sell_to_cover", "exercise_hold_sell_to_cover"):
        return "exercise_and_hold_sell_to_cover"
    if act in ("sell_held_shares", "sell_owned_shares", "liquidate_held_shares", "secondary_sale", "sell_shares"):
        return "sell_held_shares"
    return "cashless_repurchase"


def default_company_equity_event_name(equity_action: Optional[str], s_yr: int, e_yr: int) -> str:
    """Generates a descriptive default name for a company_equity event when event_name is omitted."""
    act = normalize_equity_action(equity_action)
    span = f"{s_yr}–{e_yr}" if e_yr > s_yr else str(s_yr)
    return {
        "exercise_and_hold_cash": f"Exercise & Hold (Cash Cover, {s_yr})",
        "exercise_and_hold_sell_to_cover": f"Exercise & Hold (Sell-to-Cover, {s_yr})",
        "sell_held_shares": f"Sell Held Shares ({span})",
    }.get(act, f"Exercise & Sell Options ({span})")


def normalize_custom_equity_growth_rate(rate: Optional[float]) -> Optional[float]:
    """Normalizes custom equity growth rate (converting percentages like 12.0 to 0.12)."""
    if rate is None:
        return None
    val = float(rate)
    return max(-0.50, min(1.0, round(val / 100.0 if abs(val) > 1.0 else val, 6)))


def apply_scenario_equity_growth_overrides(
    target_scen: Dict[str, Any],
    equity_growth_preset: Optional[str] = None,
    custom_equity_growth_rate: Optional[float] = None,
) -> None:
    """Applies company equity valuation growth preset and/or custom annual growth rate to a scenario."""
    overrides = target_scen.setdefault("overrides", {})
    norm_rate = normalize_custom_equity_growth_rate(custom_equity_growth_rate)
    clean_preset = sanitize_text(equity_growth_preset, 40).lower().strip() if equity_growth_preset else ""
    if clean_preset:
        target_scen["equity_growth_preset"] = clean_preset
        target_scen["equity_growth_presets"] = None
        overrides.pop("equity_growth_presets", None)
        if clean_preset == "custom":
            overrides.pop("equity_growth_preset", None)
        else:
            overrides["equity_growth_preset"] = clean_preset
        if norm_rate is None and clean_preset != "custom":
            target_scen["custom_equity_growth_rate"] = None
            target_scen.pop("equity_growth_rate", None)
            overrides.pop("custom_equity_growth_rate", None)
    if norm_rate is not None:
        target_scen["custom_equity_growth_rate"] = norm_rate
        target_scen["equity_growth_rate"] = norm_rate
        overrides["custom_equity_growth_rate"] = norm_rate
        target_scen["equity_growth_presets"] = None
        overrides.pop("equity_growth_presets", None)
        if not clean_preset:
            preset_by_rate = {0.14: "aggressive", 0.105: "baseline_curve", 0.08: "moderate", 0.05: "conservative", 0.0: "flat"}
            inferred = next((name for r, name in preset_by_rate.items() if abs(norm_rate - r) < 1e-6), "custom")
            target_scen["equity_growth_preset"] = inferred
            if inferred == "custom":
                overrides.pop("equity_growth_preset", None)
            else:
                overrides["equity_growth_preset"] = inferred


def resolve_or_clone_child_scenario(
    state: Dict[str, Any],
    scenarios: List[Dict[str, Any]],
    target_scen: Dict[str, Any],
    clean_child_name: str,
) -> Dict[str, Any]:
    """Finds an existing child scenario by name or clones a clean child scenario inheriting from target_scen."""
    existing_child = next(
        (s for s in scenarios if s.get("name", "").strip().lower() == clean_child_name.lower()),
        None,
    )
    if existing_child:
        state["active_scenario_id"] = existing_child["id"]
        return existing_child

    new_scen_id = f"scen_{uuid.uuid4().hex[:8]}"
    inherited_overrides = copy.deepcopy(target_scen.get("overrides") or {}) if target_scen.get("parent_id") else {}
    new_scen: Dict[str, Any] = {
        "id": new_scen_id,
        "name": clean_child_name,
        "parent_id": target_scen["id"],
        "is_baseline": False,
        "color": pick_unused_scenario_color(scenarios),
        "drawdown_order": target_scen.get("drawdown_order", "standard_waterfall"),
        "accelerate_lp_calls": bool(target_scen.get("accelerate_lp_calls", False)),
        "event_ids": list(target_scen.get("event_ids", [])),
        "overrides": inherited_overrides,
        **{k: inherited_overrides.get(k) if k in inherited_overrides else None for k in _INHERITABLE_SCENARIO_KEYS},
    }
    scenarios.append(new_scen)
    state["active_scenario_id"] = new_scen_id
    return new_scen


def reset_child_scenarios_to_baseline(state: Dict[str, Any], scenarios: List[Dict[str, Any]]) -> List[str]:
    """Removes all non-baseline scenarios and non-default equity events, restoring Baseline state."""
    deleted_names = [
        s.get("name", s.get("id", ""))
        for s in scenarios
        if not s.get("is_baseline") and s.get("id") not in ("baseline", "scen_baseline")
    ]
    kept = [s for s in scenarios if s.get("is_baseline") or s.get("id") in ("baseline", "scen_baseline")] or scenarios[:1]
    events_list = state.get("events", [])
    def_eq_ids = [
        e["id"]
        for e in events_list
        if e.get("id") == "evt_company_equity_exercise_custom" or str(e.get("id") or "").startswith("evt_equity_")
    ]
    non_def_eq = {
        e.get("id")
        for e in events_list
        if e.get("category") in ("company_equity", "equity") and e.get("id") not in def_eq_ids
    }
    for bs in kept:
        bs["event_ids"] = [
            eid
            for eid in (bs.get("event_ids") or [])
            if eid not in non_def_eq
            and eid not in def_eq_ids
            and eid != "evt_company_equity_exercise_custom"
            and not str(eid).startswith("evt_equity_")
        ]
        bs["overrides"] = {}
    state["scenarios"] = kept
    state["active_scenario_id"] = "scen_baseline"
    kept_eids = {eid for s in kept for eid in (s.get("event_ids") or [])}
    state["events"] = [
        e for e in events_list
        if e.get("id") in kept_eids
        or e.get("id") == "evt_company_equity_exercise_custom"
        or str(e.get("id") or "").startswith(("evt_k12_", "evt_college_", "evt_equity_"))
    ]
    return deleted_names


def extract_scenario_metrics(ssr: Dict[str, Any], sid: str) -> Dict[str, Any]:
    """Extracts net worth, solvency, and FI crossover metrics for a scenario from SSR output."""
    r = next((row for row in ssr.get("scorecard_rows", []) if row.get("id") == sid or row.get("scenario_id") == sid), None) or {}
    return {
        "nw_age_65": r.get("nw65_str") or ssr.get("nw_65") or ssr.get("val_nw65", "--"),
        "nw_age_85": r.get("nw85_str") or ssr.get("nw_85") or ssr.get("val_nw85", "--"),
        "nw_age_95": r.get("nw95_str") or ssr.get("nw_95") or ssr.get("val_nw95", "--"),
        "solvency": r.get("solv_text") or ssr.get("solv_rate_display") or ssr.get("plan_solv_text", "--"),
        "fi_crossover_year": ssr.get("fi_crossover_year", "--"),
    }


def build_key_years_schedule(
    raw_sim: Optional[Dict[str, Any]],
    scen_id: Optional[str],
    extra_years: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Extracts benchmark years (2026, 2027, 2028, 2030, 2032, 2036) plus event-window years for a scenario."""
    if not raw_sim or not isinstance(raw_sim, dict):
        return []
    sched = ((raw_sim.get("scenario_schedules") or {}).get(scen_id) if scen_id else None) or raw_sim.get("active_schedule") or []
    cfs = ((raw_sim.get("scenario_cash_flows") or {}).get(scen_id) if scen_id else None) or raw_sim.get("active_cash_flow_series") or []
    s_map = {int(r["year"]): r for r in sched if r.get("year") is not None}
    c_map = {int(r["year"]): r for r in cfs if r.get("year") is not None}
    target_years = sorted(set(_BENCHMARK_YEARS) | set(extra_years or []))
    return [
        {
            "year": y,
            "events_inflow": c_map.get(y, {}).get("event_inflows", 0.0),
            "events_outflow": c_map.get(y, {}).get("events_outflow", 0.0),
            "gross_income": c_map.get(y, {}).get("gross_compensation", s_map.get(y, {}).get("yearly_inflow", s_map.get(y, {}).get("gross_income", 0.0))),
            "living_expenses": c_map.get(y, {}).get("living_core", s_map.get(y, {}).get("living_spending", s_map.get(y, {}).get("living_expenses", 0.0))),
            "net_cash_flow": s_map.get(y, {}).get("net_cash_flow", c_map.get(y, {}).get("net_cash_flow", 0.0)),
            "liquid_portfolio": s_map.get(y, {}).get("liquid_assets", s_map.get(y, {}).get("liquid_portfolio", 0.0)),
            "company_equity": s_map.get(y, {}).get("company_equity", 0.0),
            "events_occurred": s_map.get(y, {}).get("events_occurred", []),
            "net_worth": s_map.get(y, {}).get("total_net_worth", s_map.get(y, {}).get("net_worth", 0.0)),
        }
        for y in target_years
        if y in s_map or y in c_map
    ]


def persist_or_simulate_scenario_state(
    fam_id: int,
    state: Dict[str, Any],
    target_scen_id: str,
    is_read_only: bool,
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """Saves scenario state (or temporarily mocks state in read-only mode) and builds SSR output."""
    if not is_read_only:
        forecast_engine.save_scenario_state(state, family_id=fam_id)
        try:
            import forecast_cache

            forecast_cache.invalidate_family_cache(fam_id, domains=["scenarios"])
        except Exception:
            pass
        return ("saved", *build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen_id))
    orig_load = forecast_engine.load_scenario_state
    try:
        import forecast.orchestrator

        forecast_engine.load_scenario_state = lambda family_id=0: state
        forecast.orchestrator.load_scenario_state = lambda family_id=0: state
        ssr_after, raw_after = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen_id)
    finally:
        forecast_engine.load_scenario_state = orig_load
        forecast.orchestrator.load_scenario_state = orig_load
    return "simulated_only", ssr_after, raw_after
