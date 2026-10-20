"""
Helper and projection functions for family education, 529 plans, and tuition planning.
Extracted from db/education.py for modularity.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import config
from db.session import resolve_db_path

logger = logging.getLogger(__name__)


def parse_grade_index(g: str) -> Optional[int]:
    """Maps a human-readable school grade label to a numeric index (K=0, 12th=12, College Freshman=13)."""
    if not g:
        return None
    g_low = str(g).lower()
    if "preschool" in g_low or "nursery" in g_low:
        return -2
    if "pre-k" in g_low:
        return -1
    if "kindergarten" in g_low:
        return 0
    for num, w in [
        (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (5, "5th"), (6, "6th"),
        (7, "7th"), (8, "8th"), (9, "9th"), (10, "10th"), (11, "11th"), (12, "12th"),
    ]:
        if w in g_low or f"{num}th" in g_low:
            return num
    for idx, keys in [(13, ("freshman", "college fresh")), (14, ("sophomore", "college soph")), (15, ("college junior",)), (16, ("college senior",))]:
        if any(k in g_low for k in keys):
            return idx
    if any(w in g_low for w in ("post-grad", "grad", "masters", "law", "med", "phd", "mba")):
        return 17
    return None


def load_tuition_records(
    family_id: int,
    children: List[Dict[str, Any]],
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Loads tuition records from relational SQLite table merged with normalized year store."""
    from db.education import get_tuition_store_payload, list_tuition_records

    path = resolve_db_path(db_path, family_id=family_id)
    child_map = {
        c.get("user_id"): (c.get("first_name") or c.get("name", "Child")).lower()
        for c in children
    }
    records_dict: Dict[str, Dict[str, Any]] = {}

    if path.exists():
        try:
            rows = list_tuition_records(family_id=family_id, db_path=path)
            for r in rows:
                yr = r["school_year"]
                if yr not in records_dict:
                    records_dict[yr] = {
                        "school_year": yr,
                        "contracts": [],
                        "notes": r["notes"] or "",
                        "is_projected": bool(r["is_projected"]),
                        "total": 0.0,
                    }
                    for k in child_map.values():
                        records_dict[yr][k] = 0.0
                c_key = child_map.get(r["child_user_id"])
                amt = float(r["amount"])
                if c_key:
                    records_dict[yr][c_key] = amt
                records_dict[yr]["total"] = round(records_dict[yr]["total"] + amt, 2)
                if r["notes"] and not records_dict[yr]["notes"]:
                    records_dict[yr]["notes"] = r["notes"]
        except Exception:
            pass

    tuition_data = get_tuition_store_payload(family_id=family_id, db_path=path)
    enc_records = {
        r.get("school_year"): r
        for r in tuition_data.get("records", [])
        if r.get("school_year")
    }

    if records_dict:
        for yr, rec in records_dict.items():
            if yr in enc_records:
                enc_r = enc_records[yr]
                for k, v in enc_r.items():
                    if k.endswith("_grade") or k.endswith("_school") or k not in rec:
                        rec[k] = v
        return sorted(
            records_dict.values(),
            key=lambda r: int(r["school_year"].split("-")[0]) if "-" in str(r.get("school_year", "")) else 0,
        )
    return tuition_data.get("records", [])


