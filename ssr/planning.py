"""
SSR view-model builders for Family Gifting, Philanthropy, Estate Planning, and College Education.
"""

from __future__ import annotations
import logging
import re

import db
import security
from ssr.formatting import fmt_currency, fmt_short_currency
from ssr.planning_helpers import build_ssr_college

logger = logging.getLogger(__name__)


def build_ssr_gifting(family_id: int, active_year: str | None = None) -> dict:
    """Prepares SSR data for Family Gifting (year pills, active year total, recipient rows, footers)."""
    if family_id <= 0:
        return {}
    try:
        from routes.gifting import _load_gifting_data
        limits, summary, yearly = _load_gifting_data(family_id)

        year_set = {"2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"}
        for rec in summary.values():
            if isinstance(rec, dict):
                year_set.update(rec.keys())
        for yr in yearly.keys():
            year_set.add(str(yr))
        if active_year and str(active_year).isdigit():
            year_set.add(str(active_year))

        years = sorted(year_set, key=lambda y: int(y) if str(y).isdigit() else 0)
        active_year = str(active_year) if (active_year and str(active_year) in years) else "2026"
        if active_year not in years and years:
            active_year = years[0]

        grand_total_gifted = 0.0
        grand_total_limit = 0.0
        recipients_rows = []

        for name in limits.keys():
            lim_info = limits[name] or {}
            count = lim_info.get("num_people") or lim_info.get("beneficiary_count") or 1
            limit = float(lim_info.get("limit_from_couple") or lim_info.get("joint_annual_limit") or (count * 38000.0))
            gifted = float((summary.get(name) or {}).get(active_year) or 0.0)
            headroom = max(0.0, limit - gifted)

            grand_total_limit += limit
            grand_total_gifted += gifted

            recipients_rows.append({
                "name": name,
                "count": count,
                "count_label": f"{count} Individuals" if count > 1 else "1 Individual",
                "limit": limit,
                "limit_str": fmt_currency(limit, 0),
                "gifted": gifted,
                "gifted_str": fmt_currency(gifted, 0),
                "gifted_color": "var(--status-red)" if gifted > limit else "var(--status-green)",
                "headroom_str": fmt_currency(headroom, 0),
                "headroom_color": "var(--text-muted)" if headroom == 0 else "var(--status-green)",
                "badge_class": "badge-orange" if gifted > limit else "badge-green",
                "badge_text": "Form 709 Required" if gifted > limit else "✓ 100% Tax-Exempt",
            })

        grand_total_headroom = max(0.0, grand_total_limit - grand_total_gifted)

        return {
            "active_year": active_year,
            "header_title": f"Family Gifting ({active_year} Budget)",
            "active_year_total": fmt_currency(grand_total_gifted, 0),
            "total_limit": fmt_currency(grand_total_limit, 0),
            "total_headroom": fmt_currency(grand_total_headroom, 0),
            "footer_label": f"TOTAL ANNUAL FAMILY GIFTS ({active_year})",
            "years": years,
            "recipients": recipients_rows,
        }
    except Exception as e:
        logger.warning(f"Failed to generate SSR gifting data: {e}")
        return {}


