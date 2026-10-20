"""
Chart payload builders and collapsed-chart persistence for customizable domain widgets.
Zero raw SQL: queries route strictly through security and db repositories.
Zero-In -> Zero-Out invariant: unauthenticated / family_id=0 returns clean empty series.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import security
from routes.helpers import DB_PATH

logger = logging.getLogger(__name__)


def get_collapsed_charts(family_id: int = 0, db_path: Path | None = None) -> List[str]:
    """Retrieves the list of chart widget IDs collapsed for this household."""
    try:
        from urllib.parse import unquote
        from flask import has_request_context, request, session
        from routes.helpers import get_current_universe
        if has_request_context():
            is_demo_or_viewer = bool(
                session.get("is_demo")
                or get_current_universe() == "demo"
                or session.get("role") == "viewer"
                or request.args.get("demo") == "1"
            )
            if is_demo_or_viewer:
                cookie_col = request.cookies.get("hvl_collapsed_charts")
                if cookie_col is not None:
                    raw_col = unquote(str(cookie_col)).strip()
                    if not raw_col or raw_col == "none":
                        return []
                    return [c.strip() for c in raw_col.split(",") if c.strip()]
    except Exception:
        pass
    if family_id <= 0:
        return []
    try:
        fam = security.get_family(Path(db_path or DB_PATH), family_id=family_id) or {}
        settings = fam.get("settings") if isinstance(fam.get("settings"), dict) else {}
        collapsed = settings.get("collapsed_charts")
        if isinstance(collapsed, list):
            return [str(c).strip() for c in collapsed if str(c).strip()]
    except Exception as e:
        logger.debug("Could not read collapsed charts for family %s: %s", family_id, e)
    return []


def save_collapsed_chart_state(
    family_id: int,
    chart_id: str,
    collapsed: bool,
    db_path: Path | None = None,
) -> List[str]:
    """Persists a chart's collapsed state into families.settings['collapsed_charts']."""
    if family_id <= 0:
        return []
    c_id = str(chart_id).strip()
    if not c_id:
        return get_collapsed_charts(family_id, db_path=db_path)
    try:
        resolved_path = Path(db_path or DB_PATH)
        fam = security.get_family(resolved_path, family_id=family_id) or {}
        settings = dict(fam.get("settings") or {}) if isinstance(fam.get("settings"), dict) else {}
        current_list = list(settings.get("collapsed_charts") or [])
        collapsed_set = set(str(c).strip() for c in current_list if str(c).strip())
        if collapsed:
            collapsed_set.add(c_id)
        else:
            collapsed_set.discard(c_id)
        new_list = sorted(list(collapsed_set))
        settings["collapsed_charts"] = new_list
        security.update_family(resolved_path, family_id=family_id, settings=settings)
        return new_list
    except Exception as e:
        logger.warning("Could not save collapsed chart state for family %s: %s", family_id, e)
        return []


def _build_empty_chart_payloads() -> Dict[str, Any]:
    return {
        "lifetime_forecast": {"years": [], "scenarios": [], "active_scenario_id": ""},
        "cash_flow": {"years": [], "inflows": [], "living_spend": [], "net_draw": [], "ending_nw": [], "plan_name": ""},
        "monte_carlo": {"years": [], "p10": [], "p25": [], "p50": [], "p75": [], "p90": [], "solvency_pct": 100.0, "plan_name": ""},
        "longevity": {"years": [], "ages": [], "survival_pct": [], "ending_nw": [], "plan_name": ""},
        "career_comp": {"years": [], "base_salary": [], "bonus": [], "total_comp": []},
    }


