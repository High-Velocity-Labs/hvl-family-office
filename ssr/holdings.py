"""
SSR view-model builder for Asset Allocation, IPS Drift, Rebalancing, and Public/Private Holdings.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import config
import db
from hvl_common.ui.formatting import (
    _INLINE_MD_RE,
    _tokenize_inline_markdown,
    parse_changelog_releases as _shared_parse_changelog_releases,
)

__all__ = ["_INLINE_MD_RE", "_tokenize_inline_markdown"]
from routes.helpers import DB_PATH, sanitize_text
from ssr.formatting import fmt_currency, get_private_investments_data
from services.private_markets_service import get_lp_commitments_summary

logger = logging.getLogger(__name__)

INVESTMENT_POLICY_PRESETS: dict[str, dict[str, Any]] = {
    "core_satellite": {"name": "Family Office Core & Satellite", "target": {"us_equity": 0.50, "intl_equity": 0.20, "bonds": 0.15, "cash": 0.05, "private_vc": 0.10}},
    "boglehead_80_20": {"name": "Classic Three-Fund (80/20)", "target": {"us_equity": 0.55, "intl_equity": 0.25, "bonds": 0.20, "cash": 0.00, "private_vc": 0.00}},
    "all_equity_90_10": {"name": "Aggressive All-Equity (90/10)", "target": {"us_equity": 0.65, "intl_equity": 0.25, "bonds": 0.05, "cash": 0.05, "private_vc": 0.00}},
    "glidepath_60_40": {"name": "Age-Based Glidepath (60/40)", "target": {"us_equity": 0.45, "intl_equity": 0.15, "bonds": 0.40, "cash": 0.00, "private_vc": 0.00}},
    "core_four_reit": {"name": "Boglehead Core Four (with Real Estate / REITs)", "target": {"us_equity": 0.48, "intl_equity": 0.24, "bonds": 0.20, "cash": 0.00, "real_estate": 0.08, "private_vc": 0.00}},
    "boglehead_90_10": {"name": "Boglehead 90/10 Aggressive", "target": {"us_equity": 0.60, "intl_equity": 0.30, "bonds": 0.10, "cash": 0.00, "private_vc": 0.00}},
    "boglehead_60_40": {"name": "Boglehead 60/40 Conservative", "target": {"us_equity": 0.40, "intl_equity": 0.20, "bonds": 0.40, "cash": 0.00, "private_vc": 0.00}},
}

VALID_POLICY_PRESETS = (
    "boglehead_80_20", "boglehead_90_10", "boglehead_60_40",
    "core_satellite", "all_equity_90_10", "glidepath_60_40", "core_four_reit",
)

HOLDINGS_PRESETS = {
    "core_satellite": {
        "name": "Family Office Core & Satellite", "short_name": "Core & Satellite",
        "badge": "50% US / 20% Int'l / 15% Bonds / 5% Cash / 10% VC", "risk": "Moderate-High (Growth + Venture Alpha)", "expected_cagr": "7.2% – 10.4%",
        "rationale": "Ideal for high-earning households with robust liquidity cushions who want broad market index compounding for baseline wealth, while intentionally deploying 10% to early-stage angel syndicates without risking family solvency.",
        "risk_downside": "Startup illiquidity is strictly capped at 10% with a 5% liquid cash cushion, ensuring venture write-offs never compromise baseline household security.",
        "risk_upside": "Captures asymmetric private venture upside on breakthrough winners, while 85% remains in disciplined, low-cost broad-market indexing.",
        "bogle_link": "https://www.bogleheads.org/wiki/Variations_on_Bogleheads%C2%AE_investing", "link_text": "Bogleheads Wiki: Variations & Satellite Tilts",
        "targets": {"us_equity": 0.50, "intl_equity": 0.20, "real_estate": 0.00, "bonds": 0.15, "cash": 0.05, "private_vc": 0.10},
    },
    "boglehead_80_20": {
        "name": "Classic Three-Fund (80/20)", "short_name": "80/20 Three-Fund",
        "badge": "55% US / 25% Int'l / 20% Total Bond", "risk": "Moderate (Broad Market Index)", "expected_cagr": "6.5% – 8.8%",
        "rationale": "The gold standard for multi-decade compounding. Delivers total global stock diversification (Total US + Total International) with a 20% high-grade bond ballast to dampen bear market drawdowns and provide rebalancing dry powder.",
        "risk_downside": "20% high-grade fixed income cushions market panics (limiting peak historical drawdown to ~-30% to -35% vs. -50%+ for pure equity) and prevents panic selling.",
        "risk_upside": "The 20% bond allocation incurs an annual yield drag (~1.0–1.5%) compared to pure stocks during long bull markets.",
        "bogle_link": "https://www.bogleheads.org/wiki/Three-fund_portfolio", "link_text": "Bogleheads Wiki: Three-Fund Portfolio",
        "targets": {"us_equity": 0.55, "intl_equity": 0.25, "real_estate": 0.00, "bonds": 0.20, "cash": 0.00, "private_vc": 0.00},
    },
    "core_four_reit": {
        "name": "Boglehead Core Four (with Real Estate / REITs)", "short_name": "Core Four (REITs)",
        "badge": "48% US / 24% Int'l / 20% Bonds / 8% Real Estate REITs", "risk": "Moderate (Inflation-Hedged Index)", "expected_cagr": "6.6% – 9.0%",
        "rationale": "Designed for investors who want a dedicated liquid real estate tilt (REITs) for inflation hedging, income yield, and asset-backed diversification beyond standard market-cap weights.",
        "risk_downside": "20% bonds cushions stock crashes, while real estate rental cash flows provide income stability across inflationary cycles.",
        "risk_upside": "Commercial real estate participates strongly in economic expansions, though interest rate spikes can temporarily compress property valuations.",
        "bogle_link": "https://www.bogleheads.org/wiki/Lazy_portfolios#Core_four_portfolios", "link_text": "Bogleheads Wiki: Core Four & REITs",
        "targets": {"us_equity": 0.48, "intl_equity": 0.24, "real_estate": 0.08, "bonds": 0.20, "cash": 0.00, "private_vc": 0.00},
    },
    "all_equity_90_10": {
        "name": "Aggressive All-Equity (90/10)", "short_name": "90/10 All-Equity",
        "badge": "65% US / 25% Int'l / 10% Cash & Bonds", "risk": "High (Maximum Long-Term Compounding)", "expected_cagr": "7.5% – 10.2%",
        "rationale": "Engineered for high-income accumulators in peak earning years with multi-decade horizons and the psychological discipline to withstand severe market crashes without selling.",
        "risk_downside": "With almost no bond shock absorber, paper losses reach -45% to -50% during major crises. Demands iron emotional fortitude to avoid panic selling at market bottoms.",
        "risk_upside": "Nearly 100% equity exposure maximizes terminal compound wealth (~9.0–9.5% annualized nominal compound rate).",
        "bogle_link": "https://www.bogleheads.org/wiki/Asset_allocation", "link_text": "Bogleheads Wiki: Asset Allocation & Risk",
        "targets": {"us_equity": 0.65, "intl_equity": 0.25, "real_estate": 0.00, "bonds": 0.05, "cash": 0.05, "private_vc": 0.00},
    },
    "glidepath_60_40": {
        "name": "Age-Based Glidepath (60/40)", "short_name": "60/40 Glidepath",
        "badge": "45% US / 15% Int'l / 40% Bonds", "risk": "Low-Moderate (Capital Preservation)", "expected_cagr": "5.5% – 7.6%",
        "rationale": "The classic benchmark for sequence-of-returns protection and capital preservation, tailored for families within 5–10 years of retirement or those prioritizing steady income and low volatility.",
        "risk_downside": "40% fixed income limits peak-to-trough drawdowns to ~-20% to -25%, ensuring market shocks don't derail retirement distributions.",
        "risk_upside": "Expected long-term compound return is capped at ~6.5–7.0%, requiring vigilance against multi-decade inflation erosion.",
        "bogle_link": "https://www.bogleheads.org/wiki/Glide_paths", "link_text": "Bogleheads Wiki: Glide Paths",
        "targets": {"us_equity": 0.45, "intl_equity": 0.15, "real_estate": 0.00, "bonds": 0.40, "cash": 0.00, "private_vc": 0.00},
    },
}

_ASSET_CLASS_BADGES: dict[str, tuple[str, str]] = {
    "us_equity": ("badge-us-equity asset-class-bubble", "US Equities"),
    "intl_equity": ("badge-intl-equity asset-class-bubble", "Intl Equities"),
    "bonds": ("badge-bonds asset-class-bubble", "Fixed Income"),
    "cash": ("badge-cash asset-class-bubble", "Cash & Money Market"),
    "real_estate": ("badge badge-orange asset-class-bubble", "Real Estate / REITs"),
}


def load_investment_policy_payload(family_id: int) -> dict[str, Any]:
    """Loads the household's Investment Policy Statement and standard presets."""
    policy: dict[str, Any] = {"anchor_preset": "boglehead_80_20", "drift_tolerance": 0.05, "deviations_rationale": "", "family_id": family_id}
    if DB_PATH.exists() and family_id:
        try:
            prof = db.families.get_household_profile(family_id=family_id, db_path=DB_PATH)
            raw_assump = (prof or {}).get("assumptions_json")
            if raw_assump:
                assumptions = json.loads(raw_assump) if isinstance(raw_assump, str) else raw_assump
                if isinstance(assumptions, dict) and "investment_policy" in assumptions:
                    policy.update(assumptions["investment_policy"])
        except Exception as e:
            logger.warning(f"Error loading investment policy: {e}")
    return {"success": True, "policy": policy, "presets": INVESTMENT_POLICY_PRESETS}