def build_ssr_philanthropy(
    family_id: int,
    active_year: str | None = None,
    sort_key: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    """Prepares formatted strings for SSR Philanthropy cards and grant ledger."""
    if family_id <= 0:
        return {}
    try:
        from routes.helpers import DB_PATH
        data = db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}
        lifetime = float(data.get("total_lifetime_charity") or 0.0)
        d_by_year = data.get("donations_by_year") or {}
        annual_budgets = data.get("annual_budgets") or {}
        active_year = str(active_year) if active_year else "2026"
        y_active = d_by_year.get(active_year) or {}
        donations = y_active.get("donations") or []
        yr_total = float(y_active.get("total") or sum(float(d.get("amount") or 0.0) for d in donations))
        yr_budget = float(
            y_active.get("budget") or annual_budgets.get(active_year) or (yr_total if yr_total > 0 else 0.0)
        )
        yr_allocated = sum(
            float(d.get("amount") or 0.0) for d in donations if (d.get("organization") or "").lower() != "available"
        )
        yr_remaining = max(0.0, yr_budget - yr_allocated)

        hist = data.get("lifetime_history") or []
        start_yr = hist[0].get("year") if hist else 2020
        end_yr = hist[-1].get("year") if hist else 2030
        years_span = len(hist) if hist else 19
        phil_years = sorted(
            list({str(h.get("year")) for h in hist if h.get("year")} | set(d_by_year.keys()) | set(annual_budgets.keys()) | {active_year}),
            key=lambda y: int(y) if str(y).isdigit() else 0,
        )

        grant_count_sub = (
            f"{len(donations)} grants • {fmt_short_currency(yr_allocated)} allocated • "
            f'<strong style="color: var(--status-green);">{fmt_short_currency(yr_remaining)} available</strong>'
        )

        donations_rows = []
        for orig_idx, g in enumerate(donations):
            amt = float(g.get("amount") or 0.0)
            raw_desc = re.sub(r"\$(\d{4,})", lambda m: f"${int(m.group(1)):,}", g.get("description") or "")
            clean_desc = raw_desc or "--"
            raw_date = g.get("date") or ""
            donations_rows.append({
                "orig_idx": orig_idx,
                "organization": g.get("organization") or g.get("recipient") or "",
                "description": clean_desc,
                "raw_description": raw_desc,
                "date": raw_date or "--",
                "raw_date": raw_date,
                "amount": amt,
                "amount_str": fmt_currency(amt, 0),
            })

        s_key = (sort_key or "").strip().lower()
        s_dir = "desc" if (sort_dir or "").strip().lower() == "desc" else "asc"
        if s_key == "org":
            donations_rows.sort(key=lambda r: r["organization"].lower(), reverse=(s_dir == "desc"))
        elif s_key == "date":
            donations_rows.sort(key=lambda r: r["raw_date"], reverse=(s_dir == "desc"))
        elif s_key == "amount":
            donations_rows.sort(key=lambda r: r["amount"], reverse=(s_dir == "desc"))

        return {
            "lifetime_total": fmt_currency(lifetime, 0),
            "planned_2026": fmt_currency(yr_budget, 0),
            "allocated_2026": fmt_currency(yr_allocated, 0),
            "budget_2026": fmt_currency(yr_budget, 0),
            "budget_raw": yr_budget,
            "history_badge": f"{years_span}-Year History ({start_yr}–{end_yr})",
            "years": phil_years,
            "active_year": active_year,
            "sort_key": s_key,
            "sort_dir": s_dir,
            "grant_count": len(donations),
            "allocated_str": fmt_short_currency(yr_allocated),
            "remaining_str": fmt_short_currency(yr_remaining),
            "grant_count_sub": grant_count_sub,
            "ledger_title": f"Charitable Grants & DAF Distributions ({active_year} Ledger)",
            "footer_label": f"TOTAL CHARITABLE GRANTS ({active_year})",
            "footer_total": f"{fmt_currency(yr_allocated, 0)} (Budget: {fmt_currency(yr_budget, 0)})",
            "donations_rows": donations_rows,
        }
    except Exception as e:
        logger.warning(f"Failed to generate SSR philanthropy data: {e}")
        return {}