def _extract_career_comp(family_id: int, db_path: Path | None = None) -> Dict[str, Any]:
    if family_id <= 0:
        return {"years": [], "base_salary": [], "bonus": [], "total_comp": []}
    try:
        from db.compensation import list_compensation_records
        records = list_compensation_records(family_id=family_id, db_path=db_path or DB_PATH)
        comp_by_year: Dict[int, Dict[str, float]] = {}
        for r in records:
            yr = int(r.get("year") or r.get("tax_year") or 0)
            if yr <= 0:
                continue
            if yr not in comp_by_year:
                comp_by_year[yr] = {"salary": 0.0, "bonus": 0.0, "total": 0.0}
            sal = float(r.get("salary") or r.get("base_salary") or 0.0)
            bon = float(r.get("bonus") or 0.0)
            tot = float(r.get("total_compensation") or (sal + bon))
            comp_by_year[yr]["salary"] += sal
            comp_by_year[yr]["bonus"] += bon
            comp_by_year[yr]["total"] += tot
        if not comp_by_year:
            import db
            tdata = db.transcripts.get_transcripts_payload(family_id=family_id, db_path=db_path or DB_PATH) or {}
            hist_sum = tdata.get("historical_summary") if isinstance(tdata, dict) else {}
            if isinstance(hist_sum, dict):
                for yr_str, row in hist_sum.items():
                    try:
                        yr = int(yr_str)
                    except (ValueError, TypeError):
                        continue
                    w2 = float((row or {}).get("w2_wages") or 0.0)
                    if yr > 0 and w2 > 0:
                        comp_by_year[yr] = {"salary": w2, "bonus": 0.0, "total": w2}
        sorted_years = sorted(comp_by_year.keys())
        return {
            "years": sorted_years,
            "base_salary": [round(comp_by_year[y]["salary"], 2) for y in sorted_years],
            "bonus": [round(comp_by_year[y]["bonus"], 2) for y in sorted_years],
            "total_comp": [round(comp_by_year[y]["total"], 2) for y in sorted_years],
        }
    except Exception as e:
        logger.debug("Failed extracting career compensation for family %s: %s", family_id, e)
        return {"years": [], "base_salary": [], "bonus": [], "total_comp": []}


