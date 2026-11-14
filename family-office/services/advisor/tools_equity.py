"""
Company Equity & Vesting and Equity Option Exercise Tax tools for the AI Financial Advisor:
grants, vesting, 409A value, 5-year projections, and the tax on exercising options or selling shares.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from equity.iso_amt import amt_credit_recovery_years, iso_exercise_amt
from equity.state_tax import compensation_option_tax, stock_sale_tax_for_state
from services import equity_engine, residence_state
from services.household_income import household_prior_income
from services.request_context import DB_PATH
from services.advisor.tool_errors import ADVISOR_TOOL_ERRORS
from services.advisor.tools_cash_flow import get_cash_flow_summary
from services.advisor.tools_core import _resolve_tool_family_id

logger = logging.getLogger(__name__)


def get_equity_schedule(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves executive equity grants (NSOs, ISOs, RSUs), vesting schedules, 409A share valuation,
    multi-company breakdowns, strike capital required, and 5-year net proceeds projections.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    try:
        equity_data = equity_engine.simulate_valuation_scenario(family_id=fam_id)
        equity_wa_2028 = equity_engine.simulate_valuation_scenario(include_wa_millionaire_tax=True, family_id=fam_id)
        grants_list = equity_data.get("grants", [])
        nso_count = sum(1 for g in grants_list if str(g.get("grant_type", "NSO")).upper() != "RSU")
        rsu_count = sum(1 for g in grants_list if str(g.get("grant_type", "NSO")).upper() == "RSU")
        net_pre_2028 = float(equity_data.get("true_net_post_tax_value", 0.0) or 0.0)
        net_2028_plus = float(equity_wa_2028.get("true_net_post_tax_value", net_pre_2028) or 0.0)

        companies_summary, projections_5yr = [], []
        companies_summary = equity_engine.load_equity_companies_summary(family_id=fam_id) or []
        share_p = float(equity_data.get("share_price") or 0.0)
        raw_proj = (
            equity_engine.simulate_multi_year_projections(
                annual_growth_rate=0.105,
                years=5,
                base_share_price=share_p if share_p > 0 else 100.0,
                family_id=fam_id,
            )
            or []
        )
        projections_5yr = [
            {
                "year": p.get("year"),
                "projected_share_price": p.get("projected_share_price"),
                "vested_gross_value": p.get("total_gross_value"),
                "true_net_post_tax_value": p.get("true_net_value"),
                "strike_cost_needed": p.get("total_strike_cost"),
                "estimated_tax_drag": p.get("total_tax_drag"),
            }
            for p in raw_proj[:6]
        ]

        return {
            "company_name": equity_data.get("company_name", "Primary Company"),
            "share_price": equity_data.get("share_price", 0.0),
            "total_gross_equity_value": equity_data.get("total_gross_equity_value", 0.0),
            "true_net_post_tax_value": net_pre_2028,
            "true_net_post_tax_value_with_wa_2028_tax": net_2028_plus,
            "wa_sb6346_2028_tax_penalty": round(max(0.0, net_pre_2028 - net_2028_plus), 2),
            "total_strike_cost_needed": equity_data.get("total_strike_cost_needed", 0.0),
            "total_tax_drag": equity_data.get("total_tax_drag", 0.0),
            "grants_count": len(grants_list),
            "nso_count": nso_count,
            "rsu_count": rsu_count,
            "companies": companies_summary,
            "grants": [
                {
                    "grant_id": g.get("grant_id"),
                    "nickname": g.get("nickname"),
                    "grant_type": g.get("grant_type", "NSO"),
                    "company_name": g.get("company_name"),
                    "grant_date": g.get("grant_date"),
                    "vesting_completion": g.get("vesting_completion"),
                    "total_granted": g.get("total_granted", 0),
                    "strike_price": g.get("strike_price", 0.0),
                    "unexercised_options": g.get("unexercised_options", 0),
                    "unvested_options": g.get("unvested_options", 0),
                    "owned_shares": g.get("owned_shares", 0),
                    "strike_cost": g.get("strike_cost", 0.0),
                    "spread": g.get("spread", 0.0),
                    "true_net_value": g.get("true_net_value", 0.0),
                }
                for g in grants_list
            ],
            "five_year_projections_at_10_5_pct_cagr": projections_5yr,
            "tax_guidelines": [
                "RSUs vest with $0 strike cost; taxed as ordinary income.",
                "NSOs require strike capital to exercise; spread (FMV - Strike) is taxed as ordinary income at exercise and steps up share cost basis to the exercise FMV.",
                "WA SB 6346 (9.9% Millionaire's Tax on taxable income > $1M) takes effect Jan 1, 2028 (tax years 2028+). Exercising NSOs in 2026–2027 (whether selling immediately or holding) locks in 0% WA state tax on the existing spread; if held and sold later, only post-exercise appreciation above the stepped-up FMV basis is taxed as capital gain.",
            ],
        }
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error evaluating equity schedule for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def estimate_equity_exercise_tax(
    family_id: int = 0,
    shares_to_exercise: float = 0.0,
    strike_price: Optional[float] = None,
    share_price: Optional[float] = None,
    grant_type: str = "nso",
    include_wa_millionaire_tax: bool = False,
    tax_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Calculates tax liability, stepped-up cost basis, strike cost, and pre-2028 vs. 2028+ WA SB 6346 net proceeds for exercising options or stock sales."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id or shares_to_exercise <= 0:
        return {"error": "Invalid shares or unauthenticated session"}

    try:
        current_409a = equity_engine.get_company_409a_price(family_id=fam_id)
        effective_share_price = share_price if share_price is not None and share_price > 0 else current_409a
        effective_strike = strike_price if strike_price is not None else 0.0
        if strike_price is None:
            grants = equity_engine.load_equity_grants_from_db(family_id=fam_id)
            if grants:
                effective_strike = grants[0].strike_price

        strike_cost = round(shares_to_exercise * effective_strike, 2)
        gross_value = round(shares_to_exercise * effective_share_price, 2)
        spread = max(0.0, gross_value - strike_cost)
        cf = get_cash_flow_summary(family_id=fam_id)
        filing_status = cf.get("tax_filing_status", "MFJ")
        # The exercise stacks on the whole household's income, not one earner's.
        prior_ordinary_income = household_prior_income(fam_id, db_path=DB_PATH if DB_PATH.exists() else None)

        state = residence_state.normalize(cf.get("state_residence"))
        gtype = grant_type.lower()
        if gtype in ("nso", "rsu"):
            # NSO spread and RSU vest are wages: federal, Medicare and the household's own state income tax.
            if gtype == "rsu":
                spread, strike_cost, effective_strike = gross_value, 0.0, 0.0
            wa_toggle = include_wa_millionaire_tax or (tax_year is not None and tax_year >= 2028)
            tax_res = compensation_option_tax(
                spread, prior_ordinary_income, state, wa_toggle, tax_year, filing_status,
            )
            tax_2028 = compensation_option_tax(spread, prior_ordinary_income, state, True, 2028, filing_status)
            tot_tax = tax_res.get("total_tax", 0.0)
            return {
                "shares": shares_to_exercise,
                "share_price": effective_share_price,
                "strike_price": effective_strike,
                "total_strike_cost": strike_cost,
                "gross_spread": round(spread, 2),
                "stepped_up_cost_basis_after_exercise": gross_value,
                "prior_ordinary_income_used": prior_ordinary_income,
                "state_code": state,
                "federal_tax": tax_res.get("federal_income_tax", 0.0),
                "medicare_tax": tax_res.get("medicare_tax", 0.0),
                "state_income_tax": round(tax_res.get("state_tax", 0.0), 2),
                "wa_state_tax": tax_res.get("wa_state_tax", 0.0),
                "wa_state_tax_pre_2028": 0.0,
                "wa_sb6346_tax_if_exercised_2028_plus": round(tax_2028.get("wa_state_tax", 0.0), 2),
                "total_tax_liability": round(tot_tax, 2),
                "effective_tax_rate_pct": round(tax_res.get("effective_rate", 0.0) * 100, 2),
                "net_take_home_cashless": round(spread - tot_tax, 2),
            }

        sale_tax = stock_sale_tax_for_state(
            gross_value, strike_cost, prior_ordinary_income, state, tax_year, filing_status,
        )
        result = {
            "shares": shares_to_exercise,
            "share_price": effective_share_price,
            "cost_basis": strike_cost,
            "gross_proceeds": gross_value,
            "state_code": state,
            "capital_gain": sale_tax.get("gain", 0.0),
            "federal_ltcg_tax": sale_tax.get("federal_capital_gains_tax", 0.0),
            "niit_tax": sale_tax.get("niit_tax", 0.0),
            "state_capital_gains_tax": round(sale_tax.get("state_capital_gains_tax", 0.0), 2),
            "wa_capital_gains_tax": sale_tax.get("wa_capital_gains_tax", 0.0),
            "total_tax_liability": round(sale_tax.get("total_tax", 0.0), 2),
            "net_proceeds": round(gross_value - strike_cost - sale_tax.get("total_tax", 0.0), 2),
        }
        if gtype == "iso":
            # Exercising and holding ISOs owes no regular tax but triggers AMT on the spread (credit carries forward).
            amt = iso_exercise_amt(spread, prior_ordinary_income, filing_status)
            result.update({
                "amt_preference_if_exercised_and_held": round(amt["amt_preference"], 2),
                "amt_if_exercised_and_held": round(amt["amt"], 2),
                "amt_credit_carryforward": round(amt["amt_credit_carryforward"], 2),
                "amt_credit_recovery_years": amt_credit_recovery_years(
                    amt["amt_credit_carryforward"], prior_ordinary_income, filing_status, tax_year or date.today().year,
                ),
            })
        return result
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error estimating equity exercise tax: %s", e)
        return {"error": str(e), "status": "unavailable"}
