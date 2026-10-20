"""
Tab-specific callable tools for the AI Financial Advisor:
Accounts & Balance Sheet, Multi-Scenario Forecasting & Life Events,
Career Compensation / Safe Harbor Withholding / IRS Transcripts,
Multi-State Tax Arbitrage, Education 529 & Tuition Planning,
Philanthropy & DAF Grants, and Family Gifting (IRS Form 709).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import monarch_service
from services.advisor.tools_core import (
    _resolve_tool_family_id,
    estimate_equity_exercise_tax,
    get_cash_flow_summary,
    get_equity_schedule,
    get_estate_tax_summary,
    get_monte_carlo_stress_test,
    get_portfolio_allocation,
    simulate_financial_scenario,
)
from services.advisor.tools_scenarios import enrich_scenarios_and_events_payload, manage_scenario_life_event
from ssr.accounts import build_ssr_accounts, build_ssr_arbitrage, build_ssr_compensation
from ssr.planning import build_ssr_college, build_ssr_gifting, build_ssr_philanthropy
from services.household_audit_service import audit_household_risks
from services.tax_checklist_service import compute_monarch_core_burn_calibration, get_tax_document_checklist
from services.advisor.tools_operations import (
    get_private_markets_lp_book,
    manage_lp_commitment,
    update_tax_document_checklist_status,
)

logger = logging.getLogger(__name__)


def get_accounts_and_balance_sheet(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves all individual household accounts grouped by balance sheet category
    (Cash & Liquid, Public Brokerage, Retirement, Real Estate, Private Investments,
    Education 529/530A, Mortgages, Credit Cards), including institution, account type,
    balance, sync provider (Monarch, SimpleFIN, Manual), and recent balance history.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        snap = monarch_service.get_financial_snapshot(family_id=fam_id) or {}
        ssr_acc = build_ssr_accounts(snap, family_id=fam_id)
        if not ssr_acc:
            return {}
        return {
            "total_accounts_count": ssr_acc.get("total_count", 0),
            "monarch_synced_count": ssr_acc.get("monarch_count", 0),
            "simplefin_synced_count": ssr_acc.get("simplefin_count", 0),
            "manual_accounts_count": ssr_acc.get("manual_count", 0),
            "has_monarch": ssr_acc.get("has_monarch", False),
            "has_simplefin": ssr_acc.get("has_simplefin", False),
            "categories": [
                {
                    "category_key": cat.get("key"), "category_label": cat.get("label"),
                    "category_total": cat.get("total_str"), "is_excluded_from_net_worth": cat.get("is_excluded", False),
                    "accounts": [
                        {
                            "name": a.get("name"), "type": a.get("type"), "institution": a.get("institution"),
                            "provider": a.get("source_label"), "balance": a.get("balance_raw", 0.0),
                            "balance_formatted": a.get("balance_str"), "is_child_account": a.get("is_child_account", False),
                            "include_in_net_worth": a.get("include_in_net_worth", True),
                        }
                        for a in (cat.get("accounts") or [])
                    ],
                }
                for cat in (ssr_acc.get("categories") or [])
            ],
            "recent_balance_history": [
                {"account_name": h.get("account_name"), "date": h.get("date"), "balance": h.get("balance_str"), "provider": h.get("provider_label")}
                for h in (ssr_acc.get("balance_history") or [])[:20]
            ],
            "monarch_core_burn_calibration": compute_monarch_core_burn_calibration(family_id=fam_id),
        }
    except Exception as e:
        logger.warning("Error loading accounts and balance sheet for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_scenarios_and_forecast_plan(
    family_id: int = 0,
    scenario_id: Optional[str] = None,
    scenario_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves the household's multi-scenario longevity forecast scorecard, active plan assumptions,
    retirement readiness (FI crossover year, earliest feasible retirement ages), configured life events
    (home purchases, liquidity events, sabbaticals, tuition), and milestone cash flow schedule.
    Supports case-insensitive scenario lookup by scenario_id or scenario_name.
    """
    return enrich_scenarios_and_events_payload(family_id=family_id, scenario_id=scenario_id, scenario_name=scenario_name)