def save_investment_policy_payload(family_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Validates and persists the household's Investment Policy Statement."""
    anchor = sanitize_text(body.get("anchor_preset", "boglehead_80_20"), max_length=50, field_name="Anchor preset")
    if anchor not in VALID_POLICY_PRESETS:
        raise ValueError(f"Invalid anchor preset '{anchor}'. Must be one of: {', '.join(VALID_POLICY_PRESETS)}")
    try:
        tolerance = max(0.01, min(0.20, float(body.get("drift_tolerance", 0.05))))
    except (ValueError, TypeError):
        tolerance = 0.05
    rationale = sanitize_text(body.get("deviations_rationale", ""), max_length=2000, field_name="Deviation rationale")
    policy_data = {"anchor_preset": anchor, "drift_tolerance": tolerance, "deviations_rationale": rationale}
    if DB_PATH.exists() and family_id:
        db.families.update_household_assumptions_key(family_id=family_id, section_key="investment_policy", section_value=policy_data, db_path=DB_PATH)
    return {"success": True, "message": "Investment Policy Statement and deviation profile saved successfully.", "policy": policy_data}


def build_ssr_holdings(
    snapshot: dict, family_id: int = 0, preset: str | None = None, horizon: str | None = None, drift_tolerance: float | None = None
) -> dict:
    """Prepares formatted strings for SSR Holdings KPI cards, simulator, IPS policy, private investments, and brokerage positions."""
    if not snapshot:
        return {}
    cats = snapshot.get("categories") or {}
    alloc = snapshot.get("detailed_asset_allocation") or {}
    totals = alloc.get("totals") or {}
    us_eq = float(totals.get("us_equity") if totals.get("us_equity") is not None else (alloc.get("us_equities_total") if alloc.get("us_equities_total") is not None else ((cats.get("public_brokerage") or {}).get("total") or 0.0)))
    intl_eq = float(totals.get("intl_equity") if totals.get("intl_equity") is not None else (alloc.get("intl_equities_total") or 0.0))
    bonds_val = float(totals.get("bonds") if totals.get("bonds") is not None else (alloc.get("bonds_total") or 0.0))
    cash = float(totals.get("cash_liquid") if totals.get("cash_liquid") is not None else (alloc.get("cash_total") if alloc.get("cash_total") is not None else ((cats.get("cash_liquid") or {}).get("total") or 0.0)))
    re_val = float(totals.get("real_estate_reits") if totals.get("real_estate_reits") is not None else (alloc.get("real_estate_total") or 0.0))
    priv = float((cats.get("private_investments") or {}).get("total") or 0.0)
    priv_count = (cats.get("private_investments") or {}).get("count") or 0

    policy = {"anchor_preset": "core_satellite", "drift_tolerance": 0.05, "deviations_rationale": ""}
    if family_id > 0 and DB_PATH.exists():
        try:
            hp = db.families.get_household_profile(family_id=family_id, db_path=DB_PATH)
            if isinstance(hp, dict) and isinstance(hp.get("investment_policy"), dict):
                policy.update(hp["investment_policy"])
        except Exception:
            pass

    preset_aliases = {"boglehead_90_10": "all_equity_90_10", "boglehead_60_40": "glidepath_60_40"}
    anchor_key = preset_aliases.get(policy.get("anchor_preset") or "core_satellite", policy.get("anchor_preset") or "core_satellite")
    policy["anchor_preset"] = anchor_key if anchor_key in HOLDINGS_PRESETS else "core_satellite"

    req_preset = preset_aliases.get(preset or "", preset)
    active_preset = req_preset if (req_preset and req_preset in HOLDINGS_PRESETS) else policy["anchor_preset"]
    active_horizon = str(horizon).strip() if horizon in ("5", "10", "20", "30", "none") else "10"
    show_proj = active_horizon != "none"
    horizon_yrs = int(active_horizon) if show_proj else 10
    active_drift = float(drift_tolerance) if drift_tolerance is not None else float(policy.get("drift_tolerance") or 0.05)

    priv_rows = []
    total_priv_val = priv
    if family_id > 0:
        try:
            priv_data = get_private_investments_data(family_id=family_id) or {}
            items = priv_data.get("items") or []
            total_priv_val = float(priv_data.get("total_value") or priv or 0.0)
            if items:
                priv_count = len(items)
            for item in items:
                val = float(item.get("current_value") or 0.0)
                pct = float(item.get("percentage") if item.get("percentage") is not None else ((val / total_priv_val * 100) if total_priv_val > 0 else 0))
                cat = item.get("category") or "Venture Capital / Startup"
                badge_class = "badge-blue" if ("Fund" in cat or "Buyout" in cat) else ("badge-purple" if ("Angel" in cat or "SPV" in cat) else "badge-orange")
                priv_rows.append({
                    "name": item.get("name"),
                    "is_manual": bool(item.get("is_manual")),
                    "category": cat,
                    "badge_class": badge_class,
                    "institution": item.get("institution") or "Direct Holding",
                    "percentage": f"{pct:.1f}%",
                    "val_str": fmt_currency(val, 2),
                })
        except Exception as e:
            logger.warning(f"Error loading SSR private investments: {e}")

    tot_port = us_eq + intl_eq + re_val + bonds_val + cash + total_priv_val
    p_info = HOLDINGS_PRESETS[active_preset]
    targets = p_info["targets"]
    preset_rows = [
        ("US Equities (Total Stock)", "us_equity", us_eq, targets.get("us_equity", 0.0), 0.05, 0.08),
        ("International Equities", "intl_equity", intl_eq, targets.get("intl_equity", 0.0), 0.045, 0.075),
        ("Real Estate & REITs", "real_estate", re_val, targets.get("real_estate", 0.0), 0.04, 0.07),
        ("Bonds & Fixed Income", "bonds", bonds_val, targets.get("bonds", 0.0), 0.03, 0.045),
        ("Cash & Money Market", "cash", cash, targets.get("cash", 0.0), 0.02, 0.035),
        ("Private Investments & VC", "private_vc", total_priv_val, targets.get("private_vc", 0.0), 0.08, 0.15),
    ]
    deltas_rows, rebalance_steps = [], []
    sum_t_val = sum_v_min = sum_v_max = 0.0
    for label, _key, actual, target_pct, r_min, r_max in preset_rows:
        act_pct = (actual / tot_port) if tot_port > 0 else 0.0
        t_val = tot_port * target_pct
        delta_val = t_val - actual
        drift_pct = act_pct - target_pct
        is_excess = abs(drift_pct) > active_drift
        sum_t_val += t_val
        has_proj = t_val > 0
        m_min, m_max = (1.0 + r_min) ** horizon_yrs, (1.0 + r_max) ** horizon_yrs
        v_min, v_max = t_val * m_min, t_val * m_max
        g_min, g_max = v_min - t_val, v_max - t_val
        if has_proj:
            sum_v_min += v_min
            sum_v_max += v_max
        if is_excess and abs(delta_val) >= 1000:
            action_word = "Add" if delta_val > 0 else "Trim"
            rebalance_steps.append(
                f"{action_word} {fmt_currency(abs(delta_val), 0)} {'into' if delta_val > 0 else 'from'} {label} "
                f"(Actual {act_pct * 100:.1f}% vs. Target {target_pct * 100:.1f}% • Tax Impact: $0 inside retirement/cash sweeps)."
            )
        deltas_rows.append({
            "label": label,
            "actual_str": fmt_currency(actual, 0),
            "actual_pct_str": f"{act_pct * 100:.1f}%",
            "target_pct_str": f"{target_pct * 100:.1f}%",
            "target_str": fmt_currency(t_val, 0),
            "delta_str": f"{'+' if delta_val >= 0 else ''}{fmt_currency(delta_val, 0)}",
            "delta_color": "var(--status-green)" if delta_val >= 0 else "var(--status-red)",
            "is_excess": is_excess,
            "drift_positive": drift_pct > 0,
            "drift_pct_str": f"{abs(drift_pct) * 100:.1f}%",
            "has_proj": has_proj,
            "sign_min": "+" if g_min >= 0 else "",
            "color_min": "var(--status-green)" if g_min >= 0 else "var(--status-red)",
            "g_min_str": fmt_currency(g_min, 0),
            "g_max_str": fmt_currency(g_max, 0),
            "pct_min": round((m_min - 1.0) * 100),
            "pct_max": round((m_max - 1.0) * 100),
        })

    if not rebalance_steps:
        rebalance_steps.append(f"Portfolio is currently balanced within your ±{round(active_drift * 100)}% drift threshold. No immediate trade action needed.")
    rebalance_steps.append("Taxable Shield Invariant: Never sell appreciated index shares in taxable brokerage accounts. All rebalancing executes exclusively through tax-deferred 401(k) exchanges and new cash savings sweeps.")

    net_min, net_max = sum_v_min - tot_port, sum_v_max - tot_port
    pct_min_tot = round((net_min / tot_port) * 100) if tot_port > 0 else 0
    pct_max_tot = round((net_max / tot_port) * 100) if tot_port > 0 else 0
    deltas_foot = {
        "tot_actual": fmt_currency(tot_port, 0),
        "tot_target": fmt_currency(sum_t_val, 0),
        "sign_net": "+" if net_min >= 0 else "",
        "color_net": "var(--status-green)" if net_min >= 0 else "var(--status-red)",
        "net_min_str": fmt_currency(net_min, 0),
        "net_max_str": fmt_currency(net_max, 0),
        "pct_min_tot": pct_min_tot,
        "pct_max_tot": pct_max_tot,
    }

    brokerage_accounts = []
    for acc in snapshot.get("brokerage_and_401k_positions") or snapshot.get("vanguard_and_401k_positions") or []:
        if not isinstance(acc, dict):
            continue
        bal = float(acc.get("balance") if acc.get("balance") is not None else (acc.get("total_balance") or 0.0))
        raw_positions = acc.get("positions") or []
        if bal <= 0 and not raw_positions:
            continue
        acc_name = acc.get("account_name") or "Investment Account"
        is_401k = "401(k)" in acc_name.lower() or "401k" in acc_name.lower()
        positions = []
        for pos in raw_positions:
            cls_key = pos.get("asset_class") or "other"
            badge_cls, badge_txt = _ASSET_CLASS_BADGES.get(
                cls_key,
                ("badge badge-blue asset-class-bubble", pos.get("asset_class_label") or cls_key or "Other"),
            )
            qty = float(pos.get("quantity") or 0.0)
            price = float(pos.get("price") or 0.0)
            tot_val = float(pos.get("total_value") or 0.0)
            positions.append({
                "ticker": pos.get("ticker") or "--",
                "name": pos.get("name") or pos.get("security_name") or "",
                "badge_class": badge_cls,
                "badge_text": badge_txt,
                "quantity_str": f"{qty:,.2f}",
                "price_str": fmt_currency(price, 2) if price > 1.0 else "--",
                "value_str": fmt_currency(tot_val, 2),
                "pct_of_acc": f"{(tot_val / bal * 100):.1f}%" if bal > 0 else "0.0%",
            })
        pos_total = float(acc.get("positions_total") if acc.get("positions_total") is not None else bal)
        brokerage_accounts.append({
            "account_id": acc.get("account_id") or "--",
            "account_name": acc_name,
            "badge_color": "badge-orange" if is_401k else "badge-blue",
            "type_label": "Employer 401(k) Plan" if is_401k else "Taxable Brokerage",
            "positions_count": len(positions),
            "balance_str": fmt_currency(bal, 2),
            "positions_total_str": fmt_currency(pos_total, 2),
            "positions": positions,
        })

    return {
        "active_preset": active_preset, "preset_name": p_info["name"], "preset_badge": p_info["badge"],
        "preset_risk": p_info["risk"], "preset_cagr": p_info["expected_cagr"], "preset_rationale": p_info["rationale"],
        "preset_risk_downside": p_info["risk_downside"], "preset_risk_upside": p_info["risk_upside"],
        "preset_bogle_link": p_info["bogle_link"], "preset_link_text": p_info["link_text"],
        "active_horizon": active_horizon, "show_proj": show_proj, "horizon_yrs": horizon_yrs,
        "horizon_range_str": f"{fmt_currency(sum_v_min, 0)} – {fmt_currency(sum_v_max, 0)}" if show_proj else "",
        "horizon_floor_negative": net_min < 0, "horizon_floor_pct": pct_min_tot, "horizon_ceil_pct": pct_max_tot,
        "active_drift": f"{active_drift:.2f}", "policy": policy, "rebalance_steps": rebalance_steps,
        "tot_portfolio_badge": f"{fmt_currency(tot_port, 0)} Total Portfolio",
        "us_equity": fmt_currency(us_eq, 0), "intl_equity": fmt_currency(intl_eq, 0),
        "bonds": fmt_currency(bonds_val, 0), "cash": fmt_currency(cash, 0),
        "real_estate": fmt_currency(re_val, 0), "private": fmt_currency(total_priv_val, 0),
        "us_equity_raw": us_eq, "intl_equity_raw": intl_eq, "bonds_raw": bonds_val,
        "cash_raw": cash, "real_estate_raw": re_val, "private_raw": total_priv_val,
        "private_count": f"{priv_count} Holding{'s' if priv_count != 1 else ''}" if priv_count else "0 Holdings",
        "private_rows": priv_rows, "private_foot_value": fmt_currency(total_priv_val, 2),
        "private_badge_total": f"{fmt_currency(total_priv_val, 0)} Total NAV", "private_badge_count": f"{priv_count} Holdings",
        "deltas_rows": deltas_rows, "deltas_foot": deltas_foot, "brokerage_accounts": brokerage_accounts,
        "lp_book": get_lp_commitments_summary(family_id=family_id),
    }


def parse_changelog_releases(max_releases: int = 3) -> list[dict[str, Any]]:
    """Parses CHANGELOG.md into structured release objects for semantic SSR rendering without Jinja `| safe`."""
    return _shared_parse_changelog_releases(config.BASE_DIR / "CHANGELOG.md", max_releases=max_releases)
