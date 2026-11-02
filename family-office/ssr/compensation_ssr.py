"""
SSR view-model builder for Compensation, Safe Harbor Pacing, and IRS Transcripts.
"""

from __future__ import annotations


import db
from services import tax_engine
from services.compensation_records import load_compensation_records
from services.request_context import DB_PATH
from ssr.formatting import fmt_currency, fmt_short_currency


def _prior_year_agi(item: dict) -> float | None:
    """Prior-year AGI for a transcript year: the recorded AGI, else W-2 wages as the best on-file proxy."""
    for key in ("adjusted_gross_income", "w2_wages_and_bonus", "w2_wages", "combined_w2_income"):
        val = float(item.get(key) or 0.0)
        if val > 0:
            return val
    return None


def _current_year_federal_tax_estimate(history: list, view_history: list, filing_status: str) -> float:
    """Federal income tax on the household's latest-year pay, scaled to the viewed taxpayer's share of that pay."""
    def pay(r: dict) -> float:
        base = float(r.get("salary") or r.get("base_salary") or 0.0)
        return float(r.get("total_compensation") or r.get("total_cash") or (base + float(r.get("bonus") or 0.0)))

    def latest_total(records: list) -> float:
        latest = max((int(r.get("year") or 0) for r in records), default=0)
        return sum(pay(r) for r in records if int(r.get("year") or 0) == latest)

    household_pay = latest_total(history)
    if household_pay <= 0:
        return 0.0
    take_home = tax_engine.calculate_household_take_home_pay(household_pay, "", filing_status, has_spouse=False)
    fed_tax = take_home["federal_tax"]
    return fed_tax * min(1.0, latest_total(view_history) / household_pay)


