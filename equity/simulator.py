"""
Equity scenario simulation and multi-year vesting/valuation projections.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from equity.models import EquityGrant, get_db_path
from equity.repository import (
    get_company_409a_price,
    get_company_name,
    get_historical_equity_fmv,
    load_equity_companies_summary,
    load_equity_grants_from_db,
)


def simulate_valuation_scenario(
    share_price: Optional[float] = None,
    include_wa_millionaire_tax: bool = False,
    prior_w2_income: float = 500000.0,
    grants: Optional[List[EquityGrant]] = None,
    family_id: int = 0,
    company_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Simulates the equity portfolio position at a given share price.
    If company_id is provided, share_price applies to that company's grants,
    while other companies remain at their established FMV.
    """
    target_comp_name = get_company_name(family_id=family_id, company_id=company_id)
    current_baseline_price = get_company_409a_price(family_id=family_id, company_id=company_id)
    if share_price is None:
        share_price = current_baseline_price

    if grants is None:
        grants = load_equity_grants_from_db(family_id=family_id)

    company_fmvs: Dict[int, float] = {}
    if family_id:
        from db.auth_repo import get_equity_company_fmvs
        company_fmvs = get_equity_company_fmvs(family_id=family_id, db_path=get_db_path())

    def _eval_grants(wa_tax: bool):
        results = []
        running_income = prior_w2_income
        for g in grants:
            if company_id is not None:
                if g.company_id == company_id:
                    price_for_g = share_price
                else:
                    price_for_g = company_fmvs.get(g.company_id, current_baseline_price)
            else:
                ratio = (share_price / current_baseline_price) if current_baseline_price > 0 else 1.0
                base_g_price = company_fmvs.get(g.company_id, current_baseline_price)
                price_for_g = base_g_price * ratio

            res = g.calculate_at_price(price_for_g, wa_tax, running_income)
            results.append(res)
            running_income += res["spread"]
        return results

    grant_results = _eval_grants(include_wa_millionaire_tax)
    results_no_wa = _eval_grants(False)
    results_with_wa = _eval_grants(True)

    total_gross = sum(r["total_gross_value"] for r in grant_results)
    nominal_gross = sum(r.get("nominal_gross_value", 0.0) for r in grant_results)
    total_strike_cost = sum(r["strike_cost"] for r in grant_results)
    total_spread = sum(r["spread"] for r in grant_results)
    total_tax_drag = sum(r["total_tax_drag"] for r in grant_results)
    total_true_net = sum(r["true_net_value"] for r in grant_results)
    total_owned_shares = sum(g.owned_exercised for g in grants)
    total_unexercised_options = sum(g.unexercised_vested for g in grants)
    total_unvested_options = sum(g.unvested for g in grants)

    tax_without_wa = sum(r["total_tax_drag"] for r in results_no_wa)
    tax_with_wa = sum(r["total_tax_drag"] for r in results_with_wa)
    wa_tax_penalty = tax_with_wa - tax_without_wa

    unvested_spread = max(
        0.0,
        sum((share_price - g.strike_price) * g.unvested for g in grants if share_price > g.strike_price),
    )
    wa_rate_unvested = 0.099 if include_wa_millionaire_tax else (0.07 if unvested_spread > 1000000.0 else 0.0)
    unvested_tax = unvested_spread * (0.3935 + wa_rate_unvested)
    unvested_net = max(0.0, unvested_spread - unvested_tax)
    unvested_gross = total_unvested_options * share_price

    companies_summary = load_equity_companies_summary(family_id=family_id)

    if company_id is not None:
        scoped_grants = [g for g in grants if g.company_id == company_id]
        scoped_results = [r for idx, r in enumerate(grant_results) if grants[idx].company_id == company_id]
        company_gross = sum(r["total_gross_value"] for r in scoped_results)
        company_nominal_gross = sum(r.get("nominal_gross_value", 0.0) for r in scoped_results)
        company_strike_cost = sum(r["strike_cost"] for r in scoped_results)
        company_tax_drag = sum(r["total_tax_drag"] for r in scoped_results)
        company_true_net = sum(r["true_net_value"] for r in scoped_results)
        company_owned_shares = sum(g.owned_exercised for g in scoped_grants)
        company_unexercised_options = sum(g.unexercised_vested for g in scoped_grants)
        company_unvested_options = sum(g.unvested for g in scoped_grants)
    else:
        company_gross = total_gross
        company_nominal_gross = nominal_gross
        company_strike_cost = total_strike_cost
        company_tax_drag = total_tax_drag
        company_true_net = total_true_net
        company_owned_shares = total_owned_shares
        company_unexercised_options = total_unexercised_options
        company_unvested_options = total_unvested_options

    return {
        "share_price": share_price,
        "current_409a_price": current_baseline_price,
        "price_ratio": share_price / current_baseline_price if current_baseline_price > 0 else 1.0,
        "include_wa_millionaire_tax": include_wa_millionaire_tax,
        "total_owned_shares": total_owned_shares,
        "total_unexercised_options": total_unexercised_options,
        "total_unvested_options": total_unvested_options,
        "unvested_gross_value": round(unvested_gross, 2),
        "unvested_net_value": round(unvested_net, 2),
        "total_gross_equity_value": total_gross,
        "nominal_gross_equity_value": nominal_gross,
        "total_strike_cost_needed": total_strike_cost,
        "total_taxable_spread": total_spread,
        "total_tax_drag": total_tax_drag,
        "true_net_post_tax_value": total_true_net,
        "company_gross_equity_value": company_gross,
        "company_nominal_gross_equity_value": company_nominal_gross,
        "company_strike_cost_needed": company_strike_cost,
        "company_tax_drag": company_tax_drag,
        "company_true_net_post_tax_value": company_true_net,
        "company_owned_shares": company_owned_shares,
        "company_unexercised_options": company_unexercised_options,
        "company_unvested_options": company_unvested_options,
        "wa_tax_difference": wa_tax_penalty,
        "effective_tax_rate": total_tax_drag / total_spread if total_spread > 0 else 0.0,
        "company_id": company_id,
        "company_name": target_comp_name,
        "companies": companies_summary,
        "grants": grant_results,
        "fmv_history": get_historical_equity_fmv(share_price, family_id=family_id, company_id=company_id),
    }


