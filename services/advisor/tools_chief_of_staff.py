"""
Executive Chief of Staff & High-Leverage Strategic Tools for the AI Financial Advisor:
Annual Cash Flow Waterfall Detail, In-Memory Ephemeral Life Event Simulation,
and Household Chief of Staff Cross-Domain Radar Briefing.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

import forecast_engine
from services.advisor.tools_core import _resolve_tool_family_id
from services.advisor.tools_operations import get_private_markets_lp_book
from services.advisor.tools_scenarios import _resolve_scenario
from services.advisor.tools_tabs import (
    get_compensation_and_tax_withholding,
    get_family_gifting_summary,
    get_philanthropy_and_daf_summary,
)
from services.household_audit_service import audit_household_risks
from services.tax_checklist_service import get_tax_document_checklist
from ssr.scenarios import build_ssr_scenarios
from ssr.settings import build_ssr_settings

logger = logging.getLogger(__name__)


def get_annual_cash_flow_detail(
    year: Optional[int] = None,
    age: Optional[int] = None,
    scenario_name: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """Retrieves full annual cash-flow breakdown, Sankey waterfall, and balances for a forecast year or age."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    try:
        raw_state = forecast_engine.load_scenario_state(family_id=fam_id)
        scenarios_list = raw_state.get("scenarios", [])
        target_scen = _resolve_scenario(scenarios_list, scenario_name=scenario_name)
        resolved_id = target_scen["id"] if target_scen else (raw_state.get("active_scenario_id") or "scen_baseline")

        _, raw_sim = build_ssr_scenarios(family_id=fam_id, scenario_id=resolved_id)
        sched = (raw_sim or {}).get("active_schedule") or []
        if not sched:
            return {}

        matched_row = None
        if year is not None:
            ty = int(year)
            matched_row = next((r for r in sched if int(r.get("year") or 0) == ty), None)
        elif age is not None:
            ta = int(age)
            matched_row = next((r for r in sched if int(r.get("primary_age") or r.get("age_primary") or r.get("age") or 0) == ta), None)

        if matched_row is None:
            matched_row = sched[0]

        y_val = matched_row.get("year")
        p_age = matched_row.get("primary_age") or matched_row.get("age_primary") or matched_row.get("age")
        s_age = matched_row.get("spouse_age") or matched_row.get("age_spouse")
        cf_series = (raw_sim or {}).get("active_cash_flow_series") or []
        cf_row = next((r for r in cf_series if int(r.get("year") or 0) == int(y_val or 0)), {})

        return {
            "scenario_id": resolved_id,
            "scenario_name": (target_scen.get("name") if target_scen else "Active Scenario"),
            "year": int(y_val) if y_val is not None else None,
            "primary_age": int(p_age) if p_age is not None else None,
            "spouse_age": int(s_age) if s_age is not None else None,
            "gross_income": float(matched_row.get("gross_income") or matched_row.get("yearly_inflow") or 0.0),
            "w2_income": float(matched_row.get("w2_income") or matched_row.get("household_salary") or 0.0),
            "rsu_vest_income": float(matched_row.get("rsu_vest_income") or 0.0),
            "social_security": float(matched_row.get("social_security") or 0.0),
            "rmd_amount": float(matched_row.get("rmd_amount") or 0.0),
            "roth_conversion": float(matched_row.get("roth_conversion") or 0.0),
            "living_expenses": float(matched_row.get("living_expenses") or matched_row.get("living_spending") or 0.0),
            "housing_expense": float(matched_row.get("housing_expense") or matched_row.get("mortgage_debt_service") or matched_row.get("mortgage_service") or 0.0),
            "education_tuition": float(matched_row.get("education_tuition") or matched_row.get("tuition") or 0.0),
            "healthcare_bridge": float(matched_row.get("healthcare_bridge") or 0.0),
            "total_tax": float(matched_row.get("total_tax") or matched_row.get("income_tax_haircut") or 0.0),
            "federal_tax": float(matched_row.get("federal_tax") or 0.0),
            "state_tax": float(matched_row.get("state_tax") or 0.0),
            "capital_gains_tax": float(matched_row.get("capital_gains_tax") or 0.0),
            "event_inflows": float(cf_row.get("event_inflows") or matched_row.get("yearly_event_inflow") or 0.0),
            "events_outflow": float(cf_row.get("events_outflow") or matched_row.get("yearly_event_outflow") or 0.0),
            "net_cash_flow": float(matched_row.get("net_cash_flow") or 0.0),
            "net_worth": float(matched_row.get("net_worth") or matched_row.get("total_net_worth") or 0.0),
            "liquid_portfolio": float(matched_row.get("liquid_portfolio") or matched_row.get("liquid_assets") or 0.0),
            "company_equity": float(matched_row.get("company_equity") or 0.0),
            "taxable_balance": float(matched_row.get("taxable_balance") or matched_row.get("liquid_assets") or 0.0),
            "pretax_balance": float(matched_row.get("pretax_balance") or matched_row.get("retirement_assets") or 0.0),
            "roth_balance": float(matched_row.get("roth_balance") or 0.0),
            "real_estate_equity": float(matched_row.get("real_estate_equity") or matched_row.get("real_estate_net") or 0.0),
            "event_notes": str(matched_row.get("event_notes") or matched_row.get("events_occurred") or ""),
            "available_year_range": [sched[0].get("year"), sched[-1].get("year")] if sched else [],
        }
    except Exception as e:
        logger.warning("Error getting annual cash flow detail for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def simulate_life_event_impact(
    event_type: str = "capital_outflow",
    name: str = "Hypothetical Event",
    start_year: int = 2027,
    amount: float = 100000.0,
    duration_years: int = 1,
    scenario_name: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """Simulates the wealth impact and Monte Carlo solvency of a hypothetical life event in-memory without persistence."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    try:
        raw_state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=fam_id))
        scenarios_list = raw_state.get("scenarios", [])
        target_scen = _resolve_scenario(scenarios_list, scenario_name=scenario_name)
        if target_scen is None:
            active_id = raw_state.get("active_scenario_id") or "scen_baseline"
            target_scen = next((s for s in scenarios_list if s.get("id") == active_id), scenarios_list[0] if scenarios_list else None)

        target_scen_id = target_scen.get("id") if target_scen else "scen_baseline"

        # Baseline metrics
        sim_baseline = forecast_engine.simulate_multi_scenarios(family_id=fam_id)
        b_card = next((s for s in sim_baseline.get("scorecard", []) if s.get("id") == target_scen_id), (sim_baseline.get("scorecard") or [{}])[0])
        b_readiness = b_card.get("retirement_readiness") or {}
        baseline_metrics = {
            "nw_age_65": float(b_card.get("net_worth_65") or 0.0),
            "nw_age_85": float(b_card.get("net_worth_85") or 0.0),
            "nw_age_95": float(b_card.get("net_worth_95") or 0.0),
            "fi_year": b_readiness.get("fi_crossover_year"),
        }

        # Ephemeral life event
        dur, sy = max(1, int(duration_years)), int(start_year)
        ephemeral_event = {
            "id": "evt_ephemeral_sim", "type": event_type, "category": event_type, "name": name,
            "start_year": sy, "year": sy, "end_year": sy + dur - 1, "duration": dur,
            "amount": float(amount), "enabled": True,
        }
        raw_state.setdefault("events", []).append(ephemeral_event)
        if target_scen is not None:
            target_scen.setdefault("event_ids", []).append("evt_ephemeral_sim")

        # In-memory execution with ephemeral monkeypatching
        orig_engine_load = forecast_engine.load_scenario_state
        import forecast.orchestrator
        orig_orch_load = forecast.orchestrator.load_scenario_state

        try:
            forecast_engine.load_scenario_state = lambda family_id=0: raw_state
            forecast.orchestrator.load_scenario_state = lambda family_id=0: raw_state
            sim_after = forecast_engine.simulate_multi_scenarios(family_id=fam_id)
            mc_after = forecast_engine.run_monte_carlo_simulation(family_id=fam_id, trials=250, precomputed_sim=sim_after)
        finally:
            forecast_engine.load_scenario_state = orig_engine_load
            forecast.orchestrator.load_scenario_state = orig_orch_load

        a_card = next((s for s in sim_after.get("scorecard", []) if s.get("id") == target_scen_id), (sim_after.get("scorecard") or [{}])[0])
        a_readiness = a_card.get("retirement_readiness") or {}
        with_event_metrics = {
            "nw_age_65": float(a_card.get("net_worth_65") or 0.0),
            "nw_age_85": float(a_card.get("net_worth_85") or 0.0),
            "nw_age_95": float(a_card.get("net_worth_95") or 0.0),
            "fi_year": a_readiness.get("fi_crossover_year"),
        }
        deltas = {
            "nw_age_65_delta": round(with_event_metrics["nw_age_65"] - baseline_metrics["nw_age_65"], 2),
            "nw_age_85_delta": round(with_event_metrics["nw_age_85"] - baseline_metrics["nw_age_85"], 2),
            "nw_age_95_delta": round(with_event_metrics["nw_age_95"] - baseline_metrics["nw_age_95"], 2),
        }
        mc_prob = float(mc_after.get("overall_success_rate", mc_after.get("probability_of_success", mc_after.get("success_rate_age_100", 0.0))))

        return {
            "status": "simulated_ephemeral",
            "persisted_to_db": False,
            "event_simulated": ephemeral_event,
            "target_scenario": target_scen.get("name") if target_scen else "Active Scenario",
            "baseline": baseline_metrics,
            "with_event": with_event_metrics,
            "deltas": deltas,
            "monte_carlo_probability_of_success_pct": mc_prob,
        }
    except Exception as e:
        logger.warning("Error simulating ephemeral life event for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_chief_of_staff_radar(family_id: int = 0) -> Dict[str, Any]:
    """Aggregates executive briefing across Data Freshness, Risk Audit, Tax Pacing, LP Book, and Philanthropy/Gifting."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    try:
        # 1. Data Freshness
        m_conn, m_sync, s_conn, s_sync = False, "Never", False, "Never"
        try:
            ssr_settings = build_ssr_settings(family_id=fam_id)
            m_stat = ssr_settings.get("monarch_status") or {}
            s_stat = ssr_settings.get("simplefin_status") or {}
            m_conn, m_sync = bool(m_stat.get("is_connected", False)), str(m_stat.get("last_sync") or "Never")
            s_conn, s_sync = bool(s_stat.get("is_connected", False)), str(s_stat.get("last_sync") or "Never")
        except Exception as e:
            logger.warning("Error loading data freshness for family %s: %s", fam_id, e)

        # 2. Household Risk Audit
        r_score, r_badge, top_actions = 100, "Ready", []
        try:
            audit = audit_household_risks(family_id=fam_id) or {}
            r_score, r_badge = int(audit.get("readiness_score", 100)), str(audit.get("status_badge", "Ready"))
            top_actions = [
                {"title": f.get("title"), "severity": f.get("severity"), "action_text": f.get("action_text")}
                for f in (audit.get("findings") or []) if not f.get("is_verified")
            ][:5]
        except Exception as e:
            logger.warning("Error running household risk audit for family %s: %s", fam_id, e)

        # 3. Tax & Safe Harbor Pacing
        pending_tax_docs, sh_shortfall, sh_status, sh_extra = [], 0.0, "On Track", 0.0
        try:
            tax_chk = get_tax_document_checklist(family_id=fam_id) or {}
            pending_tax_docs = [
                {"id": it.get("id"), "name": it.get("name"), "form": it.get("form"), "status": it.get("status")}
                for it in (tax_chk.get("items") or []) if it.get("status") in ("waiting", "received")
            ]
        except Exception as e:
            logger.warning("Error loading tax checklist for family %s: %s", fam_id, e)

        try:
            comp_data = get_compensation_and_tax_withholding(family_id=fam_id) or {}
            sh_data = comp_data.get("safe_harbor_withholding") or {}
            sh_shortfall = sh_data.get("remaining_shortfall") or 0.0
            sh_status = sh_data.get("status") or "On Track"
            sh_extra = sh_data.get("recommended_extra_withholding_per_paycheck") or 0.0
        except Exception as e:
            logger.warning("Error loading safe harbor comp for family %s: %s", fam_id, e)

        # 4. Private Markets & Liquidity
        unfunded, coverage_ratio, stale_mark, oldest_mark = 0.0, 0.0, False, None
        try:
            lp_book = get_private_markets_lp_book(family_id=fam_id) or {}
            lp_sum = lp_book.get("summary") or {}
            unfunded = float(lp_sum.get("total_unfunded") or 0.0)
            coverage_ratio = float(lp_sum.get("liquid_cash_coverage_ratio") or 0.0)
            stale_mark = bool(lp_sum.get("has_stale_mark", False))
            oldest_mark = lp_sum.get("oldest_mark_date")
        except Exception as e:
            logger.warning("Error loading LP book for family %s: %s", fam_id, e)

        # 5. Year-End Giving & Gifting Headroom
        daf_budget, gift_headroom = "$0", "$0"
        try:
            phil_data = get_philanthropy_and_daf_summary(family_id=fam_id) or {}
            daf_budget = phil_data.get("remaining_unallocated_budget") or "$0"
        except Exception as e:
            logger.warning("Error loading philanthropy summary for family %s: %s", fam_id, e)

        try:
            gift_data = get_family_gifting_summary(family_id=fam_id) or {}
            gift_headroom = gift_data.get("remaining_tax_exempt_headroom") or "$0"
        except Exception as e:
            logger.warning("Error loading gifting summary for family %s: %s", fam_id, e)

        return {
            "family_id": fam_id,
            "data_freshness": {
                "monarch": {"is_connected": m_conn, "last_sync": m_sync},
                "simplefin": {"is_connected": s_conn, "last_sync": s_sync},
            },
            "household_risk_audit": {
                "readiness_score": r_score, "status_badge": r_badge, "top_action_items": top_actions,
            },
            "tax_and_safe_harbor_pacing": {
                "pending_tax_documents_count": len(pending_tax_docs),
                "pending_tax_documents": pending_tax_docs,
                "safe_harbor_shortfall": sh_shortfall,
                "safe_harbor_status": sh_status,
                "recommended_extra_withholding_per_paycheck": sh_extra,
            },
            "private_markets_and_liquidity": {
                "total_unfunded": unfunded,
                "liquid_cash_coverage_ratio": coverage_ratio,
                "has_stale_mark": stale_mark,
                "oldest_mark_date": oldest_mark,
            },
            "giving_and_gifting_headroom": {
                "remaining_unallocated_budget": daf_budget,
                "remaining_tax_exempt_headroom": gift_headroom,
            },
        }
    except Exception as e:
        logger.warning("Error constructing chief of staff radar for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}
