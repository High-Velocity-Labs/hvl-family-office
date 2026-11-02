"""
Scenarios and Life Events callable tools for the AI Financial Advisor:
Multi-Scenario Lookup by Name, Full Per-Scenario Event Visibility,
and Scenario Life Event Management (add, update, enable, disable, delete).
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import config
from forecast import engine as forecast_engine
from services.request_context import can_mutate, is_sandbox_session, sanitize_text
from services.advisor.tools_core import _format_historical_backtest_summary, _resolve_tool_family_id
from services.scenario_clone_service import pick_unused_scenario_color
from ssr.plan_year import plan_start_year
from ssr.scenarios import build_ssr_scenarios
from services.advisor.tool_errors import ADVISOR_TOOL_ERRORS

logger = logging.getLogger(__name__)

# Benchmark rows are offsets from the plan's start year (2026, 2027, 2028, 2030, 2032, 2036 for a 2026 plan).
_BENCHMARK_YEAR_OFFSETS = (0, 1, 2, 4, 6, 10)


def _benchmark_years(start_year: int) -> Tuple[int, ...]:
    return tuple(start_year + off for off in _BENCHMARK_YEAR_OFFSETS)

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

_EVENT_CATEGORY_ICONS: Dict[str, str] = {
    "lifestyle": "evt-travel", "capital_outflow": "evt-capital-outflow", "capital_inflow": "evt-capital-inflow",
    "sabbatical": "evt-briefcase", "roth_conversion": "evt-roth-ladder", "real_estate": "evt-real-estate",
    "home_renovation": "evt-renovation", "college": "evt-college", "grad_school": "evt-grad-school",
    "education": "evt-k12", "eldercare": "evt-eldercare", "gifting": "evt-gifting",
    "philanthropy_daf": "evt-philanthropy", "state_relocation": "evt-relocation", "debt_payoff": "evt-debt",
    "refinance": "evt-refi", "superfund_529": "evt-529-superfund", "pe_capital_call": "evt-j-curve",
    "company_equity": "evt-equity",
}

_BASELINE_ALIASES = {"baseline", "baseline plan", "base", "base plan", "scen_baseline", "baseli"}


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
    """Extracts benchmark years (start year +0/1/2/4/6/10) plus event-window years for a scenario."""
    if not raw_sim or not isinstance(raw_sim, dict):
        return []
    sched = ((raw_sim.get("scenario_schedules") or {}).get(scen_id) if scen_id else None) or raw_sim.get("active_schedule") or []
    cfs = ((raw_sim.get("scenario_cash_flows") or {}).get(scen_id) if scen_id else None) or raw_sim.get("active_cash_flow_series") or []
    s_map = {int(r["year"]): r for r in sched if r.get("year") is not None}
    c_map = {int(r["year"]): r for r in cfs if r.get("year") is not None}
    target_years = sorted(set(_benchmark_years(plan_start_year(raw_sim))) | set(extra_years or []))
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
        from forecast import cache as forecast_cache

        forecast_cache.invalidate_family_cache(fam_id, domains=["scenarios"])
        return ("saved", *build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen_id))
    ssr_after, raw_after = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen_id, scenario_state=state)
    return "simulated_only", ssr_after, raw_after


def _resolve_scenario(
    scenarios: List[Dict[str, Any]], scenario_id: Optional[str] = None, scenario_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Resolves target scenario by baseline alias, exact id/name, or guarded substring match."""
    target = (scenario_name or scenario_id or "").strip()
    if not target:
        return None
    target_lower = target.lower()
    if target_lower in _BASELINE_ALIASES:
        return next((s for s in scenarios if s.get("is_baseline") or s.get("id") in ("baseline", "scen_baseline")), None)
    for s in scenarios:
        if s.get("id") == target or s.get("name", "").strip().lower() == target_lower:
            return s
    t_num_m = re.match(r"^(\d+)[\.\)\s:]", target_lower)
    t_num = t_num_m.group(1) if t_num_m else None
    for s in scenarios:
        if s.get("is_baseline") or s.get("id") in ("baseline", "scen_baseline"):
            continue
        s_name = s.get("name", "").strip().lower()
        if not s_name:
            continue
        s_num_m = re.match(r"^(\d+)[\.\)\s:]", s_name)
        s_num = s_num_m.group(1) if s_num_m else None
        if t_num is not None and s_num != t_num:
            continue
        if target_lower in s_name or s_name in target_lower:
            return s
    return None


