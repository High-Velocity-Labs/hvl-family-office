"""
SSR view-model builder for Overview hero KPI cards.
"""

from __future__ import annotations
import logging

import db
import equity_engine
import monarch_service
import security
from routes.helpers import DB_PATH
from ssr.accounts import build_ssr_accounts
from ssr.formatting import fmt_currency, fmt_short_currency
from ssr.onboarding import build_onboarding_state
from ssr.scenarios import build_ssr_scenarios
from ssr.settings import build_ssr_settings

logger = logging.getLogger(__name__)


def build_ssr_overview(snapshot: dict, private_investments: dict | None = None, family_id: int = 0) -> dict:
    """Prepares formatted strings for SSR hero KPI cards and customizable widgets on initial landing."""
    from ssr.widgets import build_overview_widgets

    onboarding = build_onboarding_state(family_id=family_id) if family_id > 0 else {}
    widgets_state = build_overview_widgets(family_id=family_id, snapshot=snapshot)
    if not snapshot:
        res: dict = {"widgets": widgets_state}
        if onboarding:
            res["onboarding"] = onboarding
        return res
    equity_data = snapshot.get("company_equity") or {}
    strike_cost = float(equity_data.get("total_strike_cost_needed") or 0.0)
    tax_drag = float(equity_data.get("total_tax_drag") or 0.0)
    has_strike = strike_cost > 0
    has_tax_drag = tax_drag > 0
    has_adjustment = has_strike or has_tax_drag

    if has_strike and has_tax_drag:
        net_worth_label = "NET WORTH (POST-TAX & STRIKE)"
    elif has_tax_drag:
        net_worth_label = "NET WORTH (POST-TAX)"
    elif has_strike:
        net_worth_label = "NET WORTH (POST-STRIKE)"
    else:
        net_worth_label = "TOTAL NET WORTH"

    if has_adjustment:
        parts = []
        if has_strike:
            parts.append(f"-{fmt_short_currency(strike_cost)} strike")
        if has_tax_drag:
            parts.append(f"-{fmt_short_currency(tax_drag)} tax")
        net_worth_sub = f"Adjusted: {', '.join(parts)}"
    else:
        net_worth_sub = "Consolidated balance sheet"

    company_name = equity_data.get("company_name") or "Company"
    if has_adjustment:
        equity_label = f"{company_name.upper()} POST-TAX EQUITY"
    else:
        equity_label = f"{company_name.upper()} EQUITY"

    categories = snapshot.get("categories") or {}
    cash = float((categories.get("cash_liquid") or {}).get("total") or 0.0)
    public_b = float((categories.get("public_brokerage") or {}).get("total") or 0.0)
    liquid_total = cash + public_b

    re_val = float((categories.get("real_estate") or {}).get("total") or 0.0)
    mort = abs(float((categories.get("mortgages") or {}).get("total") or 0.0))
    re_equity = re_val - mort

    ret_val = float((categories.get("retirement") or {}).get("total") or 0.0)

    priv_inv = private_investments or {}
    if "total_value" in priv_inv:
        priv_val = float(priv_inv.get("total_value") or 0.0)
    else:
        priv_val = float((categories.get("private_investments") or {}).get("total") or 0.0)

    if "items" in priv_inv:
        priv_count = len(priv_inv.get("items") or [])
    else:
        priv_count = len((categories.get("private_investments") or {}).get("accounts") or [])

    return {
        "true_net_worth": fmt_currency(snapshot.get("true_net_worth"), 0),
        "net_worth_label": net_worth_label,
        "net_worth_sub": net_worth_sub,
        "monarch_net_worth": fmt_currency(snapshot.get("monarch_reported_net_worth"), 0),
        "equity_label": equity_label,
        "equity_net_value": fmt_currency(equity_data.get("true_net_post_tax_value", 0), 0),
        "equity_gross": f"Gross: {fmt_short_currency(equity_data.get('total_gross_equity_value', 0))}",
        "liquid_portfolio": fmt_currency(liquid_total, 0),
        "liquid_sub": f"Brokerage: {fmt_short_currency(public_b)} | Cash: {fmt_short_currency(cash)}",
        "real_estate_equity": fmt_currency(re_equity, 0),
        "real_estate_sub": f"{fmt_short_currency(re_val)} home less {fmt_short_currency(mort)} debt",
        "private_investments": fmt_currency(priv_val, 0),
        "private_sub": f"{priv_count} Active Private Holdings • Monarch NAV",
        "retirement_assets": fmt_currency(ret_val, 0),
        "onboarding": onboarding,
        "widgets": widgets_state,
    }


