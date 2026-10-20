"""
forecast/storage_education.py: Tuition Ledger, 529 Reserves & Child Education Helpers.
Extracted from forecast/storage.py.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import logging

import monarch_service
from db.session import resolve_db_path

logger = logging.getLogger(__name__)


def _resolve_storage_db(family_id: int) -> Path:
    from forecast.storage import get_db_path
    return resolve_db_path(get_db_path(), family_id=family_id)


def load_children_edu_reserves(family_id: int = 0) -> List[Dict[str, Any]]:
    """
    Dynamically loads children, their birthdates, college matriculation years,
    and live 529/530A/Custodial account balances from the database.
    """
    children_reserves = []
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id:
        return children_reserves

    import db
    try:
        members = db.store.get_family_members(family_id=family_id, db_path=active_db)
        children = [m for m in members if m.get("relationship") == "child"]
        if not children:
            return children_reserves
        accounts = db.store.get_accounts(family_id=family_id, db_path=active_db)
    except Exception as e:
        logger.debug("Could not load children edu reserves for family %s: %s", family_id, e)
        return children_reserves

    ben_map = {}
    roles_cache: Dict[str, Tuple[str, bool]] = {}
    try:
        role_rows = db.store.get_account_roles(family_id=family_id, db_path=active_db)
        for r in role_rows:
            aid = str(r.get("monarch_account_id") or "").strip()
            if aid:
                if r.get("beneficiary_user_id") is not None:
                    ben_map[aid] = r["beneficiary_user_id"]
                raw_role = str(r.get("role") or "").strip()
                role_str = monarch_service.ROLE_ALIASES.get(raw_role, raw_role)
                roles_cache[aid] = (role_str, bool(r.get("is_hidden_from_family_office") or 0))
    except Exception:
        pass

    family_comps = monarch_service.get_family_company_names(family_id)

    pre_accounts = []
    for acc in accounts:
        acc_id = str(acc.get("id") or "")
        dname = (acc.get("displayName") or "").lower()
        cat = monarch_service.categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps)
        is_edu = cat in ("education_529", "education_530a") or "529" in dname or "530a" in dname or "college" in dname or "coverdell" in dname
        bal = float(acc.get("currentBalance") or 0.0)
        pre_accounts.append({
            "id": acc_id,
            "displayName": acc.get("displayName"),
            "dname": dname,
            "is_edu": is_edu,
            "balance": bal,
            "ben": ben_map.get(acc_id),
        })

    tuition_grad_map = {}
    try:
        ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
        for cid, yr_map in ledger.items():
            if yr_map:
                tuition_grad_map[cid] = max(yr_map.keys()) + 1
    except Exception:
        pass

    for child in children:
        child_id = child.get("user_id")
        c_name = child.get("name", "Child")
        first_name = c_name.split()[0]
        bdate = child.get("birthdate") or "2015-01-01"
        try:
            byear = int(bdate.split("-")[0])
        except Exception:
            byear = 2015

        college_start = tuition_grad_map.get(child_id) or (byear + 18)

        matched_bal = 0.0
        matched_accounts = []
        fn_lower = first_name.lower()
        for p_acc in pre_accounts:
            is_match = False
            if p_acc["ben"] is not None and p_acc["ben"] == child_id and p_acc["is_edu"]:
                is_match = True
            elif (fn_lower in p_acc["dname"]) and p_acc["is_edu"]:
                is_match = True

            if is_match:
                matched_bal += p_acc["balance"]
                matched_accounts.append({
                    "name": p_acc["displayName"],
                    "balance": p_acc["balance"],
                })

        children_reserves.append({
            "user_id": child_id,
            "name": c_name,
            "first_name": first_name,
            "birthdate": bdate,
            "birth_year": byear,
            "college_start": college_start,
            "current_529_balance": round(matched_bal, 2),
            "accounts": matched_accounts,
        })

    return children_reserves


def load_children_k12_tuition(family_id: int = 0) -> List[Dict[str, Any]]:
    """
    Returns dynamic per-child K-12 private school tuition plans based on decrypted database records.
    Each child gets start_year, end_year, and average annual tuition cost.
    """
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id:
        return []

    import db
    try:
        members = db.store.get_family_members(family_id=family_id, db_path=active_db)
        children = [m for m in members if m.get("relationship") == "child"]
        if not children:
            return []
    except Exception as e:
        logger.debug("Could not load children for family %s: %s", family_id, e)
        return []

    results = []
    try:
        ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
        for child in children:
            c_id = child.get("user_id")
            c_name = child.get("name", "Child")
            f_name = c_name.split()[0]
            bdate = child.get("birthdate") or "2015-01-01"
            try:
                byear = int(bdate.split("-")[0])
            except Exception:
                byear = 2015

            child_years_map = ledger.get(int(c_id), {}) if c_id is not None else {}
            future_years = []
            future_amts = []
            for y, amt in child_years_map.items():
                if y >= 2026 and amt > 0:
                    future_years.append(y)
                    future_amts.append(amt)

            if future_years:
                start_yr = min(future_years)
                end_yr = max(future_years)
                annual_amt = round(sum(future_amts) / max(1, len(set(future_years))), 2)
            else:
                start_yr = max(2026, byear + 5)
                end_yr = min(2035, byear + 17)
                annual_amt = 50000.0

            results.append({
                "user_id": c_id,
                "name": c_name,
                "first_name": f_name,
                "k12_start": start_yr,
                "k12_end": end_yr,
                "annual_amount": annual_amt,
            })
    except Exception as e:
        print(f"[WARN] Error loading children K-12 tuition: {e}")

    return results


def get_child_ledger_expense_for_year(family_id: int = 0, child_user_id: Optional[int] = None, year: int = 2026) -> Optional[float]:
    """
    Looks up the verified tuition cost from the tuition ledger for a given child and calendar year.
    Academic year 'YYYY-YYYY+1' corresponds to calendar year YYYY (e.g. '2026-2027' -> 2026).
    Returns float amount if a ledger entry exists for this year, or None if no entry found.
    """
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id or not child_user_id:
        return None
    try:
        import db
        ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
        return ledger.get(int(child_user_id), {}).get(int(year))
    except Exception as e:
        print(f"[WARN] Error loading child ledger expense for child {child_user_id} year {year}: {e}")
    return None


def child_has_tuition_ledger(family_id: int = 0, child_user_id: Optional[int] = None) -> bool:
    """Checks whether any tuition records exist in the ledger for this child."""
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id or not child_user_id:
        return False
    try:
        import db
        ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
        return int(child_user_id) in ledger
    except Exception:
        return False