def build_college_education_payload(
    family_id: int,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Computes 529 asset tracking, 7% growth projections, and tuition eligibility summary for a family."""
    import db as db_pkg
    import monarch_service
    import security
    from db.education import get_latest_high_school_grad_year, get_tuition_store_payload

    path = resolve_db_path(db_path, family_id=family_id)
    members = security.get_family_members(path, family_id=family_id)
    children = [m for m in members if m.get("relationship") == "child"]

    accounts = db_pkg.accounts.list_accounts(family_id=family_id, db_path=path)
    current_year = 2026
    children_data: List[Dict[str, Any]] = []
    total_529 = 0.0

    ben_map: Dict[str, Any] = {}
    roles_cache, family_comps = monarch_service.load_family_categorization_context(family_id)
    if path.exists():
        try:
            roles = db_pkg.families.get_account_roles(family_id=family_id, db_path=path)
            ben_map = {
                str(r["monarch_account_id"]): r["beneficiary_user_id"]
                for r in roles
                if r.get("beneficiary_user_id") is not None
            }
        except Exception:
            pass

    tuition_store = get_tuition_store_payload(family_id=family_id, db_path=path)
    t_records = tuition_store.get("records", [])

    for child in children:
        child_id = child.get("user_id")
        c_name = child.get("name", "Child")
        first_name = c_name.split()[0].lower()
        bdate = child.get("birthdate") or "2015-01-01"
        try:
            b_parts = str(bdate).split("-")
            byear = int(b_parts[0])
            bmonth = int(b_parts[1]) if len(b_parts) > 1 else 1
        except Exception:
            byear, bmonth = 2015, 1

        current_age = current_year - byear
        grad_year = byear + 19 if bmonth >= 9 else byear + 18

        latest_anchor_yr, latest_anchor_idx = None, None
        for r in t_records:
            g = r.get(f"{first_name}_grade") or r.get("notes") or ""
            yr_str = str(r.get("school_year", ""))
            if "-" in yr_str and g:
                try:
                    s_yr = int(yr_str.split("-")[0])
                    idx = parse_grade_index(g)
                    if idx is not None:
                        latest_anchor_yr, latest_anchor_idx = s_yr, idx
                except Exception:
                    pass

        if latest_anchor_yr is not None and latest_anchor_idx is not None:
            grad_year = latest_anchor_yr + (13 - latest_anchor_idx)

        if path.exists() and child_id:
            hs_grad = get_latest_high_school_grad_year(family_id=family_id, child_user_id=child_id, db_path=path)
            if hs_grad is not None:
                grad_year = hs_grad
        matr_year = grad_year
        years_to_college = max(0.5, grad_year - current_year + 0.5)

        matched_bal = 0.0
        matched_accounts: List[Dict[str, Any]] = []
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            acc_id = str(acc.get("id"))
            dname = (acc.get("displayName") or "").lower()
            cat = monarch_service.categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps)
            assigned_ben = ben_map.get(acc_id)
            is_edu = cat in ("education_529", "education_530a") or any(k in dname for k in ("529", "530a", "college", "coverdell"))
            is_match = (assigned_ben == child_id and is_edu) or (first_name in dname and is_edu)

            if is_match:
                bal = float(acc.get("currentBalance") or 0.0)
                matched_bal += bal
                acc_type_val = acc.get("type")
                type_disp = acc_type_val.get("display", "529 Plan") if isinstance(acc_type_val, dict) else str(acc_type_val or "529 Plan")
                matched_accounts.append({
                    "name": acc.get("displayName"),
                    "balance": bal,
                    "type": "530A Custodial" if "530a" in dname or cat == "education_530a" else type_disp,
                })

        total_529 += matched_bal
        children_data.append({
            "user_id": child.get("user_id"), "name": c_name, "first_name": first_name.capitalize(),
            "birthdate": bdate, "age": current_age, "high_school_grad_year": grad_year,
            "high_school_graduation_year": grad_year, "college_matriculation_year": matr_year,
            "years_to_college": years_to_college, "current_529_balance": round(matched_bal, 2),
            "accounts": matched_accounts,
        })

    proj: List[Dict[str, Any]] = []
    for yr_offset in range(1, 11):
        year, rate = current_year + yr_offset, 0.07
        entry: Dict[str, Any] = {"year": year, "total_projected": 0.0}
        for c in children_data:
            c_proj = round(c["current_529_balance"] * ((1 + rate) ** yr_offset), 2)
            entry[f"{c['first_name'].lower()}_projected"] = c_proj
            entry["total_projected"] += c_proj
        entry["total_projected"] = round(entry["total_projected"], 2)
        proj.append(entry)

    records = load_tuition_records(family_id, children_data, db_path=path)
    tuition_summary: Dict[str, Any] = {
        "total_actual_spent": 0.0, "total_future_projected": 0.0, "grand_total": 0.0,
        "k12_529_max_annual_per_child": 20000.0, "k12_529_total_eligible": 0.0,
    }

    future_years = [r for r in records if r.get("is_projected")]
    for c in children_data:
        c_key = c["first_name"].lower()
        c_actual = sum(float(r.get(c_key, 0.0) or 0.0) for r in records if not r.get("is_projected"))
        c_proj = sum(float(r.get(c_key, 0.0) or 0.0) for r in records if r.get("is_projected"))
        tuition_summary[f"{c_key}_actual"] = round(c_actual, 2)
        tuition_summary[f"{c_key}_projected"] = round(c_proj, 2)
        tuition_summary[f"{c_key}_total"] = round(c_actual + c_proj, 2)

        mat_yr = c.get("college_matriculation_year")
        c_k12_elig = 0.0
        for r in future_years:
            amt = float(r.get(c_key, 0.0) or 0.0)
            notes = (r.get("notes") or "").lower()
            s_name = (r.get(f"{c_key}_school") or r.get("school_name") or "").lower()
            yr = int(r.get("school_year", "0").split("-")[0]) if "-" in str(r.get("school_year", "")) else 0
            is_col = any(w in notes or w in s_name for w in ["college", "university", "undergrad", "higher ed"]) or (mat_yr and yr >= mat_yr)
            k12_cap = 20000.0 if (yr >= 2026 or yr == 0) else 10000.0
            c_k12_elig += amt if is_col else min(k12_cap, amt)

        tuition_summary[f"k12_529_{c_key}_eligible"] = round(c_k12_elig, 2)
        tuition_summary["total_actual_spent"] += c_actual
        tuition_summary["total_future_projected"] += c_proj
        tuition_summary["k12_529_total_eligible"] += c_k12_elig

    tuition_summary["total_actual_spent"] = round(tuition_summary["total_actual_spent"], 2)
    tuition_summary["total_future_projected"] = round(tuition_summary["total_future_projected"], 2)
    tuition_summary["grand_total"] = round(tuition_summary["total_actual_spent"] + tuition_summary["total_future_projected"], 2)
    tuition_summary["k12_529_total_eligible"] = round(tuition_summary["k12_529_total_eligible"], 2)

    child1_529 = children_data[0]["current_529_balance"] if len(children_data) > 0 else 0.0
    child2_529 = children_data[1]["current_529_balance"] if len(children_data) > 1 else 0.0

    return {
        "success": True, "children": children_data,
        "child1_529": child1_529, "child2_529": child2_529,
        "child_529_balances": {c["user_id"]: c["current_529_balance"] for c in children_data},
        "total_529_assets": round(total_529, 2), "superfunding_limit_per_child": 190000.0,
        "growth_projections_7pct": proj, "tuition_records": records, "tuition_summary": tuition_summary,
    }


def save_tuition_year_entry(
    family_id: int,
    year: str,
    notes: str,
    body: Dict[str, Any],
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Validates limits, updates relational child tuition rows, and normalizes the school year record."""
    from routes.helpers import sanitize_text
    import security
    from db.education import (
        list_tuition_records,
        list_tuition_year_records,
        upsert_tuition_record,
        upsert_tuition_year_record,
    )

    path = resolve_db_path(db_path, family_id=family_id)
    members = security.get_family_members(path, family_id=family_id)
    children = [m for m in members if m.get("relationship") == "child"]

    first_year = int(year.split("-")[0])
    is_proj = bool(body["is_projected"]) if "is_projected" in body else (first_year > 2026)

    records = list_tuition_year_records(family_id=family_id, db_path=path)
    existing = next((r for r in records if r.get("school_year") == year), None)
    if existing is None:
        max_years = int(getattr(config, "MAX_TUITION_YEARS", 50))
        if len(records) >= max_years:
            raise ValueError(f"Maximum of {max_years} tuition school years per household reached.")

    if path.exists() and children:
        existing_tuition_rows = list_tuition_records(family_id=family_id, db_path=path)
        existing_child_ids = {r.get("child_user_id") for r in existing_tuition_rows if r.get("school_year") == year}
        new_child_rows = sum(1 for c in children if c.get("user_id") not in existing_child_ids)
        max_records = int(getattr(config, "MAX_TUITION_RECORDS", 500))
        if new_child_rows > 0 and (
            len(existing_tuition_rows) >= max_records
            or len(existing_tuition_rows) + new_child_rows > max_records
        ):
            raise ValueError(f"Maximum of {max_records} tuition records per household reached.")

        try:
            for child in children:
                c_key = child["first_name"].lower() if "first_name" in child else child["name"].split()[0].lower()
                amt = float(body.get(c_key, 0.0) or 0.0)
                c_grade = sanitize_text(body.get(f"{c_key}_grade", ""), max_length=50, field_name=f"{c_key} grade")
                child_notes = (f"{c_grade} | {notes}".strip(" |") if notes else c_grade) if c_grade else notes
                upsert_tuition_record(
                    family_id=family_id,
                    child_user_id=child["user_id"],
                    school_year=year,
                    tuition_amount=amt,
                    is_projected=is_proj,
                    notes=child_notes,
                    db_path=path,
                )
        except ValueError:
            raise
        except Exception:
            pass

    if existing:
        target_record = dict(existing)
        for child in children:
            c_key = child.get("first_name", child.get("name", "").split()[0]).lower()
            if c_key in body:
                target_record[c_key] = float(body[c_key] or 0.0)
            if f"{c_key}_grade" in body:
                target_record[f"{c_key}_grade"] = sanitize_text(body[f"{c_key}_grade"], max_length=50, field_name=f"{c_key} grade")
        for k, v in body.items():
            if k not in ["school_year", "notes", "is_projected"] and not k.endswith(("_grade", "_school")):
                try:
                    target_record[k] = float(v or 0.0)
                except (ValueError, TypeError):
                    pass
            elif k.endswith(("_grade", "_school")):
                target_record[k] = sanitize_text(v, max_length=50, field_name=k)
        target_record["total"] = sum(
            float(v) for k, v in target_record.items()
            if k not in ["school_year", "contracts", "notes", "is_projected", "total", "school", "school_name"]
            and not k.endswith(("_grade", "_school"))
        )
        if notes:
            target_record["notes"] = notes
        target_record["is_projected"] = is_proj
    else:
        target_record = {"school_year": year, "contracts": [], "notes": notes, "is_projected": is_proj}
        tot = 0.0
        for child in children:
            c_key = child.get("first_name", child.get("name", "").split()[0]).lower()
            val = float(body.get(c_key, 0.0) or 0.0)
            target_record[c_key] = val
            tot += val
            if f"{c_key}_grade" in body:
                target_record[f"{c_key}_grade"] = sanitize_text(body[f"{c_key}_grade"], max_length=50, field_name=f"{c_key} grade")
        for k, v in body.items():
            if k not in ["school_year", "notes", "is_projected"] and not k.endswith(("_grade", "_school")) and k not in target_record:
                try:
                    val = float(v or 0.0)
                    target_record[k] = val
                    tot += val
                except (ValueError, TypeError):
                    pass
            elif k.endswith(("_grade", "_school")):
                target_record[k] = sanitize_text(v, max_length=50, field_name=k)
        target_record["total"] = round(tot, 2)

    upsert_tuition_year_record(family_id=family_id, school_year=year, record=target_record, db_path=path)
    return target_record
