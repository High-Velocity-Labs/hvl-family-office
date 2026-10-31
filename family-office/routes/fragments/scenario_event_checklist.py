"""Server-rendered event checklist for the scenario plan modal (htmx target `#modal-scenario-event-checklist`)."""

from __future__ import annotations

from flask import render_template, request

from forecast import cache as forecast_cache
from forecast import engine as forecast_engine
from routes.context import login_required
from routes.fragments import ui_fragments_bp
from services.request_context import get_current_family_id, get_current_universe
from services.scenario_service import get_or_compute_scenarios
from ssr.event_checklist import build_event_checklist


def _csv(name: str) -> list[str]:
    return [v for v in (request.args.get(name) or "").split(",") if v]


@ui_fragments_bp.route("/fragments/scenario_event_checklist")
@login_required
def scenario_event_checklist_fragment():
    """Accordion of catalog events for the plan being edited; the draft (checked ids, parent) arrives as query args."""
    sim = get_or_compute_scenarios(
        family_id=get_current_family_id(), universe=get_current_universe(), args={},
        engine=forecast_engine, cache=forecast_cache,
    )
    plan_id = request.args.get("scenario_id", "")
    parent_id = request.args.get("parent_id", "")
    parent = next((s for s in sim.get("scenarios") or [] if s.get("id") == parent_id), None) if parent_id else None
    if parent is not None and parent.get("id") == plan_id:
        parent = None
    checklist = build_event_checklist(
        events=sim.get("events_catalog") or [],
        selected_ids=set(_csv("selected")),
        parent=parent,
        overlay_on_baseline=request.args.get("overlay") == "1" and parent_id == "scen_baseline",
        query=request.args.get("q", "")[:100],
        open_keys=set(_csv("open")) if "open" in request.args else None,
    )
    return render_template("fragments/scenario_event_checklist.html", checklist=checklist)
