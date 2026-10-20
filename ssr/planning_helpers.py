"""
ssr/planning_helpers.py: View-model builders and benchmark estimators for 529 College & Education planning.
"""

from __future__ import annotations
from datetime import date
import logging

import db
import security
import monarch_service
from ssr.formatting import fmt_currency, fmt_short_currency

logger = logging.getLogger(__name__)


def build_ssr_college(
    family_id: int,
    horizon: str | None = None,
    enable_529_k12: bool = True,
) -> dict:
    """Prepares formatted strings for SSR Education / College planning using preloaded categorization context."""
    if family_id <= 0:
        return {}
    try:
        from routes.helpers import DB_PATH
        active_horizon = (horizon or "current").strip().lower()
        members = security.get_family_members(DB_PATH, family_id=family_id)
        children = [m for m in members if m.get("relationship") == "child"]
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=DB_PATH) or []

        ben_map = {}
        roles_cache, family_comps = monarch_service.load_family_categorization_context(family_id)
        if DB_PATH.exists():
            try:
                roles = db.families.get_account_roles(family_id=family_id, db_path=DB_PATH)
                ben_map = {
                    str(r["monarch_account_id"]): r["beneficiary_user_id"]
                    for r in roles
                    if r.get("beneficiary_user_id") is not None
                }
            except Exception:
                pass

        t_records = db.education.list_tuition_year_records(family_id=family_id, db_path=DB_PATH) or []

        from routes.education import _load_tuition_records, _parse_grade_index

        current_year = date.today().year
        children_data = []
        total_529 = 0.0
        total_accounts_count = 0

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
                byear = 2015
                bmonth = 1

            grad_year = byear + 19 if bmonth >= 9 else byear + 18
            latest_anchor_yr = None
            latest_anchor_idx = None
            for r in t_records:
                g = r.get(f"{first_name}_grade") or ""
                yr_str = str(r.get("school_year", ""))
                if not g and r.get("notes"):
                    g = r.get("notes")
                if "-" in yr_str and g:
                    try:
                        s_yr = int(yr_str.split("-")[0])
                        idx = _parse_grade_index(g)
                        if idx is not None:
                            latest_anchor_yr = s_yr
                            latest_anchor_idx = idx
                    except Exception:
                        pass
            if latest_anchor_yr is not None and latest_anchor_idx is not None:
                grad_year = latest_anchor_yr + (13 - latest_anchor_idx)

            matched_bal = 0.0
            child_accounts = []
            for acc in accounts:
                if not isinstance(acc, dict):
                    continue
                acc_id = str(acc.get("id"))
                dname = (acc.get("displayName") or "").lower()
                cat = monarch_service.categorize_account(
                    acc, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps
                )
                assigned_ben = ben_map.get(acc_id)
                is_edu = (
                    cat in ("education_529", "education_530a")
                    or "529" in dname
                    or "530a" in dname
                    or "college" in dname
                    or "coverdell" in dname
                )
                is_match = False
                if assigned_ben is not None and assigned_ben == child_id and is_edu:
                    is_match = True
                elif (first_name in dname or ("530a" in dname and first_name in dname)) and is_edu:
                    is_match = True

                if is_match:
                    bal = float(acc.get("currentBalance") or 0.0)
                    matched_bal += bal
                    type_label = "530A Custodial" if (cat == "education_530a" or "530a" in dname) else "529 Plan"
                    child_accounts.append({"type": type_label, "balance": bal})
                    total_accounts_count += 1

            total_529 += matched_bal
            types_str = (
                " • ".join(list(dict.fromkeys(a["type"] for a in child_accounts)))
                if child_accounts
                else "529 Plan • Custodial"
            )
            rem_yrs = max(0.0, grad_year - current_year)
            p_bal = matched_bal
            full_yrs = int(rem_yrs)
            annual_k12_draw = 20000.0 if enable_529_k12 else 0.0
            for _ in range(full_yrs):
                p_bal = (p_bal * 1.07) - annual_k12_draw
            part = rem_yrs - full_yrs
            if part > 0:
                p_bal = p_bal * pow(1.07, part)
            p_bal = round(max(0.0, p_bal))

            children_data.append({
                "user_id": child_id,
                "first_name": first_name.capitalize(),
                "child_key": first_name,
                "college_matriculation_year": grad_year,
                "years_remaining": rem_yrs,
                "current_529_balance": matched_bal,
                "current_529_balance_str": fmt_currency(matched_bal, 0),
                "projected_529_balance": p_bal,
                "projected_529_balance_str": fmt_currency(p_bal, 0),
                "types_str": types_str,
                "accounts": child_accounts,
            })

        records = _load_tuition_records(family_id, children_data)
        total_actual = 0.0
        total_proj = 0.0
        k12_elig = 0.0
        future_years = [r for r in records if r.get("is_projected")]
        for c in children_data:
            c_key = c["child_key"]
            c_actual = sum(float(r.get(c_key, 0.0) or 0.0) for r in records if not r.get("is_projected"))
            c_proj = sum(float(r.get(c_key, 0.0) or 0.0) for r in records if r.get("is_projected"))
            total_actual += c_actual
            total_proj += c_proj
            for r in future_years:
                amt = float(r.get(c_key, 0.0) or 0.0)
                notes = (r.get("notes") or "").lower()
                s_name = (r.get(f"{c_key}_school") or r.get("school_name") or "").lower()
                yr = int(r.get("school_year", "0").split("-")[0]) if "-" in str(r.get("school_year", "")) else 0
                is_college = any(
                    w in notes or w in s_name for w in ["college", "university", "undergrad", "higher ed"]
                ) or (c["college_matriculation_year"] and yr >= c["college_matriculation_year"])
                if is_college:
                    k12_elig += amt
                elif enable_529_k12:
                    k12_cap = 20000.0 if (yr >= 2026 or yr == 0) else 10000.0
                    k12_elig += min(k12_cap, amt)

        grand_total = total_actual + total_proj
        tuition_cashflow = max(0.0, total_proj - k12_elig)

        tuition_splits = [
            f"{c['first_name']} ({fmt_short_currency(sum(float(r.get(c['child_key'], 0.0) or 0.0) for r in records))})"
            for c in children_data
        ]
        tuition_split_str = " • ".join(tuition_splits) if tuition_splits else "Per-Child Expenses"

        child1_total = (
            sum(float(r.get(children_data[0]["child_key"], 0.0) or 0.0) for r in records)
            if len(children_data) > 0
            else 0.0
        )
        child2_total = (
            sum(float(r.get(children_data[1]["child_key"], 0.0) or 0.0) for r in records)
            if len(children_data) > 1
            else 0.0
        )

        tuition_rows = []
        for r in records:
            c1_key = children_data[0]["child_key"] if len(children_data) > 0 else "child1"
            c2_key = children_data[1]["child_key"] if len(children_data) > 1 else "child2"
            c1_amt = float(r.get(c1_key, 0.0) or 0.0) if len(children_data) > 0 else 0.0
            c2_amt = float(r.get(c2_key, 0.0) or 0.0) if len(children_data) > 1 else 0.0
            c1_grade = str(r.get(f"{c1_key}_grade") or "")
            c2_grade = str(r.get(f"{c2_key}_grade") or "")
            tot_amt = float(r.get("total", c1_amt + c2_amt) or 0.0)
            is_proj = bool(r.get("is_projected"))
            notes = r.get("notes") or ("Projected" if is_proj else "")
            s_name = (r.get("school_name") or "").lower()
            yr_int = int(r.get("school_year", "0").split("-")[0]) if "-" in str(r.get("school_year", "")) else 0
            is_col = any(
                w in notes.lower() or w in s_name for w in ["college", "university", "undergrad", "higher ed"]
            ) or any(
                c["college_matriculation_year"] and yr_int >= c["college_matriculation_year"] for c in children_data
            )
            k12_cap = 20000.0 if (yr_int >= 2026 or yr_int == 0) else 10000.0
            elig_529 = tot_amt if is_col else ((min(k12_cap, c1_amt) + min(k12_cap, c2_amt)) if enable_529_k12 else 0.0)
            tuition_rows.append({
                "school_year": r.get("school_year"),
                "c1_raw": c1_amt,
                "c1_grade": c1_grade,
                "c2_raw": c2_amt,
                "c2_grade": c2_grade,
                "c1_amt": fmt_currency(c1_amt, 0) if c1_amt > 0 else "--",
                "c2_amt": fmt_currency(c2_amt, 0) if c2_amt > 0 else "--",
                "total_amt": fmt_currency(tot_amt, 0),
                "elig_529": fmt_currency(elig_529, 0) if elig_529 > 0 else ("$0 (Disabled)" if not enable_529_k12 else "--"),
                "notes": notes,
                "is_projected": is_proj,
            })

        benchmarks = [
            {
                "tier": "In-State Public",
                "school": "In-State Public University (Flagship Campus)",
                "annual_coa": 34500,
                "four_year_total": 138000,
            },
            {
                "tier": "Out-of-State Public",
                "school": "UC Berkeley / Univ. of Michigan",
                "annual_coa": 76000,
                "four_year_total": 304000,
            },
            {
                "tier": "Private Non-Profit",
                "school": "USC / NYU / Boston University",
                "annual_coa": 92000,
                "four_year_total": 368000,
            },
            {
                "tier": "Private Elite",
                "school": "Stanford / Harvard / MIT / Ivy League",
                "annual_coa": 98000,
                "four_year_total": 392000,
            },
        ]
        benchmark_rows = []
        for b in benchmarks:
            c_cols = []
            all_funded = True
            min_pct = 999
            for idx, c in enumerate(children_data):
                use_proj = active_horizon in ("all", f"c{idx}")
                c_bal = float(c["projected_529_balance"] if use_proj else c["current_529_balance"])
                target_cost = (
                    round(b["four_year_total"] * pow(1.045, c["years_remaining"]))
                    if use_proj
                    else b["four_year_total"]
                )
                diff = c_bal - target_cost
                pct = round((c_bal / target_cost) * 100) if target_cost > 0 else 0
                if diff < 0:
                    all_funded = False
                if pct < min_pct:
                    min_pct = pct
                c_cols.append({
                    "pct": pct,
                    "diff_str": f"{'+' if diff >= 0 else ''}{fmt_short_currency(diff)}",
                    "color": "var(--status-green)" if diff >= 0 else "var(--status-red)",
                })
            benchmark_rows.append({
                "tier": b["tier"],
                "school": b["school"],
                "annual_coa": f"${b['annual_coa']:,}/yr",
                "four_year_total": f"${b['four_year_total']:,}",
                "child_cols": c_cols,
                "badge_class": "badge-green" if all_funded else "badge-orange",
                "status_text": "✓ 100% Fully Funded" if all_funded else f"{min_pct}% Funded",
            })

        milestone_cards = []
        for idx, ch in enumerate(children_data):
            c_bal = float(ch["current_529_balance"])
            p_bal = float(ch["projected_529_balance"])
            mat_yr = ch["college_matriculation_year"]
            rem_yrs = ch["years_remaining"]

            color = (
                "var(--accent-orange)"
                if idx == 0
                else ("var(--accent-blue)" if idx == 1 else "var(--accent-green)")
            )
            badge = "badge-orange" if idx == 0 else ("badge-blue" if idx == 1 else "badge-green")
            milestone_cards.append({
                "name": ch["first_name"],
                "color": color,
                "badge": badge,
                "years_remaining": f"~{rem_yrs:.1f} Years to College",
                "mat_year": mat_yr,
                "hs_grad_year": mat_yr,
                "cur_bal_str": fmt_currency(c_bal, 0),
                "proj_bal_str": f"~{fmt_currency(p_bal, 0)}",
            })

        return {
            "horizon": active_horizon,
            "enable_529_k12": enable_529_k12,
            "total_assets": fmt_currency(total_529, 0),
            "accounts_badge": f"{total_accounts_count} Synchronized Accounts",
            "children": children_data,
            "milestones": milestone_cards,
            "tuition_total": fmt_currency(grand_total, 0),
            "tuition_split_str": tuition_split_str,
            "model_529_k12_coverage": fmt_currency(k12_elig, 0),
            "model_tuition_cashflow": fmt_currency(tuition_cashflow, 0),
            "child1_total": fmt_currency(child1_total, 0),
            "child2_total": fmt_currency(child2_total, 0),
            "tuition_rows": tuition_rows,
            "benchmark_rows": benchmark_rows,
        }
    except Exception as e:
        logger.warning(f"Failed to generate SSR college data: {e}")
        return {}


def format_guardrail_mode_badge(mode: str | None) -> str:
    """Returns human-readable badge label for spending guardrail mode."""
    m = str(mode or "off").lower().strip()
    if m == "moderate":
        return "Moderate (-15%)"
    if m == "aggressive":
        return "Aggressive (-25%)"
    return "Off"


def get_scenario_guardrail_display(scen: dict | None) -> dict[str, str]:
    """Extracts guardrail mode and formatted badge for SSR scenario plan cards."""
    mode = str((scen or {}).get("spending_guardrail_mode") or "off").lower().strip()
    if mode not in ("moderate", "aggressive"):
        mode = "off"
    return {
        "spending_guardrail_mode": mode,
        "guardrails_badge_label": format_guardrail_mode_badge(mode),
    }
