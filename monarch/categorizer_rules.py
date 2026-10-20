"""
monarch/categorizer_rules.py: Account role catalogs, aliases, and role suggestion heuristics.
Extracted from monarch/categorizer.py.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

ROLE_ALIASES = {
    "cash_reserve": "cash_liquid",
    "cash_liquid": "cash_liquid",
    "checking": "cash_liquid",
    "savings": "cash_liquid",
    "money_market": "cash_liquid",
    "liquid_portfolio": "public_brokerage",
    "public_brokerage": "public_brokerage",
    "brokerage": "public_brokerage",
    "taxable_brokerage": "public_brokerage",
    "retirement": "retirement",
    "retirement_tax_deferred": "retirement",
    "retirement_roth": "retirement",
    "401k": "retirement",
    "403b": "retirement",
    "ira": "retirement",
    "roth_ira": "retirement",
    "sep_ira": "retirement",
    "education_529": "education_529",
    "education_530a": "education_530a",
    "real_estate": "real_estate",
    "mortgage": "mortgages",
    "mortgage_liability": "mortgages",
    "mortgages": "mortgages",
    "auto_loan": "vehicles",
    "vehicle": "vehicles",
    "vehicles": "vehicles",
    "credit_card": "credit_cards",
    "credit_cards": "credit_cards",
    "student_loan": "credit_cards",
    "student_loan_liability": "credit_cards",
    "donor_advised_fund": "philanthropy",
    "philanthropy": "philanthropy",
    "private_equity": "private_investments",
    "private_investments": "private_investments",
    "manual_tax_offset": "tax_liability",
    "tax_liability": "tax_liability",
    "company_equity_nso": "company_equity_nso",
    "nso_equity": "company_equity_nso",
    "hidden_from_family_office": "hidden_from_family_office",
    "other": "other_assets",
    "other_assets": "other_assets",
}

EXCLUDED_FROM_BALANCE_SHEET = {
    "company_equity_nso",
    "tax_liability",
    "hidden_from_family_office",
    "manual_tax_offset",
    "nso_equity",
}

AVAILABLE_ROLES = [
    {"role": "cash_liquid", "label": "Cash / Liquid Checking & Savings"},
    {"role": "public_brokerage", "label": "Taxable Public Brokerage"},
    {"role": "retirement", "label": "Retirement (401k / IRA / Roth)"},
    {"role": "education_529", "label": "Education 529 Plan"},
    {"role": "education_530a", "label": "Education 530A Custodial Account"},
    {"role": "real_estate", "label": "Real Estate / Primary Property"},
    {"role": "mortgages", "label": "Mortgage / Secured Loan"},
    {"role": "credit_cards", "label": "Credit Card / Short-Term Liability"},
    {"role": "private_investments", "label": "Private Equity / Angel Investment"},
    {"role": "donor_advised_fund", "label": "Philanthropy / DAF"},
    {"role": "vehicles", "label": "Vehicles & Personal Property"},
    {"role": "company_equity_nso", "label": "Company Stock / NSO (Modeled in Equity Engine - Excluded from Family Office Balance Sheet)"},
    {"role": "tax_liability", "label": "Manual Tax Liability / Offset (Excluded from Family Office Balance Sheet)"},
    {"role": "hidden_from_family_office", "label": "Hidden from Family Office (Excluded from Balance Sheet & Investments)"},
    {"role": "other_assets", "label": "Other Asset / Liability"},
]


def suggest_account_role_and_beneficiary(
    acc: Dict[str, Any],
    children: List[Dict[str, Any]],
    family_id: int = 0,
    family_comps: Optional[List[str]] = None,
) -> Tuple[str, Optional[int]]:
    """Suggests an account role and child beneficiary without consulting DB account_roles overrides."""
    name = (acc.get("displayName") or acc.get("name") or "").strip().lower()
    raw_type = acc.get("type")
    acc_type = (raw_type.get("name") if isinstance(raw_type, dict) else str(raw_type or "")).lower()
    raw_subtype = acc.get("subtype")
    acc_subtype = (raw_subtype.get("name") if isinstance(raw_subtype, dict) else str(raw_subtype or "")).lower()

    if "tax liability" in name or "nso tax" in name or "equity tax" in name:
        return "tax_liability", None
    if "401(k)" in name or "401k" in name:
        return "retirement", None

    if family_comps is not None:
        comps = family_comps
    else:
        from monarch.categorizer import get_family_company_names
        comps = get_family_company_names(family_id)

    if comps and any(
        c == name
        or (
            c in name
            and (
                acc_type in ("equity", "investment", "brokerage")
                or "nso" in name
                or "stock" in name
                or "equity" in name
            )
        )
        for c in comps
    ):
        return "company_equity_nso", None

    beneficiary_id = None
    for ch in children:
        c_name = (ch.get("name") or "").lower()
        f_name = (ch.get("first_name") or (c_name.split()[0] if c_name else "")).lower()
        if f_name and f_name in name:
            beneficiary_id = ch.get("user_id")
            break

    if "530a" in name:
        return "education_530a", beneficiary_id
    if "529" in name or "college" in name or acc_subtype in ("529", "st_529", "education_savings"):
        return "education_529", beneficiary_id
    if acc_type == "real_estate" or "real estate" in name or "residence" in name or "property" in name:
        return "real_estate", beneficiary_id
    if acc_type == "loan" or "mortgage" in name:
        return "mortgages", beneficiary_id
    if acc_type == "credit" or "credit card" in name or "visa" in name or "mastercard" in name or "student loan" in name or "student debt" in name:
        return "credit_cards", beneficiary_id
    if (
        "401k" in name
        or "401(k)" in name
        or "ira" in name
        or "roth" in name
        or "pension" in name
        or acc_subtype in ("401k", "st_401k", "403b", "ira", "roth", "roth_ira", "rollover_ira", "sep_ira", "simple_ira", "traditional_ira")
    ):
        return "retirement", beneficiary_id
    if "daf" in name or "donor advised" in name or "charit" in name or "foundation" in name:
        return "donor_advised_fund", beneficiary_id
    if (
        acc_type in ("investment", "private_fund", "equity")
        or acc_subtype in ("private_equity", "venture_capital", "equity")
        or any(
            k in name
            for k in (
                "fund",
                "spv",
                "studio",
                "games",
                "llc",
                "corp",
                "lbo",
                "angel",
                "venture",
                "co-invest",
            )
        )
    ):
        return "private_investments", beneficiary_id
    if acc_type == "vehicle" or any(k in name for k in ("vehicle", "automobile", "auto loan", "taycan", "rivian")):
        return "vehicles", beneficiary_id
    if acc_type == "brokerage" or "brokerage" in name or "stock" in name or acc_subtype in ("brokerage", "stock_plan", "taxable_brokerage", "individual", "joint"):
        return "public_brokerage", beneficiary_id
    if acc_type == "depository" or any(k in name for k in ("checking", "savings", "money market", "paypal", "cash")) or acc_subtype in ("checking", "savings", "money_market", "cd"):
        return "cash_liquid", beneficiary_id

    return "other_assets", beneficiary_id
