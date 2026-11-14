"""
Portfolio Allocation & Holdings tool for the AI Financial Advisor: investment policy targets vs. actuals,
drift, rebalancing steps, brokerage positions, private investments and the LP commitment book.
"""

from __future__ import annotations

from typing import Any, Dict

import account_sync
import db
from services.request_context import DB_PATH
from services.advisor.tools_core import _resolve_tool_family_id
from ssr.holdings import HOLDINGS_PRESETS, build_ssr_holdings


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

    pol = db.household_assumptions.get_dict_section(family_id=fam_id, section_key="investment_policy", db_path=DB_PATH)
    if pol:
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
        legacy_preset_keys = {"boglehead_90_10": "all_equity_90_10", "boglehead_60_40": "glidepath_60_40"}
        norm_key = legacy_preset_keys.get(preset_id, preset_id)
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

    snap = account_sync.get_financial_snapshot(family_id=fam_id) or {}
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

    return policy_data
