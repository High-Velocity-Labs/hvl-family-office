"""
SSR Builders for Forecasting Assumptions, Inheritance Overrides, and Preset Controls.
"""

from __future__ import annotations
from typing import Any, Dict, List

from ssr.formatting import fmt_currency, fmt_short_currency

_OVERRIDE_LABEL_MAP: Dict[str, str] = {
    "equity_growth_preset": "Company 409A Growth",
    "equity_growth_presets": "Per-Holding 409A Growth",
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

_EQUITY_PRESET_LABELS: Dict[str, str] = {
    "aggressive": "Aggressive (14.0%/yr)",
    "baseline_curve": "Baseline Curve (10.5%/yr)",
    "moderate": "Moderate (8.0%/yr)",
    "conservative": "Conservative (5.0%/yr)",
    "flat": "Flat (0.0%/yr)",
    "custom": "Custom Rate",
}


def format_equity_preset_label(val: Any) -> str:
    """Formats a 409A equity growth preset key into a human-friendly label."""
    if val is None:
        return ""
    cleaned = str(val).strip().lower()
    return _EQUITY_PRESET_LABELS.get(cleaned, str(val))


def format_override_value(key: str, val: Any) -> str:
    """Formats an assumption override key/value pair into a human-readable badge string."""
    try:
        if key == "equity_growth_preset":
            return format_equity_preset_label(val)
        if key == "equity_growth_presets" and isinstance(val, dict):
            return ", ".join(format_equity_preset_label(v) for v in val.values()) if val else ""
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
    has_custom_eq_rate = raw_overrides.get("custom_equity_growth_rate") is not None
    override_pills = []
    for k, v in raw_overrides.items():
        if v is None or (isinstance(v, dict) and not v):
            continue
        if has_custom_eq_rate and k == "equity_growth_preset" and str(v).strip().lower() == "custom":
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
