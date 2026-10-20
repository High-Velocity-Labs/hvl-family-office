"""
SSR Builders for Forecasting Assumptions, Overrides, Presets, and Multi-Scenario Scorecard Comparison Rows.
"""

from __future__ import annotations
from typing import Any, Dict, List

from ssr.formatting import fmt_currency, fmt_short_currency
from ssr.scenarios_shelf import cat_badge, cat_border

_OVERRIDE_LABEL_MAP = {
    "equity_growth_preset": "Company 409A Growth",
    "custom_equity_growth_rate": "Custom 409A Growth",
    "annual_living_spend": "Living Spend",
    "annual_savings": "Annual Savings",
    "inflation_rate": "Inflation Rate",
    "primary_retirement_age": "Primary Retirement Age",
    "spouse_retirement_age": "Spouse Retirement Age",
    "ss_claim_age": "Social Security Claim Age",
    "primary_ss_claim_age": "Primary SS Claim Age",
    "spouse_ss_claim_age": "Spouse SS Claim Age",
    "growth_us_equity": "US Equities Return",
    "growth_intl_equity": "Intl Equities Return",
    "growth_bonds": "Bonds Return",
    "growth_cash": "Cash Yield",
    "growth_private_investments": "Private Funds Return",
    "growth_real_estate": "Real Estate Appreciation",
    "spending_guardrail_mode": "Spending Guardrails",
}


def format_override_value(key: str, val: Any) -> str:
    try:
        if key == "spending_guardrail_mode":
            from ssr.planning_helpers import format_guardrail_mode_badge
            return format_guardrail_mode_badge(str(val))
        if key in ("annual_living_spend", "annual_savings"):
            return f"{fmt_short_currency(float(val))}/yr"
        if "rate" in key or key.startswith("growth_"):
            return f"{float(val) * 100:.1f}%"
        if "age" in key:
            return f"Age {int(float(val))}"
    except (ValueError, TypeError):
        pass
    return str(val)


