"""
forecast/scenarios.py: Scenario guardrails, assumption keys, and inheritance registration.
Provides per-plan dynamic spending guardrails logic (bear-market belt-tightening).
"""

from __future__ import annotations
from typing import Any, Dict, Optional

SPENDING_GUARDRAIL_MODES = ("off", "moderate", "aggressive")
DEFAULT_GUARDRAIL_MODE = "off"

GUARDRAIL_DESCRIPTIONS = {
    "off": "Fixed Real Spending (0% cut in drawdowns)",
    "moderate": "Guyton-Klinger Moderate Belt-Tightening (-15% cut when >15% drawdown)",
    "aggressive": "Flexible FIRE Guardrails (-25% cut when >15% drawdown, -15% when >10% drawdown)",
}

ROTH_AUTO_BRACKETS: Dict[str, Dict[str, Any]] = {
    "auto_bracket_12": {"ceiling": 133000.0, "rate": 0.12, "pct": 12},
    "fill_12": {"ceiling": 133000.0, "rate": 0.12, "pct": 12},
    "auto_bracket_22": {"ceiling": 243600.0, "rate": 0.22, "pct": 22},
    "fill_22": {"ceiling": 243600.0, "rate": 0.22, "pct": 22},
    "auto_bracket_24": {"ceiling": 435750.0, "rate": 0.24, "pct": 24},
    "fill_24": {"ceiling": 435750.0, "rate": 0.24, "pct": 24},
    "auto_bracket_32": {"ceiling": 544650.0, "rate": 0.32, "pct": 32},
    "fill_32": {"ceiling": 544650.0, "rate": 0.32, "pct": 32},
}
ROTH_BRACKET_CEILINGS = ROTH_AUTO_BRACKETS


def sanitize_guardrail_mode(mode: Any) -> str:
    """Normalizes guardrail mode string to 'off', 'moderate', or 'aggressive'."""
    val = str(mode or DEFAULT_GUARDRAIL_MODE).lower().strip()
    return val if val in SPENDING_GUARDRAIL_MODES else DEFAULT_GUARDRAIL_MODE


def get_scenario_guardrail_mode(scen: Optional[Dict[str, Any]]) -> str:
    """Extracts guardrail mode from a scenario dictionary with fallback to 'off'."""
    if not isinstance(scen, dict):
        return DEFAULT_GUARDRAIL_MODE
    return sanitize_guardrail_mode(scen.get("spending_guardrail_mode"))


def process_pre65_healthcare_event(
    ev: Dict[str, Any],
    year: int,
    age_primary: int,
    liquid_bal: float,
    is_working: bool,
    primary_earned_income: float,
    spouse_earned_income: float,
    earned_income_multiplier: float,
    yearly_event_outflow: float,
    events_occurred: list[str],
    events: Optional[list[Dict[str, Any]]] = None,
) -> tuple[float, float]:
    """Evaluates pre-65 early retirement healthcare bridge and dynamic ACA subsidies."""
    if age_primary >= 65:
        return liquid_bal, yearly_event_outflow

    name = ev.get("name", "Pre-65 Healthcare / ACA Bridge")
    gross_prem = float(ev.get("annual_premium") or ev.get("annual_amount") or ev.get("amount") or 24000.0)
    raw_sub = ev.get("aca_subsidy_mode") or (ev.get("parameters") or {}).get("aca_subsidy_mode") or (ev.get("metadata") or {}).get("aca_subsidy_mode")
    subsidy_mode = str(raw_sub or "aca_magi").lower()

    if subsidy_mode in ("unsubsidized_cobra", "unsubsidized", "cobra", "private"):
        net_prem = gross_prem
        yearly_event_outflow += net_prem
        liquid_bal = max(0.0, liquid_bal - net_prem)
        events_occurred.append(f"{name}: -${net_prem/1e3:.1f}k/yr unsubsidized healthcare premium")
        return liquid_bal, yearly_event_outflow

    salary_inflow = (primary_earned_income + spouse_earned_income) * earned_income_multiplier if is_working else 0.0
    taxable_yield = liquid_bal * 0.02
    roth_conv = 0.0
    if events:
        for o_ev in events:
            if o_ev.get("category") == "roth_conversion" and (o_ev.get("year", 2026) <= year <= o_ev.get("end_year", o_ev.get("year", 2026))):
                strat = str(o_ev.get("roth_strategy_preset") or "").lower()
                if strat in ROTH_AUTO_BRACKETS:
                    ceiling = ROTH_AUTO_BRACKETS[strat]["ceiling"]
                    raw_cap = o_ev.get("max_annual_conversion")
                    conv_fallback = float(raw_cap) if raw_cap is not None and float(raw_cap) > 0 else 1e9
                    dyn_conv = max(0.0, min(ceiling - (salary_inflow + taxable_yield), conv_fallback))
                    roth_conv += dyn_conv
                else:
                    roth_conv += float(o_ev.get("annual_conversion") or o_ev.get("conversion_amount") or o_ev.get("amount") or 0.0)
    aca_magi = salary_inflow + roth_conv + taxable_yield

    fpl_benchmark = 20440.0
    if aca_magi <= fpl_benchmark * 1.5:
        max_contribution = max(0.0, (aca_magi - fpl_benchmark) * 0.04) if aca_magi > fpl_benchmark else 0.0
    else:
        max_contribution = aca_magi * 0.085

    net_prem = min(gross_prem, max(0.0, max_contribution))
    subsidy = max(0.0, gross_prem - net_prem)
    yearly_event_outflow += net_prem
    liquid_bal = max(0.0, liquid_bal - net_prem)

    sub_msg = f"-${net_prem/1e3:.1f}k/yr ACA premium (saved ${subsidy/1e3:.1f}k/yr subsidy at ${aca_magi/1e3:.0f}k MAGI)" if subsidy > 0 else f"-${net_prem/1e3:.1f}k/yr healthcare premium"
    events_occurred.append(f"{name}: {sub_msg}")

    return liquid_bal, yearly_event_outflow


