"""
Monarch unified Family Office financial snapshot and balance sheet aggregation.
"""

from __future__ import annotations
from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import security
import equity_engine

logger = logging.getLogger(__name__)

from monarch.allocation import (
    get_brokerage_and_401k_positions,
    get_detailed_asset_allocation,
)
from monarch.categorizer import (
    ROLE_ALIASES,
    categorize_account,
    get_account_balance,
    get_account_name,
    get_db_path,
    get_family_company_names,
    is_account_hidden_from_family_office,
)


def get_financial_snapshot(
    share_price: Optional[float] = None,
    include_wa_tax: bool = False,
    prior_w2_income: float = 500000.0,
    grants: Optional[List[equity_engine.EquityGrant]] = None,
    family_id: int = 0,
    company_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Computes complete Family Office balance sheet with True Net Worth.
    Dynamically recalculates equity value, strike costs, and tax liabilities.
    """
    db_path = get_db_path()
    is_canonical_call = (
        grants is None
        and share_price is None
        and not include_wa_tax
        and prior_w2_income == 500000.0
        and company_id is None
    )
    snap_params = {
        "share_price": share_price,
        "include_wa_tax": include_wa_tax,
        "prior_w2_income": prior_w2_income,
        "company_id": company_id,
        "db": str(db_path),
    }
    if grants is None and family_id > 0:
        try:
            import forecast_cache
            cached_snap = forecast_cache.get_cached_snapshot(family_id, snap_params)
            if cached_snap is not None:
                return cached_snap
        except Exception:
            pass

    if share_price is None:
        share_price = equity_engine.get_current_409a_price(family_id=family_id)

    import db
    security.init_db(db_path)
    accounts = db.store.get_accounts(family_id=family_id, db_path=db_path)
    raw_holdings = db.store.get_holdings_by_account(family_id=family_id, db_path=db_path)
    if isinstance(raw_holdings, list):
        holdings: Dict[str, Any] = {}
        for h in raw_holdings:
            aid = str(h.get("account_id") or "")
            if aid:
                holdings.setdefault(aid, []).append(h)
    elif isinstance(raw_holdings, dict):
        holdings = raw_holdings
    else:
        holdings = {}
    sync_meta = security.db_load_encrypted(db_path, "last_sync_metadata", family_id=family_id) or {}
    last_sync_time = sync_meta.get("synced_at") or sync_meta.get("timestamp") or "Never"

    categories: Dict[str, Dict[str, Any]] = {
        "cash_liquid": {"label": "Cash & Cash Equivalents", "total": 0.0, "accounts": []},
        "public_brokerage": {"label": "Public Equities & Brokerage", "total": 0.0, "accounts": []},
        "retirement": {"label": "Retirement (401k / IRAs)", "total": 0.0, "accounts": []},
        "education_529": {"label": "Education (529 College Savings)", "total": 0.0, "accounts": []},
        "private_investments": {"label": "Private Equity & Venture Capital", "total": 0.0, "accounts": []},
        "real_estate": {"label": "Real Estate", "total": 0.0, "accounts": []},
        "vehicles": {"label": "Vehicles & Personal Property", "total": 0.0, "accounts": []},
        "mortgages": {"label": "Mortgages & Secured Loans", "total": 0.0, "accounts": []},
        "credit_cards": {"label": "Credit Cards & Short-Term Debt", "total": 0.0, "accounts": []},
        "company_equity_nso": {"label": "Company Stock & Options (Modeled in Equity Engine)", "total": 0.0, "accounts": []},
        "tax_liability": {"label": "Manual Tax Offsets (Modeled in Tax Engine)", "total": 0.0, "accounts": []},
        "hidden_from_family_office": {"label": "Excluded Accounts (Hidden from Family Office)", "total": 0.0, "accounts": []},
        "other_assets": {"label": "Other Assets", "total": 0.0, "accounts": []},
    }

    monarch_reported_net_worth = 0.0

    children_names: List[str] = []
    roles_cache: Dict[str, Tuple[str, bool]] = {}
    family_comps = get_family_company_names(family_id)

    if db_path.exists() and family_id:
        try:
            members = db.store.get_family_members(family_id=family_id, db_path=db_path)
            children_names = [
                str(m.get("name") or "").lower().split()[0]
                for m in members
                if str(m.get("relationship") or "").lower() == "child" and m.get("name")
            ]
            for r in db.store.get_account_roles(family_id=family_id, db_path=db_path):
                acc_id_str = str(r.get("monarch_account_id") or "").strip()
                if acc_id_str:
                    raw_role = str(r.get("role") or "").strip()
                    role_str = ROLE_ALIASES.get(raw_role, raw_role)
                    is_hidden_val = bool(r.get("is_hidden_from_family_office") or 0)
                    roles_cache[acc_id_str] = (role_str, is_hidden_val)
        except Exception as e:
            logger.warning("Failed to load family members or account roles for snapshot: %s", e)

    for acc in accounts:
        bal = get_account_balance(acc)
        raw_name = get_account_name(acc)
        lower_name = raw_name.lower()
        cat = categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps)

        acc_id_str = str(acc.get("id") or "").strip()
        role_entry = roles_cache.get(acc_id_str, ("", False))
        explicit_role = role_entry[0].lower() if role_entry else ""
        is_child_role = explicit_role in ("child", "minor / child", "minor/child") or str(acc.get("role") or "").lower() == "child" or str(acc.get("owner_role") or "").lower() == "child"
        raw_type = acc.get("type")
        acc_type = (raw_type.get("name") if isinstance(raw_type, dict) else str(raw_type or "")).lower()
        is_cash_depository = (cat == "cash_liquid" or acc_type in ("depository", "cash"))
        has_child_word = any(bool(re.search(rf"\b{re.escape(cn)}\b", lower_name)) for cn in children_names) if children_names else False
        is_child_cash = (is_child_role and is_cash_depository) or (has_child_word and any(k in lower_name for k in ("money", "custodial", "utma", "ugma")))
        is_education = cat in ("education_529", "education_530a")
        is_child_account = is_child_cash or is_education

        is_included = (
            acc.get("includeInNetWorth", True) is not False
            and acc.get("includeBalanceInNetWorth", True) is not False
            and not is_child_account
        )
        is_fo_hidden = is_account_hidden_from_family_office(
            str(acc.get("id") or ""), cat, family_id=family_id, roles_cache=roles_cache
        )
        is_hidden = (
            acc.get("hideFromList", False) is True
            or acc.get("isHidden", False) is True
            or is_child_cash
            or is_fo_hidden
        )

        clean_name = raw_name.replace("530A", "Section 530A")

        if is_included:
            monarch_reported_net_worth += bal

        if is_education:
            target_cat = "education_529"
        elif cat in categories:
            target_cat = cat
        elif is_fo_hidden:
            target_cat = "hidden_from_family_office"
        else:
            target_cat = "other_assets"

        if target_cat in categories:
            if not is_fo_hidden:
                if is_included:
                    categories[target_cat]["total"] += bal
                elif is_education:
                    categories["education_529"]["total"] += bal

            raw_acc_type = acc.get("type")
            acc_type_display = (
                (raw_acc_type.get("display") or raw_acc_type.get("name") or "")
                if isinstance(raw_acc_type, dict)
                else str(raw_acc_type or "")
            )
            acc_id_val = str(acc.get("id") or "")
            raw_prov = str(acc.get("provider") or "").lower()
            if acc_id_val.startswith("manual_") or raw_prov == "manual":
                prov = "manual"
                src_label = "Manual"
            elif acc_id_val.startswith("sfin_") or raw_prov == "simplefin":
                prov = "simplefin"
                src_label = "SimpleFIN"
            else:
                prov = "monarch"
                src_label = "Monarch Money"
            inst_obj = acc.get("institution")
            cred_obj = acc.get("credential")
            inst_label = (
                (inst_obj.get("name") if isinstance(inst_obj, dict) else str(inst_obj or ""))
                or (cred_obj.get("displayName") if isinstance(cred_obj, dict) else "")
            ).strip()

            categories[target_cat]["accounts"].append({
                "id": acc.get("id"),
                "name": clean_name,
                "raw_name": raw_name,
                "balance": bal,
                "is_manual": bool(acc.get("isManual", False) or prov == "manual"),
                "type": acc_type_display,
                "provider": prov,
                "source_label": src_label,
                "institution": inst_label,
                "include_in_net_worth": is_included,
                "is_hidden": is_hidden,
                "is_fo_hidden": is_fo_hidden,
                "is_child_account": is_child_account,
                "is_education": is_education,
                "role": cat,
                "minimum_payment": float(acc.get("minimumPayment") or acc.get("plannedPayment") or 0.0),
                "interest_rate": float(acc.get("interestRate") or 0.0),
                "as_of_date": acc.get("as_of_date"),
            })

    education_assets_total = categories["education_529"]["total"]
    categories["education_529"]["label"] = "Education (529 & 530A Custodial Accounts - Excluded from Net Worth)"

    excluded_from_nw = (
        "education_529",
        "education_530a",
        "company_equity_nso",
        "tax_liability",
        "hidden_from_family_office",
    )
    non_equity_net_worth = sum(c["total"] for k, c in categories.items() if k not in excluded_from_nw)

    liquid_non_equity = categories["cash_liquid"]["total"] + categories["public_brokerage"]["total"]

    equity_sim = equity_engine.simulate_valuation_scenario(
        share_price=share_price,
        include_wa_millionaire_tax=include_wa_tax,
        prior_w2_income=prior_w2_income,
        grants=grants,
        family_id=family_id,
        company_id=company_id,
    )

    true_net_worth = non_equity_net_worth + equity_sim["true_net_post_tax_value"]
    nominal_total_net_worth = non_equity_net_worth + equity_sim["total_gross_equity_value"]

    vanguard_and_401k_positions = get_brokerage_and_401k_positions(accounts, holdings)
    detailed_allocation = get_detailed_asset_allocation(
        accounts=accounts,
        holdings_by_account=holdings,
        equity_true_net_value=equity_sim["true_net_post_tax_value"],
        equity_gross_value=equity_sim["total_gross_equity_value"],
        categories=categories,
        family_id=family_id,
        roles_cache=roles_cache,
        family_comps=family_comps,
    )

    mortgage_annual_service = 0.0
    for acc in accounts:
        cat = categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps)
        if cat == "mortgages":
            min_pmt = float(acc.get("minimumPayment") or acc.get("plannedPayment") or 0.0)
            if min_pmt > 0:
                mortgage_annual_service += min_pmt * 12.0
            else:
                bal = abs(get_account_balance(acc))
                rate = float(acc.get("interestRate") or 0.0)
                if bal > 0:
                    r_pct = (rate if rate > 0 else 6.5) / 100.0
                    r_m = r_pct / 12.0
                    n_m = 360
                    pmt = bal * (r_m * ((1.0 + r_m) ** n_m)) / (((1.0 + r_m) ** n_m) - 1.0)
                    mortgage_annual_service += pmt * 12.0

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_monarch_sync": last_sync_time,
        "mortgage_annual_service": round(mortgage_annual_service, 2),
        "monarch_reported_net_worth": round(monarch_reported_net_worth, 2),
        "true_net_worth": round(true_net_worth, 2),
        "nominal_gross_net_worth": round(nominal_total_net_worth, 2),
        "nominal_total_net_worth": round(nominal_total_net_worth, 2),
        "company_equity": equity_sim,
        "non_equity_net_worth": round(non_equity_net_worth, 2),
        "liquid_non_equity_assets": round(liquid_non_equity, 2),
        "education_assets": round(education_assets_total, 2),
        "categories": categories,
        "detailed_asset_allocation": detailed_allocation,
        "brokerage_and_401k_positions": vanguard_and_401k_positions,
        "vanguard_and_401k_positions": vanguard_and_401k_positions,
        "accounts_count": len(accounts),
    }
    if grants is None and family_id > 0:
        try:
            import forecast_cache
            forecast_cache.set_cached_snapshot(
                family_id,
                result,
                snap_params,
                persist_l2=is_canonical_call,
            )
        except Exception:
            pass
    return result


get_full_financial_snapshot = get_financial_snapshot
