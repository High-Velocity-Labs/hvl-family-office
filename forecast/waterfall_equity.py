"""
forecast/waterfall_equity.py: Company equity exercise strategies, multi-year tranche staging,
post-tax option/share valuation, and private equity LP capital call helpers.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple

import tax_engine


_EQUITY_ACTION_MAP: Dict[str, str] = {
    "cashless_repurchase": "cashless_repurchase", "exercise_and_sell": "cashless_repurchase",
    "sell_all": "cashless_repurchase", "liquidate": "cashless_repurchase",
    "cashless": "cashless_repurchase", "repurchase": "cashless_repurchase",
    "exercise_and_hold_cash": "exercise_and_hold_cash", "hold_cash_cover": "exercise_and_hold_cash",
    "exercise_hold_cash": "exercise_and_hold_cash", "hold_cash": "exercise_and_hold_cash",
    "exercise_and_hold": "exercise_and_hold_cash",
    "exercise_and_hold_sell_to_cover": "exercise_and_hold_sell_to_cover",
    "hold_sell_to_cover": "exercise_and_hold_sell_to_cover", "sell_to_cover": "exercise_and_hold_sell_to_cover",
    "exercise_hold_sell_to_cover": "exercise_and_hold_sell_to_cover",
    "sell_held_shares": "sell_held_shares", "sell_owned_shares": "sell_held_shares",
    "liquidate_held_shares": "sell_held_shares", "secondary_sale": "sell_held_shares",
    "sell_shares": "sell_held_shares",
}


def normalize_equity_action(raw_action: Optional[str]) -> str:
    """Normalizes company equity exercise action identifiers to canonical strategy names."""
    if not raw_action:
        return "cashless_repurchase"
    cleaned = str(raw_action).strip().lower().replace("-", "_").replace(" ", "_")
    return _EQUITY_ACTION_MAP.get(cleaned, "cashless_repurchase")


def _record_held_shares_basis(options_pools: Dict[str, Dict[str, Any]], net_shares_added: float, share_price: float) -> None:
    """Tracks weighted-average stepped-up cost basis of shares acquired via NSO exercise-and-hold."""
    if net_shares_added <= 0 or not options_pools:
        return
    first_pool = next(iter(options_pools.values()))
    prev_shares = float(first_pool.get("_held_shares_tracked", 0.0) or 0.0)
    prev_basis = float(first_pool.get("_held_basis_per_share", 0.0) or 0.0)
    new_total = prev_shares + net_shares_added
    if new_total > 0:
        first_pool["_held_basis_per_share"] = ((prev_shares * prev_basis) + (net_shares_added * share_price)) / new_total
        first_pool["_held_shares_tracked"] = new_total


def tap_company_equity_liquidity(
    unfunded_after_retire: float, share_price: float,
    options_pools: Dict[str, Dict[str, Any]], owned_shares_count: float,
    household_salary: float, user_state: str, filing_status: str,
    events_occurred: List[str], year: int = 2028,
) -> Tuple[float, float]:
    """Taps company equity via cashless option repurchase or secondary tender to cover unfunded living deficit."""
    equity_drawn_net = 0.0
    if share_price <= 0:
        return equity_drawn_net, owned_shares_count

    include_wa = (user_state == "WA" and year >= 2028)
    for gid, pool in options_pools.items():
        if pool["active"] and pool["options"] > 0:
            opt_spread = max(0.0, share_price - pool["strike"])
            if opt_spread > 0:
                needed_net = unfunded_after_retire - equity_drawn_net
                tax_calc = tax_engine.calculate_nso_exercise_tax(
                    spread=opt_spread, prior_ordinary_income=household_salary,
                    include_wa_millionaire_tax=include_wa, is_mfj=(filing_status == "MFJ"),
                )
                nso_retention = max(0.50, min(1.0, 1.0 - tax_calc.get("effective_rate", 0.40)))
                opts_needed = min(pool["options"], (needed_net / nso_retention) / opt_spread)
                net_proceeds = (opts_needed * opt_spread) * nso_retention
                pool["options"] = max(0.0, pool["options"] - opts_needed)
                if pool["options"] <= 0.001:
                    pool["active"], pool["options"] = False, 0.0
                equity_drawn_net += net_proceeds
                events_occurred.append(
                    f"Company Equity Liquidity: Repurchased {int(opts_needed):,} options "
                    f"(+${net_proceeds/1e3:.0f}k net to fund living expenses)"
                )
                if equity_drawn_net >= unfunded_after_retire:
                    break

    if equity_drawn_net < unfunded_after_retire and owned_shares_count > 0:
        needed_net = unfunded_after_retire - equity_drawn_net
        shares_needed = min(owned_shares_count, (needed_net / 0.75) / share_price)
        net_proceeds = shares_needed * share_price * 0.75
        owned_shares_count -= shares_needed
        equity_drawn_net += net_proceeds
        events_occurred.append(
            f"Company Equity Liquidity: Tendered {int(shares_needed):,} shares "
            f"(+${net_proceeds/1e3:.0f}k net to fund living expenses)"
        )

    return equity_drawn_net, owned_shares_count


def process_company_equity_event(
    ev: Dict[str, Any], share_price: float,
    options_pools: Dict[str, Dict[str, Any]],
    primary_earned_income: float, spouse_earned_income: float,
    liquid_bal: float, yearly_event_inflow: float,
    events_occurred: List[str], year: int = 2026,
    ev_start: Optional[int] = None, ev_end: Optional[int] = None,
    owned_shares_count: float = 0.0, yearly_event_outflow: float = 0.0,
    effective_user_state: str = "WA", filing_status: str = "MFJ",
) -> Tuple[float, float, float, float]:
    """Processes single-year or multi-year staged company option exercises and held-share sales."""
    start_yr = int(ev_start if ev_start is not None else ev.get("year", ev.get("start_year", year)))
    end_yr = int(ev_end if ev_end is not None else ev.get("end_year", start_yr))
    if not (start_yr <= year <= end_yr):
        return liquid_bal, yearly_event_inflow, yearly_event_outflow, owned_shares_count

    action = normalize_equity_action(ev.get("action"))
    opt_qty = ev.get("options_quantity")
    name = ev.get("name", "Company Equity Exercise")
    is_multi_year = end_yr > start_yr
    tranche_fraction = (1.0 / max(1, end_yr - year + 1)) if is_multi_year else 1.0
    use_fixed_qty = bool(opt_qty and float(opt_qty) > 0 and not is_multi_year)
    yr_suffix = f" (Yr {year - start_yr + 1}/{end_yr - start_yr + 1})" if is_multi_year else ""

    if ev.get("include_wa_tax") is True:
        include_wa = True
    elif ev.get("exempt_wa_tax") is True:
        include_wa = False
    elif is_multi_year or ev.get("include_wa_tax") is None:
        include_wa = (effective_user_state == "WA" and year >= 2028)
    else:
        include_wa = bool(ev.get("include_wa_tax"))

    if action == "sell_held_shares":
        if owned_shares_count <= 0:
            return liquid_bal, yearly_event_inflow, yearly_event_outflow, owned_shares_count
        shares_to_sell = min(owned_shares_count, float(opt_qty)) if use_fixed_qty else (owned_shares_count * tranche_fraction)
        first_pool = next(iter(options_pools.values()), {}) if options_pools else {}
        if ev.get("cost_basis_per_share") is not None and float(ev.get("cost_basis_per_share") or 0) > 0:
            basis_per_share = float(ev["cost_basis_per_share"])
        elif float(first_pool.get("_held_basis_per_share", 0.0) or 0.0) > 0:
            basis_per_share = float(first_pool["_held_basis_per_share"])
        else:
            strikes = [float(p.get("strike", 0.0)) for p in options_pools.values()]
            basis_per_share = (sum(strikes) / len(strikes)) if strikes else 0.0

        sale_proceeds = shares_to_sell * share_price
        cost_basis = shares_to_sell * basis_per_share
        sale_tax = tax_engine.calculate_stock_sale_tax(
            sale_proceeds=sale_proceeds, cost_basis=cost_basis,
            holding_period_days=366, is_mfj=(filing_status == "MFJ"),
        )
        total_sale_tax = float(sale_tax.get("total_tax", 0.0))
        if not include_wa:
            total_sale_tax = max(0.0, total_sale_tax - float(sale_tax.get("wa_capital_gains_tax", 0.0)))

        net_cash = max(0.0, sale_proceeds - total_sale_tax)
        owned_shares_count = max(0.0, owned_shares_count - shares_to_sell)
        if first_pool and "_held_shares_tracked" in first_pool:
            first_pool["_held_shares_tracked"] = max(0.0, float(first_pool.get("_held_shares_tracked", 0.0) or 0.0) - shares_to_sell)
        liquid_bal += net_cash
        yearly_event_inflow += net_cash
        events_occurred.append(
            f"{name}{yr_suffix}: Sold {int(round(shares_to_sell)):,} held shares "
            f"(+${net_cash/1e6:.2f}M net after ${total_sale_tax/1e6:.2f}M LTCG tax)"
        )
        return liquid_bal, yearly_event_inflow, yearly_event_outflow, owned_shares_count

    total_spread, total_strike_cost, total_qty = 0.0, 0.0, 0.0
    raw_gid = ev.get("grant_id")
    if raw_gid and raw_gid != "all":
        target_gids = [raw_gid]
    elif use_fixed_qty:
        target_gids = [list(options_pools.keys())[0]] if options_pools else ["Grant 1"]
    else:
        target_gids = list(ev.get("grants") or options_pools.keys())

    for gid in target_gids:
        if gid in options_pools and options_pools[gid]["active"] and options_pools[gid]["options"] > 0:
            pool = options_pools[gid]
            qty = min(float(pool["options"]), float(opt_qty)) if use_fixed_qty else (float(pool["options"]) * tranche_fraction)
            strike = float(pool.get("strike", 0.0))
            total_qty += qty
            total_strike_cost += strike * qty
            total_spread += max(0.0, (share_price - strike) * qty)
            pool["options"] = max(0.0, float(pool["options"]) - qty)
            if pool["options"] <= 0.001 or (not use_fixed_qty and year >= end_yr):
                pool["options"], pool["active"] = 0.0, False

    if total_qty <= 0:
        return liquid_bal, yearly_event_inflow, yearly_event_outflow, owned_shares_count

    tax_info = tax_engine.calculate_nso_exercise_tax(
        spread=total_spread, prior_ordinary_income=(primary_earned_income + spouse_earned_income),
        include_wa_millionaire_tax=include_wa, is_mfj=(filing_status == "MFJ"),
    )
    total_tax = float(tax_info.get("total_tax", 0.0))

    if action == "exercise_and_hold_cash":
        total_cash_needed = total_strike_cost + total_tax
        liquid_used = min(liquid_bal, total_cash_needed)
        liquid_bal = max(0.0, liquid_bal - liquid_used)
        yearly_event_outflow += liquid_used
        unfunded_cost = max(0.0, total_cash_needed - liquid_used)
        shares_surrendered = (unfunded_cost / share_price) if share_price > 0 else 0.0
        net_shares_added = max(0.0, total_qty - shares_surrendered)
        owned_shares_count += net_shares_added
        _record_held_shares_basis(options_pools, net_shares_added, share_price)
        retained_val = net_shares_added * share_price
        events_occurred.append(
            f"{name}{yr_suffix}: Exercised & held {int(round(net_shares_added)):,} shares "
            f"(+${retained_val/1e6:.2f}M equity, -${liquid_used/1e6:.2f}M cash tax/strike cover)"
        )
    elif action == "exercise_and_hold_sell_to_cover":
        net_equity_val = max(0.0, total_spread - total_tax)
        net_shares_added = (net_equity_val / share_price) if share_price > 0 else 0.0
        owned_shares_count += net_shares_added
        _record_held_shares_basis(options_pools, net_shares_added, share_price)
        events_occurred.append(
            f"{name}{yr_suffix}: Exercised & held {int(round(net_shares_added)):,} net shares via sell-to-cover "
            f"(+${net_equity_val/1e6:.2f}M retained equity, $0 cash outlay)"
        )
    else:
        net_cash = max(0.0, total_spread - total_tax)
        liquid_bal += net_cash
        yearly_event_inflow += net_cash
        events_occurred.append(f"{name}{yr_suffix}: +${net_cash/1e6:.2f}M reinvested")

    return liquid_bal, yearly_event_inflow, yearly_event_outflow, owned_shares_count


def compute_company_equity_valuation(
    grants: List[Any], company_fmvs: Dict[int, float],
    share_price: float, owned_shares_count: float,
    baseline_owned_shares: float, options_pools: Dict[str, Dict[str, Any]],
    household_salary: float, effective_user_state: str,
    filing_status: str, year: int,
) -> float:
    """Computes total mark-to-market company equity including baseline grants, newly exercised held shares, and net unexercised options."""
    extra_held_shares = max(0.0, owned_shares_count - baseline_owned_shares)
    tendered_shares = max(0.0, baseline_owned_shares - owned_shares_count)
    if grants:
        base_owned_val = sum(
            g.owned_exercised * company_fmvs.get(int(getattr(g, "company_id", 0) or 0), share_price)
            for g in grants
        )
        company_owned_val = max(0.0, base_owned_val + ((extra_held_shares - tendered_shares) * share_price))
    else:
        company_owned_val = max(0.0, owned_shares_count * share_price)

    company_options_spread = 0.0
    for pool in options_pools.values():
        if pool["active"] and pool["options"] > 0:
            c_price = company_fmvs.get(int(pool.get("company_id", 0)), share_price)
            company_options_spread += max(0.0, (c_price - pool["strike"]) * pool["options"])

    if company_options_spread > 0:
        opt_tax = tax_engine.calculate_nso_exercise_tax(
            spread=company_options_spread, prior_ordinary_income=household_salary,
            include_wa_millionaire_tax=(effective_user_state == "WA" and year >= 2028),
            is_mfj=(filing_status == "MFJ"),
        )
        opt_retention = max(0.50, min(1.0, 1.0 - opt_tax.get("effective_rate", 0.40)))
    else:
        opt_retention = 0.60

    return company_owned_val + (company_options_spread * opt_retention)


def process_pe_capital_call_event(
    ev: Dict[str, Any], year: int, ev_start: int, ev_end: int,
    is_pe_harvest: bool, name: str, liquid_bal: float, other_bal: float,
    yearly_event_inflow: float, yearly_event_outflow: float, events_occurred: List[str],
) -> Tuple[float, float, float, float]:
    """Processes Private Equity / Venture Capital LP capital calls and J-curve harvest distributions."""
    call_amt = float(ev.get("annual_call") or ev.get("annual_call_amount") or ev.get("annual_amount") or ev.get("amount") or 100000.0)
    if ev_start <= year <= ev_end:
        liquid_bal = max(0.0, liquid_bal - call_amt)
        other_bal += call_amt
        yearly_event_outflow += call_amt
        events_occurred.append(f"{name}: -${call_amt/1e3:.0f}k LP capital call drawdown")
    if is_pe_harvest:
        total_committed = float(ev.get("total_commitment") or (call_amt * max(1, (ev_end - ev_start + 1))))
        tvpi = float(ev.get("tvpi_multiple") or ev.get("target_tvpi") or ev.get("target_moic") or 2.2)
        dist_gross = total_committed * tvpi
        dist_net = dist_gross - max(0.0, (dist_gross - total_committed) * 0.238)
        other_bal = max(0.0, other_bal - min(other_bal, total_committed))
        liquid_bal += dist_net
        yearly_event_inflow += dist_net
        events_occurred.append(f"{name}: +${dist_net/1e3:.0f}k PE/VC J-curve distribution ({tvpi:.1f}x TVPI net of LTCG)")
    return liquid_bal, other_bal, yearly_event_inflow, yearly_event_outflow
