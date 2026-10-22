"""
Monarch holdings classification and granular asset allocation calculators.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from monarch.categorizer import (
    categorize_account,
    get_account_balance,
    get_account_name,
    get_db_path,
    is_account_hidden_from_family_office,
    load_family_categorization_context,
)

HOLDINGS_ASSET_CLASS = {
    # US Equities
    "VITSX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "VFIAX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "VTSAX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "VTI": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "VOO": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "VIIIX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "FXAIX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "FSKAX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "SWTSX": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "SPYM": {"class": "us_equity", "label": "US Equities (Custodial 530A)", "color": "#10B981"},
    # International Equities
    "VFWAX": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "VTIAX": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "VXUS": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "IXUS": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "FTIHX": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "SWISX": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    # Bonds & Fixed Income
    "VBMPX": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "VBTLX": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "BND": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "AGG": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "FXNAX": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "SWAGX": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "VWIUX": {"class": "bonds", "label": "Municipal Tax-Exempt Bonds", "color": "#D97706"},
    # Cash & Money Market
    "VMFXX": {"class": "cash", "label": "Cash & Money Market", "color": "#64748B"},
    "SPAXX": {"class": "cash", "label": "Cash & Money Market", "color": "#64748B"},
    "FDRXX": {"class": "cash", "label": "Cash & Money Market", "color": "#64748B"},
    "SWVXX": {"class": "cash", "label": "Cash & Money Market", "color": "#64748B"},
    "USD-USD": {"class": "cash", "label": "Cash & Settlement", "color": "#64748B"},
    # Real Estate & REITs
    "VNQ": {"class": "real_estate", "label": "Real Estate / REITs", "color": "#F59E0B"},
    "VGSLX": {"class": "real_estate", "label": "Real Estate / REITs", "color": "#F59E0B"},
    "SCHH": {"class": "real_estate", "label": "Real Estate / REITs", "color": "#F59E0B"},
    "IYR": {"class": "real_estate", "label": "Real Estate / REITs", "color": "#F59E0B"},
}

_FALLBACK_CLASS_META = {
    "equity": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "us_equity": {"class": "us_equity", "label": "US Equities", "color": "#10B981"},
    "international": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "intl_equity": {"class": "intl_equity", "label": "International Equities", "color": "#06B6D4"},
    "fixed_income": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "bonds": {"class": "bonds", "label": "Bonds & Fixed Income", "color": "#F59E0B"},
    "cash": {"class": "cash", "label": "Cash & Money Market", "color": "#64748B"},
    "real_estate": {"class": "real_estate", "label": "Real Estate / REITs", "color": "#F59E0B"},
}


def get_brokerage_and_401k_positions(
    accounts: List[Dict[str, Any]],
    holdings_by_account: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Pulls individual positions and asset class categorization for each brokerage account and 401(k)."""
    result = []

    for acc in accounts:
        name = (acc.get("displayName") or "").strip()
        lower_name = name.lower()
        inst_name = ((acc.get("institution") or {}).get("name") or "").lower()
        acc_id = str(acc.get("id"))

        is_brokerage = (
            "brokerage" in lower_name
            or "taxable" in lower_name
            or "trust" in lower_name
            or "individual" in lower_name
            or "vanguard" in inst_name
            or "vanguard" in lower_name
        ) and "529" not in lower_name and "530a" not in lower_name
        is_401k = "401(k)" in lower_name or "401k" in lower_name
        if not (is_brokerage or is_401k):
            continue

        acc_balance = get_account_balance(acc)
        items = holdings_by_account.get(acc_id, [])
        positions = []
        positions_total = 0.0

        for item in items:
            sec = item.get("security") or {}
            ticker = (sec.get("ticker") or item.get("ticker") or "").strip()
            sec_name = (sec.get("name") or item.get("name") or item.get("security_name") or ticker).strip()
            val = float(item.get("totalValue") if item.get("totalValue") is not None else (item.get("total_value") or 0.0))
            qty = float(item.get("quantity") or 0.0)
            price = (val / qty) if qty > 0 else 0.0

            raw_cls = str(item.get("asset_class") or "").lower().strip()
            meta = HOLDINGS_ASSET_CLASS.get(ticker) or _FALLBACK_CLASS_META.get(raw_cls) or {"class": "other", "label": "Other", "color": "#94A3B8"}
            positions_total += val

            positions.append({
                "ticker": ticker,
                "name": sec_name,
                "asset_class": meta["class"],
                "asset_class_label": meta["label"],
                "color": meta["color"],
                "total_value": round(val, 2),
                "quantity": round(qty, 4),
                "price": round(price, 2),
            })

        unallocated_cash = max(0.0, acc_balance - positions_total)
        if unallocated_cash > 1.0:
            positions.append({
                "ticker": "CASH",
                "name": "Settlement Fund / Uninvested Cash",
                "asset_class": "cash",
                "asset_class_label": "Cash & Money Market",
                "color": "#64748B",
                "total_value": round(unallocated_cash, 2),
                "quantity": round(unallocated_cash, 2),
                "price": 1.0,
            })

        raw_t = acc.get("type")
        display_t = (
            raw_t.get("display", "Brokerage")
            if isinstance(raw_t, dict)
            else (str(raw_t) if raw_t else "Brokerage")
        )

        result.append({
            "account_id": acc_id,
            "account_name": name,
            "balance": round(acc_balance, 2),
            "type": display_t,
            "positions": positions,
            "positions_total": round(sum(p["total_value"] for p in positions), 2),
        })

    return result


