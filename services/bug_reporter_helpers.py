"""
Pane invariant manifests, live numeric reconciliation walkthroughs, and
AI Triage prompt formatting helpers for the Pane Bug Reporter service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

VALID_PANES: tuple[str, ...] = (
    "overview",
    "equity",
    "scenarios",
    "holdings",
    "arbitrage",
    "compensation",
    "philanthropy",
    "gifting",
    "estate",
    "college",
    "accounts",
    "settings",
)
VALID_CATEGORIES: tuple[str, ...] = ("math", "sync", "ui", "permission")


def _m(
    t: str,
    m: str,
    f: str,
    invs: list[str],
    gotchas: list[str],
    mode: str = "isomorphic_scale",
) -> dict[str, Any]:
    return {
        "title": t,
        "suspected_module": m,
        "formula_summary": f,
        "invariants": invs,
        "common_gotchas": gotchas,
        "anonymization_mode": mode,
    }


PANE_MANIFESTS: dict[str, dict[str, Any]] = {
    "overview": _m(
        "Net Worth & Overview",
        "monarch_service.py :: get_consolidated_balance_sheet",
        "Net Worth = Total Assets - Total Liabilities.",
        [
            "Net Worth = Sum(Active Balances) + Vested Equity - Liabilities",
            "Runway = Cash / Spending",
        ],
        [
            "Unvested equity excluded from net worth",
            "Inactive accounts excluded",
            "Aggregator sync lag may cause divergence",
        ],
    ),
    "equity": _m(
        "Equity & RSUs",
        "equity_engine.py :: get_equity_summary",
        "Gross Vest FMV = Shares × Price. Net Proceeds = Gross Spread - Exercise Cost - Withholding.",
        [
            "Total Grant Value = Vested Value + Unvested Value",
            "Net Vest Proceeds = Gross Spread - Strike Cost - Withholding",
        ],
        [
            "Federal withholding jumps from 22% to 37% for wages > $1M",
            "WA 7% LTCG tax applies above $250k deduction",
            "Unvested grants fluctuate with market price",
        ],
    ),
    "scenarios": _m(
        "Scenarios & Monte Carlo",
        "forecast_engine.py :: run_financial_forecast",
        "Terminal Wealth = Beginning Wealth × (1 + Return - Inflation) + Savings - Spending - Taxes.",
        [
            "Probability of Success = Percentage of trials with terminal wealth > $0",
            "Real wealth adjusts cashflows by inflation",
        ],
        [
            "Real vs Nominal dollars toggle alters balance view",
            "Early sequence-of-returns risk affects 10th percentile",
            "Spending guardrails trigger in drawdown years",
        ],
    ),
    "holdings": _m(
        "Holdings & Asset Allocation",
        "monarch_service.py :: get_holdings_allocation",
        "Asset Allocation % = Class Value / Total Investable Value.",
        [
            "Sum of all asset allocation percentages equals 100.0%",
            "Total Investable Assets matches sum of investment balances",
        ],
        [
            "Brokerage sweep cash is classified under Cash",
            "Target drift is relative to policy presets",
            "Uncategorized tickers fall into Other/Alternatives",
        ],
    ),
    "arbitrage": _m(
        "Tax Arbitrage",
        "tax_engine.py :: calculate_tax_projection",
        "Tax Delta = Effective Tax on Conversion - Marginal Tax in Retirement.",
        [
            "Tax Delta = Projected Future Tax Saved - Immediate Tax Paid",
            "Total Conversion = Sum of bracket tranches converted",
        ],
        [
            "NIIT (3.8%) and state taxes apply when MAGI exceeds thresholds",
            "Medicare IRMAA creates cliff brackets 2 years later",
            "TCJA sunset changes long-term brackets",
        ],
        "statutory_delta",
    ),
    "compensation": _m(
        "Executive Compensation & W-2",
        "tax_engine.py :: calculate_tax_projection",
        "Total Comp = Base Salary + Bonus + Vested Equity. Box 1 Wages = Gross Wages - Pre-Tax Deductions.",
        [
            "Taxable Box 1 Wages = Gross Total Comp - Pre-Tax Deductions (401k/HSA)",
            "Take-Home Pay = Gross Earnings - Taxes - Deductions",
        ],
        [
            "Social Security wage base caps at annual limit",
            "Pre-tax 401(k) reduces Box 1 but not Box 3 wages",
            "Filing status alters standard deduction and brackets",
        ],
        "statutory_delta",
    ),
    "philanthropy": _m(
        "Philanthropy & DAF",
        "tax_engine.py :: calculate_charitable_deduction",
        "Charitable Tax Savings = Contributed FMV × Marginal Rate. AGI Deduction Cap: 60% cash, 30% assets.",
        [
            "Deductible Amount = Min(Charitable Contribution, AGI Limit)",
            "5-Year Carryforward = Unused Contribution exceeding AGI cap",
        ],
        [
            "Donating appreciated stock avoids capital gains tax and deducts full FMV",
            "Excess contributions carry forward for 5 years",
            "DAF bunching clears standard deduction hurdle",
        ],
    ),
    "gifting": _m(
        "Annual Exclusion Gifting",
        "estate.py :: calculate_gifting_allowance",
        "Tax-Free Annual Exclusion = Statutory Limit per donor per donee. Lifetime Exemption absorbs excess.",
        [
            "Annual Tax-Free Gifting = Number of Donees × Annual Exclusion Limit ($19,000 / $38,000 MFJ)",
            "Taxable Gifts = Max(0, Total Gifts - Annual Exclusions)",
        ],
        [
            "Gift-splitting requires filing Form 709",
            "Direct tuition or medical payments are exempt",
            "529 superfunding allows 5-year front-loading",
        ],
    ),
    "estate": _m(
        "Estate Planning & Inheritance",
        "estate.py :: run_estate_distribution",
        "Gross Estate = Real + Tangible + Intangible Assets + Life Insurance. Taxable = Gross - Deductions.",
        [
            "Federal Estate Tax = Max(0, Taxable Estate - Remaining Lifetime Exemption) × 40%",
            "Net Inheritance = Gross Estate - Taxes - Administrative Costs",
        ],
        [
            "WA estate tax has a lower exemption threshold without portability",
            "ILIT removes life insurance proceeds from estate",
            "Scheduled sunset of TCJA exemption affects future estates",
        ],
        "statutory_delta",
    ),
    "college": _m(
        "College Education (529)",
        "education.py :: project_college_savings",
        "Future Cost = Tuition × (1 + Inflation)^Years. Projected 529 = Current × (1 + Return)^Years + Contributions.",
        [
            "Funding Surplus/Shortfall = Projected 529 Balance - Total Projected Cost",
            "Qualified Withdrawals = 100% Tax-Free",
        ],
        [
            "Higher education inflation typically exceeds CPI",
            "SECURE 2.0 allows up to $35k rollover into Roth IRA",
            "Room and board requires at least half-time enrollment",
        ],
    ),
    "accounts": _m(
        "Accounts & Institutions",
        "monarch_service.py :: list_accounts",
        "Total Balance = Sum of all active depository, investment, loan, and credit balances.",
        [
            "Total Household Accounts = Active Accounts + Inactive Accounts",
            "Total Net Balance = Positive Assets - Liabilities",
        ],
        [
            "Aggregator sync latency may take up to 24 hours",
            "Duplicate accounts may appear if manually tracked overlap with feeds",
            "Inverted liability sign depends on institution",
        ],
    ),
    "settings": _m(
        "Household Settings & Access",
        "security.py :: get_family_key",
        "Cryptographic Household Vault Protocol: Zero-Knowledge Support Access with Browser/Drive Escrow.",
        [
            "Support Access = 0 ensures FEK is completely NULL in database",
            "Role permissions: Admin > Editor > Viewer",
        ],
        [
            "Toggling Support Access OFF purges escrowed FEK immediately",
            "Sandbox sessions cannot toggle persistent escrow",
            "Demo persona is strictly read-only",
        ],
    ),
}


def _build_live_numeric_walkthrough(clean_pane: str, family_id: int, db_path: Optional[Path]) -> list[str]:
    """Computes live dollar reconciliation lines for the active pane to show the user how their numbers add up."""
    if family_id <= 0:
        return []
    lines: list[str] = []
    try:
        import equity_engine
        import monarch_service

        share_price = equity_engine.get_current_409a_price(family_id=family_id)
        snap = monarch_service.get_financial_snapshot(share_price=share_price, include_wa_tax=False, family_id=family_id) or {}
        true_nw = float(snap.get("true_net_worth") or 0.0)
        agg_nw = float(snap.get("monarch_reported_net_worth") or 0.0)
        non_eq = float(snap.get("non_equity_net_worth") or 0.0)
        eq = snap.get("company_equity") or {}
        eq_net = float(eq.get("true_net_post_tax_value") or 0.0)
        eq_gross = float(eq.get("nominal_gross_equity_value") or eq.get("total_gross_equity_value") or 0.0)
        strike = float(eq.get("total_strike_cost_needed") or 0.0)
        tax_drag = float(eq.get("total_tax_drag") or 0.0)
        cats = snap.get("categories") or {}

        def _cat_total(key: str) -> float:
            return float((cats.get(key) or {}).get("total") or 0.0)

        if clean_pane in ("overview", "accounts"):
            delta_nw = true_nw - agg_nw
            delta_fmt = f"+${delta_nw:,.0f}" if delta_nw >= 0 else f"-${abs(delta_nw):,.0f}"
            lines.append(
                f"• Your Live Figures: HVL True Net Worth = ${true_nw:,.0f} vs. Aggregator Reported Net Worth = ${agg_nw:,.0f} (Delta: {delta_fmt})."
            )
            lines.append(
                f"• HVL Formula Breakdown: Active Non-Equity Accounts (${non_eq:,.0f}) + Post-Tax Company Equity (${eq_net:,.0f} [Gross ${eq_gross:,.0f} - Strike ${strike:,.0f} - Tax Drag ${tax_drag:,.0f}]) = ${true_nw:,.0f}."
            )
            excl_map = [
                ("company_equity_nso", "Raw Aggregator Equity Placeholder (replaced by HVL post-tax model)"),
                ("hidden_from_family_office", "Hidden from Family Office"),
                ("education_529", "529/Custodial Education"),
                ("tax_liability", "Tax Liability Reserve"),
            ]
            excl_parts = [f"{lbl} (${_cat_total(key):,.0f})" for key, lbl in excl_map if abs(_cat_total(key)) > 0]
            if excl_parts:
                lines.append(f"• Why They Differ: {', '.join(excl_parts)}.")
        elif clean_pane == "equity":
            lines.append(
                f"• Your Live Equity Figures: Post-Tax Value = ${eq_net:,.0f} (Gross ${eq_gross:,.0f} - Strike Cost ${strike:,.0f} - Estimated Tax Drag ${tax_drag:,.0f} @ ${share_price:,.2f}/sh)."
            )
        elif clean_pane == "holdings":
            lines.append(
                f"• Your Live Portfolio Breakdown: Public Brokerage (${_cat_total('public_brokerage'):,.0f}) + Cash (${_cat_total('cash_liquid'):,.0f}) + Retirement (${_cat_total('retirement'):,.0f}) + Private (${_cat_total('private_investments'):,.0f}) + Post-Tax Equity (${eq_net:,.0f})."
            )
        else:
            from db import families as db_fam

            hp = (db_fam.get_household_profile(family_id=family_id, db_path=db_path) if db_path else None) or {}
            liq_brok = _cat_total("cash_liquid") + _cat_total("public_brokerage")
            ret_tot = _cat_total("retirement")
            lines.append(
                f"• Your Live Context: Baseline True Net Worth = ${true_nw:,.0f} (Liquid & Brokerage ${liq_brok:,.0f}, Retirement ${ret_tot:,.0f}) • Profile: {hp.get('state') or 'WA'} / {hp.get('filing_status') or 'MFJ'}, Target Annual Spend ${float(hp.get('annual_spending') or 0.0):,.0f}."
            )
    except Exception:
        pass
    return lines


def _resolve_app_instance() -> str:
    """Returns the running application instance ('finances-beta', 'finances-local', or 'finances')."""
    import config

    if config.is_local_mode():
        return "finances-local"
    if config.is_beta_instance():
        return "finances-beta"
    return "finances"


def _resolve_app_version(client_context: Optional[dict[str, Any]] = None) -> str:
    """Returns formatted app instance, version, and git SHA, noting if client asset version differs."""
    import config

    instance = _resolve_app_instance()
    semver = str(getattr(config, "APP_VERSION", "0.2.0") or "0.2.0")
    server_asset = ""
    try:
        import app as _app

        server_asset = str(getattr(_app, "ASSET_VERSION", "") or "")
    except Exception:
        pass
    server_sha = server_asset.split("-")[0] if server_asset else ""
    base = f"{instance} v{semver} ({server_sha})" if server_sha else f"{instance} v{semver}"
    client_v = str((client_context or {}).get("client_version") or "").strip()[:40]
    if client_v and server_asset and client_v != server_asset:
        client_sha = client_v.split("-")[0]
        if client_sha and client_sha != server_sha:
            return f"{base} [client: {client_sha}]"
    return base


def format_antigravity_prompt(report: dict[str, Any]) -> str:
    """Formats an anonymized bug report into a copy-pasteable AI Triage Markdown prompt without leaking scale_factor."""
    support = "ON" if report.get("support_access_enabled") else "OFF"
    follow = report.get("scrubbed_followup", "")
    follow_block = f"\n**User Clarification:**\n{follow}\n" if follow else ""
    app_ver = report.get("app_version") or (report.get("sanitized_snapshot") or {}).get("app_version") or "unknown"
    return (
        f"### Bug Report #{report.get('bug_id', 0)}: [{str(report.get('category', 'math')).upper()}] Pane `{report.get('pane', 'overview')}` ({report.get('universe', 'public')})\n"
        f"- **App Version**: `{app_ver}` • **Universe**: `{report.get('universe', 'public')}`\n"
        f"- **Status**: `{report.get('status', 'open')}`\n"
        f"- **Suspected Module**: `{report.get('suspected_module', '')}`\n"
        f"- **User**: `{report.get('user_ref', '')}` (Support Access: `{support}`)\n"
        f"- **Anonymization**: `{report.get('anonymization_mode', 'isomorphic_scale')}` (ephemeral multiplier discarded)\n\n"
        f"#### Mathematical Invariant\n> {report.get('invariant_summary', '')}\n\n"
        f"#### User Observation (Scrubbed & Scaled)\n{report.get('scrubbed_description', '')}\n{follow_block}\n"
        f"#### AI Diagnostic Triage\n{report.get('ai_explanation', '')}\n\n"
        f"#### Anonymized Household Snapshot\n```json\n{json.dumps(report.get('sanitized_snapshot') or {}, indent=2)}\n```"
    )
