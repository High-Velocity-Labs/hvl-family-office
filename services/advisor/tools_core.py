"""
Core callable tools for the AI Financial Advisor:
Portfolio Allocation & Holdings, Company Equity & Vesting, Cash Flow & Balance Sheet Summary,
Stochastic Monte Carlo Stress Testing, Estate Tax Profile, Dynamic What-If Scenarios,
and Equity Option Exercise Tax Estimation.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict

import db
import equity_engine
import monarch_service
import security
from routes.helpers import DB_PATH, get_current_family_id
from services.advisor.tools_core_helpers import (
    _format_historical_backtest_summary,
    estimate_equity_exercise_tax,
    get_estate_tax_summary,
    get_monte_carlo_stress_test,
    simulate_financial_scenario,
)
from ssr.holdings import HOLDINGS_PRESETS, build_ssr_holdings

logger = logging.getLogger(__name__)


def _resolve_tool_family_id(family_id: int = 0) -> int:
    """Safely resolves active family_id in both request and background worker contexts."""
    ctx_fam = get_current_family_id()
    if ctx_fam > 0:
        return ctx_fam
    return int(family_id) if family_id > 0 else 0


def get_portfolio_allocation(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves the household investment policy statement (IPS), target vs. actual asset allocation,
    drift tolerance, rebalancing action steps, brokerage/401(k) ticker positions, and private investments.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    policy_data: Dict[str, Any] = {
        "anchor_preset": "core_satellite",
        "preset_name": "Core & Satellite (50/20/15/5/10)",
        "drift_tolerance": 0.05,
        "deviations_rationale": "Adhering to standard core-satellite asset allocation.",
        "target_allocation": {
            "us_total_market": 0.50,
            "international_equities": 0.20,
            "us_aggregate_bonds": 0.15,
            "cash_reserves": 0.05,
            "satellite_growth": 0.10,
        },
        "rebalancing_guidelines": [
            "Rebalance tax-free via incoming cash sweeps and 401(k) reallocations.",
            "Avoid selling appreciated taxable lots to satisfy drift tolerance.",
        ],
    }

    try:
        hp = db.families.get_household_profile(family_id=fam_id, db_path=DB_PATH)
        if hp and hp.get("assumptions_json"):
            assumptions = json.loads(hp["assumptions_json"]) if isinstance(hp["assumptions_json"], str) else hp["assumptions_json"]
            if isinstance(assumptions, dict) and isinstance(assumptions.get("investment_policy"), dict):
                pol = assumptions["investment_policy"]
                preset_id = pol.get("anchor_preset", "core_satellite")
                preset_names = {
                    "core_satellite": "Core & Satellite (50/20/15/5/10)",
                    "boglehead_80_20": "Classic Three-Fund (80/20)",
                    "all_equity_90_10": "Aggressive All-Equity (90/10)",
                    "boglehead_90_10": "Aggressive All-Equity (90/10)",
                    "glidepath_60_40": "Age-Based Glidepath (60/40)",
                    "boglehead_60_40": "Age-Based Glidepath (60/40)",
                    "core_four_reit": "Core Four with Real Estate REITs (48/24/20/8)",
                }
                policy_data["anchor_preset"] = preset_id
                policy_data["preset_name"] = preset_names.get(preset_id, preset_id.replace("_", " ").title())
                policy_data["drift_tolerance"] = float(pol.get("drift_tolerance", 0.05))
                policy_data["deviations_rationale"] = str(pol.get("deviations_rationale", ""))
                norm_key = {"boglehead_90_10": "all_equity_90_10", "boglehead_60_40": "glidepath_60_40"}.get(preset_id, preset_id)
                if norm_key in HOLDINGS_PRESETS:
                    t_map = HOLDINGS_PRESETS[norm_key]["targets"]
                    policy_data["target_allocation"] = {
                        "us_total_market": t_map.get("us_equity", 0.0),
                        "international_equities": t_map.get("intl_equity", 0.0),
                        "real_estate_reits": t_map.get("real_estate", 0.0),
                        "us_aggregate_bonds": t_map.get("bonds", 0.0),
                        "cash_reserves": t_map.get("cash", 0.0),
                        "satellite_growth": t_map.get("private_vc", 0.0),
                    }
    except Exception as e:
        logger.warning("Error getting portfolio allocation policy for family %s: %s", fam_id, e)

    try:
        snap = monarch_service.get_financial_snapshot(family_id=fam_id) or {}
        ssr_h = build_ssr_holdings(snap, family_id=fam_id)
        if ssr_h:
            policy_data["total_portfolio_value"] = ssr_h.get("deltas_foot", {}).get("tot_actual", "$0")
            policy_data["actual_balances"] = {
                "us_equity": ssr_h.get("us_equity_raw", 0.0),
                "intl_equity": ssr_h.get("intl_equity_raw", 0.0),
                "bonds": ssr_h.get("bonds_raw", 0.0),
                "cash": ssr_h.get("cash_raw", 0.0),
                "real_estate": ssr_h.get("real_estate_raw", 0.0),
                "private_vc": ssr_h.get("private_raw", 0.0),
            }
            policy_data["asset_class_drift_rows"] = [
                {
                    "asset_class": r.get("label"),
                    "actual": r.get("actual_str"),
                    "actual_pct": r.get("actual_pct_str"),
                    "target": r.get("target_str"),
                    "target_pct": r.get("target_pct_str"),
                    "delta": r.get("delta_str"),
                    "drift_pct": r.get("drift_pct_str"),
                    "exceeds_tolerance": r.get("is_excess", False),
                }
                for r in (ssr_h.get("deltas_rows") or [])
            ]
            policy_data["rebalance_action_steps"] = ssr_h.get("rebalance_steps") or []
            policy_data["private_investments"] = [
                {
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "institution": p.get("institution"),
                    "value": p.get("val_str"),
                    "percentage": p.get("percentage"),
                }
                for p in (ssr_h.get("private_rows") or [])
            ]
            policy_data["brokerage_accounts"] = [
                {
                    "account_name": a.get("account_name"),
                    "type": a.get("type_label"),
                    "balance": a.get("balance_str"),
                    "positions": [
                        {
                            "ticker": pos.get("ticker"),
                            "name": pos.get("name"),
                            "asset_class": pos.get("badge_text"),
                            "quantity": pos.get("quantity_str"),
                            "price": pos.get("price_str"),
                            "value": pos.get("value_str"),
                            "pct_of_account": pos.get("pct_of_acc"),
                        }
                        for pos in (a.get("positions") or [])[:25]
                    ],
                }
                for a in (ssr_h.get("brokerage_accounts") or [])
            ]
        from services.private_markets_service import get_lp_commitments_summary
        policy_data["lp_commitment_book"] = get_lp_commitments_summary(family_id=fam_id)
    except Exception as e:
        logger.warning("Error enriching holdings details for family %s: %s", fam_id, e)

    return policy_data


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
        grants_list = equity_data.get("grants", [])
        nso_count = sum(1 for g in grants_list if str(g.get("grant_type", "NSO")).upper() != "RSU")
        rsu_count = sum(1 for g in grants_list if str(g.get("grant_type", "NSO")).upper() == "RSU")

        companies_summary, projections_5yr = [], []
        try:
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
        except Exception:
            pass

        return {
            "company_name": equity_data.get("company_name", "Primary Company"),
            "share_price": equity_data.get("share_price", 0.0),
            "total_gross_equity_value": equity_data.get("total_gross_equity_value", 0.0),
            "true_net_post_tax_value": equity_data.get("true_net_post_tax_value", 0.0),
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
                "NSOs require strike capital to exercise; spread taxed at exercise.",
            ],
        }
    except Exception as e:
        logger.warning("Error evaluating equity schedule for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_cash_flow_summary(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves the household balance sheet, net worth snapshot, liquid cash reserves,
    investable portfolios, liabilities, annual spending, safe withdrawal rate, and family members.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    summary: Dict[str, Any] = {
        "net_worth": 0.0,
        "liquid_cash": 0.0,
        "investments": 0.0,
        "real_estate": 0.0,
        "total_liabilities": 0.0,
        "annual_spending": 0.0,
        "annual_savings": 0.0,
        "retirement_age": 0,
        "safe_withdrawal_rate_pct": 0.0,
        "state_residence": "WA",
        "tax_filing_status": "MFJ",
        "family_members": [],
    }
    try:
        hp = db.families.get_household_profile(family_id=fam_id, db_path=DB_PATH)
        if hp:
            summary.update({
                "state_residence": str(hp.get("state") or "WA"),
                "tax_filing_status": str(hp.get("filing_status") or "MFJ"),
                "annual_spending": float(hp.get("annual_spending") or 0.0),
                "annual_savings": float(hp.get("annual_savings") or 0.0),
                "retirement_age": int(hp.get("retirement_age") or 0),
            })
    except Exception as e:
        logger.warning("Error loading profile assumptions for cash flow: %s", e)
        return {"error": f"Failed to load household profile: {e}", "status": "unavailable"}

    try:
        members = security.get_family_members(DB_PATH, family_id=fam_id) if DB_PATH.exists() else []
        summary["family_members"] = [
            {"name": m.get("name"), "relationship": m.get("relationship"), "birthdate": m.get("birthdate")}
            for m in (members or [])
        ]
    except Exception:
        pass

    try:
        snap = monarch_service.get_financial_snapshot(family_id=fam_id)
        if snap:
            cats = snap.get("categories", {})
            liquid_cash = cats.get("cash_liquid", {}).get("total", snap.get("liquid_cash", 0.0))
            investments = (
                cats.get("public_brokerage", {}).get("total", 0.0)
                + cats.get("retirement", {}).get("total", 0.0)
                + cats.get("private_investments", {}).get("total", 0.0)
            )
            real_estate = cats.get("real_estate", {}).get("total", snap.get("real_estate", 0.0))
            liabilities = cats.get("mortgages", {}).get("total", 0.0) + cats.get("credit_cards", {}).get("total", 0.0)
            nw = snap.get("true_net_worth", snap.get("monarch_reported_net_worth", 0.0))
            summary.update({
                "net_worth": nw,
                "liquid_cash": liquid_cash,
                "real_estate": real_estate,
                "investments": investments if investments > 0 else snap.get("total_investments", snap.get("investments", 0.0)),
                "total_liabilities": liabilities if liabilities > 0 else snap.get("total_liabilities", 0.0),
                "safe_withdrawal_rate_pct": round(summary["annual_spending"] / nw * 100, 2) if (nw > 0 and summary["annual_spending"] > 0) else 0.0,
            })
    except Exception as e:
        logger.warning("Error loading balance sheet for cash flow: %s", e)
        return {"error": str(e), "status": "unavailable"}

    return summary


get_net_worth_summary = get_cash_flow_summary
get_tax_profile = get_estate_tax_summary
get_monte_carlo_summary = get_monte_carlo_stress_test

__all__ = [
    "_format_historical_backtest_summary",
    "_resolve_tool_family_id",
    "estimate_equity_exercise_tax",
    "get_cash_flow_summary",
    "get_equity_schedule",
    "get_estate_tax_summary",
    "get_monte_carlo_stress_test",
    "get_monte_carlo_summary",
    "get_net_worth_summary",
    "get_portfolio_allocation",
    "get_tax_profile",
    "simulate_financial_scenario",
]
