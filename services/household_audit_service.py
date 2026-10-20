"""
HVL Family Office: Household Risk & Survivorship Audit Service.
Deterministic evaluation of probate exposure, beneficiary designations, emergency liquidity,
equity concentration, supplemental tax withholding gaps, cash drag, 529 coverage, and estate tax sunset.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import db
import monarch_service
from routes.helpers import DB_PATH
from ssr.formatting import fmt_currency

logger = logging.getLogger(__name__)

PROBATE_AVOIDANCE_KEYWORDS = ("trust", "revocable", "slat", "tod", "pod", "joint", "jtwros")


def _add_finding(
    findings: List[Dict[str, Any]],
    fid: str,
    severity: str,
    category: str,
    title: str,
    detail: str,
    action_label: str,
    *,
    action_nav: str = "",
    account_id: str = "",
    verify_label: str = "Mark Verified",
    verified_ids: Optional[set] = None,
) -> None:
    is_verified = bool(verified_ids and fid in verified_ids and severity in ("critical", "warning"))
    findings.append({
        "id": fid,
        "severity": "info" if is_verified else severity,
        "original_severity": severity,
        "is_verified": is_verified,
        "category": category,
        "title": title,
        "detail": detail,
        "action_label": action_label,
        "action_nav": action_nav,
        "account_id": account_id,
        "verify_label": verify_label,
    })


def evaluate_household_risks(
    db_path: Optional[Path] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """
    Evaluates up to 8 deterministic household survivorship and operational checks against live household data:
    1. Individually Titled Taxable Accounts Exposed to Probate (> $100,000)
    2. Retirement Accounts Beneficiary Verification (> $50,000)
    3. Emergency Liquidity Runway (< 6 Months of Baseline Burn)
    4. Single-Stock / Employer Equity Concentration (> 20% of Net Worth)
    5. Upcoming RSU Supplemental Tax Withholding Gap (22% flat vs. top marginal bracket)
    6. Tax-Advantaged Cash Drag (> 10% in uninvested cash)
    7. Education 529 Coverage Gap (minor children without dedicated 529 account)
    8. Estate Tax TCJA Sunset Exposure (> $7.0M Single / > $14.0M MFJ without trust architecture)
    """
    default_payload: Dict[str, Any] = {
        "readiness_score": 100, "status_badge": "Ready",
        "critical_count": 0, "warning_count": 0, "info_count": 0, "verified_count": 0,
        "findings": [], "has_data": False,
    }
    if not family_id or family_id <= 0:
        return default_payload

    resolved_db = db_path or DB_PATH
    try:
        snap = monarch_service.get_financial_snapshot(family_id=family_id)
    except Exception as e:
        logger.warning("Could not fetch snapshot for family %s: %s", family_id, e)
        snap = None

    if not snap or not snap.get("categories"):
        return default_payload

    categories = snap.get("categories") or {}
    total_nw = float(snap.get("true_net_worth") or 0.0)
    cats_with_balance = [c for c in categories.values() if float(c.get("total") or 0.0) != 0.0]
    if total_nw <= 0 and not cats_with_balance:
        return default_payload

    findings: List[Dict[str, Any]] = []
    verified_ids: set = set()
    try:
        ep_assump = db.estate.get_estate_planning_assumptions(family_id=family_id, db_path=resolved_db)
        raw_v = ep_assump.get("verified_audit_ids")
        if isinstance(raw_v, list):
            verified_ids = {str(x) for x in raw_v if x}
    except Exception as e:
        logger.debug("Failed loading verified_audit_ids for family %s: %s", family_id, e)

    # Load account roles, household members, and annual spend cleanly through db layer
    roles_cache: Dict[str, Dict[str, Any]] = {}
    try:
        for r in db.store.get_account_roles(family_id=family_id, db_path=resolved_db):
            aid = str(r.get("monarch_account_id") or "").strip()
            if aid:
                roles_cache[aid] = r
    except Exception as e:
        logger.debug("Failed loading roles for family %s: %s", family_id, e)

    members: List[Dict[str, Any]] = []
    try:
        members = db.household.get_household_members(family_id=family_id, db_path=resolved_db)
    except Exception as e:
        logger.debug("Failed loading members for family %s: %s", family_id, e)

    annual_spend = 0.0
    try:
        annual_spend = db.household.get_annual_spending(family_id=family_id, db_path=resolved_db)
    except Exception as e:
        logger.debug("Failed loading annual spend for family %s: %s", family_id, e)

    # 1. Individually Titled Taxable Accounts Exposed to Probate (> $100k)
    for cat_key in ("public_brokerage", "cash_liquid", "real_estate"):
        for acc in categories.get(cat_key, {}).get("accounts", []):
            bal = float(acc.get("balance") or 0.0)
            if bal > 100000.0:
                aid = str(acc.get("id") or "")
                name, raw_name = str(acc.get("name") or ""), str(acc.get("raw_name") or "")
                role_info = roles_cache.get(aid, {})
                role_val = str(role_info.get("role") or acc.get("role") or "").lower()
                desc = f"{name} {raw_name} {role_val}".lower()
                if not any(k in desc for k in PROBATE_AVOIDANCE_KEYWORDS):
                    is_crit = bal >= 500000.0
                    _add_finding(
                        findings, f"probate_{aid}", "critical" if is_crit else "warning", "probate_exposure",
                        f"Probate Exposure: Individually Titled Account ({name})",
                        f"{name} ({fmt_currency(bal, 0)}) lacks trust titling or TOD/POD designation in its account name. Upon death, untitled individual assets face court probate delays (6–18 months) and statutory fees.",
                        "Retitle into Revocable Trust or Add TOD/POD",
                        action_nav="settings:roles",
                        account_id=aid,
                        verify_label="Mark Trust / TOD On File",
                        verified_ids=verified_ids,
                    )

    # 2. Retirement Accounts Beneficiary Verification (> $50,000)
    for acc in categories.get("retirement", {}).get("accounts", []):
        bal = float(acc.get("balance") or 0.0)
        if bal > 50000.0:
            aid = str(acc.get("id") or "")
            role_info = roles_cache.get(aid, {})
            ben_id = role_info.get("beneficiary_user_id")
            name = str(acc.get("name") or "Retirement Account")
            if not ben_id or ben_id == 0:
                _add_finding(
                    findings, f"ben_{aid}", "warning", "beneficiary_verification",
                    f"Unassigned Beneficiary: {name}",
                    f"{name} ({fmt_currency(bal, 0)}) has no confirmed primary or contingent beneficiary recorded. Unassigned retirement accounts may default to probate and accelerate tax realization.",
                    "Designate Primary & Contingent Beneficiaries",
                    action_nav="settings:roles",
                    account_id=aid,
                    verify_label="Mark Beneficiary On File",
                    verified_ids=verified_ids,
                )

    # 3. Emergency Liquidity Runway (< 6 Months of Baseline Burn)
    cash_liquid = float(categories.get("cash_liquid", {}).get("total") or 0.0)
    if annual_spend > 0:
        monthly_burn = annual_spend / 12.0
        months_runway = (cash_liquid / monthly_burn) if monthly_burn > 0 else 999.0
        target_6mo = annual_spend / 2.0
        if months_runway < 3.0:
            _add_finding(
                findings, "runway_critical", "critical", "emergency_runway",
                f"Critical Liquidity Shortfall: {months_runway:.1f} Months Runway",
                f"Liquid cash ({fmt_currency(cash_liquid, 0)}) provides only {months_runway:.1f} months of baseline burn ({fmt_currency(monthly_burn, 0)}/mo). Target minimum is 6 months ({fmt_currency(target_6mo, 0)}).",
                "Replenish Liquid Cash Reserves",
                action_nav="section-accounts",
                verify_label="Mark Cash Buffer Reviewed",
                verified_ids=verified_ids,
            )
        elif months_runway < 6.0:
            _add_finding(
                findings, "runway_warning", "warning", "emergency_runway",
                f"Cash Runway Below 6-Month Target: {months_runway:.1f} Months",
                f"Liquid cash ({fmt_currency(cash_liquid, 0)}) is below the recommended 6-month buffer ({fmt_currency(target_6mo, 0)}) based on {fmt_currency(annual_spend, 0)} annual burn.",
                "Build 6-Month Emergency Buffer",
                action_nav="section-accounts",
                verify_label="Mark Cash Buffer Reviewed",
                verified_ids=verified_ids,
            )
        else:
            _add_finding(
                findings, "runway_info", "info", "emergency_runway",
                f"Emergency Runway Fully Funded: {months_runway:.1f} Months",
                f"Liquid cash reserves ({fmt_currency(cash_liquid, 0)}) exceed 6 months of baseline burn ({fmt_currency(target_6mo, 0)}).",
                "Maintain Cash Target",
                action_nav="section-accounts",
            )

    # 4. Single-Stock / Employer Equity Concentration (> 20% of Net Worth)
    company_eq = snap.get("company_equity") or {}
    eq_val = float(company_eq.get("true_net_post_tax_value") or company_eq.get("total_gross_equity_value") or 0.0)
    if total_nw > 0 and eq_val > 0:
        conc_ratio = eq_val / total_nw
        comp_name = str(company_eq.get("company_name") or "Employer Stock")
        if conc_ratio > 0.35:
            _add_finding(
                findings, "equity_concentration_crit", "critical", "equity_concentration",
                f"Excessive Equity Concentration: {conc_ratio*100:.1f}% in {comp_name}",
                f"{comp_name} equity ({fmt_currency(eq_val, 0)}) represents {conc_ratio*100:.1f}% of total net worth, exceeding the 20% prudential concentration ceiling.",
                "Adopt Rule 10b5-1 Diversification Plan",
                action_nav="section-equity",
                verify_label="Mark 10b5-1 / Reviewed",
                verified_ids=verified_ids,
            )
        elif conc_ratio > 0.20:
            _add_finding(
                findings, "equity_concentration_warn", "warning", "equity_concentration",
                f"Equity Concentration Notice: {conc_ratio*100:.1f}% in {comp_name}",
                f"{comp_name} equity ({fmt_currency(eq_val, 0)}) exceeds 20% of household net worth. Review downside volatility and lock-up exposure.",
                "Review Diversification Strategy",
                action_nav="section-equity",
                verify_label="Mark Concentration Reviewed",
                verified_ids=verified_ids,
            )

    # 5. Upcoming RSU Supplemental Tax Withholding Gap (22% Flat vs. 35–37% Marginal Rate)
    unvested_shares = float(company_eq.get("unvested_shares") or company_eq.get("total_unvested_shares") or 0.0)
    unvested_val = float(company_eq.get("total_unvested_value") or company_eq.get("unvested_rsu_value") or 0.0)
    has_active_grants = bool(company_eq.get("grants")) or unvested_shares > 0 or unvested_val > 0
    if has_active_grants and total_nw > 500000.0:
        _add_finding(
            findings, "rsu_withholding_gap", "warning", "tax_withholding_gap",
            "RSU Supplemental Tax Withholding Gap (22% Flat vs. 35–37% Marginal Rate)",
            "Statutory supplemental wage withholding is fixed at 22% on RSU vests under $1M, but your top marginal rate is 35%–37%. Each vest incurs an automatic 13%–15% shortfall.",
            "Adjust Form W-4 Additional Withholding or Pay Form 1040-ES",
            action_nav="section-compensation",
            verify_label="Mark W-4 / 1040-ES Handled",
            verified_ids=verified_ids,
        )

    # 6. Tax-Advantaged Cash Drag (> 10% in retirement/529)
    ret_total = float(categories.get("retirement", {}).get("total") or 0.0)
    edu_total = float(categories.get("education_529", {}).get("total") or 0.0)
    tax_adv_total = ret_total + edu_total
    cash_in_tax_adv = 0.0
    for pos in (snap.get("brokerage_and_401k_positions") or []):
        p_cat = str(pos.get("category") or pos.get("account_category") or "").lower()
        if "retirement" in p_cat or "529" in p_cat or "education" in p_cat:
            t = str(pos.get("ticker") or pos.get("symbol") or "").upper()
            if t in ("SPAXX", "VMFXX", "FDRXX", "SWVXX", "CASH", "MMF") or "money market" in str(pos.get("name") or "").lower():
                cash_in_tax_adv += float(pos.get("totalValue") or pos.get("value") or 0.0)

    if tax_adv_total > 25000.0 and (cash_in_tax_adv / tax_adv_total) > 0.10:
        cash_pct = (cash_in_tax_adv / tax_adv_total) * 100.0
        _add_finding(
            findings, "cash_drag_tax_adv", "warning", "cash_drag",
            f"Tax-Advantaged Cash Drag: {cash_pct:.1f}% Uninvested ({fmt_currency(cash_in_tax_adv, 0)})",
            f"{fmt_currency(cash_in_tax_adv, 0)} is held in cash or money market instruments within retirement/529 accounts, missing tax-sheltered compounding.",
            "Deploy Idle Cash into Target Asset Allocation",
            action_nav="section-holdings",
            verify_label="Mark Allocation Reviewed",
            verified_ids=verified_ids,
        )

    # 7. Education 529 Coverage Gap (minor children without dedicated 529 account)
    child_members = [
        m for m in members
        if str(m.get("relationship") or "").lower() == "child" or (isinstance(m.get("age"), (int, float)) and m["age"] < 18)
    ]
    edu_accounts = categories.get("education_529", {}).get("accounts", [])
    if child_members and (not edu_accounts or edu_total <= 0):
        c_count = len(child_members)
        _add_finding(
            findings, "edu_529_gap", "warning", "education_gap",
            f"529 Education Funding Gap: {c_count} Minor Child{'ren' if c_count > 1 else ''} Without Account",
            f"Household roster lists {c_count} minor child{'ren' if c_count > 1 else ''}, but no 529 College Savings accounts are present on the balance sheet.",
            "Open State 529 Plan or Execute 5-Year Superfunding",
            action_nav="section-college",
            verify_label="Mark 529 Plan Handled",
            verified_ids=verified_ids,
        )

    # 8. Estate Tax TCJA Sunset Exposure (> $7.0M Single / > $14.0M Joint)
    try:
        from db.auth_repo import get_household_profile_for_estate
        hp = get_household_profile_for_estate(family_id=family_id, db_path=resolved_db) or {}
        filing_status = hp.get("filing_status") or "MFJ"
    except Exception:
        filing_status = "MFJ"

    is_mfj = (filing_status == "MFJ")
    sunset_threshold = 14000000.0 if is_mfj else 7000000.0
    if total_nw > sunset_threshold:
        _add_finding(
            findings, "estate_sunset_exposure", "warning", "estate_tax_sunset",
            f"Estate Tax TCJA Sunset Exposure ({fmt_currency(total_nw, 0)} Gross Estate)",
            f"Household net worth exceeds the projected post-2025 TCJA sunset exemption ({fmt_currency(sunset_threshold, 0)} {'Joint' if is_mfj else 'Single'}). Wealth above this threshold faces up to 40% federal estate tax plus state death tax.",
            "Model Irrevocable Trust Shielding (SLAT / IDGT / GRAT)",
            action_nav="scroll:#trust-vehicles-grid",
            verify_label="Mark Trust Strategy Reviewed",
            verified_ids=verified_ids,
        )

    _sev_rank = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: (1 if item.get("is_verified") else 0, _sev_rank.get(item.get("severity", "info"), 3)))

    crit_count = sum(1 for f in findings if f["severity"] == "critical" and not f.get("is_verified"))
    warn_count = sum(1 for f in findings if f["severity"] == "warning" and not f.get("is_verified"))
    verified_count = sum(1 for f in findings if f.get("is_verified"))
    info_count = sum(1 for f in findings if f["severity"] == "info" and not f.get("is_verified"))
    score = max(0, min(100, 100 - (crit_count * 20) - (warn_count * 10)))

    badge = "Action Required" if crit_count > 0 else ("Needs Review" if warn_count > 0 else "Ready")

    return {
        "readiness_score": score, "status_badge": badge,
        "critical_count": crit_count, "warning_count": warn_count,
        "info_count": info_count, "verified_count": verified_count,
        "findings": findings, "has_data": True,
    }


def audit_household_risks(family_id: int = 0) -> Dict[str, Any]:
    """
    Evaluates comprehensive household financial risks, survivorship gaps, and estate readiness:
    probate exposure on taxable accounts, missing retirement beneficiary designations,
    emergency cash runway, single-stock / employer equity concentration, RSU supplemental
    withholding shortfalls, tax-advantaged cash drag, education 529 coverage, and TCJA sunset exposure.
    """
    try:
        from services.advisor.tools_core import _resolve_tool_family_id
        fam_id = _resolve_tool_family_id(family_id)
    except Exception:
        fam_id = int(family_id) if family_id > 0 else 0

    if not fam_id:
        return {}
    return evaluate_household_risks(family_id=fam_id)