def build_dashboard_api_payload(family_id: int) -> dict:
    """Assembles the aggregated Family Office balance sheet and baseline valuation payload."""
    from ssr.formatting import get_private_investments_data

    current_share_price = equity_engine.get_current_409a_price(family_id=family_id)
    snapshot = monarch_service.get_financial_snapshot(share_price=current_share_price, include_wa_tax=False, family_id=family_id)

    transcripts_meta = db.transcripts.get_transcripts_payload(family_id=family_id, db_path=DB_PATH) or {}
    historical_summary = transcripts_meta.get("historical_summary", {})
    safe_harbor_2026 = transcripts_meta.get("safe_harbor_2026_target")
    if safe_harbor_2026 is None:
        prior_fed = float(historical_summary.get("2025", {}).get("federal_tax_withheld", 0.0) or 0.0)
        safe_harbor_2026 = round(prior_fed * 1.10, 2) if prior_fed > 0 else 0.0

    projections = equity_engine.simulate_multi_year_projections(
        annual_growth_rate=0.08, years=5, include_wa_tax_from_year=2028,
        non_equity_net_worth=snapshot.get("non_equity_net_worth", 0.0),
        base_share_price=current_share_price, family_id=family_id,
    )

    return {
        "success": True, "snapshot": snapshot, "historical_transcripts_summary": historical_summary,
        "safe_harbor_2026_target": safe_harbor_2026, "multi_year_projections": projections,
        "spending_summary": monarch_service.get_monarch_spending_history(family_id=family_id),
        "private_investments": get_private_investments_data(family_id=family_id),
    }


def build_networth_history_payload(family_id: int, granularity: str = "auto") -> dict:
    """Returns historical True Net Worth curves (annual, quarterly, monthly), recommended granularity, and annual savings."""
    snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
    current_true_nw = float(snapshot.get("true_net_worth", 0.0))
    equity_data = snapshot.get("company_equity") or snapshot.get("equity_company") or {}
    current_equity_net = float(equity_data.get("true_net_post_tax_value", 0.0))
    cat = snapshot.get("categories", {})
    current_cash = float(cat.get("cash_liquid", {}).get("total", 0.0))
    current_pub = float(cat.get("public_brokerage", {}).get("total", 0.0))
    current_ret = float(cat.get("retirement", {}).get("total", 0.0))
    current_re = float(cat.get("real_estate", {}).get("total", 0.0)) - abs(float(cat.get("mortgages", {}).get("total", 0.0)))

    db_history = security.db_load_encrypted(DB_PATH, "historical_net_worth", family_id=family_id)
    rebuilt_history = None
    monthly_nw: list[dict] = []
    quarterly_nw: list[dict] = []
    if family_id > 0:
        get_hist_fn = getattr(db.accounts, "get_account_balance_history", None)
        try:
            has_snapshots = bool(callable(get_hist_fn) and get_hist_fn(family_id=family_id, db_path=DB_PATH))
        except Exception:
            has_snapshots = False
        if has_snapshots or not db_history:
            rebuild_fn = getattr(db.accounts, "rebuild_historical_net_worth_from_snapshots", None)
            if callable(rebuild_fn):
                try:
                    rebuilt_history = rebuild_fn(family_id=family_id, db_path=DB_PATH, persist=False)
                except TypeError:
                    rebuilt_history = rebuild_fn(family_id=family_id, db_path=DB_PATH)
                except Exception:
                    pass
        series_fn = getattr(db.accounts, "build_dated_net_worth_series", None)
        if callable(series_fn):
            try:
                monthly_nw = series_fn(family_id=family_id, granularity="monthly", db_path=DB_PATH)
                quarterly_nw = series_fn(family_id=family_id, granularity="quarterly", db_path=DB_PATH)
            except Exception:
                pass

    source_history = rebuilt_history if rebuilt_history else db_history
    if source_history:
        historical_nw = [dict(row) for row in source_history if isinstance(row, dict)]
        if historical_nw and historical_nw[-1].get("year") == 2026 and current_true_nw != 0:
            historical_nw[-1].update({
                "true_net_worth": round(current_true_nw), "equity_net": round(current_equity_net),
                "company_net": round(current_equity_net), "liquid_investments": round(current_cash + current_pub + current_ret),
                "real_estate": round(current_re),
            })
    elif family_id > 0 and current_true_nw != 0:
        historical_nw = [{
            "year": 2026, "true_net_worth": round(current_true_nw), "equity_net": round(current_equity_net),
            "company_net": round(current_equity_net), "liquid_investments": round(current_cash + current_pub + current_ret),
            "real_estate": round(current_re),
        }]
    else:
        historical_nw = []

    recommended_gran = "monthly" if (len(historical_nw) < 2 and len(monthly_nw) >= 2) else "annual"
    norm_gran = str(granularity or "auto").strip().lower()
    active_gran = recommended_gran if norm_gran not in ("annual", "quarterly", "monthly") else norm_gran

    return {
        "success": True, "historical_net_worth": historical_nw, "monthly_net_worth": monthly_nw,
        "quarterly_net_worth": quarterly_nw, "recommended_granularity": recommended_gran,
        "active_granularity": active_gran,
        "annual_savings_history": security.db_load_encrypted(DB_PATH, "annual_savings_history", family_id=family_id) or [],
    }


__all__ = [
    "DB_PATH",
    "build_dashboard_api_payload",
    "build_networth_history_payload",
    "build_onboarding_state",
    "build_ssr_accounts",
    "build_ssr_overview",
    "build_ssr_scenarios",
    "build_ssr_settings",
    "db",
    "security",
]
