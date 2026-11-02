"""
forecast/storage_education.py: Tuition Ledger, 529 Reserves & Child Education Helpers.
Extracted from forecast/storage.py.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import logging
from datetime import date

import account_sync
from account_sync.categorizer_rules import is_coverdell_name
import config
from db.session import resolve_db_path

from forecast.tuition_levels import COLLEGE, K12, PREK, classify_tuition_level

logger = logging.getLogger(__name__)


def _child_age(children: List[Dict[str, Any]], child_id: Any, year: int) -> Optional[int]:
    """Child's age in `year` from the family-member birthdate, or None if unknown."""
    for c in children:
        if c.get("user_id") == child_id:
            try:
                return year - int(str(c.get("birthdate") or "").split("-")[0])
            except ValueError:
                return None
    return None


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
    members = db.store.get_family_members(family_id=family_id, db_path=active_db)
    children = [m for m in members if m.get("relationship") == "child"]
    if not children:
        return children_reserves
    accounts = db.store.get_accounts(family_id=family_id, db_path=active_db)

    ben_map = {}
    roles_cache: Dict[str, Tuple[str, bool]] = {}
    role_rows = db.store.get_account_roles(family_id=family_id, db_path=active_db)
    for r in role_rows:
        aid = str(r.get("monarch_account_id") or "").strip()
        if aid:
            if r.get("beneficiary_user_id") is not None:
                ben_map[aid] = r["beneficiary_user_id"]
            raw_role = str(r.get("role") or "").strip()
            role_str = account_sync.ROLE_ALIASES.get(raw_role, raw_role)
            roles_cache[aid] = (role_str, bool(r.get("is_hidden_from_family_office") or 0))

    family_comps = account_sync.get_family_company_names(family_id)

    pre_accounts = []
    for acc in accounts:
        acc_id = str(acc.get("id") or "")
        dname = (acc.get("displayName") or "").lower()
        cat = account_sync.categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps)
        is_edu = cat in ("education_529", "education_530a") or "529" in dname or "college" in dname or is_coverdell_name(dname)
        bal = float(acc.get("currentBalance") or 0.0)
        pre_accounts.append({
            "id": acc_id,
            "displayName": acc.get("displayName"),
            "dname": dname,
            "is_edu": is_edu,
            "balance": bal,
            "ben": ben_map.get(acc_id),
        })

    college_ledger: Dict[int, Dict[int, float]] = {}
    ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
    labels = db.store.get_tuition_labels(family_id=family_id, db_path=active_db)
    for cid, yr_map in ledger.items():
        for y, amt in yr_map.items():
            if amt <= 0:
                continue
            age = _child_age(children, cid, y)
            if classify_tuition_level(labels.get(cid, {}).get(y, ""), age) == COLLEGE:
                college_ledger.setdefault(cid, {})[y] = amt

    for child in children:
        child_id = child.get("user_id")
        c_name = child.get("name", "Child")
        first_name = c_name.split()[0]
        bdate = child.get("birthdate") or f"{date.today().year - config.PLACEHOLDER_CHILD_AGE}-01-01"
        try:
            byear = int(bdate.split("-")[0])
        except ValueError:
            byear = date.today().year - config.PLACEHOLDER_CHILD_AGE

        cl_all = college_ledger.get(child_id)
        # Future college years drive the event; a fully-past ledger keeps its own window so no default is invented.
        cl = {y: a for y, a in (cl_all or {}).items() if y >= date.today().year} or cl_all
        college_start = min(cl) if cl else byear + 18
        college_end = max(cl) if cl else college_start + 3

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
            "college_end": college_end,
            "college_from_ledger": bool(cl),
            "college_annual_amount": round(sum(cl.values()) / len(cl), 2) if cl else None,
            "current_529_balance": round(matched_bal, 2),
            "accounts": matched_accounts,
        })

    return children_reserves


def load_children_k12_tuition(family_id: int = 0, as_of_year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Returns dynamic per-child K-12 and pre-K tuition plans (one record per child per level, `level` = "k12"/"prek")
    from decrypted database records. College ledger rows are excluded (see `load_children_edu_reserves`).
    Only years from `as_of_year` (default: the current calendar year) onward are future spend.
    Each child gets start_year, end_year, and average annual tuition cost.
    """
    as_of_year = as_of_year if as_of_year is not None else date.today().year
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id:
        return []

    import db
    members = db.store.get_family_members(family_id=family_id, db_path=active_db)
    children = [m for m in members if m.get("relationship") == "child"]
    if not children:
        return []

    results = []
    ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
    labels = db.store.get_tuition_labels(family_id=family_id, db_path=active_db)
    for child in children:
        c_id = child.get("user_id")
        c_name = child.get("name", "Child")
        f_name = c_name.split()[0]
        bdate = child.get("birthdate") or f"{date.today().year - config.PLACEHOLDER_CHILD_AGE}-01-01"
        try:
            byear = int(bdate.split("-")[0])
        except ValueError:
            byear = date.today().year - config.PLACEHOLDER_CHILD_AGE

        has_ledger = c_id is not None and int(c_id) in ledger
        child_years_map = ledger.get(int(c_id), {}) if c_id is not None else {}
        child_labels = labels.get(int(c_id), {}) if c_id is not None else {}
        by_level: Dict[str, Dict[int, float]] = {}
        for y, amt in child_years_map.items():
            if y >= as_of_year and amt > 0:
                lvl = classify_tuition_level(child_labels.get(y, ""), y - byear)
                by_level.setdefault(lvl, {})[y] = amt

        if has_ledger:
            plans = [(lvl, yrs) for lvl, yrs in by_level.items() if lvl in (K12, PREK)]
        else:
            plans = [(K12, None)]
        for lvl, yrs in plans:
            if yrs:
                start_yr, end_yr = min(yrs), max(yrs)
                annual_amt = round(sum(yrs.values()) / len(yrs), 2)
            else:
                start_yr = max(as_of_year, byear + 5)
                end_yr = min(2035, byear + 17)
                annual_amt = 50000.0
            results.append({
                "user_id": c_id,
                "name": c_name,
                "first_name": f_name,
                "level": lvl,
                "event_id": f"evt_{'prek' if lvl == PREK else 'k12'}_{f_name.lower()}",
                "k12_start": start_yr,
                "k12_end": end_yr,
                "annual_amount": annual_amt,
            })

    return results


def get_child_ledger_expense_for_year(family_id: int, child_user_id: Optional[int], year: int) -> Optional[float]:
    """
    Looks up the verified tuition cost from the tuition ledger for a given child and calendar year.
    Academic year 'YYYY-YYYY+1' corresponds to calendar year YYYY (e.g. '2026-2027' -> 2026).
    Returns float amount if a ledger entry exists for this year, or None if no entry found.
    """
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id or not child_user_id:
        return None
    import db
    ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
    return ledger.get(int(child_user_id), {}).get(int(year))
    return None


def child_has_tuition_ledger(family_id: int = 0, child_user_id: Optional[int] = None) -> bool:
    """Checks whether any tuition records exist in the ledger for this child."""
    active_db = _resolve_storage_db(family_id=family_id)
    if not active_db.exists() or not family_id or not child_user_id:
        return False
    import db
    ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=active_db)
    return int(child_user_id) in ledger
