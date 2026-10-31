"""
forecast/scenarios.py: Scenario guardrails, assumption keys, and inheritance registration.
Provides per-plan dynamic spending guardrails logic (bear-market belt-tightening).
"""

from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional

from forecast import event_amounts
from forecast.event_amounts import EventIndexer
from forecast.tax_indexing import threshold_index
from services import tax_engine
from forecast.benefit_constants import aca_poverty_line
from forecast.household_roster import HouseholdRoster
from forecast.investment_income import DEFAULT_TAXABLE_YIELD_RATE
from services.statutory_limits import aca_applicable_percentage

SPENDING_GUARDRAIL_MODES = ("off", "moderate", "aggressive")
DEFAULT_GUARDRAIL_MODE = "off"

GUARDRAIL_DESCRIPTIONS = {
    "off": "Fixed Real Spending (0% cut in drawdowns)",
    "moderate": "Custom Drawdown Rule, Moderate (-15% cut when >15% drawdown)",
    "aggressive": "Flexible FIRE Guardrails (-25% cut when >15% drawdown, -15% when >10% drawdown)",
}

def _mfj_bracket_ceiling(rate: float) -> float:
    """Gross ordinary income that fills the MFJ bracket at `rate` (bracket top + standard deduction)."""
    top = next(upper for _lower, upper, r in tax_engine.FED_BRACKETS_MFJ_2026 if r == rate)
    return top + tax_engine.STANDARD_DEDUCTION_MFJ_2026