def get_compensation_and_tax_withholding(
    family_id: int = 0,
    taxpayer: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves household career W-2 compensation history (base salary, bonus, employer, total cash),
    IRS Safe Harbor 110% withholding pacing (prior-year tax, safe harbor target, YTD withheld,
    shortfall, extra per-paycheck withholding needed), and parsed IRS transcript records by year.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        ssr_comp = build_ssr_compensation(family_id=fam_id, taxpayer_filter=taxpayer)
        if not ssr_comp:
            return {}
        return {
            "selected_taxpayer": ssr_comp.get("selected_adult_name", "Combined Household"),
            "active_base_salary": ssr_comp.get("active_salary"),
            "active_base_salary_detail": ssr_comp.get("active_salary_sub"),
            "peak_annual_compensation": ssr_comp.get("peak_total"),
            "peak_compensation_detail": ssr_comp.get("peak_sub"),
            "lifetime_cash_earnings": ssr_comp.get("lifetime_total"),
            "lifetime_bonus_earnings": ssr_comp.get("bonus_total"),
            "bonus_summary": ssr_comp.get("bonus_sub"),
            "safe_harbor_withholding": {
                "status": ssr_comp.get("sh_status_badge"),
                "prior_year_federal_tax": ssr_comp.get("sh_prior_tax"),
                "safe_harbor_110_pct_target": ssr_comp.get("sh_target"),
                "ytd_federal_tax_withheld": ssr_comp.get("ytd_withheld", 0),
                "remaining_shortfall": ssr_comp.get("sh_shortfall"),
                "remaining_paychecks": ssr_comp.get("remaining_paychecks", 12),
                "recommended_extra_withholding_per_paycheck": ssr_comp.get("sh_extra_per_paycheck"),
            },
            "compensation_history": [
                {"year": r.get("year"), "taxpayer": r.get("taxpayer"), "employer": r.get("employer"), "base_salary": r.get("salary"), "bonus": r.get("bonus"), "total_cash_comp": r.get("total"), "source": r.get("source")}
                for r in (ssr_comp.get("history_rows") or [])[:25]
            ],
            "irs_transcripts_by_year": [
                {"tax_year": t.get("tax_year"), "federal_tax_withheld": t.get("fed_withheld"), "fica_and_medicare": t.get("fica"), "mortgage_interest_paid": t.get("mortgage"), "dividends_and_cap_gains": t.get("div_cap"), "safe_harbor_target": t.get("target"), "status": t.get("status")}
                for t in (ssr_comp.get("transcript_rows") or [])[:15]
            ],
            "tax_season_checklist": get_tax_document_checklist(family_id=fam_id),
        }
    except Exception as e:
        logger.warning("Error loading compensation and tax withholding for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_state_tax_arbitrage(
    family_id: int = 0,
    home_state: Optional[str] = None,
    scenario: str = "recurring",
    mode: str = "comprehensive",
) -> Dict[str, Any]:
    """
    Retrieves Multi-State Tax Arbitrage comparisons across WA, CA, NY, OR, NV, TX, FL, and WY
    for either a recurring W-2 income year ('recurring') or a major equity liquidity event ('liquidity'),
    plus Monarch historical household spending benchmarks and category drivers.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        ssr_arb = build_ssr_arbitrage(family_id=fam_id, home_state=home_state, mode=mode, scenario=scenario)
        if not ssr_arb:
            return {}
        return {
            "baseline_home_state": ssr_arb.get("default_state", "WA"),
            "active_mode": ssr_arb.get("active_mode", "comprehensive"),
            "active_scenario": ssr_arb.get("active_scenario", "recurring"),
            "modeled_home_value": ssr_arb.get("home_value"),
            "modeled_annual_spend": ssr_arb.get("annual_spend"),
            "base_w2_salary": ssr_arb.get("base_salary_short"),
            "options_ordinary_spread": ssr_arb.get("ordinary_spread_short"),
            "long_term_cap_gains": ssr_arb.get("cap_gains_short"),
            "spending_benchmarks": [{"label": p.get("label"), "annual_spend": p.get("spend")} for p in (ssr_arb.get("presets") or [])],
            "state_comparisons": [
                {
                    "state_code": s.get("state_code"), "state_name": s.get("state_name"),
                    "is_current_residence": s.get("is_home", False), "is_optimal_winner": s.get("is_winner", False),
                    "primary_cost_label": s.get("primary_label"), "primary_cost": s.get("primary_cost_str"),
                    "annual_state_tax": s.get("state_tax_str"), "effective_state_tax_rate": s.get("eff_rate_str"),
                    "property_tax": s.get("prop_tax_str"), "living_cost": s.get("living_cost_str"),
                    "savings_vs_home_state": s.get("savings_val_str"), "notes": s.get("notes"),
                }
                for s in (ssr_arb.get("state_cards") or [])
            ],
            "historical_spending_summary": [
                {"year": r.get("year_label"), "period": r.get("badge_text"), "total_outflow": r.get("total_outflow"), "housing_expenses": r.get("housing"), "gifts_and_donations": r.get("gifts"), "non_housing_living": r.get("living"), "annualized_living_pace": r.get("annualized_living"), "top_spending_drivers": r.get("top_drivers")}
                for r in (ssr_arb.get("spending_rows") or [])
            ],
        }
    except Exception as e:
        logger.warning("Error loading state tax arbitrage for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_education_529_plan(
    family_id: int = 0,
    enable_529_k12: bool = True,
) -> Dict[str, Any]:
    """
    Retrieves Education & 529 college funding details: children's profiles, college matriculation years,
    current and projected 529/530A balances, K-12 and university tuition ledger, and 4-year university
    cost-of-attendance funding benchmarks (In-State Public, Out-of-State Public, Private, Elite/Ivy).
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        ssr_col = build_ssr_college(family_id=fam_id, horizon="all", enable_529_k12=enable_529_k12)
        if not ssr_col:
            return {}
        return {
            "total_529_and_education_assets": ssr_col.get("total_assets"),
            "synchronized_accounts_summary": ssr_col.get("accounts_badge"),
            "enable_529_k12_withdrawals": ssr_col.get("enable_529_k12", True),
            "total_modeled_tuition": ssr_col.get("tuition_total"),
            "per_child_tuition_split": ssr_col.get("tuition_split_str"),
            "total_529_eligible_coverage": ssr_col.get("model_529_k12_coverage"),
            "projected_out_of_pocket_cashflow": ssr_col.get("model_tuition_cashflow"),
            "children": [
                {"name": c.get("first_name"), "college_matriculation_year": c.get("college_matriculation_year"), "years_until_college": c.get("years_remaining"), "current_529_balance": c.get("current_529_balance_str"), "projected_529_at_matriculation": c.get("projected_529_balance_str"), "account_types": c.get("types_str")}
                for c in (ssr_col.get("children") or [])
            ],
            "university_funding_benchmarks": [
                {
                    "tier": b.get("tier"), "representative_schools": b.get("school"), "annual_cost_of_attendance": b.get("annual_coa"),
                    "four_year_baseline_total": b.get("four_year_total"), "funding_status": b.get("status_text"),
                    "per_child_coverage": [{"funded_pct": col.get("pct"), "surplus_or_shortfall": col.get("diff_str")} for col in (b.get("child_cols") or [])],
                }
                for b in (ssr_col.get("benchmark_rows") or [])
            ],
            "tuition_schedule_rows": [
                {"school_year": r.get("school_year"), "child_1_grade": r.get("c1_grade"), "child_1_tuition": r.get("c1_amt"), "child_2_grade": r.get("c2_grade"), "child_2_tuition": r.get("c2_amt"), "total_annual_tuition": r.get("total_amt"), "eligible_529_withdrawal": r.get("elig_529"), "is_projected": r.get("is_projected", False), "notes": r.get("notes")}
                for r in (ssr_col.get("tuition_rows") or [])[:20]
            ],
        }
    except Exception as e:
        logger.warning("Error loading education 529 plan for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_philanthropy_and_daf_summary(
    family_id: int = 0,
    year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves Philanthropy & Donor-Advised Fund (DAF) records: lifetime charitable giving total,
    annual giving budget, allocated vs. remaining grant budget for the active year, and the
    organization-by-organization charitable grant ledger.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        ssr_phil = build_ssr_philanthropy(family_id=fam_id, active_year=year)
        if not ssr_phil:
            return {}
        return {
            "active_year": ssr_phil.get("active_year", "2026"),
            "available_years": ssr_phil.get("years", []),
            "lifetime_charitable_giving": ssr_phil.get("lifetime_total"),
            "history_span": ssr_phil.get("history_badge"),
            "annual_budget": ssr_phil.get("budget_2026"),
            "allocated_grants_total": ssr_phil.get("allocated_2026"),
            "remaining_unallocated_budget": ssr_phil.get("remaining_str"),
            "grant_count": ssr_phil.get("grant_count", 0),
            "donations_ledger": [
                {"organization": d.get("organization"), "description": d.get("description"), "date": d.get("date"), "amount": d.get("amount_str")}
                for d in (ssr_phil.get("donations_rows") or [])
            ],
        }
    except Exception as e:
        logger.warning("Error loading philanthropy summary for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_family_gifting_summary(
    family_id: int = 0,
    year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves Intergenerational Family Gifting & IRS Form 709 Annual Exclusion tracking:
    annual gift exclusion limits per recipient group, gifts completed in the active year,
    remaining tax-exempt headroom, and Form 709 filing requirements.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        ssr_gift = build_ssr_gifting(family_id=fam_id, active_year=year)
        if not ssr_gift:
            return {}
        return {
            "active_year": ssr_gift.get("active_year", "2026"),
            "available_years": ssr_gift.get("years", []),
            "total_gifted_in_year": ssr_gift.get("active_year_total"),
            "total_annual_exclusion_limit": ssr_gift.get("total_limit"),
            "remaining_tax_exempt_headroom": ssr_gift.get("total_headroom"),
            "recipients": [
                {"recipient_group": r.get("name"), "beneficiary_count": r.get("count_label"), "annual_couple_exclusion_limit": r.get("limit_str"), "gifted_amount": r.get("gifted_str"), "remaining_headroom": r.get("headroom_str"), "tax_status": r.get("badge_text")}
                for r in (ssr_gift.get("recipients") or [])
            ],
        }
    except Exception as e:
        logger.warning("Error loading family gifting summary for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


ALL_ADVISOR_TOOLS: List[Any] = [
    get_portfolio_allocation,
    get_equity_schedule,
    get_cash_flow_summary,
    get_monte_carlo_stress_test,
    get_estate_tax_summary,
    simulate_financial_scenario,
    estimate_equity_exercise_tax,
    get_accounts_and_balance_sheet,
    get_scenarios_and_forecast_plan,
    get_compensation_and_tax_withholding,
    get_state_tax_arbitrage,
    get_education_529_plan,
    get_philanthropy_and_daf_summary,
    get_family_gifting_summary,
    manage_scenario_life_event,
    audit_household_risks,
    get_private_markets_lp_book,
    manage_lp_commitment,
    update_tax_document_checklist_status,
]