def enrich_scenarios_and_events_payload(
    family_id: int = 0, scenario_id: Optional[str] = None, scenario_name: Optional[str] = None
) -> Dict[str, Any]:
    """Enriches scenario forecast data with full multi-scenario lookup by name, per-scenario events, and catalog."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        raw_state = forecast_engine.load_scenario_state(family_id=fam_id)
        scenarios_list, events_list = raw_state.get("scenarios", []), raw_state.get("events", [])
        target_scen = _resolve_scenario(scenarios_list, scenario_id=scenario_id, scenario_name=scenario_name)
        resolved_id = target_scen["id"] if target_scen else scenario_id

        ssr_scen, raw_sim = build_ssr_scenarios(family_id=fam_id, scenario_id=resolved_id)
        if not ssr_scen and not raw_sim:
            return {}

        sched = (raw_sim or {}).get("active_schedule") or []
        benchmark_years = _benchmark_years(plan_start_year(raw_sim or {}))
        milestone_years = [
            {
                "year": r.get("year"),
                "primary_age": r.get("age_primary", r.get("primary_age", r.get("age"))),
                "spouse_age": r.get("age_spouse", r.get("spouse_age")),
                "net_worth": r.get("total_net_worth", r.get("net_worth", 0.0)),
                "liquid_portfolio": r.get("liquid_assets", r.get("liquid_portfolio", 0.0)),
                "company_equity": r.get("company_equity", 0.0),
                "retirement_assets": r.get("retirement_assets", 0.0),
                "gross_income": r.get("yearly_inflow", r.get("gross_income", 0.0)),
                "living_expenses": r.get("living_spending", r.get("living_expenses", 0.0)),
                "taxes_paid": r.get("income_tax_haircut", r.get("total_tax", 0.0)),
                "net_cash_flow": r.get("net_cash_flow", 0.0),
                "events_occurred": r.get("events_occurred", []),
            }
            for idx, r in enumerate(sched)
            if idx in (0, len(sched) - 1)
            or int(r.get("year") or 0) in benchmark_years
            or int(r.get("age_primary") or r.get("primary_age") or r.get("age") or 0) in (50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100)
        ]

        hist_summary: Dict[str, Any] = {}
        active_mc = (raw_sim or {}).get("active_monte_carlo")
        if active_mc and (active_mc.get("historical_cohorts") or active_mc.get("historical_backtest")):
            hist_summary = _format_historical_backtest_summary(active_mc.get("historical_cohorts") or active_mc.get("historical_backtest"))
        if not hist_summary:
            mc_res = forecast_engine.run_monte_carlo_simulation(
                family_id=fam_id, trials=100, sandbox=is_sandbox_session()
            )
            if mc_res and (mc_res.get("historical_cohorts") or mc_res.get("historical_backtest")):
                hist_summary = _format_historical_backtest_summary(
                    mc_res.get("historical_cohorts") or mc_res.get("historical_backtest")
                )

        scorecard_map = {r.get("id"): r for r in (ssr_scen.get("scorecard_rows") or [])}
        selected_scen_id = ssr_scen.get("selected_scenario_id") or resolved_id
        scenarios_by_name: Dict[str, Dict[str, Any]] = {}
        for s in scenarios_list:
            s_id, s_name = s.get("id"), s.get("name", "Scenario")
            s_card = scorecard_map.get(s_id, {})
            sc_event_ids = set(s.get("event_ids", []))
            scenarios_by_name[s_name] = {
                "scenario_id": s_id, "name": s_name, "is_baseline": bool(s.get("is_baseline", False)),
                "parent_id": s.get("parent_id"), "is_selected": (s_id == selected_scen_id),
                "assumptions": {
                    "retirement_age": s.get("retirement_age") or s.get("primary_retirement_age"),
                    "spouse_retirement_age": s.get("spouse_retirement_age"),
                    "annual_living_spend": s.get("annual_living_spend"), "annual_savings": s.get("annual_savings"),
                    "drawdown_order": s.get("drawdown_order", "standard_waterfall"),
                    "spending_guardrail_mode": s.get("spending_guardrail_mode", "off"),
                    "accelerate_lp_calls": bool(s.get("accelerate_lp_calls", False)),
                    "equity_growth_preset": s.get("equity_growth_preset", raw_state.get("equity_growth_preset", "moderate")),
                    "custom_equity_growth_rate": s.get("custom_equity_growth_rate", s.get("equity_growth_rate")),
                },
                "metrics": {"nw_65": s_card.get("nw65_str", "--"), "nw_85": s_card.get("nw85_str", "--"),
                            "nw_95": s_card.get("nw95_str", "--"), "solvency": s_card.get("solv_text", "--")},
                "enabled_events": [dict(ev) for ev in events_list if ev.get("id") in sc_event_ids],
                "key_years_schedule": build_key_years_schedule(raw_sim, s_id),
            }

        all_household_events = [
            {**ev, "enabled_in_scenario_names": [s.get("name", "") for s in scenarios_list if ev.get("id") in s.get("event_ids", [])]}
            for ev in events_list
        ]

        return {
            "active_plan_name": ssr_scen.get("plan_name", "Baseline Plan"), "selected_scenario_id": selected_scen_id,
            "view_mode": ssr_scen.get("view_mode", "real"), "net_worth_age_65": ssr_scen.get("nw_65"),
            "net_worth_age_85": ssr_scen.get("nw_85"), "net_worth_age_95": ssr_scen.get("nw_95"),
            "solvency_status": ssr_scen.get("solv_rate_display"), "solvency_detail": ssr_scen.get("solv_sub"),
            "primary_retirement_target": ssr_scen.get("val_primary_ret"), "spouse_retirement_target": ssr_scen.get("val_spouse_ret"),
            "fi_achieved": ssr_scen.get("fi_achieved", False), "fi_crossover_year": ssr_scen.get("fi_crossover_year"),
            "fi_threshold": ssr_scen.get("fi_threshold"),
            "assumptions": {
                "annual_living_spend": ssr_scen.get("living_spend_str"), "annual_savings": ssr_scen.get("annual_savings_str"),
                "inflation_rate": ssr_scen.get("inflation_pct_str"), "primary_ss_claim_age": ssr_scen.get("primary_ss_claim_age"),
                "spouse_ss_claim_age": ssr_scen.get("spouse_ss_claim_age"), "blended_liquid_growth": ssr_scen.get("blended_liquid_pct"),
                "spending_guardrail_mode": ssr_scen.get("spending_guardrail_mode", "off"),
                "guardrails_badge_label": ssr_scen.get("guardrails_badge_label", "Off"),
            },
            "historical_backtest_summary": hist_summary, "historical_backtest": hist_summary,
            "scenarios_scorecard": [
                {"scenario_id": r.get("id"), "name": r.get("name"), "is_selected": r.get("is_selected", False),
                 "retirement_ages": r.get("ret_ages_str"), "annual_spend": r.get("spend_str"), "events_summary": r.get("events_summary"),
                 "nw_65": r.get("nw65_str"), "nw_85": r.get("nw85_str"), "nw_95": r.get("nw95_str"), "solvency": r.get("solv_text")}
                for r in (ssr_scen.get("scorecard_rows") or [])
            ],
            "active_life_events": [
                {"name": ev.get("name"), "year": ev.get("year_str"), "amount": ev.get("amount_str"),
                 "category": ev.get("type_label"), "enabled_in_active_plan": ev.get("is_checked", True)}
                for ev in (ssr_scen.get("event_rows") or [])
            ],
            "milestone_schedule": milestone_years, "scenarios_by_name": scenarios_by_name,
            "all_household_events_catalog": all_household_events,
        }
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error loading scenarios and forecast plan for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


from services.advisor.tools_scenarios_equity import (
    apply_company_equity_event_fields,
    apply_relocation_and_gifting_fields,
    update_scenario_assumptions,
)


def manage_scenario_life_event(
    action: str = "upsert", event_name: str = "", category: str = "lifestyle",
    start_year: Optional[int] = None, end_year: Optional[int] = None, amount: float = 0.0,
    is_outflow: bool = True, description: str = "", scenario_name: Optional[str] = None,
    scenario_id: Optional[str] = None, create_child_scenario_name: Optional[str] = None,
    event_id: Optional[str] = None, roth_strategy_preset: Optional[str] = None,
    equity_action: Optional[str] = None, grant_id: Optional[str] = None,
    options_quantity: Optional[float] = None, include_wa_tax: Optional[bool] = None,
    cost_basis_per_share: Optional[float] = None, equity_growth_preset: Optional[str] = None,
    custom_equity_growth_rate: Optional[float] = None, origin_state: Optional[str] = None,
    target_state: Optional[str] = None, family_id: int = 0,
) -> Dict[str, Any]:
    """
    Creates, modifies, enables/disables, or deletes a life event on a household forecast scenario
    (or clones a new child scenario for the event), persists the change, and returns Before vs. After impact.
    Supports `category='company_equity'` with `equity_action` ('cashless_repurchase', 'exercise_and_hold_cash',
    'exercise_and_hold_sell_to_cover', 'sell_held_shares'), `category='state_relocation'` with `origin_state`
    (e.g. 'WA') and `target_state` (e.g. 'NV', 'TX') + `amount` moving cost, and `category='gifting'` overrides.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {"error": "Unauthenticated session", "status": "unavailable"}

    clean_name, clean_desc = sanitize_text(event_name, 100), sanitize_text(description, 500)
    clean_cat = sanitize_text(category, 50).lower().strip() or "lifestyle"
    if equity_action or clean_cat in ("company_equity", "equity", "stock_options", "option_exercise"):
        clean_cat = "company_equity"
    elif target_state or origin_state or clean_cat in ("state_relocation", "relocation", "tax_relocation", "domicile_relocation"):
        clean_cat = "state_relocation"
    elif clean_cat in ("gifting", "gifting_throughline", "family_gifting", "annual_gifting"):
        clean_cat = "gifting"
    clean_scen_name, clean_child_name = sanitize_text(scenario_name, 100), sanitize_text(create_child_scenario_name, 100)
    act = (action or "upsert").lower().strip()
    is_upsert_act = act in ("upsert", "add", "update", "create", "simulate_only")

    try:
        state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=fam_id))
        scenarios = state.get("scenarios", [])
        if not scenarios:
            return {"error": "No scenarios found in household", "status": "unavailable"}

        target_scen = _resolve_scenario(scenarios, scenario_id=scenario_id, scenario_name=clean_scen_name)
        if not target_scen and clean_scen_name and not clean_child_name and is_upsert_act:
            clean_child_name = clean_scen_name
        if not target_scen:
            active_id = "scen_baseline" if clean_child_name else (state.get("active_scenario_id") or "scen_baseline")
            target_scen = next((s for s in scenarios if s.get("id") == active_id or (clean_child_name and s.get("is_baseline"))), scenarios[0])

        ssr_before, _ = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen["id"])
        is_demo = not can_mutate()
        is_read_only = is_demo or (act == "simulate_only")

        if clean_child_name:
            target_scen = resolve_or_clone_child_scenario(state, scenarios, target_scen, clean_child_name)
        if equity_growth_preset is not None or custom_equity_growth_rate is not None:
            apply_scenario_equity_growth_overrides(target_scen, equity_growth_preset, custom_equity_growth_rate)

        events = state.setdefault("events", [])
        target_event_ids = target_scen.setdefault("event_ids", [])
        matched_event: Optional[Dict[str, Any]] = None
        if event_id:
            matched_event = next((e for e in events if e.get("id") == event_id), None)
        if not matched_event and clean_name and not (clean_cat == "gifting" and is_upsert_act):
            c_lower = clean_name.lower()
            own_evts = [e for e in events if e.get("id") in target_event_ids]
            matched_event = (
                next((e for e in own_evts if e.get("name", "").strip().lower() == c_lower), None)
                or next((e for e in events if e.get("name", "").strip().lower() == c_lower), None)
                or next((e for e in own_evts if c_lower in e.get("name", "").strip().lower() or e.get("name", "").strip().lower() in c_lower), None)
                or next((e for e in events if c_lower in e.get("name", "").strip().lower() or e.get("name", "").strip().lower() in c_lower), None)
            )
            if matched_event and clean_cat == "company_equity" and equity_action:
                if (normalize_equity_action(equity_action) == "sell_held_shares") != (normalize_equity_action(matched_event.get("action")) == "sell_held_shares"):
                    matched_event = None

        this_year = date.today().year
        # With no start year given, a gifting program starts this year and other events next year.
        s_yr = int(start_year) if start_year else (this_year if clean_cat == "gifting" else this_year + 1)
        default_end = max(s_yr, this_year + 19) if clean_cat == "gifting" else s_yr
        e_yr = s_yr if clean_cat == "state_relocation" else int(end_year if end_year is not None else default_end)
        if e_yr < s_yr:
            e_yr = s_yr
        amt = float(amount or 0.0)
        if clean_cat == "company_equity" and not clean_name:
            clean_name = default_company_equity_event_name(equity_action, s_yr, e_yr)

        if is_upsert_act:
            shared_with_other = (clean_cat == "gifting")
            if matched_event and not shared_with_other:
                m_id = matched_event.get("id")
                other_refs = any(sc.get("id") != target_scen.get("id") and m_id in (sc.get("event_ids") or []) for sc in scenarios)
                is_default_cat = bool(
                    m_id in ("evt_company_equity_exercise_custom", "evt_state_relocation", "evt_family_gifting")
                    or str(m_id or "").startswith("evt_equity_")
                )
                shared_with_other = other_refs or (is_default_cat and not target_scen.get("is_baseline"))

            if matched_event and not shared_with_other:
                ev = matched_event
                if clean_name:
                    ev["name"] = clean_name
            else:
                max_events = getattr(config, "MAX_FORECAST_EVENTS", 40)
                if len(events) >= max_events:
                    return {"error": f"Maximum scenario events limit ({max_events}) reached", "status": "limit_exceeded"}
                if matched_event and shared_with_other and matched_event.get("id") in target_event_ids:
                    target_event_ids.remove(matched_event["id"])
                    if target_scen.get("parent_id"):
                        target_scen.setdefault("excluded_event_ids", []).append(matched_event["id"])
                ev = copy.deepcopy(matched_event) if matched_event else {}
                ev["id"] = f"evt_{uuid.uuid4().hex[:8]}"
                ev["name"] = clean_name or ev.get("name") or "Life Event"
                events.append(ev)

            ev.update({
                "category": clean_cat, "year": s_yr, "start_year": s_yr, "end_year": e_yr,
                "amount": amt, "annual_amount": amt, "is_outflow": bool(is_outflow),
                "description": clean_desc or ev.get("description", ""),
                "icon": _EVENT_CATEGORY_ICONS.get(clean_cat, "evt-capital-outflow"),
            })
            if roth_strategy_preset:
                ev["roth_strategy_preset"] = roth_strategy_preset
            if clean_cat == "company_equity":
                apply_company_equity_event_fields(
                    ev, target_scen, events, equity_action, grant_id, options_quantity, include_wa_tax, cost_basis_per_share
                )
            elif clean_cat in ("state_relocation", "gifting"):
                apply_relocation_and_gifting_fields(
                    ev, target_scen, events, clean_cat, s_yr, e_yr, amt, origin_state, target_state, clean_name, clean_desc
                )
            if ev["id"] not in target_scen["event_ids"]:
                if clean_cat == "state_relocation":
                    target_scen["event_ids"].insert(0, ev["id"])
                else:
                    target_scen["event_ids"].append(ev["id"])
            if target_scen.get("parent_id"):
                if isinstance(target_scen.get("added_event_ids"), list) and ev["id"] not in target_scen["added_event_ids"]:
                    target_scen["added_event_ids"].append(ev["id"])
                if isinstance(target_scen.get("excluded_event_ids"), list) and ev["id"] in target_scen["excluded_event_ids"]:
                    target_scen["excluded_event_ids"].remove(ev["id"])
        elif act in ("enable", "disable", "delete"):
            if not matched_event:
                return {"error": f"Event '{clean_name or event_id}' not found", "status": "not_found"}
            ev = matched_event
            if act == "enable" and ev["id"] not in target_event_ids:
                target_event_ids.append(ev["id"])
                if target_scen.get("parent_id") and isinstance(target_scen.get("excluded_event_ids"), list) and ev["id"] in target_scen["excluded_event_ids"]:
                    target_scen["excluded_event_ids"].remove(ev["id"])
            elif act == "disable" and ev["id"] in target_event_ids:
                target_event_ids.remove(ev["id"])
                if target_scen.get("parent_id"):
                    if isinstance(target_scen.get("added_event_ids"), list) and ev["id"] in target_scen["added_event_ids"]:
                        target_scen["added_event_ids"].remove(ev["id"])
                    exc = target_scen.setdefault("excluded_event_ids", [])
                    if ev["id"] not in exc:
                        exc.append(ev["id"])
            elif act == "delete":
                for sc in scenarios:
                    for key in ("event_ids", "added_event_ids", "excluded_event_ids"):
                        if isinstance(sc.get(key), list) and ev["id"] in sc[key]:
                            sc[key].remove(ev["id"])
                state["events"] = [e for e in events if e.get("id") != ev["id"]]
        else:
            return {"error": f"Unsupported action '{act}'", "status": "invalid_action"}

        status, ssr_after, raw_after = persist_or_simulate_scenario_state(fam_id, state, target_scen["id"], is_read_only)
        before_m, after_m = extract_scenario_metrics(ssr_before, target_scen["id"]), extract_scenario_metrics(ssr_after, target_scen["id"])
        window_cf = build_key_years_schedule(raw_after, target_scen["id"], list(range(s_yr, min(e_yr, s_yr + 9) + 1)))

        return {
            "status": status, "scenario_id": target_scen["id"], "scenario_name": target_scen.get("name", ""),
            "event": ev, "before_metrics": before_m, "after_metrics": after_m, "event_window_cash_flow": window_cf,
        }
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error managing life event for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}
