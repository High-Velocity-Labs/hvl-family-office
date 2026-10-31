"""Server-rendered Master Event Catalog list (htmx target `#events-catalog-list`)."""

from __future__ import annotations

from flask import render_template, request

from forecast import cache as forecast_cache
from forecast import engine as forecast_engine
from routes.context import login_required
from routes.fragments import ui_fragments_bp
from services.request_context import get_current_family_id, get_current_universe
from services.scenario_service import get_or_compute_scenarios
from ssr.scenario_event_catalog import build_event_catalog


@ui_fragments_bp.route("/fragments/scenario_event_catalog")
@login_required
def scenario_event_catalog_fragment():
    """Catalog cards for the search text (`q`) and category filter (`category`) in the query string."""
    sim = get_or_compute_scenarios(
        family_id=get_current_family_id(), universe=get_current_universe(), args={},
        engine=forecast_engine, cache=forecast_cache,
    )
    catalog = build_event_catalog(
        events=sim.get("events_catalog") or [],
        scenarios=sim.get("scenarios") or [],
        query=request.args.get("q", "")[:100],
        category=request.args.get("category", "ALL")[:40],
    )
    return render_template("fragments/scenario_event_catalog.html", catalog=catalog)
