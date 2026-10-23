"""
Scenario Cloning, Hierarchy Traversal & Inheritance Service.
Manages scenario DAG tree depth, cycle detection, lineage derivation, and CSV serialization.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

import config
import forecast_cache
import forecast_engine
from routes.helpers import parse_query_params

COLOR_PALETTE = ("#1D4ED8", "#059669", "#0284C7", "#D97706", "#0D9488", "#C75D6E", "#64748B")

_LEGACY_COLOR_ALIASES: dict[str, str] = {
    "#0265E8": "#1D4ED8",
    "#3B82F6": "#1D4ED8",
    "#10B981": "#059669",
    "#F59E0B": "#D97706",
    "#14B8A6": "#0D9488",
    "#EF4444": "#C75D6E",
    "#F43F5E": "#C75D6E",
}


def pick_unused_scenario_color(scenarios: list[dict[str, Any]]) -> str:
    """Returns the first theme preset color not yet used by existing scenarios."""
    used_colors: set[str] = set()
    for s in scenarios or []:
        raw = str(s.get("color") or "").strip().upper()
        if raw:
            used_colors.add(_LEGACY_COLOR_ALIASES.get(raw, raw))
    for color in COLOR_PALETTE:
        if color not in used_colors:
            return color
    return COLOR_PALETTE[len(scenarios or []) % len(COLOR_PALETTE)]

INHERITED_NULL_FIELDS = (
    "annual_living_spend",
    "primary_retirement_age",
    "spouse_retirement_age",
    "annual_savings",
    "inflation_rate",
    "equity_growth_preset",
    "equity_growth_presets",
    "custom_equity_growth_rate",
    "ss_claim_age",
    "primary_ss_claim_age",
    "spouse_ss_claim_age",
    "growth_us_equity",
    "growth_intl_equity",
    "growth_bonds",
    "growth_cash",
    "growth_private_investments",
    "growth_real_estate",
)


def validate_scenario_hierarchy(
    scen_id: str,
    parent_id: str | None,
    scenarios: list[dict[str, Any]],
    existing: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Validates hierarchy rules, circular references, sibling limits, and depth constraints."""
    if scen_id == "scen_baseline" or not parent_id:
        return True, None

    if parent_id == scen_id:
        return False, "A scenario cannot be its own parent"

    if not any(s.get("id") == parent_id for s in scenarios):
        return False, f"Parent scenario '{parent_id}' not found"

    # Cycle check
    curr = parent_id
    visited = {scen_id}
    while curr:
        if curr in visited:
            return False, "Circular scenario hierarchy detected"
        visited.add(curr)
        p_scen = next((s for s in scenarios if s.get("id") == curr), None)
        curr = p_scen.get("parent_id") if p_scen else None

    # Sibling count check
    if existing is None or existing.get("parent_id") != parent_id:
        sibling_count = sum(1 for s in scenarios if s.get("parent_id") == parent_id and s.get("id") != scen_id)
        if sibling_count >= config.MAX_CHILD_SCENARIOS_PER_PARENT:
            return False, f"Maximum of {config.MAX_CHILD_SCENARIOS_PER_PARENT} child scenarios per parent scenario reached."

    # Hierarchy depth check
    scen_map = {s["id"]: s for s in scenarios if "id" in s}
    ancestor_count = 0
    curr_anc = parent_id
    seen_anc = {scen_id}
    while curr_anc and curr_anc not in seen_anc:
        ancestor_count += 1
        seen_anc.add(curr_anc)
        p_scen = scen_map.get(curr_anc)
        curr_anc = p_scen.get("parent_id") if p_scen else None

    def _max_descendant_hops(node_id: str, visited_desc: set[str]) -> int:
        children = [
            s["id"] for s in scenarios
            if s.get("parent_id") == node_id and s.get("id") != scen_id and s.get("id") not in visited_desc
        ]
        if not children:
            return 0
        return 1 + max(_max_descendant_hops(cid, visited_desc | {cid}) for cid in children)

    max_desc_hops = _max_descendant_hops(scen_id, {scen_id}) if existing else 0
    if ancestor_count + 1 + max_desc_hops > config.MAX_SCENARIO_DEPTH:
        return False, f"Maximum scenario hierarchy depth of {config.MAX_SCENARIO_DEPTH} levels reached."

    return True, None