def build_widget_chart_payloads(
    family_id: int = 0,
    ssr_scen: Dict[str, Any] | None = None,
    sim: Dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """
    Builds clean, JSON-serializable series data for all domain and companion charts.
    Strictly isolated: returns empty series if family_id <= 0.
    """
    if family_id <= 0:
        return _build_empty_chart_payloads()

    if not ssr_scen and not sim:
        try:
            from ssr.scenarios import build_ssr_scenarios
            ssr_scen, sim = build_ssr_scenarios(family_id=family_id)
        except Exception as e:
            logger.debug("Could not resolve ssr scenarios for family %s: %s", family_id, e)

    ssr_scen = ssr_scen or {}
    sim = sim or {}
    active_sched = sim.get("active_schedule") or []
    years = [int(r.get("year")) for r in active_sched if r.get("year")]
    if not years and sim.get("comparison_curves"):
        years = [int(r["year"]) for r in sim["comparison_curves"] if "year" in r]

    inflation = float(sim.get("inflation_rate") or 0.025)
    view_mode = str(sim.get("view_mode") or "real").lower()
    active_scen_id = sim.get("active_scenario_id") or ssr_scen.get("active_scenario_id") or "scen_baseline"
    plan_name = ssr_scen.get("plan_name") or sim.get("plan_name") or "Baseline Plan"

    # 1. Multi-scenario Lifetime Forecast
    scenarios_out: List[Dict[str, Any]] = []
    raw_scens = sim.get("scenarios") or ssr_scen.get("scenarios") or []
    scheds_map = sim.get("scenario_schedules") or {}
    comp_curves = sim.get("comparison_curves") or []
    for sc in raw_scens:
        s_id = sc.get("id") or "scen_baseline"
        s_name = sc.get("name") or sc.get("title") or s_id
        is_act = (s_id == active_scen_id)
        color = sc.get("color") or ("#3B82F6" if is_act else "#6B7280")
        sc_sched = scheds_map.get(s_id) or (active_sched if is_act else [])
        if sc_sched:
            vals = [float(r.get("total_net_worth") or 0.0) for r in sc_sched]
        else:
            vals = [float(r.get(s_id, 0.0)) for r in comp_curves]
        if view_mode == "nominal":
            nw_nom = [round(v, 2) for v in vals]
            nw_real = [round(v / ((1.0 + inflation) ** i), 2) for i, v in enumerate(nw_nom)]
        else:
            nw_real = [round(v, 2) for v in vals]
            nw_nominal_calc = [round(v * ((1.0 + inflation) ** i), 2) for i, v in enumerate(nw_real)]
            nw_nom = nw_nominal_calc
        scenarios_out.append({
            "id": s_id,
            "name": s_name,
            "is_active": is_act,
            "color": color,
            "net_worth_real": nw_real,
            "net_worth_nominal": nw_nom,
        })
    lifetime_forecast = {"years": years, "scenarios": scenarios_out, "active_scenario_id": active_scen_id}

    # 2. Cash Flow & Tax Drawdown
    cash_flow = {
        "years": years,
        "inflows": [round(float(r.get("yearly_inflow") or 0.0), 2) for r in active_sched],
        "living_spend": [round(float(r.get("living_spending") or 0.0), 2) for r in active_sched],
        "net_draw": [round(float(r.get("net_portfolio_draw") or 0.0), 2) for r in active_sched],
        "ending_nw": [round(float(r.get("total_net_worth") or 0.0), 2) for r in active_sched],
        "plan_name": plan_name,
    }

    # 3. Monte Carlo Percentile Fan
    active_mc = sim.get("active_monte_carlo") or {}
    pct_tl = active_mc.get("percentiles_timeline") or []
    if pct_tl:
        mc_years = [int(r.get("year") or 0) for r in pct_tl]
        p10 = [round(float(r.get("p10") or 0.0), 2) for r in pct_tl]
        p25 = [round(float(r.get("p25") or 0.0), 2) for r in pct_tl]
        p50 = [round(float(r.get("p50") or 0.0), 2) for r in pct_tl]
        p75 = [round(float(r.get("p75") or 0.0), 2) for r in pct_tl]
        p90 = [round(float(r.get("p90") or 0.0), 2) for r in pct_tl]
        solv_pct = float(active_mc.get("solvency_rate") or active_mc.get("solvency_pct") or 100.0)
    else:
        mc_years = years
        p50 = cash_flow["ending_nw"]
        p10 = [round(v * 0.70, 2) for v in p50]
        p25 = [round(v * 0.85, 2) for v in p50]
        p75 = [round(v * 1.15, 2) for v in p50]
        p90 = [round(v * 1.35, 2) for v in p50]
        solv_disp = str(ssr_scen.get("solv_rate_display") or "100").replace("%", "").strip()
        try:
            solv_pct = float(solv_disp)
        except ValueError:
            solv_pct = 100.0
    monte_carlo = {
        "years": mc_years, "p10": p10, "p25": p25, "p50": p50,
        "p75": p75, "p90": p90, "solvency_pct": round(solv_pct, 1), "plan_name": plan_name,
    }

    # 4. Actuarial Longevity
    long_rows = sim.get("active_longevity_breakdown") or active_sched
    l_years = [int(r.get("year") or 0) for r in long_rows]
    l_ages = [int(r.get("age", r.get("age_primary", 0)) or 0) for r in long_rows]
    survival_pct = [
        round(float(r.get("prob_joint_alive") if r.get("prob_joint_alive") is not None else ((float(r.get("joint_survival_prob") or 0.0)) * 100.0)), 1)
        for r in long_rows
    ]
    l_ending_nw = [
        round(float(r.get("net_worth") if r.get("net_worth") is not None else (r.get("total_net_worth") or 0.0)), 2)
        for r in long_rows
    ]
    longevity = {
        "years": l_years, "ages": l_ages, "survival_pct": survival_pct, "ending_nw": l_ending_nw, "plan_name": plan_name,
    }

    # 5. Career Compensation
    career_comp = _extract_career_comp(family_id=family_id, db_path=db_path)

    return {
        "lifetime_forecast": lifetime_forecast,
        "cash_flow": cash_flow,
        "monte_carlo": monte_carlo,
        "longevity": longevity,
        "career_comp": career_comp,
    }