ROTH_AUTO_BRACKETS: Dict[str, Dict[str, Any]] = {
    f"{prefix}{pct}": {"ceiling": _mfj_bracket_ceiling(pct / 100.0), "rate": pct / 100.0, "pct": pct}
    for pct in (12, 22, 24, 32)
    for prefix in ("auto_bracket_", "fill_")
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
    price_index: float = 1.0,
    inflation_rate: float = 0.0,
    *,
    indexer: EventIndexer,
    roster: Optional[HouseholdRoster] = None,
    taxable_yield_rate: float = DEFAULT_TAXABLE_YIELD_RATE,
    other_taxable_income: float = 0.0,
) -> tuple[float, float]:
    """
    Evaluates pre-65 early retirement healthcare bridge and dynamic ACA subsidies.
    Earned income arrives in today's dollars (`price_index` makes it nominal); FPL and bracket
    thresholds are indexed to `year`. Premiums are scaled by the event's `amount_basis`.
    The bridge covers each adult until their own 65th birthday (the entered premium is for all adults
    on the plan, so it shrinks pro rata as adults leave for Medicare). The poverty line is for the whole
    household (adults plus dependents) from `roster`; without a roster it is the adults passed in.
    MAGI is wages, Roth conversions, `other_taxable_income` (pension) and `taxable_yield_rate` on the liquid balance
    (the household's actual dividend and interest income over its balance when known, else 2%).
    """
    spouse_age = roster.spouse_age(year) if roster is not None else None
    adult_ages = [age_primary] + ([spouse_age] if spouse_age is not None else [])
    covered_adults = sum(1 for a in adult_ages if a < 65)
    if covered_adults == 0:
        return liquid_bal, yearly_event_outflow
    household_size = roster.household_size(year) if roster is not None else len(adult_ages)

    name = ev.get("name", "Pre-65 Healthcare / ACA Bridge")
    entered_prem = float(ev.get("annual_premium") or ev.get("annual_amount") or ev.get("amount") or 24000.0)
    full_prem = event_amounts.scale_event_amount(ev, entered_prem, year, indexer)
    gross_prem = full_prem * covered_adults / len(adult_ages)
    raw_sub = ev.get("aca_subsidy_mode") or (ev.get("parameters") or {}).get("aca_subsidy_mode") or (ev.get("metadata") or {}).get("aca_subsidy_mode")
    subsidy_mode = str(raw_sub or "aca_magi").lower()

    if subsidy_mode in ("unsubsidized_cobra", "unsubsidized", "cobra", "private"):
        net_prem = gross_prem
        yearly_event_outflow += net_prem
        liquid_bal = liquid_bal - net_prem
        events_occurred.append(f"{name}: -${net_prem/1e3:.1f}k/yr unsubsidized healthcare premium")
        return liquid_bal, yearly_event_outflow

    salary_inflow = (primary_earned_income + spouse_earned_income) * earned_income_multiplier * price_index if is_working else 0.0
    taxable_yield = max(0.0, liquid_bal) * taxable_yield_rate
    thresholds = threshold_index(year, inflation_rate)
    roth_conv = 0.0
    if events:
        for o_ev in events:
            if o_ev.get("category") == "roth_conversion" and (o_ev.get("year", year) <= year <= o_ev.get("end_year", o_ev.get("year", year))):
                strat = str(o_ev.get("roth_strategy_preset") or "").lower()
                if strat in ROTH_AUTO_BRACKETS:
                    ceiling = ROTH_AUTO_BRACKETS[strat]["ceiling"] * thresholds
                    raw_cap = o_ev.get("max_annual_conversion")
                    conv_fallback = float(raw_cap) if raw_cap is not None and float(raw_cap) > 0 else 1e9
                    headroom = ceiling - (salary_inflow + taxable_yield + other_taxable_income)
                    dyn_conv = max(0.0, min(headroom, conv_fallback))
                    roth_conv += dyn_conv
                else:
                    roth_conv += event_amounts.scale_event_amount(o_ev, float(o_ev.get("annual_conversion") or o_ev.get("conversion_amount") or o_ev.get("amount") or 0.0), year, indexer)
    aca_magi = salary_inflow + roth_conv + taxable_yield + other_taxable_income

    applicable_pct = aca_applicable_percentage(aca_magi / (aca_poverty_line(household_size) * thresholds))
    max_contribution = gross_prem if applicable_pct is None else aca_magi * applicable_pct

    net_prem = min(gross_prem, max(0.0, max_contribution))
    subsidy = max(0.0, gross_prem - net_prem)
    yearly_event_outflow += net_prem
    liquid_bal = liquid_bal - net_prem

    if subsidy > 0:
        sub_msg = f"-${net_prem/1e3:.1f}k/yr ACA premium (saved ${subsidy/1e3:.1f}k/yr subsidy at ${aca_magi/1e3:.0f}k MAGI)"
    elif applicable_pct is None:
        sub_msg = f"-${net_prem/1e3:.1f}k/yr healthcare premium (no ACA credit above 400% of the poverty line at ${aca_magi/1e3:.0f}k MAGI)"
    else:
        sub_msg = f"-${net_prem/1e3:.1f}k/yr healthcare premium"
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
    year: Optional[int] = None,
    price_index: float = 1.0,
    inflation_rate: float = 0.0,
    *,
    indexer: EventIndexer,
    taxable_yield_rate: float = DEFAULT_TAXABLE_YIELD_RATE,
    other_taxable_income: float = 0.0,
) -> tuple[float, float, float]:
    """
    Processes Multi-Year Roth Conversion Ladder or IRC §72(t) SEPP Pre-59½ Penalty-Free Bridge.
    Earned income arrives in today's dollars (`price_index` makes it nominal); bracket ceilings are
    indexed to `year`. Explicit conversion amounts are scaled by the event's `amount_basis` (fixed by default);
    bracket-fill caps are applied as entered.
    """
    strategy = str(ev.get("roth_strategy_preset") or "bracket_24").lower()
    if strategy == "rule_72t_sepp" and age_primary >= 60:
        return retire_bal, liquid_bal, yearly_event_outflow

    if strategy in ROTH_AUTO_BRACKETS:
        # SECURE 2.0: RMD age is 75 if born 1960 or later, else 73
        birth_year = ev.get("primary_birth_year") or ev.get("birth_year")
        if birth_year is None:
            sim_year = ev.get("year")
            if sim_year or year is not None:
                birth_year = (sim_year or year) - age_primary
            else:
                birth_year = date.today().year - (age_primary if age_primary <= 66 else 67)
        rmd_age = 75 if birth_year >= 1960 else 73

        if (age_primary >= rmd_age and not ev.get("allow_post_rmd")) or retire_bal <= 0:
            return retire_bal, liquid_bal, yearly_event_outflow

        earned_inc = (primary_earned_income + spouse_earned_income) * earned_income_multiplier * price_index if is_working else 0.0
        taxable_yield = max(0.0, liquid_bal) * taxable_yield_rate
        baseline_ordinary_income = earned_inc + taxable_yield + other_taxable_income

        b_cfg = ROTH_AUTO_BRACKETS[strategy]
        bracket_ceiling = b_cfg["ceiling"] * (threshold_index(year, inflation_rate) if year is not None else 1.0)
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
        liquid_bal = liquid_bal + actual_conv - tax_cost
        yearly_event_outflow += tax_cost
        events_occurred.append(
            f"{name}: Auto-filled {b_cfg['pct']}% bracket (${actual_conv/1e3:.0f}k Trad → Roth, -${tax_cost/1e3:.0f}k tax)"
        )
        return retire_bal, liquid_bal, yearly_event_outflow

    entered_conv = float(ev.get("annual_conversion") or ev.get("conversion_amount") or ev.get("annual_amount") or ev.get("amount") or 100000.0)
    conv_amt = event_amounts.scale_event_amount(ev, entered_conv, year if year is not None else indexer.start_year, indexer)
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
            liquid_bal = liquid_bal + actual_conv - tax_cost
    else:
        actual_conv = max(0.0, conv_amt)
        tax_cost = actual_conv * tax_rate
        liquid_bal = liquid_bal - tax_cost

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

