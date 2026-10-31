"""
forecast/waterfall_withdrawals.py: Modular calculation helpers for scenario cash flow simulation.
Covers debt service amortization, Social Security adjustments, education/529 drawdown,
real estate transactions, and dynamic equity liquidity fallbacks.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple

from services import statutory_limits, tax_engine
from forecast import event_amounts
from forecast.benefit_constants import SS_SPOUSAL_SHARE_OF_PIA
from forecast.mortgage_amortization import (
    DEFAULT_BASELINE_MORTGAGE_RATE,
    DEFAULT_BASELINE_MORTGAGE_TERM_YEARS,
    BaselineLoan,
    monthly_payment,
    principal_paid_in_year,
    balance_after,
)
from forecast.event_amounts import EventIndexer
from forecast.storage import get_child_ledger_expense_for_year, child_has_tuition_ledger
from forecast.waterfall_equity import (
    normalize_equity_action,
    tap_company_equity_liquidity,
    process_company_equity_event,
    compute_company_equity_valuation,
)


def compute_initial_mortgage_service(
    mortgage_bal: float, annual_rate: float = DEFAULT_BASELINE_MORTGAGE_RATE,
    term_years: float = DEFAULT_BASELINE_MORTGAGE_TERM_YEARS,
) -> float:
    """Annual level debt service on the starting balance over its remaining term at its rate."""
    return BaselineLoan(mortgage_bal, annual_rate, term_years).level_annual_service()


def _ss_factor(age: int) -> float:
    """SSA reduction for FRA=67: 5/9 of 1%/mo for first 36 mo, 5/12 of 1%/mo beyond 36 mo, +8%/yr after 67."""
    if age < 67:
        months_early = (67 - age) * 12
        early_36, extra_months = min(36, months_early), max(0, months_early - 36)
        reduction = (early_36 * (5.0 / 900.0)) + (extra_months * (5.0 / 1200.0))
        return round(1.0 - reduction, 6)
    return round(1.0 + (age - 67) * 0.08, 6) if age > 67 else 1.0


def _ss_spousal_factor(age: int) -> float:
    """SSA spousal benefit reduction for FRA=67: 25/36 of 1%/mo for first 36 mo, 5/12 of 1%/mo beyond 36 mo; capped at 1.0 at FRA 67."""
    if age < 67:
        m = (67 - age) * 12
        return round(1.0 - (min(36, m) * (25.0 / 3600.0) + max(0, m - 36) * (5.0 / 1200.0)), 6)
    return 1.0


def compute_social_security(
    age_primary: int,
    age_spouse: int,
    has_spouse: bool,
    primary_ss_claim_age: int,
    spouse_ss_claim_age: int,
    *,
    primary_pia: float,
    spouse_pia: float,
) -> Tuple[float, float, float]:
    """
    Age-adjusted annual Social Security (today's dollars) from each person's own annual PIA.
    The spouse receives their own reduced or delayed benefit plus the excess spousal benefit (50% of the
    primary's PIA over their own PIA, reduced for claiming before 67), which starts only once the primary claims.
    """
    claim_pri, claim_spouse = max(62, min(70, primary_ss_claim_age)), max(62, min(70, spouse_ss_claim_age))
    pri_claiming = age_primary >= claim_pri
    ss_primary = primary_pia * _ss_factor(claim_pri) if pri_claiming else 0.0
    ss_spouse = 0.0
    if has_spouse and age_spouse >= claim_spouse:
        ss_spouse = spouse_pia * _ss_factor(claim_spouse)
        if pri_claiming:
            excess = max(0.0, SS_SPOUSAL_SHARE_OF_PIA * primary_pia - spouse_pia)
            ss_spouse += excess * _ss_spousal_factor(claim_spouse)
    return ss_primary, ss_spouse, ss_primary + ss_spouse


def process_education_event(
    ev: Dict[str, Any],
    year: int,
    ev_start: int,
    ev_end: int,
    cat: str,
    name: str,
    liquid_bal: float,
    edu_reserves: Dict[str, Dict[str, Any]],
    context: Any,
    family_id: int,
    yearly_event_outflow: float,
    events_occurred: List[str],
    indexer: EventIndexer,
) -> Tuple[float, float]:
    """Handles higher education (college/grad school) and K-12 tuition plans with 529 draws."""
    if cat in ("college", "grad_school") or (cat == "education" and ev.get("use_529_reserves")):
        is_synced = bool(ev.get("sync_with_ledger"))
        cid = ev.get("child_user_id")
        cost = None
        if is_synced and cid:
            try: cid_int = int(cid)
            except (ValueError, TypeError): cid_int = None
            if cid_int is not None and (context.tuition_ledger_loaded or context.tuition_ledger):
                cost = context.tuition_ledger.get(cid_int, {}).get(year)
            else:
                cost = get_child_ledger_expense_for_year(family_id=family_id, child_user_id=cid, year=year)
        if cost is None:
            cost = event_amounts.scale_event_amount(ev, ev.get("override_annual_amount") or ev.get("annual_amount") or ev.get("amount", 85000.0), year, indexer)

        tot_yrs = max(1, (ev_end - ev_start) + 1)
        yr_num = min(tot_yrs, max(1, (year - ev_start) + 1))
        use_529 = ev.get("use_529_reserves", True)

        matched_res = None
        cid_req = str(ev.get("child_user_id")) if ev.get("child_user_id") is not None else None
        if cid_req and cid_req in edu_reserves:
            matched_res = edu_reserves[cid_req]
        else:
            for r in edu_reserves.values():
                if r["first_name"].lower() in name.lower() or r["first_name"].lower() in ev.get("id", "").lower():
                    matched_res = r
                    break
        if not matched_res and edu_reserves:
            matched_res = max(edu_reserves.values(), key=lambda r: r["balance"], default=None)

        if use_529 and matched_res:
            res_bal = matched_res["balance"]
            if res_bal >= cost:
                matched_res["balance"] -= cost
                events_occurred.append(f"{name} (Yr {yr_num}/{tot_yrs}): -${cost/1e3:.0f}k (100% funded by 529, ~${matched_res['balance']/1e3:.0f}k remaining)")
            elif res_bal > 0:
                covered = res_bal
                shortfall = cost - covered
                matched_res["balance"] = 0.0
                liquid_bal -= shortfall
                yearly_event_outflow += shortfall
                events_occurred.append(f"{name} (Yr {yr_num}/{tot_yrs}): -${cost/1e3:.0f}k (${covered/1e3:.0f}k from 529, -${shortfall/1e3:.0f}k drawn from liquid accounts)")
            else:
                liquid_bal -= cost
                yearly_event_outflow += cost
                events_occurred.append(f"{name} (Yr {yr_num}/{tot_yrs}): -${cost/1e3:.0f}k (529 exhausted: -${cost/1e3:.0f}k drawn from liquid accounts)")
        else:
            liquid_bal -= cost
            yearly_event_outflow += cost
            events_occurred.append(f"{name} (Yr {yr_num}/{tot_yrs}): -${cost/1e3:.0f}k (Drawn from liquid accounts)")

    elif cat == "education":
        is_synced = bool(ev.get("sync_with_ledger", ev.get("id", "").startswith("evt_k12_")))
        cid, cost = ev.get("child_user_id"), None
        if is_synced and cid:
            try: cid_int = int(cid)
            except (ValueError, TypeError): cid_int = None
            if cid_int is not None and (context.tuition_ledger_loaded or context.tuition_ledger):
                cost = context.tuition_ledger[cid_int].get(year, 0.0) if cid_int in context.tuition_ledger else None
            else:
                cost = (get_child_ledger_expense_for_year(family_id=family_id, child_user_id=cid, year=year) or 0.0) if child_has_tuition_ledger(family_id=family_id, child_user_id=cid) else None
        if cost is None:
            entered = ev.get("override_annual_amount") or ev.get("annual_amount") or ev.get("amount") or 0.0
            if not entered and not is_synced:
                entered = (ev.get("child1_annual", 0.0) if year <= ev.get("child1_end_year", 2030) else 0.0) + (ev.get("child2_annual", 0.0) if year <= ev.get("child2_end_year", 2030) else 0.0)
            cost = event_amounts.scale_event_amount(ev, entered, year, indexer)

        if cost > 0:
            use_529_k12 = ev.get("use_529_k12_election", True)
            k12_529_drawn = 0.0
            if use_529_k12:
                cid_req = str(ev.get("child_user_id")) if ev.get("child_user_id") is not None else None
                matched_res = None
                if cid_req and cid_req in edu_reserves:
                    matched_res = edu_reserves[cid_req]
                else:
                    for r in edu_reserves.values():
                        if r["first_name"].lower() in name.lower() or r["first_name"].lower() in ev.get("id", "").lower():
                            matched_res = r
                            break
                if matched_res and matched_res["balance"] > 0:
                    k12_cap = statutory_limits.k12_529_limit(year)
                    k12_529_drawn = min(k12_cap, min(cost, matched_res["balance"]))
                    matched_res["balance"] -= k12_529_drawn

            outflow = max(0.0, cost - k12_529_drawn)
            if outflow > 0:
                yearly_event_outflow += outflow
                liquid_bal -= outflow

            if k12_529_drawn > 0:
                events_occurred.append(f"{name}: -${cost/1e3:.1f}k/yr (${k12_529_drawn/1e3:.0f}k from 529 K-12, -${outflow/1e3:.1f}k cash flow)")
            else:
                events_occurred.append(f"{name}: -${cost/1e3:.1f}k/yr")

    return liquid_bal, yearly_event_outflow


def process_real_estate_event(
    ev: Dict[str, Any],
    year: int,
    ev_start: int,
    cat: str,
    name: str,
    liquid_bal: float,
    re_bal: float,
    mortgage_bal: float,
    yearly_event_inflow: float,
    yearly_event_outflow: float,
    events_occurred: List[str],
    indexer: EventIndexer,
) -> Tuple[float, float, float, float, float]:
    """Handles real estate purchase, sale, ongoing carry, remodel, and debt payoffs."""
    if cat in ("real_estate", "home_sale") and year == ev_start:
        re_action = ev.get("re_action", "buy")
        if re_action in ("sell", "downsize") or cat == "home_sale":
            sale_price = event_amounts.scale_event_amount(ev, float(ev.get("sale_price") or ev.get("sale_proceeds") or ev.get("net_proceeds") or ev.get("purchase_price") or ev.get("amount") or 0.0), year, indexer)
            selling_cost_pct = float(ev.get("selling_cost_pct") if ev.get("selling_cost_pct") is not None else (0.0 if ev.get("net_proceeds") else 0.06))
            if selling_cost_pct > 1.0:
                selling_cost_pct = selling_cost_pct / 100.0
            selling_friction = sale_price * selling_cost_pct
            payoff = min(mortgage_bal, float(ev.get("mortgage_payoff_amount") if ev.get("mortgage_payoff_amount") is not None else (0.0 if ev.get("net_proceeds") else mortgage_bal)))
            replacement_price = event_amounts.scale_event_amount(ev, float(ev.get("replacement_price") or 0.0), year, indexer)
            net_proceeds = max(0.0, sale_price - selling_friction - payoff - replacement_price)
            liquid_bal += net_proceeds
            re_bal = max(0.0, re_bal - sale_price + replacement_price)
            mortgage_bal = max(0.0, mortgage_bal - payoff)
            yearly_event_inflow += net_proceeds
            events_occurred.append(f"{name}: +${net_proceeds/1e6:.2f}M net proceeds (${sale_price/1e6:.2f}M sale, -${payoff/1e6:.2f}M mortgage payoff)")
        else:
            if re_action == "buy_primary":
                # The new primary residence replaces the old one: sell it and retire its mortgage from the proceeds.
                # The model tracks one real-estate pool, so unless the event states `replaced_home_value`
                # the existing pool is the home being sold.
                old_value = re_bal
                if ev.get("replaced_home_value") is not None:
                    old_value = event_amounts.scale_event_amount(ev, float(ev["replaced_home_value"]), year, indexer)
                old_value = min(re_bal, max(0.0, old_value))
                cost_pct = float(ev.get("selling_cost_pct") if ev.get("selling_cost_pct") is not None else 0.06)
                cost_pct = cost_pct / 100.0 if cost_pct > 1.0 else cost_pct
                old_net = old_value * (1.0 - cost_pct) - mortgage_bal
                liquid_bal += old_net
                re_bal -= old_value
                mortgage_bal = 0.0
                if old_net >= 0:
                    yearly_event_inflow += old_net
                else:
                    yearly_event_outflow += -old_net
                sign = "+" if old_net >= 0 else "-"
                events_occurred.append(
                    f"{name}: sold prior residence (${old_value/1e6:.2f}M), old mortgage paid off, "
                    f"{sign}${abs(old_net)/1e6:.2f}M net"
                )
            price = event_amounts.scale_event_amount(ev, float(ev.get("purchase_price") or ev.get("amount") or 0.0), year, indexer)
            mort_term = ev.get("mortgage_term", "30_fixed")
            down_pct = 1.0 if mort_term == "all_cash" else float(ev.get("down_payment_pct") if ev.get("down_payment_pct") is not None else 0.20)
            down_pmt = price * down_pct
            closing_friction = price * 0.02
            new_loan = max(0.0, price - down_pmt)

            liquid_bal -= (down_pmt + closing_friction)
            re_bal += price
            mortgage_bal += new_loan
            yearly_event_outflow += (down_pmt + closing_friction)
            events_occurred.append(f"{name}: -${(down_pmt + closing_friction)/1e6:.2f}M cash outlay, +${price/1e6:.2f}M property")

    elif cat == "real_estate" and ev.get("re_action", "buy") not in ("sell", "downsize") and year > ev_start:
        entered_price = float(ev.get("purchase_price") or ev.get("amount") or 0.0)
        # The loan was fixed at purchase, so it is sized from the price in the purchase year.
        price = event_amounts.scale_event_amount(ev, entered_price, ev_start, indexer)
        mort_term = ev.get("mortgage_term", "30_fixed")
        down_pct = 1.0 if mort_term == "all_cash" else float(ev.get("down_payment_pct") if ev.get("down_payment_pct") is not None else 0.20)
        new_loan = max(0.0, price * (1.0 - down_pct))
        entered_carry = float(ev.get("annual_ongoing_carrying_cost") or (max(20000.0, entered_price * 0.015) if entered_price > 0 else 0.0))
        carry = event_amounts.scale_event_amount(ev, entered_carry, year, indexer)

        loan_service = 0.0
        loan_age = year - ev_start
        if new_loan > 0:
            if mort_term == "15_fixed" and loan_age <= 15:
                rate, term = float(ev.get("interest_rate") or 0.050), 180
                loan_service = monthly_payment(new_loan, rate, term) * 12.0
                mortgage_bal = max(0.0, mortgage_bal - principal_paid_in_year(new_loan, rate, term, loan_age))
            elif mort_term in ("7_1_arm", "5_1_arm", "10_1_arm") or ev.get("arm_fixed_years"):
                default_fixed = 5 if "5_1" in mort_term else 10 if "10_1" in mort_term else 7
                arm_fixed = int(ev.get("arm_fixed_years") or default_fixed)
                rate, term = float(ev.get("interest_rate") or 0.04875), 360
                if loan_age <= arm_fixed:
                    loan_service = monthly_payment(new_loan, rate, term) * 12.0
                    mortgage_bal = max(0.0, mortgage_bal - principal_paid_in_year(new_loan, rate, term, loan_age))
                elif loan_age <= 30:
                    reset_rate = float(ev.get("arm_reset_rate") or 0.0575)
                    reset_bal = balance_after(new_loan, rate, term, arm_fixed * 12)
                    reset_term = max(12, term - arm_fixed * 12)
                    loan_service = monthly_payment(reset_bal, reset_rate, reset_term) * 12.0
                    reset_principal = principal_paid_in_year(reset_bal, reset_rate, reset_term, loan_age - arm_fixed)
                    mortgage_bal = max(0.0, mortgage_bal - reset_principal)
                    if loan_age == arm_fixed + 1:
                        reset_pct, service_k = reset_rate * 100, loan_service / 1e3
                        events_occurred.append(
                            f"{name}: Real estate ARM reset to {reset_pct:.2f}% (${service_k:.1f}k/yr debt service)"
                        )
            elif mort_term != "all_cash" and loan_age <= 30:
                rate, term = float(ev.get("interest_rate") or 0.055), 360
                loan_service = monthly_payment(new_loan, rate, term) * 12.0
                mortgage_bal = max(0.0, mortgage_bal - principal_paid_in_year(new_loan, rate, term, loan_age))

        total_annual_re_drain = carry + loan_service
        yearly_event_outflow += total_annual_re_drain
        liquid_bal -= total_annual_re_drain

    elif cat == "home_renovation":
        cost = event_amounts.scale_event_amount(ev, float(ev.get("annual_amount") or ev.get("amount") or 0.0), year, indexer)
        retention_pct = float(ev.get("value_retention_pct") if ev.get("value_retention_pct") is not None else 0.60)
        if retention_pct > 1.0:
            retention_pct = retention_pct / 100.0
        equity_added = cost * retention_pct
        liquid_bal -= cost
        re_bal += equity_added
        yearly_event_outflow += cost
        events_occurred.append(f"{name}: -${cost/1e3:.0f}k remodel outlay (+${equity_added/1e3:.0f}k property value)")

    elif cat == "debt_payoff" and year == ev_start and mortgage_bal > 0:
        payoff_amt = min(mortgage_bal, event_amounts.scale_event_amount(ev, float(ev.get("amount", mortgage_bal)), year, indexer))
        liquid_bal -= payoff_amt
        mortgage_bal = 0.0
        yearly_event_outflow += payoff_amt
        events_occurred.append(f"{name}: Paid off ${payoff_amt/1e6:.2f}M debt")

    return liquid_bal, re_bal, mortgage_bal, yearly_event_inflow, yearly_event_outflow


def cover_cash_deficit_from_pools(
    net_draw: float,
    taxable_bal: float,
    pretax_bal: float,
    roth_bal: float,
    drawdown_order: str = "taxable_first",
) -> Tuple[float, float, float, float]:
    """Allocates living deficit across taxable, pre-tax, and Roth pools based on drawdown_order."""
    order = str(drawdown_order or "taxable_first").lower().strip()
    rem = max(0.0, net_draw)
    if rem <= 0:
        return taxable_bal, pretax_bal, roth_bal, 0.0

    def _draw(bal: float, req: float) -> Tuple[float, float]:
        d = min(bal, req)
        return bal - d, req - d

    if order == "pretax_first":
        pretax_bal, rem = _draw(pretax_bal, rem)
        taxable_bal, rem = _draw(taxable_bal, rem)
        roth_bal, rem = _draw(roth_bal, rem)
    elif order == "pro_rata":
        tot = taxable_bal + pretax_bal
        if tot > 0:
            if tot <= rem:
                rem -= tot
                taxable_bal, pretax_bal = 0.0, 0.0
            else:
                d_tax = rem * (taxable_bal / tot)
                taxable_bal = max(0.0, taxable_bal - d_tax)
                pretax_bal = max(0.0, pretax_bal - (rem - d_tax))
                rem = 0.0
        roth_bal, rem = _draw(roth_bal, rem)
    else:  # taxable_first
        taxable_bal, rem = _draw(taxable_bal, rem)
        pretax_bal, rem = _draw(pretax_bal, rem)
        roth_bal, rem = _draw(roth_bal, rem)

    return taxable_bal, pretax_bal, roth_bal, rem