def build_ssr_estate(
    family_id: int,
    state_override: str | None = None,
    apply_tcja_sunset: bool | None = None,
    charitable_pct_override: float | None = None,
) -> dict:
    """Prepares formatted strings for SSR Estate Planning cards."""
    if family_id <= 0:
        return {}
    try:
        import estate_engine
        kwargs: dict = {"family_id": family_id}
        if state_override:
            kwargs["state_override"] = state_override
        if apply_tcja_sunset is not None:
            kwargs["apply_tcja_sunset"] = apply_tcja_sunset
        profile = estate_engine.get_family_estate_profile(**kwargs)
        if not profile:
            return {}
        cur_tax = profile.get("current_estate_tax") or {}
        gross_val = float(cur_tax.get("gross_estate") or profile.get("current_net_worth") or 0.0)
        tot_tax = float(cur_tax.get("total_estate_tax") or 0.0)
        eff_rate = float(cur_tax.get("effective_tax_rate") or 0.0)
        net_heirs = float(cur_tax.get("net_estate_to_heirs") or 0.0)
        fed_t = float(cur_tax.get("federal_estate_tax") or 0.0)
        st_t = float(cur_tax.get("state_estate_tax") or 0.0)
        st_code = profile.get("state") or "WA"
        kids = profile.get("children") or []
        num_kids = max(1, len(kids))
        per_kid = net_heirs / num_kids
        kid_prev = (
            f"{fmt_short_currency(per_kid)} each across {len(kids)} child{'ren' if len(kids) > 1 else ''}"
            if kids
            else "100% to designated heirs"
        )
        sandbox = profile.get("trust_sandbox") or {}
        max_shield = float(sandbox.get("max_potential_tax_savings") or 0.0)

        vehicles = []
        for v in sandbox.get("vehicles") or []:
            is_base = v.get("id") == "status_quo"
            tax_sav = float(v.get("tax_savings") or 0.0)
            has_sav = tax_sav > 0
            tax_due = float(v.get("estate_tax_due") or 0.0)
            border = (
                "rgba(239, 68, 68, 0.3)"
                if is_base
                else ("rgba(16, 185, 129, 0.35)" if has_sav else "var(--border-subtle)")
            )
            badge_class = "badge-red" if is_base else ("badge-green" if has_sav else "badge-blue")
            vehicles.append({
                "name": v.get("name"),
                "badge": v.get("badge"),
                "badge_class": badge_class,
                "description": v.get("description"),
                "border": border,
                "estate_tax_due": fmt_currency(tax_due, 0),
                "estate_tax_color": "var(--accent-red)" if tax_due > 0 else "var(--accent-green)",
                "tax_savings": f"+{fmt_currency(tax_sav, 0)}" if has_sav else "$0",
                "tax_savings_color": "var(--accent-green)" if has_sav else "var(--text-muted)",
                "key_mechanic": v.get("key_mechanic"),
            })

        projections_rows = []
        charity_pct = (
            float(charitable_pct_override)
            if charitable_pct_override is not None
            else float(profile.get("charitable_pct") or 0.05)
        )
        for p in profile.get("projections") or []:
            val = float(p.get("projected_gross_estate") or 0.0)
            st_tax = float(p.get("state_tax") or 0.0)
            fed_tax = float(p.get("federal_tax") or 0.0)
            tot_t = float(p.get("total_estate_tax") or 0.0)
            rem = max(0.0, val - tot_t)
            charity_amt = round(rem * charity_pct)
            heirs_amt = round(rem - charity_amt)
            p_kid = round(heirs_amt / num_kids)
            projections_rows.append({
                "milestone_age": p.get("milestone_age"),
                "projected_year": p.get("projected_year"),
                "gross_estate": fmt_currency(val, 0),
                "state_tax": fmt_currency(st_tax, 0),
                "federal_tax": fmt_currency(fed_tax, 0),
                "total_tax": fmt_currency(tot_t, 0),
                "charity_amt": fmt_currency(charity_amt, 0),
                "heirs_amt": fmt_currency(heirs_amt, 0),
                "per_kid": fmt_currency(p_kid, 0),
            })

        state_rows = []
        for sc in profile.get("state_comparisons") or []:
            is_cur = sc.get("state") == st_code
            has_tax = sc.get("has_estate_tax")
            tax_amt = float(sc.get("tax_liability") or 0.0)
            border_col = (
                "var(--accent-blue)"
                if is_cur
                else ("var(--border-subtle)" if has_tax else "rgba(16, 185, 129, 0.4)")
            )
            state_rows.append({
                "state_name": sc.get("state_name"),
                "state": sc.get("state"),
                "is_current": is_cur,
                "border": border_col,
                "tax_liability": fmt_currency(tax_amt, 0) if has_tax else "$0 State Tax",
                "tax_color": "var(--accent-red)" if tax_amt > 0 else "var(--accent-green)",
                "notes": sc.get("notes"),
            })

        survivorship_audit = {}
        try:
            from services.household_audit_service import evaluate_household_risks
            survivorship_audit = evaluate_household_risks(family_id=family_id)
        except Exception as e:
            logger.warning(f"Failed to generate survivorship audit: {e}")

        return {
            "state": st_code,
            "apply_tcja_sunset": bool(profile.get("apply_tcja_sunset")),
            "charitable_pct_int": round(charity_pct * 100),
            "gross_estate": fmt_currency(gross_val, 0),
            "total_estate_tax": fmt_currency(tot_tax, 0),
            "tax_breakdown_sub": f"Fed: {fmt_short_currency(fed_t)} + {st_code}: {fmt_short_currency(st_t)}",
            "effective_rate": f"{eff_rate:.1f}%",
            "net_to_heirs": fmt_currency(net_heirs, 0),
            "per_child_preview": kid_prev,
            "max_shielding_badge": f"Max Potential Tax Shielded: {fmt_short_currency(max_shield)}",
            "vehicles": vehicles,
            "children": kids,
            "projections": projections_rows,
            "state_comparisons": state_rows,
            "survivorship_audit": survivorship_audit,
        }
    except Exception as e:
        logger.warning(f"Failed to generate SSR estate data: {e}")
        return {}