def build_ssr_compensation(
    family_id: int,
    taxpayer_filter: str | None = None,
    subtab: str | None = None,
    ytd_withheld_override: float | None = None,
    remaining_paychecks_override: int | None = None,
) -> dict:
    """Prepares formatted strings for SSR Compensation, Safe Harbor Pacing, and IRS Transcripts."""
    if family_id <= 0:
        return {}
    history, _, _, raw_adults = load_compensation_records(family_id, DB_PATH)
    if not history and not raw_adults:
        return {}

    adults = []
    for idx, a in enumerate(raw_adults, start=1):
        if a.get("name") == "Combined Household" or str(a.get("relationship") or "").lower() == "combined":
            continue
        item = dict(a)
        uid_val = item.get("id") if item.get("id") is not None else item.get("user_id")
        item["id"] = uid_val if uid_val is not None else idx
        adults.append(item)

    valid_subtabs = ("comp-subtab-career", "comp-subtab-safeharbor", "comp-subtab-transcripts")
    active_subtab = str(subtab).strip() if (subtab and str(subtab).strip() in valid_subtabs) else "comp-subtab-career"

    raw_tp = str(taxpayer_filter).strip() if taxpayer_filter is not None else ""
    if not raw_tp or raw_tp.lower() in ("all", "combined household", "none"):
        active_taxpayer, selected_adult_name = "all", "Combined Household"
    else:
        matched_adult = next((a for a in adults if str(a.get("id")) == raw_tp or str(a.get("name") or "").lower() == raw_tp.lower()), None)
        active_taxpayer = str(matched_adult["id"]) if matched_adult else raw_tp
        selected_adult_name = str(matched_adult.get("name") or "Household Member") if matched_adult else raw_tp

    filtered_history = (
        history if active_taxpayer == "all" else [
            item for item in history
            if str(item.get("user_id", 1)) == active_taxpayer or str(item.get("taxpayer") or "").lower() == selected_adult_name.lower()
        ]
    )

    total_base = total_bonus = total_cash = 0.0
    bonus_years = 0
    peak_record = latest_record = None
    for item in filtered_history:
        base = float(item.get("salary") or item.get("base_salary") or 0.0)
        bonus = float(item.get("bonus") or 0.0)
        tot = float(item.get("total_compensation") or item.get("total_cash") or (base + bonus))
        yr = int(item.get("year") or 0)
        total_base += base
        total_bonus += bonus
        total_cash += tot
        if bonus > 0:
            bonus_years += 1
        if not peak_record or tot > peak_record["total"]:
            peak_record = {"year": yr, "salary": base, "bonus": bonus, "total": tot}
        if not latest_record or yr > latest_record["year"]:
            latest_record = {"year": yr, "salary": base, "bonus": bonus, "total": tot}

    bonus_pct = ((total_bonus / total_cash) * 100.0) if total_cash > 0 else 0.0
    bonus_sub = f"{bonus_years} Bonus Years • {bonus_pct:.1f}% of Lifetime Comp"
    peak_str = fmt_currency(peak_record["total"], 0) if peak_record else "--"
    peak_sub = f"{peak_record['year']} Peak ({fmt_short_currency(peak_record['salary'])} Base + {fmt_short_currency(peak_record['bonus'])} Bonus)" if peak_record else "--"
    active_salary_str = fmt_currency(latest_record["salary"], 0) if latest_record else "--"
    active_salary_sub = f"{latest_record['year']} Active Base ({fmt_currency(latest_record['salary'] / 12, 0)}/mo)" if latest_record else "Regular payroll"

    sh_prior_tax = sh_target = sh_shortfall = ytd_withheld = 0.0
    sh_prior_agi = None
    hp = db.household.get_household_profile(family_id=family_id, db_path=DB_PATH) or {}
    filing_status = str(hp.get("filing_status") or "MFJ")
    # No pay frequency is stored for the household: paychecks left is known only when the caller supplies it.
    remaining_paychecks = (
        max(1, min(52, int(remaining_paychecks_override))) if remaining_paychecks_override is not None else None
    )
    sh_extra, sh_rule_target = "Not set", "$0"
    sh_multiplier = tax_engine.safe_harbor_prior_year_multiplier(None, filing_status)
    sh_status_badge, sh_status_badge_class = "No Prior Tax Liability on File (Penalty-Free)", "badge badge-green"
    withholding_transcripts_rows, transcript_rows = [], []
    transcript_adults = [a.get("name") for a in adults if a.get("name") and a.get("name") != "Combined Household"]

    tdata = db.transcripts.get_transcripts_payload(family_id=family_id, db_path=DB_PATH) or {}
    raw_historical = tdata.get("historical_summary") or {}

    t_adults = list(tdata.get("adults") or []) or (["Combined Household"] + transcript_adults)
    transcript_adults = [a for a in t_adults if a != "Combined Household"]

    primary_adult = t_adults[1] if len(t_adults) > 1 else "Taxpayer 1"
    spouse_adult = t_adults[2] if len(t_adults) > 2 else "Taxpayer 2"
    adult_data = dict(tdata.get("transcripts_by_adult") or {})
    if not adult_data:
        adult_data = {primary_adult: raw_historical, spouse_adult: {}}
    else:
        adult_data.setdefault(primary_adult, raw_historical)
        adult_data.setdefault(spouse_adult, {})

    if active_taxpayer == "all":
        sh_source_historical = raw_historical
    elif selected_adult_name in adult_data:
        sh_source_historical = adult_data.get(selected_adult_name) or {}
    elif active_taxpayer == "1" or (adults and str(adults[0].get("id")) == active_taxpayer):
        sh_source_historical = adult_data.get(primary_adult) or {}
    else:
        sh_source_historical = adult_data.get(spouse_adult) or {}

    normalized_history = {}
    for yr, ydata in (sh_source_historical or {}).items():
        if not isinstance(ydata, dict):
            continue
        item = dict(ydata)
        if "w2_forms" in item and isinstance(item["w2_forms"], list):
            total_w2 = sum(float(f.get("wages_tips_compensation", 0.0) or 0.0) for f in item["w2_forms"])
            total_fed = sum(float(f.get("federal_income_tax_withheld", 0.0) or 0.0) for f in item["w2_forms"])
            total_ss = sum(float(f.get("social_security_tax_withheld", 0.0) or (float(f.get("social_security_wages", 0.0) or 0.0) * 0.062)) for f in item["w2_forms"])
            total_med = sum(float(f.get("medicare_tax_withheld", 0.0) or (float(f.get("medicare_wages", 0.0) or 0.0) * 0.0145)) for f in item["w2_forms"])
            if not item.get("federal_tax_withheld"):
                item["federal_tax_withheld"] = total_fed
            if not item.get("w2_wages_and_bonus") and not item.get("w2_wages"):
                item["w2_wages_and_bonus"] = total_w2
            if not item.get("social_security_withheld"):
                item["social_security_withheld"] = total_ss
            if not item.get("medicare_tax_withheld"):
                item["medicare_tax_withheld"] = total_med
        if "combined_w2_income" in item and not item.get("w2_wages_and_bonus"):
            item["w2_wages_and_bonus"] = item["combined_w2_income"]
        row_mult = tax_engine.safe_harbor_prior_year_multiplier(_prior_year_agi(item), filing_status)
        item["safe_harbor_multiplier"] = row_mult
        if item.get("federal_tax_withheld") and (not item.get("safe_harbor_110_target") or row_mult < 1.10):
            item["safe_harbor_110_target"] = round(float(item["federal_tax_withheld"]) * row_mult, 2)
        normalized_history[str(yr)] = item

    sorted_wh_years = sorted(normalized_history.keys(), key=lambda y: int(y) if str(y).isdigit() else 0, reverse=True)
    for yr in sorted_wh_years:
        val = float(normalized_history[yr].get("federal_tax_withheld", 0.0) or 0.0)
        if val > 0:
            sh_prior_tax = val
            sh_prior_agi = _prior_year_agi(normalized_history[yr])
            break

    if ytd_withheld_override is not None:
        ytd_withheld = max(0.0, float(ytd_withheld_override))
    else:
        ytd_withheld = 0.0

    sh_calc = tax_engine.calculate_withholding_safe_harbor(
        current_year_projected_tax=_current_year_federal_tax_estimate(history, filtered_history, filing_status),
        prior_year_total_tax=sh_prior_tax,
        current_ytd_withheld=ytd_withheld,
        remaining_paychecks=remaining_paychecks or 0,
        prior_year_agi=sh_prior_agi,
        filing_status=filing_status,
    )
    sh_multiplier = float(sh_calc.get("prior_year_multiplier") or 1.0)
    sh_target = float(sh_calc.get("safe_harbor_target") or 0.0)
    sh_shortfall = max(0.0, sh_target - ytd_withheld)
    if remaining_paychecks:
        sh_extra = f"{fmt_currency(sh_shortfall / remaining_paychecks, 0)} / pay"
    sh_rule_target = fmt_currency(sh_target, 0)

    if sh_target == 0:
        sh_status_badge_class, sh_status_badge = "badge badge-green", "No Prior Tax Liability on File (Penalty-Free)"
    elif sh_shortfall <= 0:
        sh_status_badge_class, sh_status_badge = "badge badge-green", "Safe Harbor Met (100% Penalty-Free)"
    else:
        sh_status_badge_class, sh_status_badge = "badge badge-orange", f"{fmt_currency(sh_shortfall, 0)} Shortfall Remaining"

    latest_wh_year = sorted_wh_years[0] if sorted_wh_years else None
    for yr in sorted_wh_years:
        item = normalized_history[yr]
        is_latest = yr == latest_wh_year
        w2_val = float(item.get("w2_wages_and_bonus") or item.get("w2_wages") or item.get("base_salary_and_bonus") or item.get("adjusted_gross_income") or 0.0)
        fed_val = float(item.get("federal_tax_withheld") or 0.0)
        fica_val = float(item.get("social_security_withheld") or 0.0) + float(item.get("medicare_tax_withheld") or 0.0)
        target_val = float(item.get("safe_harbor_110_target") or (fed_val * float(item.get("safe_harbor_multiplier") or 1.10)))
        next_yr = (int(yr) + 1) if str(yr).isdigit() else yr
        withholding_transcripts_rows.append({
            "year": str(yr), "is_latest": is_latest,
            "w2_str": fmt_currency(w2_val, 0) if w2_val > 0 else "--",
            "fed_str": fmt_currency(fed_val, 0) if fed_val > 0 else "--",
            "fica_str": fmt_currency(fica_val, 0) if fica_val > 0 else "--",
            "target_str": (f"{fmt_currency(target_val, 0)} (For {next_yr})" if is_latest else fmt_currency(target_val, 0)) if target_val > 0 else "--",
            "status_badge_class": "badge-green" if is_latest else "badge-blue",
            "status_text": f"Sets {next_yr} Target" if is_latest else "Completed",
        })

    all_t_years = sorted(
        set(list(raw_historical.keys()) + [yr for a in adult_data.values() if isinstance(a, dict) for yr in a.keys()])
        if active_taxpayer == "all" else list((sh_source_historical or {}).keys()),
        key=lambda y: int(y) if str(y).isdigit() else 0,
        reverse=True,
    )

    for yr in all_t_years:
        if active_taxpayer == "all":
            non_comb = [a for a in t_adults if a != "Combined Household"]
            fed_tot = sum(float((adult_data.get(a) or {}).get(yr, {}).get("federal_tax_withheld", 0.0) or 0.0) for a in non_comb)
            ss_tot = sum(float((adult_data.get(a) or {}).get(yr, {}).get("social_security_withheld", 0.0) or 0.0) for a in non_comb)
            med_tot = sum(float((adult_data.get(a) or {}).get(yr, {}).get("medicare_tax_withheld", 0.0) or 0.0) for a in non_comb)
            mort_tot = sum(float((adult_data.get(a) or {}).get(yr, {}).get("mortgage_interest_paid", 0.0) or 0.0) for a in non_comb)
            div_tot = sum(float((adult_data.get(a) or {}).get(yr, {}).get("qualified_dividends", 0.0) or 0.0) for a in non_comb)
            cg_tot = sum(float((adult_data.get(a) or {}).get(yr, {}).get("realized_capital_gains", 0.0) or 0.0) for a in non_comb)
            t_target = (normalized_history.get(str(yr)) or {}).get("safe_harbor_110_target")
            if fed_tot == 0 and yr in raw_historical:
                row_src = raw_historical[yr] or {}
                fed_tot = float(row_src.get("federal_tax_withheld", 0.0) or 0.0)
                ss_tot = float(row_src.get("social_security_withheld", 0.0) or 0.0)
                med_tot = float(row_src.get("medicare_tax_withheld", 0.0) or 0.0)
                mort_tot = float(row_src.get("mortgage_interest_paid", 0.0) or 0.0)
                div_tot = float(row_src.get("qualified_dividends", 0.0) or 0.0)
                cg_tot = float(row_src.get("realized_capital_gains", 0.0) or 0.0)
                t_target = (normalized_history.get(str(yr)) or {}).get("safe_harbor_110_target") or row_src.get("safe_harbor_110_target")
        else:
            row_src = (sh_source_historical or {}).get(yr) or {}
            fed_tot = float(row_src.get("federal_tax_withheld", 0.0) or 0.0)
            ss_tot = float(row_src.get("social_security_withheld", 0.0) or 0.0)
            med_tot = float(row_src.get("medicare_tax_withheld", 0.0) or 0.0)
            mort_tot = float(row_src.get("mortgage_interest_paid", 0.0) or 0.0)
            div_tot = float(row_src.get("qualified_dividends", 0.0) or 0.0)
            cg_tot = float(row_src.get("realized_capital_gains", 0.0) or 0.0)
            t_target = (normalized_history.get(str(yr)) or {}).get("safe_harbor_110_target") or row_src.get("safe_harbor_110_target")

        fica_med, divs_cg = ss_tot + med_tot, div_tot + cg_tot
        if t_target:
            row_pct = int(round(float((normalized_history.get(str(yr)) or {}).get("safe_harbor_multiplier") or 1.10) * 100))
            t_badge, t_status = ("badge-green", f"✓ Met ({row_pct}%)") if fed_tot >= float(t_target) else ("badge-orange", "Shortfall")
        else:
            t_badge, t_status = "badge-gray", "Baseline"

        transcript_rows.append({
            "tax_year": str(yr), "fed_withheld": fmt_currency(fed_tot, 0), "fica": fmt_currency(fica_med, 0),
            "mortgage": fmt_currency(mort_tot, 0) if mort_tot > 0 else "--",
            "div_cap": fmt_currency(divs_cg, 0) if divs_cg != 0 else "--",
            "target": fmt_currency(float(t_target), 0) if t_target else "N/A",
            "badge_class": t_badge, "status": t_status,
        })

    history_rows = []
    for item in sorted(filtered_history, key=lambda x: int(x.get("year", 0)), reverse=True):
        b = float(item.get("salary") or item.get("base_salary") or 0.0)
        bo = float(item.get("bonus") or 0.0)
        t = float(item.get("total_compensation") or item.get("total_cash") or (b + bo))
        emp = item.get("company") or item.get("employer") or "Company"
        uid = item.get("user_id") or 1
        yr_int = int(item.get("year", 0))
        comp_clean = "".join(c for c in emp.lower() if c.isalnum())
        history_rows.append({
            "year": yr_int, "user_id": uid, "employer": emp,
            "taxpayer": item.get("taxpayer") or "Household Member",
            "taxpayer_badge": "badge-blue" if uid == 1 else "badge-purple",
            "salary_num": b, "bonus_num": bo,
            "salary": fmt_currency(b, 0), "bonus": fmt_currency(bo, 0) if bo > 0 else "--",
            "total": fmt_currency(t, 0), "source": item.get("source") or "Verified Record / W-2",
            "row_key": f"{yr_int}_{comp_clean}_{uid}",
        })

    tax_checklist = {}
    from services.tax_checklist_service import get_tax_document_checklist
    tax_checklist = get_tax_document_checklist(family_id=family_id, db_path=DB_PATH)

    return {
        "active_taxpayer": active_taxpayer, "selected_adult_name": selected_adult_name,
        "active_subtab": active_subtab, "lifetime_total": fmt_currency(total_cash, 0),
        "bonus_total": fmt_currency(total_bonus, 0), "bonus_sub": bonus_sub,
        "peak_total": peak_str, "peak_sub": peak_sub,
        "active_salary": active_salary_str, "active_salary_sub": active_salary_sub,
        "sh_target": fmt_currency(sh_target, 0) if sh_target > 0 else "$0",
        "sh_multiplier_pct": int(round(sh_multiplier * 100)),
        "sh_prior_tax": fmt_currency(sh_prior_tax, 0) if sh_prior_tax > 0 else "$0",
        "sh_shortfall": fmt_currency(sh_shortfall, 0), "sh_extra_per_paycheck": sh_extra,
        "sh_rule_target": sh_rule_target, "sh_status_badge": sh_status_badge,
        "sh_status_badge_class": sh_status_badge_class,
        "ytd_withheld": int(round(ytd_withheld)), "remaining_paychecks": remaining_paychecks,
        "withholding_transcripts_rows": withholding_transcripts_rows,
        "transcript_rows": transcript_rows, "transcript_adults": transcript_adults,
        "adults": adults, "foot_base": fmt_currency(total_base, 0),
        "foot_bonus": fmt_currency(total_bonus, 0), "foot_total": fmt_currency(total_cash, 0),
        "history_rows": history_rows,
        "tax_checklist": tax_checklist,
    }


__all__ = ["build_ssr_compensation"]
