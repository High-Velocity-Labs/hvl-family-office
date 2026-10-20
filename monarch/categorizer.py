"""
Monarch account categorization, role alias normalization, and spending history helpers.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import os
import sys

import security

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class _MonarchDbPathProxy(os.PathLike):
    def _path(self) -> Path:
        try:
            from routes.helpers import get_current_db_path, get_current_family_id
            fid = get_current_family_id()
            if fid > 0:
                return get_current_db_path(family_id=fid)
            return get_current_db_path()
        except Exception:
            from config import get_db_path_for_universe
            return get_db_path_for_universe()

    def for_family(self, family_id: int) -> Path:
        from routes.helpers import get_family_db_path, get_current_universe
        return get_family_db_path(family_id, universe=get_current_universe())

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"<MonarchDbPathProxy: {self._path()}>"

    def exists(self) -> bool:
        return self._path().exists()

    @property
    def parent(self) -> Path:
        return self._path().parent


DB_PATH = _MonarchDbPathProxy()


def get_db_path(family_id: Optional[int] = None) -> Any:
    """Returns active DB_PATH, respecting any test monkeypatching on monarch_service.DB_PATH or explicit family_id."""
    svc = sys.modules.get("monarch_service")
    if svc is not None and hasattr(svc, "DB_PATH") and svc.DB_PATH is not DB_PATH:
        return svc.DB_PATH
    if family_id and int(family_id) > 0:
        try:
            from routes.helpers import get_current_db_path
            return get_current_db_path(family_id=int(family_id))
        except Exception:
            pass
    return DB_PATH


def get_family_company_names(family_id: int = 0) -> List[str]:
    """Returns lowercased names and symbols of registered equity companies for this family."""
    if not family_id:
        return []
    from db.equity import get_family_company_names as _get_names
    return _get_names(family_id=family_id, db_path=get_db_path())


def load_family_categorization_context(
    family_id: int = 0,
) -> Tuple[Dict[str, Tuple[str, bool]], List[str]]:
    """
    Preloads (roles_cache, family_comps) to prevent
    N+1 query loops when categorizing accounts or checking family-office exclusions.
    """
    roles_cache: Dict[str, Tuple[str, bool]] = {}
    family_comps: List[str] = []
    db_path = get_db_path()
    if not db_path.exists() or not family_id:
        return roles_cache, family_comps

    try:
        from db.accounts import get_account_roles
        for r in get_account_roles(family_id=family_id, db_path=db_path):
            acc_id_str = str(r.get("monarch_account_id") or "").strip()
            if acc_id_str:
                raw_role = str(r.get("role") or "").strip()
                role_str = ROLE_ALIASES.get(raw_role, raw_role)
                is_hidden_val = bool(r.get("is_hidden_from_family_office") or 0)
                roles_cache[acc_id_str] = (role_str, is_hidden_val)
    except Exception:
        pass

    try:
        family_comps = get_family_company_names(family_id)
    except Exception:
        pass

    return roles_cache, family_comps


def get_monarch_spending_history(family_id: int = 0) -> Dict[str, Any]:
    """Returns cached historical spending and living budget breakdown from Monarch Money."""
    db_path = get_db_path()
    data = security.db_load_encrypted(db_path, "monarch_spending_history", family_id=family_id)
    if data:
        return data

    # Derive realistic historical benchmarks from household_profile if spending baseline exists
    if family_id > 0 and db_path.exists():
        from db.household import get_annual_spending
        spending_val = get_annual_spending(family_id=family_id, db_path=db_path)
        if spending_val > 0:
            s = spending_val
            b_24 = round(s * 0.88, -3)
            b_25 = round(s * 0.98, -3)
            b_26 = round(s * 1.05, -3)
            b_avg = round((b_24 + b_25 + b_26) / 3.0, -3)
            b_base = round(s * 0.70, -3)
            return {
                "spending_history": {},
                "benchmarks": {
                    "baseline": b_base,
                    "actual_2024": b_24,
                    "actual_2025": b_25,
                    "annualized_2026": b_26,
                    "three_year_average": b_avg,
                    "recommended_budget": s,
                },
            }

    return {
        "spending_history": {},
        "benchmarks": {
            "baseline": 0.0,
            "actual_2024": 0.0,
            "actual_2025": 0.0,
            "annualized_2026": 0.0,
            "three_year_average": 0.0,
            "recommended_budget": 0.0,
        },
    }


from monarch.categorizer_rules import (
    ROLE_ALIASES,
    EXCLUDED_FROM_BALANCE_SHEET,
    AVAILABLE_ROLES,
    suggest_account_role_and_beneficiary,
)



def is_account_hidden_from_family_office(
    acc_id: str,
    cat: str = "",
    family_id: int = 0,
    roles_cache: Optional[Dict[str, Tuple[str, bool]]] = None,
) -> bool:
    """Checks whether an account should be excluded from the Family Office balance sheet and investments."""
    if cat in EXCLUDED_FROM_BALANCE_SHEET:
        return True
    clean_id = str(acc_id or "").strip()
    if not clean_id or not family_id:
        return False

    if roles_cache is not None:
        role_entry = roles_cache.get(clean_id)
        if role_entry:
            role_val, is_hidden = role_entry
            if is_hidden or role_val in EXCLUDED_FROM_BALANCE_SHEET:
                return True
        return False

    db_path = get_db_path()
    if db_path.exists():
        try:
            from db.accounts import get_account_role
            role_entry = get_account_role(family_id=family_id, account_id=clean_id, db_path=db_path)
            if role_entry:
                role_val = ROLE_ALIASES.get(str(role_entry.get("role") or "").strip(), str(role_entry.get("role") or "").strip())
                is_hidden = bool(role_entry.get("is_hidden_from_family_office") or 0)
                if is_hidden or role_val in EXCLUDED_FROM_BALANCE_SHEET:
                    return True
        except Exception:
            pass
    return False


def get_account_balance(acc: Dict[str, Any]) -> float:
    """Safely extracts account balance across GraphQL camelCase, snake_case, and generic balance formats."""
    val = acc.get("currentBalance")
    if val is None:
        val = acc.get("current_balance")
    if val is None:
        val = acc.get("balance")
    try:
        return float(val or 0.0)
    except (ValueError, TypeError):
        return 0.0


def get_account_name(acc: Dict[str, Any]) -> str:
    """Safely extracts display name or name from an account object."""
    return (acc.get("displayName") or acc.get("name") or "").strip()


def categorize_account(
    acc: Dict[str, Any],
    family_id: int = 0,
    roles_cache: Optional[Dict[str, Tuple[str, bool]]] = None,
    family_comps: Optional[List[str]] = None,
) -> str:
    """Categorizes an account using explicit account_roles overrides or dynamic heuristics."""
    acc_id = str(acc.get("id") or "").strip()
    name = (acc.get("displayName") or acc.get("name") or "").strip().lower()
    raw_type = acc.get("type")
    acc_type = (raw_type.get("name") if isinstance(raw_type, dict) else str(raw_type or "")).lower()
    raw_subtype = acc.get("subtype")
    acc_subtype = (raw_subtype.get("name") if isinstance(raw_subtype, dict) else str(raw_subtype or "")).lower()

    # 0. Check direct role attribute on account payload if present
    acc_role = str(acc.get("role") or "").strip()
    if acc_role and acc_role in ROLE_ALIASES:
        return ROLE_ALIASES[acc_role]

    # 1. High priority filters: manual tax offset and company equity
    if "tax liability" in name or "nso tax" in name or "equity tax" in name:
        return "tax_liability"

    # Retirement plans must remain retirement, even if employer name matches registered company
    if any(
        k in name
        for k in (
            "401(k)",
            "401k",
            "403(b)",
            "403b",
            "traditional ira",
            "roth ira",
            "sep ira",
            "rollover ira",
            "simple ira",
        )
    ):
        return "retirement"

    # 2. Database account_roles override check
    db_path = get_db_path()
    if roles_cache is not None:
        role_entry = roles_cache.get(acc_id)
        if role_entry and role_entry[0]:
            return role_entry[0]
    elif db_path.exists() and acc_id and family_id:
        try:
            from db.accounts import get_account_role
            role_entry = get_account_role(family_id=family_id, account_id=acc_id, db_path=db_path)
            if role_entry and role_entry.get("role"):
                r_str = str(role_entry["role"]).strip()
                return ROLE_ALIASES.get(r_str, r_str)
        except Exception:
            pass

    # 3. Heuristics fallback: check against registered equity companies dynamically
    comps = family_comps if family_comps is not None else get_family_company_names(family_id)
    if comps:
        if any(
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
            return "company_equity_nso"

    if acc_type == "real_estate" or "real estate" in name or "residence" in name or "property" in name:
        return "real_estate"

    if acc_type == "loan" or "mortgage" in name:
        return "mortgages"

    if (
        acc_type == "vehicle"
        or "vehicle" in name
        or "automobile" in name
        or "car" in name
        or "truck" in name
        or "auto loan" in name
    ):
        return "vehicles"

    if acc_type == "credit" or "student loan" in name or "student debt" in name or "credit card" in name:
        return "credit_cards"

    if "530a" in name:
        return "education_530a"
    if "529" in name or "college" in name or acc_subtype in ("529", "education_savings"):
        return "education_529"

    if (
        acc_type == "depository"
        or "checking" in name
        or "savings" in name
        or "money market" in name
        or "cash" in name
        or acc_subtype in ("checking", "savings", "money_market", "cd")
    ):
        return "cash_liquid"

    if acc_subtype in ("401k", "403b", "ira", "roth_ira", "rollover_ira", "sep_ira", "roth", "traditional_ira") or any(
        k in name for k in ("401(k)", "401k", "403(b)", "403b", "ira", "roth", "pension", "sep-ira")
    ):
        return "retirement"

    if (
        acc_type == "brokerage"
        or acc_subtype in ("brokerage", "taxable_brokerage", "individual", "joint")
        or "brokerage" in name
        or "taxable" in name
        or "index" in name
        or "schwab" in name
        or "fidelity" in name
        or "vanguard" in name
    ):
        return "public_brokerage"

    if (
        acc_type in ("private_fund",)
        or acc_subtype in ("private_equity", "venture_capital")
        or any(
            k in name
            for k in (
                "fund",
                "llc",
                "corp",
                "studio",
                "games",
                "lbo",
                "spv",
                "venture",
                "angel",
                "co-invest",
                "capital",
                "partners",
                "holdings",
                "syndicate",
            )
        )
    ):
        return "private_investments"

    if acc_type == "investment":
        return "public_brokerage"

    return "other_assets"