def simulate_multi_year_projections(
    annual_growth_rate: float = 0.08,
    years: int = 5,
    include_wa_tax_from_year: int = 2028,
    base_share_price: Optional[float] = None,
    non_equity_net_worth: float = 0.0,
    family_id: int = 0,
    company_id: Optional[int] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Generates multi-year forward projections starting from 2026.
    Gradually vests unvested options and compounds share price.
    Excludes unvested options from current net worth, bringing them into
    net worth gradually as options vest across the projection window.
    """
    projections = []
    base_price = (
        base_share_price
        if base_share_price is not None
        else get_company_409a_price(family_id=family_id, company_id=company_id)
    )
    all_grants = load_equity_grants_from_db(family_id=family_id)
    grants = [g for g in all_grants if g.company_id == company_id] if company_id is not None else all_grants

    unvested_grants = [g for g in grants if g.unvested > 0]
    initial_unvested_map = {g.grant_id: (g.unexercised_vested, g.unvested) for g in unvested_grants}

    for i in range(years + 1):
        year = 2026 + i
        price = base_price * ((1.0 + annual_growth_rate) ** i)
        include_wa = year >= include_wa_tax_from_year

        for g in unvested_grants:
            init_vested, init_unvested = initial_unvested_map[g.grant_id]
            if year >= 2028:
                g.unexercised_vested = init_vested + init_unvested
                g.unvested = 0.0
            elif year == 2027:
                addl = init_unvested * 0.5
                g.unexercised_vested = init_vested + addl
                g.unvested = init_unvested - addl
            else:
                g.unexercised_vested = init_vested
                g.unvested = init_unvested

        sim = simulate_valuation_scenario(
            share_price=price,
            include_wa_millionaire_tax=include_wa,
            grants=grants,
            family_id=family_id,
            company_id=company_id,
        )
        sim["year"] = year
        if company_id is not None:
            sim["gross_equity"] = sim.get("company_nominal_gross_equity_value", sim["nominal_gross_equity_value"])
            sim["true_net_equity"] = sim.get("company_true_net_post_tax_value", sim["true_net_post_tax_value"])
        else:
            sim["gross_equity"] = sim["nominal_gross_equity_value"]
            sim["true_net_equity"] = sim["true_net_post_tax_value"]

        tot_unvested = sum(g.unvested for g in grants)
        sim["unvested_options"] = tot_unvested
        u_spread = max(0.0, sum((price - g.strike_price) * g.unvested for g in grants if price > g.strike_price))
        wa_u = 0.099 if include_wa else (0.07 if u_spread > 1000000.0 else 0.0)
        u_tax = u_spread * (0.3935 + wa_u)
        sim["unvested_net_value"] = max(0.0, u_spread - u_tax)
        sim["unvested_gross_value"] = tot_unvested * price

        projected_non_equity = non_equity_net_worth * ((1.0 + 0.06) ** i)
        sim["non_equity_net_worth"] = round(projected_non_equity, 2)
        sim["total_true_net_worth"] = round(projected_non_equity + sim["true_net_post_tax_value"], 2)
        sim["total_gross_net_worth"] = round(projected_non_equity + sim["gross_equity"], 2)

        projections.append(sim)

    return projections