def resolve_scenario_event_lineage(
    data: dict[str, Any],
    event_ids: list[str],
    parent_id: str | None,
    scenarios: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Resolves added and excluded event IDs based on parent scenario event lineage."""
    if parent_id:
        parent_scen = next((s for s in scenarios if s.get("id") == parent_id), None)
        parent_events = set(parent_scen.get("event_ids", []) if parent_scen else [])
        curr_set = set(event_ids)
        excl = list(data["excluded_event_ids"]) if "excluded_event_ids" in data else list(parent_events - curr_set)
        added = list(data["added_event_ids"]) if "added_event_ids" in data else [eid for eid in event_ids if eid not in parent_events]
        return added, excl
    added = list(data.get("added_event_ids", [])) if "added_event_ids" in data else []
    excl = list(data.get("excluded_event_ids", [])) if "excluded_event_ids" in data else []
    return added, excl


def clone_scenario(
    family_id: int,
    source_id: str,
    engine: Any = None,
    cache: Any = None,
) -> tuple[bool, Any, int]:
    """Clones an existing scenario as an inherited child scenario."""
    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    scenarios = state.get("scenarios", [])
    source = next((s for s in scenarios if s.get("id") == source_id), None)
    if not source:
        return False, f"Scenario '{source_id}' not found", 404

    if len(scenarios) >= config.MAX_SCENARIOS:
        return False, f"Maximum of {config.MAX_SCENARIOS} scenarios per household reached.", 400

    child_count = sum(1 for s in scenarios if s.get("parent_id") == source["id"])
    if child_count >= config.MAX_CHILD_SCENARIOS_PER_PARENT:
        return False, f"Maximum of {config.MAX_CHILD_SCENARIOS_PER_PARENT} child scenarios per parent scenario reached.", 400

    scen_map = {s["id"]: s for s in scenarios if "id" in s}
    ancestor_count = 0
    curr_anc = source["id"]
    seen_anc: set[str] = set()
    while curr_anc and curr_anc not in seen_anc:
        ancestor_count += 1
        seen_anc.add(curr_anc)
        p_scen = scen_map.get(curr_anc)
        curr_anc = p_scen.get("parent_id") if p_scen else None
    if ancestor_count + 1 > config.MAX_SCENARIO_DEPTH:
        return False, f"Maximum scenario hierarchy depth of {config.MAX_SCENARIO_DEPTH} levels reached.", 400

    raw_name = source.get("name", "Plan")
    base_prefix = raw_name[:85] if len(raw_name) > 85 else raw_name
    base_name = f"{base_prefix} (Copy)"
    existing_names = {s.get("name") for s in scenarios}
    name = base_name
    counter = 2
    while name in existing_names:
        name = f"{base_prefix} (Copy {counter})"
        counter += 1

    new_id = f"scen_clone_{int(time.time() * 1000)}"
    new_scen = dict(source)
    new_scen["id"] = new_id
    new_scen["name"] = name
    new_scen["is_baseline"] = False
    new_scen["parent_id"] = source["id"]
    new_scen["added_event_ids"] = []
    new_scen["excluded_event_ids"] = []
    new_scen["event_ids"] = list(source.get("event_ids", []))

    for k in INHERITED_NULL_FIELDS:
        new_scen[k] = None

    new_scen["color"] = pick_unused_scenario_color(scenarios)

    scenarios.append(new_scen)
    state["scenarios"] = scenarios
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)
    return True, new_scen, 200


def delete_scenario_hierarchy(
    family_id: int,
    scenario_id: str,
    engine: Any = None,
    cache: Any = None,
) -> list[str]:
    """Recursively deletes a scenario and all of its descendants, preserving baseline."""
    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    scenarios = state.get("scenarios", [])

    to_delete = {scenario_id}
    added = True
    while added:
        added = False
        for s in scenarios:
            if s.get("parent_id") in to_delete and s.get("id") not in to_delete:
                to_delete.add(s["id"])
                added = True

    to_delete.discard("scen_baseline")
    state["scenarios"] = [s for s in scenarios if s.get("id") not in to_delete]
    if state.get("active_scenario_id") in to_delete:
        state["active_scenario_id"] = "scen_baseline"

    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)
    return list(to_delete)


def serialize_forecast_csv(res: dict[str, Any], target_scen_id: str | None = None) -> str:
    """Serializes multi-year forecast schedule & tax cash flow rows into CSV format."""
    scen_id = target_scen_id or res.get("active_scenario_id") or "scen_baseline"
    sched = (
        res.get("timeline")
        or res.get("years")
        or (res.get("scenario_schedules") or {}).get(scen_id)
        or res.get("active_schedule")
        or []
    )
    cf_list = (res.get("scenario_cash_flows") or {}).get(scen_id) or res.get("active_cash_flow_series") or []
    cf_by_year = {r.get("year"): r for r in cf_list if isinstance(r, dict) and r.get("year") is not None}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Year", "Age", "Gross Income", "W2 & Salary", "RSU Vest Value",
        "Total Taxes", "Effective Tax Rate", "Annual Spending", "Net Cash Flow",
        "Liquid Portfolio", "Retirement Accounts", "Real Estate Equity",
        "Company Equity (Post-Tax)", "True Net Worth",
    ])
    for row in sched:
        yr = row.get("year", "")
        cf = cf_by_year.get(yr, {})
        gross = float(row.get("gross_income", cf.get("gross_compensation", row.get("yearly_inflow", 0.0))) or 0.0)
        w2_sal = float(row.get("w2_salary", cf.get("household_salary", row.get("salary_savings", 0.0))) or 0.0)
        rsu_val = float(row.get("rsu_vest_value", cf.get("event_inflows", 0.0)) or 0.0)
        taxes = float(row.get("total_taxes", cf.get("income_tax_haircut", 0.0)) or 0.0)
        eff_rate = row.get("effective_tax_rate")
        if eff_rate is None:
            eff_rate = round((taxes / gross) * 100.0, 2) if gross > 0 else 0.0
        spend = float(row.get("annual_spending", row.get("living_spending", cf.get("total_outflow", 0.0))) or 0.0)
        net_cf = float(row.get("net_cash_flow", cf.get("net_cash_flow", 0.0)) or 0.0)
        liquid = float(row.get("liquid_portfolio", row.get("liquid_assets", 0.0)) or 0.0)
        retire = float(row.get("retirement_accounts", row.get("retirement_assets", 0.0)) or 0.0)
        re_eq = float(row.get("real_estate_equity", row.get("real_estate_net", 0.0)) or 0.0)
        comp_eq = float(row.get("company_equity_post_tax", row.get("company_equity", 0.0)) or 0.0)
        true_nw = float(row.get("true_net_worth", row.get("total_net_worth", 0.0)) or 0.0)
        writer.writerow([
            yr,
            row.get("age", row.get("age_primary", "")),
            f"{gross:.2f}",
            f"{w2_sal:.2f}",
            f"{rsu_val:.2f}",
            f"{taxes:.2f}",
            f"{float(eff_rate):.2f}%",
            f"{spend:.2f}",
            f"{net_cf:.2f}",
            f"{liquid:.2f}",
            f"{retire:.2f}",
            f"{re_eq:.2f}",
            f"{comp_eq:.2f}",
            f"{true_nw:.2f}",
        ])
    return buf.getvalue()


def export_forecast_csv(family_id: int, args: Any, engine: Any = None) -> str:
    """Computes forecast schedule for CSV download and formats as text."""
    eng = engine or forecast_engine
    params = parse_query_params(args, {
        "primary_retirement_age": int,
        "retirement_age": int,
        "spouse_retirement_age": int,
        "annual_living_spend": float,
        "annual_spending": float,
        "annual_savings": float,
        "inflation_rate": float,
        "growth_us_equity": float,
        "stock_growth": float,
    })
    target_scen_id = args.get("scenario_id") or args.get("target_scenario_id") or None
    ret_age = params["primary_retirement_age"] if params["primary_retirement_age"] is not None else params["retirement_age"]
    spend = params["annual_living_spend"] if params["annual_living_spend"] is not None else params["annual_spending"]
    us_growth = params["growth_us_equity"] if params["growth_us_equity"] is not None else params["stock_growth"]

    runner = getattr(eng, "run_forecast", None) or eng.simulate_multi_scenarios
    res = runner(
        family_id=family_id,
        target_scenario_id=target_scen_id,
        primary_retirement_age=ret_age,
        spouse_retirement_age=params["spouse_retirement_age"],
        annual_living_spend=spend,
        annual_savings=params["annual_savings"],
        inflation_rate=params["inflation_rate"],
        growth_us_equity=us_growth,
        view_mode=args.get("view_mode") or None,
    )
    return serialize_forecast_csv(res if isinstance(res, dict) else {}, target_scen_id)