get_vanguard_and_401k_positions = get_brokerage_and_401k_positions


def get_detailed_asset_allocation(
    accounts: List[Dict[str, Any]],
    holdings_by_account: Dict[str, Any],
    equity_true_net_value: float = 0.0,
    equity_gross_value: float = 0.0,
    categories: Optional[Dict[str, Dict[str, Any]]] = None,
    family_id: int = 0,
    roles_cache: Optional[Dict[str, Tuple[str, bool]]] = None,
    family_comps: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Computes precise granular asset allocation breaking public equity into:
    US Equities, International Equities, Bonds & Fixed Income, Cash,
    Private PE/VC, Real Estate, Vehicles, and Company Equity.
    Explicitly excludes education accounts (529 / 530A).
    """
    if categories is None:
        categories = {}

    if roles_cache is None or family_comps is None:
        pre_roles, pre_comps = load_family_categorization_context(family_id)
        if roles_cache is None:
            roles_cache = pre_roles
        if family_comps is None:
            family_comps = pre_comps

    totals = {
        "us_equity": 0.0,
        "intl_equity": 0.0,
        "bonds": 0.0,
        "cash_liquid": 0.0,
        "real_estate_reits": 0.0,
    }

    comp_name = "Primary Equity"
    db_path = get_db_path()
    if db_path.exists() and family_id:
        from db.equity import get_primary_company_name
        comp_name = get_primary_company_name(family_id=family_id, db_path=db_path)

    for acc in accounts:
        cat = categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps)
        acc_id = str(acc.get("id"))
        bal = get_account_balance(acc)

        if (
            cat in ("education_529", "education_530a", "manual_tax_offset", "tax_liability", "company_equity_nso")
            or is_account_hidden_from_family_office(acc_id, cat, family_id=family_id, roles_cache=roles_cache)
        ):
            continue

        if cat in ("public_brokerage", "retirement"):
            items = holdings_by_account.get(acc_id, [])
            items_sum = 0.0
            for item in items:
                sec = item.get("security") or {}
                ticker = (sec.get("ticker") or item.get("ticker") or "").strip()
                val = float(item.get("totalValue") if item.get("totalValue") is not None else (item.get("total_value") or 0.0))
                items_sum += val
                raw_cls = str(item.get("asset_class") or "").lower().strip()
                cls_info = HOLDINGS_ASSET_CLASS.get(ticker) or _FALLBACK_CLASS_META.get(raw_cls) or {"class": "us_equity"}
                cls_key = cls_info["class"]
                if cls_key in totals:
                    totals[cls_key] += val
                elif cls_key == "cash":
                    totals["cash_liquid"] += val
                elif cls_key == "real_estate":
                    totals["real_estate_reits"] += val
                else:
                    totals["us_equity"] += val

            unallocated = max(0.0, bal - items_sum)
            if unallocated > 1.0:
                totals["cash_liquid"] += unallocated
        elif cat == "cash_liquid":
            totals["cash_liquid"] += bal

    real_estate = categories.get("real_estate", {}).get("total", 0.0) + totals.get("real_estate_reits", 0.0)
    private_investments = categories.get("private_investments", {}).get("total", 0.0)
    vehicles = categories.get("vehicles", {}).get("total", 0.0)

    total_wealth_net = (
        totals["us_equity"]
        + totals["intl_equity"]
        + totals["bonds"]
        + totals["cash_liquid"]
        + private_investments
        + real_estate
        + vehicles
        + equity_true_net_value
    )

    allocation_items = [
        {"key": "company_equity", "label": f"{comp_name} (Post-Tax Net)", "value": round(equity_true_net_value, 2), "color": "#059669"},
        {"key": "us_equity", "label": "US Equities", "value": round(totals["us_equity"], 2), "color": "#059669"},
        {"key": "intl_equity", "label": "International Equities", "value": round(totals["intl_equity"], 2), "color": "#0284C7"},
        {"key": "real_estate", "label": "Real Estate", "value": round(real_estate, 2), "color": "#D97706"},
        {"key": "bonds", "label": "Bonds & Fixed Income", "value": round(totals["bonds"], 2), "color": "#7C3AED"},
        {"key": "private_investments", "label": "Private VC & Angel", "value": round(private_investments, 2), "color": "#1D4ED8"},
        {"key": "cash_liquid", "label": "Cash & Money Market", "value": round(totals["cash_liquid"], 2), "color": "#64748B"},
        {"key": "vehicles", "label": "Vehicles & Personal Property", "value": round(vehicles, 2), "color": "#94A3B8"},
    ]

    for item in allocation_items:
        item["percentage"] = round((item["value"] / total_wealth_net * 100), 2) if total_wealth_net > 0 else 0.0

    return {
        "items": allocation_items,
        "totals": {
            "us_equity": round(totals["us_equity"], 2),
            "intl_equity": round(totals["intl_equity"], 2),
            "bonds": round(totals["bonds"], 2),
            "cash_liquid": round(totals["cash_liquid"], 2),
            "private_investments": round(private_investments, 2),
            "real_estate": round(real_estate, 2),
            "real_estate_reits": round(totals.get("real_estate_reits", 0.0), 2),
            "vehicles": round(vehicles, 2),
            "company_equity_true_net": round(equity_true_net_value, 2),
            "company_equity_gross": round(equity_gross_value, 2),
            "total_wealth_net": round(total_wealth_net, 2),
        },
    }
