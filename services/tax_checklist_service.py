"""
Tax Season Document Checklist and Monarch Core Burn Calibration Services.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import security
from db.session import resolve_db_path, get_orm_session

logger = logging.getLogger(__name__)

STATUS_ORDER = ("waiting", "received", "sent_to_cpa")
STATUS_LABELS = {"waiting": "Waiting", "received": "Received", "sent_to_cpa": "Sent to CPA"}
STATUS_BADGES = {"waiting": "badge-amber", "received": "badge-blue", "sent_to_cpa": "badge-green"}
NEXT_STATUS = {"waiting": "received", "received": "sent_to_cpa", "sent_to_cpa": "waiting"}


def _derive_w2_items(target_db: Path, family_id: int, tax_year: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    adults = [m for m in (security.get_family_members(target_db, family_id=family_id) or []) if m.get("relationship") != "child"]
    primary_comp = ""
    try:
        from db import equity
        primary_comp = equity.get_primary_company_name(family_id=family_id, db_path=target_db) or ""
    except Exception:
        pass
    comp_records: List[Dict[str, Any]] = []
    try:
        from db import compensation
        comp_records = compensation.list_compensation_records(family_id=family_id, db_path=target_db) or []
    except Exception:
        pass
    seen: set[str] = set()
    active_comp = [r for r in comp_records if int(r.get("year", 0)) == tax_year] or comp_records
    for r in active_comp:
        emp = r.get("company") or primary_comp or "Primary Employer"
        tp = r.get("taxpayer") or (adults[0]["name"] if adults else "Primary Taxpayer")
        key = f"w2_{emp}_{tp}".lower().replace(" ", "_")
        if key not in seen:
            seen.add(key)
            items.append({"id": key, "form_type": "Form W-2", "form_title": "Wage and Tax Statement", "source": f"{emp} ({tp})", "category": "Earned Income"})
    if not seen and adults:
        for a in adults:
            a_name = a.get("name") or "Primary Taxpayer"
            emp = primary_comp or "Primary Employer"
            key = f"w2_{emp}_{a_name}".lower().replace(" ", "_")
            if key not in seen:
                seen.add(key)
                items.append({"id": key, "form_type": "Form W-2", "form_title": "Wage and Tax Statement", "source": f"{emp} ({a_name})", "category": "Earned Income"})
    return items


def _derive_account_items(target_db: Path, family_id: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    accounts = []
    try:
        import db.accounts
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=target_db) or []
    except Exception:
        pass
    roles_map: Dict[str, str] = {}
    try:
        from db import account_roles
        for r in (account_roles.get_account_roles(family_id=family_id, db_path=target_db) or []):
            roles_map[str(r.get("monarch_account_id"))] = str(r.get("role") or "")
    except Exception:
        pass

    for acc in accounts:
        aid = str(acc.get("id") or acc.get("account_id") or "")
        name = str(acc.get("name") or acc.get("displayName") or "Account")
        inst = str(acc.get("institution") or acc.get("institution_name") or "")
        bal = float(acc.get("currentBalance") or acc.get("balance") or 0.0)
        role = roles_map.get(aid) or str(acc.get("role") or "")
        src = f"{name} ({inst})" if inst and inst.lower() not in name.lower() else name
        act_type = str(acc.get("account_type") or "").lower()
        nl = name.lower()

        if role == "public_brokerage" or (act_type in ("brokerage", "investment") and role != "retirement" and not any(x in nl for x in ("401k", "ira", "529", "roth"))):
            items.append({"id": f"brokerage_1099_{aid}", "form_type": "Form 1099-Consolidated", "form_title": "1099-B / 1099-DIV Summary", "source": src, "category": "Investments"})
        elif bal > 1000.0 and (role == "cash_liquid" or act_type in ("depository", "cash", "checking", "savings") or any(x in nl for x in ("checking", "savings", "hysa", "money market"))):
            items.append({"id": f"cash_1099int_{aid}", "form_type": "Form 1099-INT", "form_title": "Interest Income", "source": src, "category": "Cash & Banking"})
        elif role in ("education_529", "education_530a") or any(x in nl for x in ("529", "college", "530a")):
            items.append({"id": f"edu_1099q_{aid}", "form_type": "Form 1099-Q", "form_title": "529 Contribution Summary", "source": src, "category": "Education"})
        elif role == "mortgages" or act_type in ("loan", "mortgage") or any(x in nl for x in ("mortgage", "home loan")):
            items.append({"id": f"mortgage_1098_{aid}", "form_type": "Form 1098", "form_title": "Mortgage Interest Statement", "source": src, "category": "Liabilities"})
        elif role in ("private_investments", "other_assets") or any(x in nl for x in ("venture", "fund", "partner", " lp")):
            items.append({"id": f"k1_acc_{aid}", "form_type": "Schedule K-1 (Form 1065)", "form_title": "Partner's Share of Income", "source": src, "category": "Private LP & Illiquid"})
    return items


def _derive_equity_phil_lp_items(target_db: Path, family_id: int, tax_year: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        from db.equity import EquityGrantRecord
        from sqlalchemy import select
        with get_orm_session(target_db, family_id=family_id) as session:
            grants = session.scalars(select(EquityGrantRecord).where(EquityGrantRecord.family_id == family_id)).all()
            seen_c: set[str] = set()
            for g in grants:
                cname = g.company.company_name if (g.company and g.company.company_name) else "Company Equity"
                if cname not in seen_c:
                    seen_c.add(cname)
                    items.append({"id": f"equity_3921_{cname.lower().replace(' ', '_')[:24]}", "form_type": "Form 3921 / Equity Summary", "form_title": "Equity Supplemental Tax Summary", "source": f"{cname} Stock Administration", "category": "Equity Grants"})
    except Exception:
        pass
    try:
        from db import philanthropy
        pay = philanthropy.get_philanthropy_payload(family_id=family_id, db_path=target_db) or {}
        if pay.get("donations") or any(float(b.get("budget", 0) or 0) > 0 for b in pay.get("budgets") or []):
            items.append({"id": f"daf_8283_{tax_year}", "form_type": "Form 8283 / DAF Receipt", "form_title": "DAF Contribution Receipt", "source": "Donor-Advised Fund & Philanthropy", "category": "Philanthropy"})
    except Exception:
        pass
    try:
        lp_comms = security.db_load_encrypted(target_db, "lp_commitments", family_id=family_id) or []
        if isinstance(lp_comms, list):
            for idx, lp in enumerate(lp_comms):
                lp_name = lp.get("fund_name") or lp.get("name") or f"Private Fund #{idx+1}"
                items.append({"id": f"k1_lp_{idx}_{lp_name.lower().replace(' ', '_')[:20]}", "form_type": "Schedule K-1 (Form 1065)", "form_title": "Partner's Share of Income", "source": lp_name, "category": "Private LP & Illiquid"})
    except Exception:
        pass
    return items


def get_tax_document_checklist(
    db_path: Optional[Union[str, Path]] = None,
    family_id: int = 0,
    tax_year: int = 2025,
) -> Dict[str, Any]:
    """Auto-derives expected tax season documents from active household accounts and records."""
    if not family_id:
        return {"tax_year": tax_year, "items": [], "checklist_items": [], "completed_count": 0, "total_count": 0}
    target_db = resolve_db_path(db_path, family_id=family_id)
    if not target_db.exists():
        return {"tax_year": tax_year, "items": [], "checklist_items": [], "completed_count": 0, "total_count": 0}

    saved_raw = security.db_load_encrypted(target_db, "tax_document_checklist", family_id=family_id) or {}
    saved_map = saved_raw.get(str(tax_year), saved_raw) if isinstance(saved_raw, dict) else {}

    items = _derive_w2_items(target_db, family_id, tax_year)
    items.extend(_derive_account_items(target_db, family_id))
    items.extend(_derive_equity_phil_lp_items(target_db, family_id, tax_year))

    completed = 0
    for it in items:
        raw_st = saved_map.get(it["id"]) if isinstance(saved_map, dict) else "waiting"
        st = raw_st if raw_st in STATUS_ORDER else "waiting"
        it["status"] = st
        it["status_label"] = STATUS_LABELS[st]
        it["badge_class"] = STATUS_BADGES[st]
        it["next_status"] = NEXT_STATUS[st]
        if st in ("received", "sent_to_cpa"):
            completed += 1

    return {"tax_year": tax_year, "items": items, "checklist_items": items, "completed_count": completed, "total_count": len(items)}


def update_tax_document_status(
    db_path: Optional[Union[str, Path]] = None,
    family_id: int = 0,
    item_id: str = "",
    status: str = "cycle",
    tax_year: int = 2025,
) -> Dict[str, Any]:
    """Updates or cycles the status of an expected tax document in encrypted store."""
    if not family_id or not item_id:
        return {"success": False, "error": "Invalid family_id or item_id"}
    target_db = resolve_db_path(db_path, family_id=family_id)
    saved = security.db_load_encrypted(target_db, "tax_document_checklist", family_id=family_id) or {}
    if not isinstance(saved, dict):
        saved = {}

    curr = saved.get(item_id, "waiting")
    new_status = NEXT_STATUS.get(curr, "received") if status == "cycle" else (status if status in STATUS_ORDER else "waiting")
    saved[item_id] = new_status
    security.db_save_encrypted(target_db, "tax_document_checklist", "tax_checklist", saved, family_id=family_id)
    try:
        from db import store
        store.notify_family_mutation(family_id, domains=["tax_profile"], db_path=target_db)
    except Exception:
        pass

    return {
        "success": True, "item_id": item_id, "status": new_status,
        "status_label": STATUS_LABELS[new_status],
        "checklist": get_tax_document_checklist(target_db, family_id=family_id, tax_year=tax_year),
    }


def compute_monarch_core_burn_calibration(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Computes steady-state core living burn calibrated against Monarch Money spending minus mortgage & tuition."""
    empty_res = {"gross_annual_spend": 0.0, "estimated_mortgage_annual": 0.0, "estimated_kids_edu_annual": 0.0, "calibrated_core_burn": 0.0, "formatted": {"gross": "--", "mortgage": "--", "education": "--", "core_burn": "--"}}
    if not family_id:
        return empty_res

    target_db = resolve_db_path(db_path, family_id=family_id)
    gross_spend = 0.0
    try:
        import monarch_service
        benchmarks = (monarch_service.get_monarch_spending_history(family_id=family_id) or {}).get("benchmarks") or {}
        for k in ("recommended_budget", "actual_2025", "baseline", "three_year_average"):
            if float(benchmarks.get(k) or 0.0) > 0:
                gross_spend = float(benchmarks[k])
                break
    except Exception:
        pass

    if gross_spend <= 0 and target_db.exists():
        try:
            from db.household import get_annual_spending
            gross_spend = float(get_annual_spending(family_id=family_id, db_path=target_db) or 0.0)
        except Exception:
            pass

    mortgage_ann = 0.0
    if target_db.exists():
        try:
            import db.accounts
            m_bal = sum(
                abs(float(a.get("currentBalance") or a.get("balance") or 0.0))
                for a in (db.accounts.list_accounts(family_id=family_id, db_path=target_db) or [])
                if str(a.get("role") or "").lower() == "mortgages"
                or str(a.get("account_type") or "").lower() in ("mortgage", "loan")
                or any(k in str(a.get("name") or "").lower() for k in ("mortgage", "home loan"))
            )
            if m_bal > 0:
                r_m, n_m = 0.065 / 12.0, 360
                mortgage_ann = m_bal * (r_m * ((1.0 + r_m) ** n_m)) / (((1.0 + r_m) ** n_m) - 1.0) * 12.0
        except Exception:
            pass

    kids_ann = 0.0
    try:
        from forecast.storage_education import load_children_k12_tuition
        kids_ann = sum(float(c.get("annual_amount") or 0.0) for c in (load_children_k12_tuition(family_id=family_id) or []))
    except Exception:
        pass

    core_burn = max(0.0, gross_spend - mortgage_ann - kids_ann) if gross_spend > 0 else 0.0
    return {
        "gross_annual_spend": round(gross_spend, 2),
        "estimated_mortgage_annual": round(mortgage_ann, 2),
        "estimated_kids_edu_annual": round(kids_ann, 2),
        "calibrated_core_burn": round(core_burn, 2),
        "formatted": {
            "gross": f"${gross_spend:,.0f}" if gross_spend > 0 else "--",
            "mortgage": f"${mortgage_ann:,.0f}" if mortgage_ann > 0 else "--",
            "education": f"${kids_ann:,.0f}" if kids_ann > 0 else "--",
            "core_burn": f"${core_burn:,.0f}" if core_burn > 0 else "--",
        },
    }
