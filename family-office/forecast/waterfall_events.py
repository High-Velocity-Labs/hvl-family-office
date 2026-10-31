"""
forecast/waterfall_events.py: Annual lifecycle event evaluator for scenario simulations.
Processes multi-asset equity liquidations, sabbaticals, debt refinance, gifting,
private equity J-curves, long-term care, and state relocations.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple

from forecast import event_amounts
from services import statutory_limits
from forecast.capital_market_assumptions import DEFAULT_EDUCATION_INFLATION_RATE
from forecast.charitable_limits import CASH, CharitableGivingState, agi_proxy, apply_agi_limits
from forecast.investment_income import DEFAULT_TAXABLE_YIELD_RATE
from forecast.mortgage_amortization import BaselineLoan
from forecast.scenarios import process_pre65_healthcare_event, process_roth_or_72t_event
from forecast.waterfall_equity import (
    STATE_INCOME_TAX_RATES,
    process_company_equity_event,
    process_pe_capital_call_event,
)
from forecast.waterfall_withdrawals import process_education_event, process_real_estate_event

_STATE_NAME_MAP: Dict[str, str] = {
    "nevada": "NV", "texas": "TX", "florida": "FL", "wyoming": "WY", "tennessee": "TN",
    "new hampshire": "NH", "south dakota": "SD", "alaska": "AK", "washington": "WA",
    "california": "CA", "oregon": "OR", "idaho": "ID", "new york": "NY", "new jersey": "NJ",
    "massachusetts": "MA", "colorado": "CO", "arizona": "AZ", "utah": "UT", "hawaii": "HI",
}


def default_move_destination(origin_state: str) -> str:
    """A zero-income-tax destination for a relocation that names none (never the household's own state)."""
    return next(code for code in ("NV", "TX", "FL") if code != origin_state)


def superfund_limit(year: int, context: Any) -> float:
    """The 5-year 529 front-load an event without an amount contributes: the gift-tax limit per donor, per adult."""
    adults = 2 if getattr(context, "has_spouse", False) else 1
    return adults * statutory_limits.section_529_superfund_limit(year)


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
    user_state: str = "",
    filing_status: str = "MFJ",
    lp_call_schedule: Optional[Dict[int, float]] = None,
    accelerate_lp_calls: bool = False,
    price_index: float = 1.0,
    inflation_rate: float = 0.0,
    start_year: Optional[int] = None,
    education_inflation_rate: float = DEFAULT_EDUCATION_INFLATION_RATE,
    baseline_loan: Optional[BaselineLoan] = None,
    charity: Optional[CharitableGivingState] = None,
    prior_year_taxable_withdrawals: float = 0.0,
    primary_active: Optional[bool] = None,
    spouse_active: Optional[bool] = None,
    seniors_65_plus: int = 0,
    current_year_taxable_income: float = 0.0,
    taxable_yield_rate: float = DEFAULT_TAXABLE_YIELD_RATE,
) -> Tuple[float, float, float, float, float, float, float, List[str], float, float, Optional[str], float, float]:
    """
    Iterates through all scenario events active in the given year and adjusts balances.
    `baseline_loan` (the starting mortgage) takes the rate and balance of a refinance. `charity` carries DAF gifts
    over the AGI caps to later years and is updated in place; the year's AGI is estimated from the earning adults
    (`primary_active`/`spouse_active`, default `is_working`), `taxable_yield_rate` on the liquid balance (the
    household's actual investment income over its balance when known), this year's known taxable income
    `current_year_taxable_income` (pension), and last year's `prior_year_taxable_withdrawals` (this year's draw
    depends on the gifts, so it cannot be used without a cycle). `seniors_65_plus` feeds the equity tax calls and
    `taxable_yield_rate` the ACA MAGI and the Roth bracket fill.
    """
    yearly_event_inflow = 0.0
    daf_cash = daf_property = 0.0
    yearly_event_outflow = 0.0
    events_occurred: List[str] = []
    indexer = event_amounts.EventIndexer(
        start_year=start_year if start_year is not None else year,
        inflation_rate=inflation_rate, education_inflation_rate=education_inflation_rate,
    )

    def amount_of(ev: Dict[str, Any], raw: float) -> float:
        return event_amounts.scale_event_amount(ev, raw, year, indexer)

    ordered_events = sorted(events, key=lambda e: 0 if e.get("category") == "state_relocation" else 1)
    for ev in ordered_events:
        ev_start = ev.get("year", start_year if start_year is not None else year)
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
                options_aliases=getattr(context, "options_aliases", None),
                price_index=price_index, inflation_rate=inflation_rate, seniors_65_plus=seniors_65_plus,
            )

        # 2. Real Estate / Home Sales / Renovations / Debt Payoff
        elif cat in ("real_estate", "home_sale", "home_renovation", "debt_payoff"):
            liquid_bal, re_bal, mortgage_bal, yearly_event_inflow, yearly_event_outflow = process_real_estate_event(
                ev=ev, year=year, ev_start=ev_start, cat=cat, name=name,
                liquid_bal=liquid_bal, re_bal=re_bal, mortgage_bal=mortgage_bal,
                yearly_event_inflow=yearly_event_inflow, yearly_event_outflow=yearly_event_outflow,
                events_occurred=events_occurred, indexer=indexer,
            )
            if cat == "real_estate" and year == ev_start and ev.get("re_action") == "buy_primary":
                # The prior loan was paid off; the new loan's service is charged by the purchase event itself.
                mortgage_annual_service = 0.0
                if baseline_loan is not None:
                    baseline_loan.balance = 0.0

        # 2c. Career Sabbatical / Income Change / Consulting Pivot
        elif cat in ("sabbatical", "income_change"):
            inc_mode = ev.get("income_mode") or ev.get("sabbatical_mode") or "sabbatical"
            if inc_mode in ("sabbatical", "pause", "part_time", "coast"):
                raw_mult = ev.get("income_multiplier_pct") if ev.get("income_multiplier_pct") is not None else ev.get("income_multiplier")
                mult = float(raw_mult if raw_mult is not None else 0.0)
                if mult > 1.0:
                    mult = mult / 100.0
                earned_income_multiplier = min(earned_income_multiplier, max(0.0, mult))
                extra_amt = amount_of(ev, float(ev.get("annual_amount") or ev.get("amount") or 0.0))
                if extra_amt > 0:
                    if ev.get("is_outflow", True):
                        yearly_event_outflow += extra_amt
                        liquid_bal -= extra_amt
                        events_occurred.append(f"{name}: Income at {int(mult*100)}%, -${extra_amt/1e3:.0f}k/yr sabbatical spend")
                    else:
                        yearly_event_inflow += extra_amt
                        liquid_bal += extra_amt
                        events_occurred.append(f"{name}: Income at {int(mult*100)}%, +${extra_amt/1e3:.0f}k/yr consulting/side income")
                else:
                    events_occurred.append(f"{name}: Earned income scaled to {int(mult*100)}%")
            else:
                amt = amount_of(ev, float(ev.get("annual_amount") or ev.get("amount") or 0.0))
                yearly_event_inflow += amt
                liquid_bal += amt
                events_occurred.append(f"{name}: +${amt/1e3:.0f}k/yr income")

        # 3b. Mortgage Refinance (Initial Year)
        elif cat == "refinance" and year == ev_start:
            if mortgage_bal > 0:
                fees = amount_of(ev, ev.get("closing_costs", 8000.0))
                liquid_bal -= fees
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
                if baseline_loan is not None:
                    baseline_loan.balance, baseline_loan.annual_rate = mortgage_bal, new_rate
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
                if baseline_loan is not None:
                    baseline_loan.balance, baseline_loan.annual_rate = mortgage_bal, arm_reset_rate
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
                events_occurred=events_occurred, indexer=indexer,
            )

        # 5. Eldercare / Assisted Living
        elif cat in ("eldercare", "parent_care"):
            care_cost = amount_of(ev, ev.get("annual_care_cost", 90000.0))
            parent_offset = amount_of(ev, ev.get("parent_offset_annual", 20000.0))
            sibling_split = ev.get("sibling_split_pct", 50.0) / 100.0
            net_eldercare = max(0.0, (care_cost - parent_offset) * sibling_split)
            if net_eldercare > 0:
                yearly_event_outflow += net_eldercare
                liquid_bal -= net_eldercare
                events_occurred.append(f"{name}: -${net_eldercare/1e3:.0f}k/yr care support")

        # 6. Lifestyle / Travel Surge
        elif cat in ("lifestyle", "travel_surge"):
            amt = amount_of(ev, ev.get("annual_amount") or ev.get("amount") or 0.0)
            if ev.get("apply_gogo_taper", False):
                if age_primary >= 78:
                    amt = 0.0
                elif age_primary >= 68:
                    amt = amt * 0.5
            if amt > 0:
                yearly_event_outflow += amt
                liquid_bal -= amt
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: -{amt_str}/yr" if ev_end > ev_start else f"{name}: -{amt_str}")

        # 7. Family Gifting Program
        elif cat in ("gifting", "gifting_throughline"):
            amt = amount_of(ev, ev.get("annual_amount") or ev.get("amount") or 0.0)
            if amt > 0:
                yearly_event_outflow += amt
                liquid_bal -= amt
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: -{amt_str} gifting")

        # 7b. Philanthropy / Donor-Advised Fund (DAF) Front-Load
        elif cat == "philanthropy_daf":
            amt = amount_of(ev, float(ev.get("annual_amount") or ev.get("amount") or 0.0))
            yearly_event_outflow += amt
            liquid_bal -= amt
            if ev.get("include_tax_offset", True):
                # The deduction is settled once per year below, against the AGI caps and carryforwards.
                if ev.get("asset_type") == CASH:
                    daf_cash += amt
                else:
                    daf_property += amt
                if charity is not None:
                    ded_rate = float(ev.get("tax_deduction_rate") if ev.get("tax_deduction_rate") is not None else 0.35)
                    charity.deduction_rate = ded_rate / 100.0 if ded_rate > 1.0 else ded_rate
            kind = "DAF" if ev.get("include_tax_offset", True) else "charitable"
            events_occurred.append(f"{name}: -${amt/1e3:.0f}k {kind} contribution")

        # 7l. State Tax Domicile Relocation (Inter-State Tax Arbitrage)
        elif cat == "state_relocation":
            if year == ev_start:
                move_cost = amount_of(ev, float(ev.get("moving_cost") if ev.get("moving_cost") is not None else (ev.get("amount") if ev.get("amount") is not None else 35000.0)))
                if move_cost > 0:
                    liquid_bal -= move_cost
                    yearly_event_outflow += move_cost
                raw_origin = str(ev.get("origin_state") or ev.get("from_state") or "").strip().upper()
                raw_target = str(ev.get("target_state") or ev.get("to_state") or "").strip().upper()
                text_low = f"{name} {ev.get('description', '')}".lower()
                parsed_st = next((code for s_name, code in _STATE_NAME_MAP.items() if s_name in text_low and code != (user_state or "").upper()), None)
                origin_st = raw_origin or (user_state or "").upper()
                target_st = raw_target or parsed_st or default_move_destination(origin_st)
                if origin_st == target_st and parsed_st:
                    target_st = parsed_st
                active_tax_state_override = target_st
                rate_diff = STATE_INCOME_TAX_RATES.get(origin_st, 0.0) - STATE_INCOME_TAX_RATES.get(target_st, 0.0)
                raw_sav = ev.get("state_tax_savings_rate") if ev.get("state_tax_savings_rate") is not None else (ev.get("tax_rate_savings_pct") if ev.get("tax_rate_savings_pct") is not None else ev.get("tax_savings_pct"))
                if origin_st == "WA":
                    active_state_tax_delta_rate = rate_diff
                elif raw_sav is not None:
                    sav_val = float(raw_sav)
                    active_state_tax_delta_rate = (sav_val / 100.0) if sav_val > 1.0 else sav_val
                else:
                    active_state_tax_delta_rate = rate_diff
                events_occurred.append(
                    f"{name}: Relocated tax domicile {origin_st} → {target_st} (-${move_cost/1e3:.0f}k moving cost; {active_state_tax_delta_rate*100:.1f}% ongoing state tax reduction)"
                )

        # 7m. Multi-Year Roth Conversion Ladder & Rule 72(t) SEPP Pre-59½ Bridge
        elif cat == "roth_conversion":
            retire_bal, liquid_bal, yearly_event_outflow = process_roth_or_72t_event(
                ev, name, age_primary, retire_bal, liquid_bal, yearly_event_outflow, events_occurred,
                is_working=is_working, primary_earned_income=primary_earned_income,
                spouse_earned_income=spouse_earned_income, earned_income_multiplier=earned_income_multiplier,
                year=year, price_index=price_index, inflation_rate=inflation_rate, indexer=indexer,
                taxable_yield_rate=taxable_yield_rate, other_taxable_income=current_year_taxable_income,
            )

        # 7n. 529 Plan 5-Year Superfund
        elif cat == "superfund_529":
            if year == ev_start:
                entered = float(ev.get("amount") or ev.get("annual_amount") or superfund_limit(year, context))
                contrib = amount_of(ev, entered)
                liquid_bal -= contrib
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
                events_occurred=events_occurred, indexer=indexer,
            )

        # 7p. Long-Term Care (LTC) Hybrid Insurance Policy
        elif cat == "ltc_insurance":
            if ev_start <= year <= ev_end:
                entered = float(ev.get("annual_premium") or ev.get("annual_amount") or ev.get("amount") or 0.0)
                prem = amount_of(ev, entered)
                liquid_bal -= prem
                yearly_event_outflow += prem
                events_occurred.append(f"{name}: -${prem/1e3:.0f}k LTC hybrid policy premium")
            if is_ltc_benefit:
                benefit = amount_of(ev, float(ev.get("annual_benefit") or (float(ev.get("monthly_benefit_cap") or 10000.0) * 12.0)))
                liquid_bal += benefit
                yearly_event_inflow += benefit
                events_occurred.append(f"{name}: +${benefit/1e3:.0f}k tax-free LTC benefit shield payout")

        # 7q. Marital Settlement / QDRO Asset Division & Alimony
        elif cat == "marital_settlement":
            if year == ev_start:
                raw_split = float(ev.get("asset_split_pct") if ev.get("asset_split_pct") is not None else 0.50)
                split_pct = max(0.0, min(0.95, (raw_split / 100.0) if raw_split > 1.0 else raw_split))
                legal_fee = amount_of(ev, float(ev.get("legal_fee") or ev.get("legal_settlement_cost") or 45000.0))
                liq_out, ret_out = max(0.0, liquid_bal) * split_pct + legal_fee, retire_bal * split_pct
                liquid_bal -= liq_out
                retire_bal = max(0.0, retire_bal - ret_out)
                yearly_event_outflow += (liq_out + ret_out)
                events_occurred.append(f"{name}: -{split_pct*100:.0f}% QDRO / marital asset division (-${(liq_out+ret_out)/1e3:.0f}k)")
            alimony = amount_of(ev, float(ev.get("annual_alimony") or ev.get("annual_support") or 0.0))
            if alimony > 0 and ev_start <= year <= ev_end:
                liquid_bal -= alimony
                yearly_event_outflow += alimony
                events_occurred.append(f"{name}: -${alimony/1e3:.0f}k spousal support / maintenance")

        # 7r. Pre-65 Early Retirement Healthcare & ACA Subsidy Bridge
        elif cat == "pre65_healthcare":
            liquid_bal, yearly_event_outflow = process_pre65_healthcare_event(
                ev=ev, year=year, age_primary=age_primary, liquid_bal=liquid_bal,
                is_working=is_working, primary_earned_income=primary_earned_income,
                spouse_earned_income=spouse_earned_income, earned_income_multiplier=earned_income_multiplier,
                yearly_event_outflow=yearly_event_outflow, events_occurred=events_occurred, events=events,
                price_index=price_index, inflation_rate=inflation_rate, indexer=indexer,
                roster=context.roster, taxable_yield_rate=taxable_yield_rate,
                other_taxable_income=current_year_taxable_income,
            )

        # 8. Capital Inflows / Windfalls
        elif cat in ("capital_inflow", "custom_spike", "windfall") or (ev.get("is_outflow") is False):
            amt = amount_of(ev, ev.get("annual_amount") or ev.get("amount") or 0.0)
            if amt > 0:
                yearly_event_inflow += amt
                liquid_bal += amt
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: +{amt_str}")

        # 9. Capital Outflows / Withdrawals
        elif cat in ("capital_outflow", "withdrawal") or ev.get("is_outflow", True):
            amt = amount_of(ev, ev.get("annual_amount") or ev.get("amount") or 0.0)
            if amt > 0:
                yearly_event_outflow += amt
                liquid_bal -= amt
                amt_str = f"${amt/1e6:.2f}M".rstrip('0').rstrip('.') if amt >= 1_000_000 else f"${amt/1e3:.0f}k"
                events_occurred.append(f"{name}: -{amt_str}")

    if charity is not None and (daf_cash + daf_property > 0 or charity.carryforwards):
        earning = [primary_active if primary_active is not None else is_working,
                   spouse_active if spouse_active is not None else is_working]
        earned = sum(inc for inc, on in zip((primary_earned_income, spouse_earned_income), earning) if on)
        agi = agi_proxy(
            earned * earned_income_multiplier * price_index, liquid_bal, prior_year_taxable_withdrawals,
            current_year_taxable_income, taxable_yield_rate,
        )
        deductible, charity.carryforwards = apply_agi_limits(agi, daf_cash, daf_property, year, charity.carryforwards)
        tax_saved = deductible * charity.deduction_rate
        if tax_saved > 0:
            # The saving nets against the year's gifts; a carryforward deducted in a year without gifts is an inflow.
            offset = min(tax_saved, daf_cash + daf_property)
            yearly_event_outflow -= offset
            yearly_event_inflow += tax_saved - offset
            liquid_bal += tax_saved
            events_occurred.append(
                f"Charitable gifts: +${tax_saved/1e3:.0f}k tax deduction offset "
                f"(${deductible/1e3:.0f}k deductible within the AGI limits)"
            )

    # Inject deterministic LP commitment capital call outflows (Tier B #7)
    if lp_call_schedule and lp_call_schedule.get(year, 0.0) > 0:
        lp_call = float(lp_call_schedule[year])
        liquid_bal -= lp_call
        other_bal += lp_call
        yearly_event_outflow += lp_call
        acc_tag = " (Accelerated 18m)" if accelerate_lp_calls else ""
        events_occurred.append(f"Private LP Capital Call Schedule{acc_tag}: -${lp_call/1e3:.0f}k called into NAV")

    return (
        liquid_bal, retire_bal, re_bal, mortgage_bal, other_bal,
        yearly_event_inflow, yearly_event_outflow, events_occurred,
        earned_income_multiplier, mortgage_annual_service,
        active_tax_state_override, active_state_tax_delta_rate,
        owned_shares_count,
    )