def process_roth_or_72t_event(
    ev: Dict[str, Any],
    name: str,
    age_primary: int,
    retire_bal: float,
    liquid_bal: float,
    yearly_event_outflow: float,
    events_occurred: list[str],
    is_working: bool = False,
    primary_earned_income: float = 0.0,
    spouse_earned_income: float = 0.0,
    earned_income_multiplier: float = 1.0,
) -> tuple[float, float, float]:
    """Processes Multi-Year Roth Conversion Ladder or IRC §72(t) SEPP Pre-59½ Penalty-Free Bridge."""
    strategy = str(ev.get("roth_strategy_preset") or "bracket_24").lower()
    if strategy == "rule_72t_sepp" and age_primary >= 60:
        return retire_bal, liquid_bal, yearly_event_outflow

    if strategy in ROTH_AUTO_BRACKETS:
        # SECURE 2.0: RMD age is 75 if born 1960 or later, else 73
        birth_year = ev.get("primary_birth_year") or ev.get("birth_year")
        if birth_year is None:
            sim_year = ev.get("year")
            birth_year = (sim_year - age_primary) if sim_year else (2026 - (age_primary if age_primary <= 66 else 67))
        rmd_age = 75 if birth_year >= 1960 else 73

        if (age_primary >= rmd_age and not ev.get("allow_post_rmd")) or retire_bal <= 0:
            return retire_bal, liquid_bal, yearly_event_outflow

        earned_inc = (primary_earned_income + spouse_earned_income) * earned_income_multiplier if is_working else 0.0
        taxable_yield = liquid_bal * 0.02
        baseline_ordinary_income = earned_inc + taxable_yield

        b_cfg = ROTH_AUTO_BRACKETS[strategy]
        bracket_ceiling = b_cfg["ceiling"]
        bracket_headroom = max(0.0, bracket_ceiling - baseline_ordinary_income)

        user_cap = float(ev.get("max_annual_conversion") or 0.0)
        target_conv = min(bracket_headroom, user_cap) if user_cap > 0 else bracket_headroom

        if target_conv <= 0:
            events_occurred.append(
                f"{name}: $0 converted ({b_cfg['pct']}% bracket filled by ${baseline_ordinary_income/1e3:.0f}k baseline income)"
            )
            return retire_bal, liquid_bal, yearly_event_outflow

        raw_rate = ev.get("marginal_tax_rate") or ev.get("conversion_tax_rate")
        tax_rate = float(raw_rate) if raw_rate is not None else b_cfg["rate"]
        if tax_rate > 1.0:
            tax_rate = tax_rate / 100.0

        actual_conv = min(retire_bal, target_conv)
        tax_cost = actual_conv * tax_rate
        retire_bal = max(0.0, retire_bal - actual_conv)
        liquid_bal = max(0.0, liquid_bal + actual_conv - tax_cost)
        yearly_event_outflow += tax_cost
        events_occurred.append(
            f"{name}: Auto-filled {b_cfg['pct']}% bracket (${actual_conv/1e3:.0f}k Trad → Roth, -${tax_cost/1e3:.0f}k tax)"
        )
        return retire_bal, liquid_bal, yearly_event_outflow

    conv_amt = float(ev.get("annual_conversion") or ev.get("conversion_amount") or ev.get("annual_amount") or ev.get("amount") or 100000.0)
    tax_rate = float(ev.get("marginal_tax_rate") or ev.get("conversion_tax_rate") or 0.24)
    if tax_rate > 1.0:
        tax_rate = tax_rate / 100.0

    if retire_bal > 0:
        actual_conv = min(retire_bal, max(0.0, conv_amt))
        tax_cost = actual_conv * tax_rate
        retire_bal = max(0.0, retire_bal - actual_conv)
        if ev.get("tax_payment_source") == "withhold_from_conversion":
            liquid_bal += max(0.0, actual_conv - tax_cost)
        else:
            liquid_bal = max(0.0, liquid_bal + actual_conv - tax_cost)
    else:
        actual_conv = max(0.0, conv_amt)
        tax_cost = actual_conv * tax_rate
        liquid_bal = max(0.0, liquid_bal - tax_cost)

    yearly_event_outflow += tax_cost
    if strategy == "rule_72t_sepp":
        events_occurred.append(
            f"{name}: Rule 72(t) SEPP ${actual_conv/1e3:.0f}k penalty-free pre-59½ bridge (-${tax_cost/1e3:.0f}k tax at {tax_rate*100:.0f}%, 0% penalty)"
        )
    else:
        events_occurred.append(
            f"{name}: Converted ${actual_conv/1e3:.0f}k Trad → Roth (-${tax_cost/1e3:.0f}k conversion tax at {tax_rate*100:.0f}%)"
        )
    return retire_bal, liquid_bal, yearly_event_outflow

