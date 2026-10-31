"""
Per-plan detail the forecasting page loads on demand instead of shipping it for every plan: another plan's
year-by-year series (when a chart's plan pill picks it) and the year-by-year schedule table (when it is opened).
Both read the cached forecast the page was rendered from: the page carries `plan_detail_query`, the exact query
that forecast is cached under, and sends it back with each request.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ssr.scenarios import load_or_run_simulation
from ssr.scenarios_shelf import build_schedule_rows

# One entry per plan, keyed by plan id, in the forecast result.
PLAN_SERIES_KEYS = ("scenario_schedules", "scenario_cash_flows", "scenario_longevity_breakdowns")


def client_scenarios_payload(sim: Dict[str, Any]) -> Dict[str, Any]:
    """The forecast as the page's data script carries it: the per-plan series of the selected plan only."""
    if not sim:
        return sim
    selected = sim.get("selected_scenario_id")
    payload = dict(sim)
    for key in PLAN_SERIES_KEYS:
        series = sim.get(key) or {}
        payload[key] = {selected: series[selected]} if selected in series else {}
    return payload


def _page_simulation(family_id: int, args: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The page's cached forecast, from the `plan_detail_query` it sent back (`plan_id` is this request's own)."""
    params = {k: v for k, v in args.items() if k not in ("scenario_id", "plan_id")}
    sim, _, _ = load_or_run_simulation(family_id, args.get("scenario_id"), params)
    return sim


def build_plan_series(family_id: int, args: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """One plan's (`plan_id`) year-by-year series, keyed like the forecast's maps; None for an unknown plan."""
    plan_id = args.get("plan_id")
    if family_id <= 0 or not plan_id:
        return None
    sim = _page_simulation(family_id, args)
    if not sim or plan_id not in (sim.get("scenario_schedules") or {}):
        return None
    return {"plan_id": plan_id, **{key: (sim.get(key) or {}).get(plan_id) or [] for key in PLAN_SERIES_KEYS}}


def build_schedule_table(family_id: int, args: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The schedule rows of the plan the page shows: its `scenario_id`, else the household's active plan."""
    if family_id <= 0:
        return []
    sim = _page_simulation(family_id, args)
    if not sim:
        return []
    schedules = sim.get("scenario_schedules") or {}
    plan_id = args.get("scenario_id")
    if plan_id not in schedules:
        plan_id = sim.get("active_scenario_id") or "scen_baseline"
    return build_schedule_rows(schedules.get(plan_id) or [])
