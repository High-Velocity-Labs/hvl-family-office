"""
forecast/waterfall_events.py: Annual lifecycle event evaluator for scenario simulations.
Processes multi-asset equity liquidations, sabbaticals, debt refinance, gifting,
private equity J-curves, long-term care, and state relocations.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple

from forecast.scenarios import process_pre65_healthcare_event, process_roth_or_72t_event
from forecast.waterfall_equity import process_company_equity_event, process_pe_capital_call_event
from forecast.waterfall_helpers import process_education_event, process_real_estate_event


def process_year_events(
    events: List[Dict[str, Any]],
    year: int,
    liquid_bal: float,
    retire_bal: float,
    re_bal: float,
    mortgage_bal: float,
    other_bal: float,
    share_price: float,
    options_pools: Dict[str, Dict[str, Any]],
    edu_reserves: Dict[str, Dict[str, Any]],
    primary_earned_income: float,
    spouse_earned_income: float,
    earned_income_multiplier: float,
    active_tax_state_override: Optional[str],
    active_state_tax_delta_rate: float,
    mortgage_annual_service: float,
    is_working: bool,
    age_primary: int,
    context: Any,
    family_id: int,
    owned_shares_count: float = 0.0,
    user_state: str = "WA",
    filing_status: str = "MFJ",
) -> Tuple[float, float, float, float, float, float, float, List[str], float, float, Optional[str], float, float]:
    """Iterates through all scenario events active in the given year and adjusts balances."""
    yearly_event_inflow = 0.0
    yearly_event_outflow = 0.0
    events_occurred: List[str] = []

    for ev in events:
        ev_start = ev.get("year", 2026)
        ev_end = ev.get("end_year", ev_start)
        cat = ev.get("category", "")
        name = ev.get("name", "")
        is_arm_reset = (cat == "refinance" and ev.get("refinance_type") == "arm" and year == ev_start + ev.get("arm_fixed_years", 7))
        is_re_ongoing = (cat == "real_estate" and ev.get("re_action", "buy") not in ("sell", "downsize") and year >= ev_start)
        pe_harvest_yr = int(ev.get("harvest_year") or ev.get("distribution_start_year") or (ev_end + 4))
        is_pe_harvest = (cat in ("pe_capital_call", "capital_call", "j_curve") and year == pe_harvest_yr and ev.get("include_harvest", True))
        ltc_ben_start = int(ev.get("benefit_start_year") or (ev_start + 15))
        ltc_pool_yrs = int(ev.get("benefit_pool_years") or 4)
        ltc_ben_end = int(ev.get("benefit_end_year") or (ltc_ben_start + max(1, ltc_pool_yrs) - 1))
        is_ltc_benefit = (cat == "ltc_insurance" and ltc_ben_start <= year <= ltc_ben_end)

        if not ((ev_start <= year <= ev_end) or is_arm_reset or is_re_ongoing or is_pe_harvest or is_ltc_benefit):
            continue

        # 1. Company Option Repurchase / Exercise (Single-Year or Multi-Year Staged)
        if cat in ("company_equity", "equity") and ev_start <= year <= ev_end:
            liquid_bal, yearly_event_inflow, yearly_event_outflow, owned_shares_count = process_company_equity_event(
                ev=ev, share_price=share_price, options_pools=options_pools,
                primary_earned_income=primary_earned_income, spouse_earned_income=spouse_earned_income,
                liquid_bal=liquid_bal, yearly_event_inflow=yearly_event_inflow,
                events_occurred=events_occurred, year=year, ev_start=ev_start, ev_end=ev_end,
                owned_shares_count=owned_shares_count, yearly_event_outflow=yearly_event_outflow,
                effective_user_state=(active_tax_state_override or user_state), filing_status=filing_status,
            )

        # 2. Real Estate / Home Sales / Renovations / Debt Payoff
        elif cat in ("real_estate", "home_sale", "home_renovation", "debt_payoff"):
            liquid_bal, re_bal, mortgage_bal, yearly_event_inflow, yearly_event_outflow = process_real_estate_event(
                ev=ev, year=year, ev_start=ev_start, cat=cat, name=name,
                liquid_bal=liquid_bal, re_bal=re_bal, mortgage_bal=mortgage_bal,
                yearly_event_inflow=yearly_event_inflow, yearly_event_outflow=yearly_event_outflow,
                events_occurred=events_occurred,
            )

        # 2c. Career Sabbatical / Income Change / Consulting Pivot
        elif cat in ("sabbatical", "income_change"):
            inc_mode = ev.get("income_mode") or ev.get("sabbatical_mode") or "sabbatical"
            if inc_mode in ("sabbatical", "pause", "part_time", "coast"):
                raw_mult = ev.get("income_multiplier_pct") if ev.get("income_multiplier_pct") is not None else ev.get("income_multiplier")
                mult = float(raw_mult if raw_mult is not None else 0.0)
                if mult > 1.0:
                    mult = mult / 100.0
                earned_income_multiplier = min(earned_income_multiplier, max(0.0, mult))
                extra_amt = float(ev.get("annual_amount") or ev.get("amount") or 0.0)
                if extra_amt > 0:
                    if ev.get("is_outflow", True):
                        yearly_event_outflow += extra_amt
                        liquid_bal = max(0.0, liquid_bal - extra_amt)
                        events_occurred.append(f"{name}: Income at {int(mult*100)}%, -${extra_amt/1e3:.0f}k/yr sabbatical spend")
                    else:
                        yearly_event_inflow += extra_amt
                        liquid_bal += extra_amt
                        events_occurred.append(f"{name}: Income at {int(mult*100)}%, +${extra_amt/1e3:.0f}k/yr consulting/side income")
                else:
                    events_occurred.append(f"{name}: Earned income scaled to {int(mult*100)}%")
            else:
                amt = float(ev.get("annual_amount") or ev.get("amount") or 0.0)
                yearly_event_inflow += amt
                liquid_bal += amt
                events_occurred.append(f"{name}: +${amt/1e3:.0f}k/yr income")

        # 3b. Mortgage Refinance (Initial Year)
        elif cat == "refinance" and year == ev_start:
            if mortgage_bal > 0:
                fees = ev.get("closing_costs", 8000.0)
                liquid_bal = max(0.0, liquid_bal - fees)
                yearly_event_outflow += fees
                new_rate = ev.get("new_interest_rate", 0.045)
                new_term = ev.get("new_term_years", 30)
                ref_type = ev.get("refinance_type", "fixed")
                arm_fixed_years = ev.get("arm_fixed_years", 7)

                r = new_rate / 12.0
                n = new_term * 12
                monthly_pmt = mortgage_bal * (r * ((1.0 + r) ** n)) / (((1.0 + r) ** n) - 1.0)
                old_service = mortgage_annual_service
                mortgage_annual_service = monthly_pmt * 12.0
                annual_savings_cf = max(0.0, old_service - mortgage_annual_service)
                if ref_type == "arm":
                    events_occurred.append(f"{name}: Refinanced to {arm_fixed_years}/1 ARM @ {new_rate*100:.2f}%, saves ${annual_savings_cf/1e3:.1f}k/yr debt service")
                else:
                    events_occurred.append(f"{name}: Refinanced to {new_rate*100:.2f}%, saves ${annual_savings_cf/1e3:.1f}k/yr debt service")

        # 3c. Mortgage Refinance ARM Rate Reset
        elif cat == "refinance" and ev.get("refinance_type") == "arm":
            arm_fixed_years = ev.get("arm_fixed_years", 7)
            if year == ev_start + arm_fixed_years and mortgage_bal > 0:
                arm_reset_rate = ev.get("arm_reset_rate", 0.055)
                new_term = ev.get("new_term_years", 30)
                rem_years = max(1, new_term - arm_fixed_years)
                r_adj = arm_reset_rate / 12.0
                n_adj = rem_years * 12
                monthly_pmt = mortgage_bal * (r_adj * ((1.0 + r_adj) ** n_adj)) / (((1.0 + r_adj) ** n_adj) - 1.0)
                old_service = mortgage_annual_service
                mortgage_annual_service = monthly_pmt * 12.0
                diff = mortgage_annual_service - old_service
                if diff >= 0:
                    events_occurred.append(f"{name}: ARM rate reset to {arm_reset_rate*100:.2f}% (+${diff/1e3:.1f}k/yr debt service)")
                else:
                    events_occurred.append(f"{name}: ARM rate reset to {arm_reset_rate*100:.2f}% (-${abs(diff)/1e3:.1f}k/yr debt service)")

        # 4. College, Graduate Education & K-12 Private School
        elif cat in ("college", "grad_school", "education"):
            liquid_bal, yearly_event_outflow = process_education_event(
                ev=ev, year=year, ev_start=ev_start, ev_end=ev_end, cat=cat, name=name,
                liquid_bal=liquid_bal, edu_reserves=edu_reserves, context=context,
                family_id=family_id, yearly_event_outflow=yearly_event_outflow,
                events_occurred=events_occurred,
            )

        # 5. Eldercare / Assisted Living
        elif cat in ("eldercare", "parent_care"):
            care_cost = ev.get("annual_care_cost", 90000.0)
            parent_offset = ev.get("parent_offset_annual", 20000.0)
            sibling_split = ev.get("sibling_split_pct", 50.0) / 100.0
            net_eldercare = max(0.0, (care_cost - parent_offset) * sibling_split)
            if net_eldercare > 0:
                yearly_event_outflow += net_eldercare
                if not is_working:
                    liquid_bal = max(0.0, liquid_bal - net_eldercare)
                events_occurred.append(f"{name}: -${net_eldercare/1e3:.0f}k/yr care support")

        # 6. Lifestyle / Travel Surge
        elif cat in ("lifestyle", "travel_surge"):
            amt = ev.get("annual_amount") or ev.get("amount") or 0.0
            if ev.get("apply_gogo_taper", False):
                if age_primary >= 78:
                    amt = 0.0
                elif age_primary >= 68:
                    amt = amt * 0.5
            if amt > 0:
                yearly_event_outflow += amt
                liquid_bal = max(0.0, liquid_bal - amt)
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: -{amt_str}/yr" if ev_end > ev_start else f"{name}: -{amt_str}")

        # 7. Family Gifting Program
        elif cat in ("gifting", "gifting_throughline"):
            amt = ev.get("annual_amount") or ev.get("amount") or 0.0
            if amt > 0:
                yearly_event_outflow += amt
                if not is_working:
                    liquid_bal = max(0.0, liquid_bal - amt)
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: -{amt_str} gifting")

        # 7b. Philanthropy / Donor-Advised Fund (DAF) Front-Load
        elif cat == "philanthropy_daf":
            amt = float(ev.get("annual_amount") or ev.get("amount") or 0.0)
            ded_rate = float(ev.get("tax_deduction_rate") if ev.get("tax_deduction_rate") is not None else 0.35)
            if ded_rate > 1.0:
                ded_rate = ded_rate / 100.0
            tax_saved = amt * ded_rate if ev.get("include_tax_offset", True) else 0.0
            net_out = max(0.0, amt - tax_saved)
            yearly_event_outflow += net_out
            liquid_bal = max(0.0, liquid_bal - net_out)
            if tax_saved > 0:
                events_occurred.append(f"{name}: -${amt/1e3:.0f}k DAF contribution (+${tax_saved/1e3:.0f}k tax deduction offset)")
            else:
                events_occurred.append(f"{name}: -${amt/1e3:.0f}k charitable contribution")

        # 7l. State Tax Domicile Relocation (Inter-State Tax Arbitrage)
        elif cat == "state_relocation":
            if year == ev_start:
                move_cost = float(ev.get("moving_cost") or ev.get("amount") or 35000.0)
                if move_cost > 0:
                    liquid_bal = max(0.0, liquid_bal - move_cost)
                    yearly_event_outflow += move_cost
                target_st = str(ev.get("target_state") or ev.get("to_state") or "WA").upper()
                origin_st = str(ev.get("origin_state") or ev.get("from_state") or "CA").upper()
                active_tax_state_override = target_st
                state_rates = {
                    "CA": 0.113, "NY": 0.0985, "NJ": 0.095, "OR": 0.09, "MA": 0.09, "MN": 0.088,
                    "CO": 0.044, "IL": 0.0495, "PA": 0.0307,
                    "WA": 0.0, "TX": 0.0, "NV": 0.0, "FL": 0.0, "WY": 0.0, "TN": 0.0, "NH": 0.0,
                }
                raw_sav = ev.get("state_tax_savings_rate") or ev.get("tax_rate_savings_pct") or ev.get("tax_savings_pct")
                raw_savings_rate = float(raw_sav if raw_sav is not None else max(0.0, state_rates.get(origin_st, 0.093) - state_rates.get(target_st, 0.0)))
                if raw_savings_rate > 1.0:
                    raw_savings_rate = raw_savings_rate / 100.0
                active_state_tax_delta_rate = raw_savings_rate
                events_occurred.append(
                    f"{name}: Relocated tax domicile {origin_st} → {target_st} (-${move_cost/1e3:.0f}k moving cost; {active_state_tax_delta_rate*100:.1f}% ongoing state tax reduction)"
                )

        # 7m. Multi-Year Roth Conversion Ladder & Rule 72(t) SEPP Pre-59½ Bridge
        elif cat == "roth_conversion":
            retire_bal, liquid_bal, yearly_event_outflow = process_roth_or_72t_event(
                ev, name, age_primary, retire_bal, liquid_bal, yearly_event_outflow, events_occurred,
                is_working=is_working, primary_earned_income=primary_earned_income,
                spouse_earned_income=spouse_earned_income, earned_income_multiplier=earned_income_multiplier,
            )

        # 7n. 529 Plan 5-Year Superfund
        elif cat == "superfund_529":
            if year == ev_start:
                contrib = float(ev.get("amount") or ev.get("annual_amount") or 190000.0)
                liquid_bal = max(0.0, liquid_bal - contrib)
                yearly_event_outflow += contrib
                if edu_reserves:
                    first_key = next(iter(edu_reserves))
                    edu_reserves[first_key]["balance"] += contrib
                else:
                    edu_reserves["superfund_529"] = {"first_name": "Beneficiary", "balance": contrib}
                events_occurred.append(f"{name}: -${contrib/1e3:.0f}k 5-year 529 superfund front-load")

        # 7o. Private Equity / Venture Capital Call Schedule (J-Curve)
        elif cat in ("pe_capital_call", "capital_call", "j_curve"):
            liquid_bal, other_bal, yearly_event_inflow, yearly_event_outflow = process_pe_capital_call_event(
                ev=ev, year=year, ev_start=ev_start, ev_end=ev_end, is_pe_harvest=is_pe_harvest,
                name=name, liquid_bal=liquid_bal, other_bal=other_bal,
                yearly_event_inflow=yearly_event_inflow, yearly_event_outflow=yearly_event_outflow,
                events_occurred=events_occurred,
            )

        # 7p. Long-Term Care (LTC) Hybrid Insurance Policy
        elif cat == "ltc_insurance":
            if ev_start <= year <= ev_end:
                prem = float(ev.get("annual_premium") or ev.get("annual_amount") or ev.get("amount") or 18000.0)
                liquid_bal = max(0.0, liquid_bal - prem)
                yearly_event_outflow += prem
                events_occurred.append(f"{name}: -${prem/1e3:.0f}k LTC hybrid policy premium")
            if is_ltc_benefit:
                benefit = float(ev.get("annual_benefit") or (float(ev.get("monthly_benefit_cap") or 10000.0) * 12.0))
                liquid_bal += benefit
                yearly_event_inflow += benefit
                events_occurred.append(f"{name}: +${benefit/1e3:.0f}k tax-free LTC benefit shield payout")

        # 7q. Marital Settlement / QDRO Asset Division & Alimony
        elif cat == "marital_settlement":
            if year == ev_start:
                raw_split = float(ev.get("asset_split_pct") if ev.get("asset_split_pct") is not None else 0.50)
                split_pct = max(0.0, min(0.95, (raw_split / 100.0) if raw_split > 1.0 else raw_split))
                legal_fee = float(ev.get("legal_fee") or ev.get("legal_settlement_cost") or 45000.0)
                liq_out, ret_out = liquid_bal * split_pct + legal_fee, retire_bal * split_pct
                liquid_bal = max(0.0, liquid_bal - liq_out)
                retire_bal = max(0.0, retire_bal - ret_out)
                yearly_event_outflow += (liq_out + ret_out)
                events_occurred.append(f"{name}: -{split_pct*100:.0f}% QDRO / marital asset division (-${(liq_out+ret_out)/1e3:.0f}k)")
            alimony = float(ev.get("annual_alimony") or ev.get("annual_support") or 0.0)
            if alimony > 0 and ev_start <= year <= ev_end:
                liquid_bal = max(0.0, liquid_bal - alimony)
                yearly_event_outflow += alimony
                events_occurred.append(f"{name}: -${alimony/1e3:.0f}k spousal support / maintenance")

        # 7r. Pre-65 Early Retirement Healthcare & ACA Subsidy Bridge
        elif cat == "pre65_healthcare":
            liquid_bal, yearly_event_outflow = process_pre65_healthcare_event(
                ev=ev, year=year, age_primary=age_primary, liquid_bal=liquid_bal,
                is_working=is_working, primary_earned_income=primary_earned_income,
                spouse_earned_income=spouse_earned_income, earned_income_multiplier=earned_income_multiplier,
                yearly_event_outflow=yearly_event_outflow, events_occurred=events_occurred, events=events,
            )

        # 8. Capital Inflows / Windfalls
        elif cat in ("capital_inflow", "custom_spike", "windfall") or (ev.get("is_outflow") is False):
            amt = ev.get("annual_amount") or ev.get("amount") or 0.0
            if amt > 0:
                yearly_event_inflow += amt
                liquid_bal += amt
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: +{amt_str}")

        # 9. Capital Outflows / Withdrawals
        elif cat in ("capital_outflow", "withdrawal") or ev.get("is_outflow", True):
            amt = ev.get("annual_amount") or ev.get("amount") or 0.0
            if amt > 0:
                yearly_event_outflow += amt
                liquid_bal = max(0.0, liquid_bal - amt)
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: -{amt_str}")

    # Inject deterministic LP commitment capital call outflows (Tier B #7)
    from forecast.orchestrator_params import get_active_scenario_run_params
    run_p = get_active_scenario_run_params()
    lp_sched = run_p.get("lp_call_schedule") if family_id > 0 and run_p.get("family_id") == family_id else None
    if lp_sched and year in lp_sched and lp_sched[year] > 0:
        lp_call = float(lp_sched[year])
        liquid_bal = max(0.0, liquid_bal - lp_call)
        other_bal += lp_call
        yearly_event_outflow += lp_call
        acc_tag = " (Accelerated 18m)" if run_p.get("accelerate_lp_calls") else ""
        events_occurred.append(f"Private LP Capital Call Schedule{acc_tag}: -${lp_call/1e3:.0f}k called into NAV")

    return (
        liquid_bal, retire_bal, re_bal, mortgage_bal, other_bal,
        yearly_event_inflow, yearly_event_outflow, events_occurred,
        earned_income_multiplier, mortgage_annual_service,
        active_tax_state_override, active_state_tax_delta_rate,
        owned_shares_count,
    )