def build_assumptions_and_overrides(
    sim: Dict[str, Any],
    card: Dict[str, Any],
    cur_scen: Dict[str, Any],
    scens: List[Dict[str, Any]],
    selected_scen_id: str,
    default_scen_id: str,
    living_spend_num: float,
    annual_savings_num: float,
) -> Dict[str, Any]:
    """Computes scenario inheritance, override pills, spending/savings presets, and asset growth parameters."""
    scen_name_by_id = {s.get("id"): s.get("name") for s in scens if isinstance(s, dict) and s.get("id")}
    for s in scens:
        if isinstance(s, dict):
            if s.get("parent_id") and not s.get("parent_name"):
                s["parent_name"] = scen_name_by_id.get(s.get("parent_id")) or "Base Plan"
            s["is_active"] = (s.get("id") == default_scen_id)
            s["is_selected"] = (s.get("id") == selected_scen_id)

    parent_id = cur_scen.get("parent_id") or card.get("parent_id") or cur_scen.get("parent_scenario_id")
    parent_name = (
        cur_scen.get("parent_name")
        or card.get("parent_name")
        or (scen_name_by_id.get(parent_id, "Base Plan") if parent_id else None)
    )
    plan_color = card.get("color") or cur_scen.get("color") or "#3B82F6"

    raw_overrides = cur_scen.get("overrides") if isinstance(cur_scen.get("overrides"), dict) else {}
    if not raw_overrides and isinstance(card.get("overrides"), dict):
        raw_overrides = card.get("overrides") or {}
    override_pills = []
    for k, v in raw_overrides.items():
        if v is None:
            continue
        lbl = _OVERRIDE_LABEL_MAP.get(k, k)
        val_str = format_override_value(k, v)
        override_pills.append({
            "key": k,
            "label": lbl,
            "val_str": val_str,
            "text": f"{lbl}: {val_str}",
        })
    overrides_count = len(override_pills)
    overrides_summary_text = (
        f"{overrides_count} assumption{'s' if overrides_count > 1 else ''} overridden"
        if overrides_count > 0
        else "All assumptions inherited"
    )
    overrides_tooltip = (
        "Custom Overrides: " + " • ".join(p["text"] for p in override_pills)
        if override_pills
        else ""
    )
    can_revert_assumptions = bool(
        (parent_id and overrides_count > 0)
        or (selected_scen_id == "scen_baseline" and overrides_count > 0)
    )

    raw_presets = sim.get("spending_presets") or []
    spending_presets = []
    found_active_preset = False
    for p in raw_presets:
        s_val = float(p.get("spend") or 0)
        is_match = abs(s_val - living_spend_num) < 1000
        is_active = is_match and not found_active_preset
        if is_active:
            found_active_preset = True
        spending_presets.append({
            "label": p.get("label"),
            "spend": s_val,
            "is_active": is_active,
        })

    raw_savings_presets = sim.get("savings_presets") or []
    savings_presets = []
    found_active_sav_preset = False
    for p in raw_savings_presets:
        s_val = float(p.get("savings") or 0)
        is_match = abs(s_val - annual_savings_num) < 1000
        is_active = is_match and not found_active_sav_preset
        if is_active:
            found_active_sav_preset = True
        savings_presets.append({
            "label": p.get("label"),
            "savings": s_val,
            "is_active": is_active,
        })

    primary_ss_claim_age = int(cur_scen.get("primary_ss_claim_age") or card.get("primary_ss_claim_age") or sim.get("primary_ss_claim_age") or 67)
    spouse_ss_claim_age = int(cur_scen.get("spouse_ss_claim_age") or card.get("spouse_ss_claim_age") or sim.get("spouse_ss_claim_age") or 67)

    inflation_rate_val = float(
        cur_scen.get("inflation_rate")
        if cur_scen.get("inflation_rate") is not None
        else (card.get("inflation_rate") if card.get("inflation_rate") is not None else (sim.get("inflation_rate") if sim.get("inflation_rate") is not None else 0.025))
    )
    blended_liquid_val = float(
        cur_scen.get("blended_liquid_growth")
        if cur_scen.get("blended_liquid_growth") is not None
        else (card.get("blended_liquid_growth") if card.get("blended_liquid_growth") is not None else (sim.get("blended_liquid_growth") or 0.072))
    )
    growth_priv_val = float(cur_scen.get("growth_private_investments") if cur_scen.get("growth_private_investments") is not None else (card.get("growth_private_investments") if card.get("growth_private_investments") is not None else (sim.get("growth_private_investments") or 0.10)))
    growth_re_val = float(cur_scen.get("growth_real_estate") if cur_scen.get("growth_real_estate") is not None else (card.get("growth_real_estate") if card.get("growth_real_estate") is not None else (sim.get("growth_real_estate") or 0.035)))
    growth_us_val = float(cur_scen.get("growth_us_equity") if cur_scen.get("growth_us_equity") is not None else (card.get("growth_us_equity") if card.get("growth_us_equity") is not None else (sim.get("growth_us_equity") or 0.085)))
    growth_intl_val = float(cur_scen.get("growth_intl_equity") if cur_scen.get("growth_intl_equity") is not None else (card.get("growth_intl_equity") if card.get("growth_intl_equity") is not None else (sim.get("growth_intl_equity") or 0.070)))
    growth_bonds_val = float(cur_scen.get("growth_bonds") if cur_scen.get("growth_bonds") is not None else (card.get("growth_bonds") if card.get("growth_bonds") is not None else (sim.get("growth_bonds") or 0.045)))
    growth_cash_val = float(cur_scen.get("growth_cash") if cur_scen.get("growth_cash") is not None else (card.get("growth_cash") if card.get("growth_cash") is not None else (sim.get("growth_cash") or 0.035)))

    aw = sim.get("asset_weights") or {}
    w_us = float(aw.get("us_equity", aw.get("us", 60)) or 60)
    w_intl = float(aw.get("intl_equity", aw.get("intl", 20)) or 20)
    w_bonds = float(aw.get("bonds", 15) or 15)
    w_cash = float(aw.get("cash", 5) or 5)
    liquid_weights_str = f"Live Portfolio Weights: US {w_us:.0f}% • Intl {w_intl:.0f}% • Bonds {w_bonds:.0f}% • Cash {w_cash:.0f}%"

    equity_companies = sim.get("equity_companies") or []
    equity_holdings = []
    for comp in equity_companies:
        if not isinstance(comp, dict):
            continue
        fmv_val = comp.get("current_fmv")
        equity_holdings.append({
            "company_id": comp.get("company_id"),
            "company_name": comp.get("company_name") or "Company",
            "grant_types_str": " / ".join(comp.get("grant_types") or ["NSO"]),
            "fmv_str": fmt_currency(float(fmv_val), 2) if fmv_val else "FMV Pending",
            "vested_str": f"{round(float(comp.get('total_vested_options') or 0)):,}",
            "owned_str": f"{round(float(comp.get('total_exercised_shares') or 0)):,}",
        })
    equity_growth_preset = cur_scen.get("equity_growth_preset") or card.get("equity_growth_preset") or "moderate"
    from ssr.planning_helpers import get_scenario_guardrail_display
    guardrail_disp = get_scenario_guardrail_display(cur_scen or card)

    rates_tup = (
        round(growth_us_val, 4), round(growth_intl_val, 4),
        round(growth_bonds_val, 4), round(growth_cash_val, 4),
        round(growth_priv_val, 4), round(growth_re_val, 4),
    )
    if rates_tup == (0.085, 0.070, 0.045, 0.035, 0.100, 0.035):
        market_return_profile = "baseline"
    elif rates_tup == (0.065, 0.055, 0.040, 0.030, 0.075, 0.025):
        market_return_profile = "conservative"
    elif rates_tup == (0.100, 0.085, 0.050, 0.040, 0.125, 0.045):
        market_return_profile = "aggressive"
    else:
        market_return_profile = "custom"

    return {
        "scen_name_by_id": scen_name_by_id,
        "parent_id": parent_id,
        "parent_name": parent_name,
        "plan_color": plan_color,
        "raw_overrides": raw_overrides,
        "override_pills": override_pills,
        "overrides_count": overrides_count,
        "overrides_summary_text": overrides_summary_text,
        "overrides_tooltip": overrides_tooltip,
        "can_revert_assumptions": can_revert_assumptions,
        "spending_presets": spending_presets,
        "savings_presets": savings_presets,
        "primary_ss_claim_age": primary_ss_claim_age,
        "spouse_ss_claim_age": spouse_ss_claim_age,
        "inflation_pct_str": f"{inflation_rate_val * 100:.1f}%",
        "inflation_input_val": f"{inflation_rate_val:.3f}".rstrip("0").rstrip(".") if inflation_rate_val else "0.025",
        "blended_liquid_pct": f"{blended_liquid_val * 100:.1f}% CAGR",
        "private_vc_pct": f"{growth_priv_val * 100:.1f}%",
        "real_estate_pct": f"{growth_re_val * 100:.1f}%",
        "growth_us_val": f"{growth_us_val * 100:.1f}",
        "growth_intl_val": f"{growth_intl_val * 100:.1f}",
        "growth_bonds_val": f"{growth_bonds_val * 100:.1f}",
        "growth_cash_val": f"{growth_cash_val * 100:.1f}",
        "growth_priv_val": f"{growth_priv_val * 100:.1f}",
        "growth_re_val": f"{growth_re_val * 100:.1f}",
        "market_return_profile": market_return_profile,
        "liquid_weights_str": liquid_weights_str,
        "equity_holdings": equity_holdings,
        "equity_growth_preset": equity_growth_preset,
        "spending_guardrail_mode": guardrail_disp["spending_guardrail_mode"],
        "guardrails_badge_label": guardrail_disp["guardrails_badge_label"],
    }


def build_scorecard_rows(
    scorecard_items: List[Dict[str, Any]],
    catalog: Dict[Any, Dict[str, Any]],
    scen_name_by_id: Dict[Any, Any],
    active_scen_id: str,
    default_scen_id: str,
    p_cur_age: int,
    s_cur_age: int,
) -> List[Dict[str, Any]]:
    """Builds the side-by-side scenario scorecard comparison table rows."""
    scorecard_rows: List[Dict[str, Any]] = []
    for sc in scorecard_items:
        if not isinstance(sc, dict):
            continue
        sc_id = sc.get("id") or ""
        sc_readiness = sc.get("retirement_readiness") or {}
        sc_is_dep = bool(sc.get("is_depleted"))
        sc_is_sust = (sc_readiness.get("is_sustainable") is True) and not sc_is_dep
        sc_can_now = sc_is_sust and (sc_readiness.get("can_retire_today") is True)

        sc_p_plan_age = sc_readiness.get("primary_planned_age") or sc.get("primary_retirement_age") or 50
        sc_p_plan_yr = sc_readiness.get("primary_planned_year") or sc.get("primary_retirement_year") or 2027
        sc_p_ear_age = sc_readiness.get("earliest_primary_age")
        sc_s_plan_age = sc_readiness.get("spouse_planned_age") or sc.get("spouse_retirement_age") or 52
        sc_s_plan_yr = sc_readiness.get("spouse_planned_year") or sc.get("spouse_retirement_year") or 2031
        sc_s_ear_age = sc_readiness.get("earliest_spouse_age")
        sc_ear_joint_yr = sc_readiness.get("earliest_joint_year")

        if sc_can_now:
            p_ret_badge = "badge-green"
            p_ret_text = f"Now (Age {p_cur_age})"
            p_ret_sub = f"Plan: Age {sc_p_plan_age} ({sc_p_plan_yr})"
            p_ret_sub_red = False
            p_ret_tooltip = f"Financially independent today at Age {p_cur_age} (Planned target: Age {sc_p_plan_age} in {sc_p_plan_yr})"
        elif sc_is_sust:
            p_ret_badge = "badge-blue"
            p_ret_text = f"Age {sc_p_plan_age} ({sc_p_plan_yr})"
            p_ret_sub = "Sustainable"
            p_ret_sub_red = False
            p_ret_tooltip = f"Planned retirement at Age {sc_p_plan_age} ({sc_p_plan_yr}) is fully sustainable through Age 100"
        elif sc_p_ear_age:
            p_ret_badge = "badge-orange"
            p_ret_text = f"Age {sc_p_ear_age} ({sc_ear_joint_yr})"
            p_ret_sub = f"Plan Age {sc_p_plan_age}: Depleted"
            p_ret_sub_red = True
            p_ret_tooltip = f"Planned retirement at Age {sc_p_plan_age} depletes portfolio. Earliest sustainable retirement is Age {sc_p_ear_age} ({sc_ear_joint_yr})"
        else:
            p_ret_badge = "badge-red"
            p_ret_text = "Infeasible"
            p_ret_sub = f"Plan Age {sc_p_plan_age}: Depleted"
            p_ret_sub_red = False
            p_ret_tooltip = "Current spending & events exceed portfolio capacity at any retirement age"

        if sc_can_now:
            s_ret_badge = "badge-green"
            s_ret_text = f"Now (Age {s_cur_age})"
            s_ret_sub = f"Plan: Age {sc_s_plan_age} ({sc_s_plan_yr})"
            s_ret_sub_red = False
            s_ret_tooltip = f"Financially independent today at Age {s_cur_age} (Planned target: Age {sc_s_plan_age} in {sc_s_plan_yr})"
        elif sc_is_sust:
            s_ret_badge = "badge-blue"
            s_ret_text = f"Age {sc_s_plan_age} ({sc_s_plan_yr})"
            s_ret_sub = "Sustainable"
            s_ret_sub_red = False
            s_ret_tooltip = f"Planned retirement at Age {sc_s_plan_age} ({sc_s_plan_yr}) is fully sustainable through Age 100"
        elif sc_s_ear_age:
            s_ret_badge = "badge-orange"
            s_ret_text = f"Age {sc_s_ear_age} ({sc_ear_joint_yr})"
            s_ret_sub = f"Plan Age {sc_s_plan_age}: Depleted"
            s_ret_sub_red = True
            s_ret_tooltip = f"Planned retirement at Age {sc_s_plan_age} depletes portfolio. Earliest sustainable retirement is Age {sc_s_ear_age} ({sc_ear_joint_yr})"
        else:
            s_ret_badge = "badge-red"
            s_ret_text = "Infeasible"
            s_ret_sub = f"Plan Age {sc_s_plan_age}: Depleted"
            s_ret_sub_red = False
            s_ret_tooltip = "Current spending & events exceed portfolio capacity at any retirement age"

        sc_ev_raw = sc.get("events_details") or [catalog[eid] for eid in (sc.get("events_included") or []) if eid in catalog]
        sc_ev_chips = []
        for sev in sc_ev_raw:
            if not isinstance(sev, dict):
                continue
            sey = sev.get("year")
            seend = sev.get("end_year")
            st_range = f" ({sey}{f'–{seend}' if seend and seend > sey else ''})" if sey else ""
            samt = sev.get("amount")
            samt_str = f": ${round(float(samt) / 1000.0):,}k/yr" if samt else ""
            scat = sev.get("category") or "other"
            sen = str(sev.get("name") or "")
            sc_ev_chips.append({
                "id": sev.get("id") or "",
                "name": sen,
                "category": scat,
                "icon": sev.get("icon") or "",
                "cat_badge": cat_badge(scat),
                "border_color": cat_border(scat),
                "tooltip": f"{sen}{st_range}{samt_str}",
                "short_name": f"{sen[:15]}…" if len(sen) > 16 else sen,
            })

        sc_parent_id = sc.get("parent_id")
        sc_parent_name = sc.get("parent_name") or (scen_name_by_id.get(sc_parent_id, "Base Plan") if sc_parent_id else None)
        sc_overrides = sc.get("overrides") or {}
        sc_overrides_count = len(sc_overrides) if isinstance(sc_overrides, dict) else 0
        sc_blended = sc.get("blended_liquid_growth")
        sc_eq_preset = sc.get("equity_growth_preset")
        sc_has_eq_override = bool(sc_overrides.get("equity_growth_preset")) if isinstance(sc_overrides, dict) else False

        sc_mc = sc.get("monte_carlo_solvency")
        if sc_mc is not None:
            sc_mc_fmt = int(sc_mc) if isinstance(sc_mc, float) and sc_mc.is_integer() else sc_mc
            sc_solv_badge = "badge-green" if sc_mc >= 90 else ("badge-orange" if sc_mc >= 75 else "badge-red")
            sc_solv_text = f"{sc_mc_fmt}% MC"
            sc_solv_title = f"{sc_mc_fmt}% of 1,000 Monte Carlo paths solvent through Age 100"
        elif sc_is_dep:
            sc_solv_badge = "badge-red"
            sc_solv_text = f"Depleted ({sc.get('depletion_year') or ''})"
            sc_solv_title = ""
        else:
            sc_solv_badge = "badge-green"
            sc_solv_text = "Solvent @ 100"
            sc_solv_title = ""

        scorecard_rows.append({
            "id": sc_id,
            "name": sc.get("name") or "Scenario",
            "description": sc.get("description") or "",
            "color": sc.get("color") or "#3B82F6",
            "is_current_view": sc_id == active_scen_id,
            "is_active": sc_id == default_scen_id,
            "is_baseline": bool(sc.get("is_baseline")) or sc_id == "scen_baseline",
            "is_child": bool(sc_parent_id),
            "parent_id": sc_parent_id or "",
            "parent_name": sc_parent_name or "Base Plan",
            "overrides_count": sc_overrides_count,
            "blended_liquid_pct": f"{float(sc_blended) * 100:.1f}" if sc_blended else None,
            "equity_growth_preset": sc_eq_preset,
            "has_equity_override": sc_has_eq_override,
            "events": sc_ev_chips,
            "primary_ret_badge": p_ret_badge,
            "primary_ret_text": p_ret_text,
            "primary_ret_sub": p_ret_sub,
            "primary_ret_sub_red": p_ret_sub_red,
            "primary_ret_tooltip": p_ret_tooltip,
            "spouse_ret_badge": s_ret_badge,
            "spouse_ret_text": s_ret_text,
            "spouse_ret_sub": s_ret_sub,
            "spouse_ret_sub_red": s_ret_sub_red,
            "spouse_ret_tooltip": s_ret_tooltip,
            "nw65": fmt_short_currency(sc.get("net_worth_65")),
            "nw85": fmt_short_currency(sc.get("net_worth_85")),
            "nw95": fmt_short_currency(sc.get("net_worth_95")),
            "is_depleted": sc_is_dep,
            "solv_badge": sc_solv_badge,
            "solv_text": sc_solv_text,
            "solv_title": sc_solv_title,
            "solv_earliest_yr": sc_ear_joint_yr if sc_is_dep else None,
        })

    return scorecard_rows
