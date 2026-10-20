"""
Scenario Studio, Event Modeling, and Multi-Scenario Forecasting APIs.
Delegates heavy simulation and persistence business logic to modular services.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from hvl_common.web import rate_limit

import db
import forecast_cache
import forecast_engine
from routes.helpers import (
    DB_PATH,
    editor_required,
    get_current_family_id,
    get_current_universe,
    login_required,
    sanitize_text,
)
from services.scenario_clone_service import clone_scenario, delete_scenario_hierarchy
from services.scenario_service import (
    export_forecast_csv,
    get_or_compute_monte_carlo,
    get_or_compute_scenarios,
    save_scenario,
    serialize_forecast_csv,
)

# Preserve backward compatibility for tests or callers that import _serialize_forecast_csv
_serialize_forecast_csv = serialize_forecast_csv

# Bind multi-tenant/multi-universe DB path proxy so forecast_engine isolates demo vs public data
forecast_engine.DB_PATH = DB_PATH

scenarios_bp = Blueprint("scenarios", __name__)
rate_limit("120/min")(scenarios_bp)


@scenarios_bp.route("/api/scenarios", methods=["GET"])
@login_required
def api_get_scenarios():
    family_id = get_current_family_id()
    universe = get_current_universe()
    res = get_or_compute_scenarios(
        family_id=family_id,
        universe=universe,
        args=request.args,
        engine=forecast_engine,
        cache=forecast_cache,
    )
    return jsonify(res)


@scenarios_bp.route("/api/scenarios/export_csv", methods=["GET"])
@login_required
def api_export_scenarios_csv():
    """Exports the multi-year forecast & tax projection schedule as a downloadable CSV."""
    from flask import Response

    family_id = get_current_family_id()
    csv_data = export_forecast_csv(
        family_id=family_id,
        args=request.args,
        engine=forecast_engine,
    )
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="family_office_forecast_projection.csv"',
            "Cache-Control": "no-store",
        },
    )


@scenarios_bp.route("/api/scenarios/monte-carlo", methods=["GET"])
@login_required
def api_get_monte_carlo():
    """
    Stochastic Monte Carlo simulation & sequence-of-returns crisis stress testing.
    Strictly isolated to active family_id.
    """
    family_id = get_current_family_id()
    universe = get_current_universe()
    res = get_or_compute_monte_carlo(
        family_id=family_id,
        universe=universe,
        args=request.args,
        engine=forecast_engine,
        cache=forecast_cache,
    )
    return jsonify(res)


@scenarios_bp.route("/api/scenarios/active", methods=["POST"])
@editor_required
def api_set_active_scenario():
    family_id = get_current_family_id()
    data = request.get_json() or {}
    scen_id = data.get("scenario_id")
    if not scen_id:
        return jsonify({"success": False, "error": "scenario_id is required"}), 400
    state = forecast_engine.load_scenario_state(family_id=family_id)
    state["active_scenario_id"] = scen_id
    forecast_engine.save_scenario_state(state, family_id=family_id, invalidate_cache=False)
    forecast_cache.update_active_scenario(family_id, scen_id)
    return jsonify({"success": True, "active_scenario_id": scen_id})


@scenarios_bp.route("/api/scenarios", methods=["POST"])
@editor_required
def api_save_scenario():
    family_id = get_current_family_id()
    data = request.get_json() or {}
    success, err_msg = save_scenario(
        family_id=family_id,
        data=data,
        engine=forecast_engine,
        cache=forecast_cache,
        db_module=db,
        db_path=DB_PATH,
    )
    if not success:
        return jsonify({"success": False, "error": err_msg}), 400
    if "drawdown_order" in data or "accelerate_lp_calls" in data:
        state = forecast_engine.load_scenario_state(family_id=family_id)
        scen_id = data.get("id")
        scen = next((s for s in state.get("scenarios", []) if s.get("id") == scen_id), None)
        if scen:
            if "drawdown_order" in data:
                scen["drawdown_order"] = str(data["drawdown_order"]).lower().strip()
            if "accelerate_lp_calls" in data:
                scen["accelerate_lp_calls"] = bool(data["accelerate_lp_calls"])
            forecast_engine.save_scenario_state(state, family_id=family_id)
            forecast_cache.invalidate_family_cache(family_id)
    return jsonify({"success": True})


@scenarios_bp.route("/api/holdings/lp_commitments", methods=["GET"])
@login_required
def api_get_lp_commitments():
    """Retrieves annotated LP commitments and portfolio dry powder metrics."""
    from services.private_markets_service import get_lp_commitments_summary
    family_id = get_current_family_id()
    data = get_lp_commitments_summary(family_id=family_id)
    return jsonify({"success": True, **data})


@scenarios_bp.route("/api/holdings/lp_commitments", methods=["POST"])
@editor_required
def api_save_lp_commitment():
    """Creates or updates an LP commitment annotation."""
    if session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "LP commitments cannot be modified in demo mode."}), 403
    from services.private_markets_service import save_lp_commitment
    family_id = get_current_family_id()
    data = request.get_json() or {}
    item = save_lp_commitment(family_id=family_id, item_data=data)
    forecast_cache.invalidate_family_cache(family_id, domains=["holdings", "balance_sheet"])
    return jsonify({"success": True, "commitment": item})


@scenarios_bp.route("/api/holdings/lp_commitments/<item_id>", methods=["DELETE"])
@editor_required
def api_delete_lp_commitment(item_id: str):
    """Deletes an LP commitment annotation."""
    if session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "LP commitments cannot be modified in demo mode."}), 403
    from services.private_markets_service import delete_lp_commitment
    family_id = get_current_family_id()
    clean_id = sanitize_text(item_id, max_length=64, field_name="Item ID", required=True)
    deleted = delete_lp_commitment(family_id=family_id, item_id=clean_id)
    if not deleted:
        return jsonify({"success": False, "error": "LP commitment not found"}), 404
    forecast_cache.invalidate_family_cache(family_id, domains=["holdings", "balance_sheet"])
    return jsonify({"success": True})


@scenarios_bp.route("/api/scenarios/<source_id>/clone", methods=["POST"])
@editor_required
def api_clone_scenario(source_id: str):
    """Clones an existing scenario as an inherited child scenario."""
    family_id = get_current_family_id()
    success, result, status_code = clone_scenario(
        family_id=family_id,
        source_id=source_id,
        engine=forecast_engine,
        cache=forecast_cache,
    )
    if not success:
        return jsonify({"success": False, "error": result}), status_code
    return jsonify({"success": True, "scenario": result})


@scenarios_bp.route("/api/scenarios/<scenario_id>", methods=["DELETE"])
@editor_required
def api_delete_scenario(scenario_id: str):
    if scenario_id == "scen_baseline":
        return jsonify({"success": False, "error": "Cannot delete Baseline Plan"}), 400
    family_id = get_current_family_id()
    deleted_ids = delete_scenario_hierarchy(
        family_id=family_id,
        scenario_id=scenario_id,
        engine=forecast_engine,
        cache=forecast_cache,
    )
    return jsonify({"success": True, "deleted_ids": deleted_ids})


@scenarios_bp.route("/api/events", methods=["POST"])
@editor_required
def api_save_event():
    import config

    family_id = get_current_family_id()
    data = request.get_json() or {}
    try:
        evt_id = sanitize_text(data.get("id"), max_length=100, field_name="Event id", required=True)
        name = sanitize_text(data.get("name"), max_length=100, field_name="Event name", required=True)
        description = sanitize_text(data.get("description", ""), max_length=500, field_name="Event description", multiline=True)
        category = sanitize_text(data.get("category", ""), max_length=50, field_name="Event category")
        icon = sanitize_text(data.get("icon", ""), max_length=60, field_name="Event icon")
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    data["id"] = evt_id
    data["name"] = name
    data["description"] = description
    data["icon"] = icon
    if category:
        data["category"] = category

    state = forecast_engine.load_scenario_state(family_id=family_id)
    events = state.get("events", [])

    existing = next((e for e in events if e.get("id") == evt_id), None)
    if existing:
        existing.update(data)
    else:
        if len(events) >= config.MAX_FORECAST_EVENTS:
            return jsonify({"success": False, "error": f"Maximum of {config.MAX_FORECAST_EVENTS} forecast events per household reached."}), 400
        events.append(data)

    state["events"] = events
    forecast_engine.save_scenario_state(state, family_id=family_id)
    forecast_cache.invalidate_family_cache(family_id)
    return jsonify({"success": True})


@scenarios_bp.route("/api/events/<event_id>", methods=["DELETE"])
@editor_required
def api_delete_event(event_id: str):
    family_id = get_current_family_id()
    state = forecast_engine.load_scenario_state(family_id=family_id)
    state["events"] = [e for e in state.get("events", []) if e.get("id") != event_id]
    for scen in state.get("scenarios", []):
        scen["event_ids"] = [eid for eid in scen.get("event_ids", []) if eid != event_id]
    forecast_engine.save_scenario_state(state, family_id=family_id)
    forecast_cache.invalidate_family_cache(family_id)
    return jsonify({"success": True})


@scenarios_bp.route("/api/scenarios/settings", methods=["POST"])
@editor_required
def api_save_scenario_settings():
    if session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    state = forecast_engine.load_scenario_state(family_id=family_id)
    if "equity_growth_preset" in data:
        val = data.get("equity_growth_preset")
        state["equity_growth_preset"] = val
    if "view_mode" in data:
        state["view_mode"] = data["view_mode"]
    forecast_engine.save_scenario_state(state, family_id=family_id)
    forecast_cache.invalidate_family_cache(family_id)
    return jsonify({"success": True})


@scenarios_bp.route("/api/widgets/preferences", methods=["GET"])
@login_required
def api_get_widget_preferences():
    from ssr.widgets import get_household_widget_ids

    family_id = get_current_family_id()
    return jsonify({
        "success": True,
        "overview_widgets": get_household_widget_ids(family_id, "overview"),
        "scenarios_widgets": get_household_widget_ids(family_id, "scenarios"),
    })


@scenarios_bp.route("/api/widgets/preferences", methods=["POST"])
@editor_required
def api_save_widget_preferences():
    from ssr.widgets import save_household_widget_ids

    if session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Widget preferences cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    page = sanitize_text(str(data.get("page") or ""), max_length=20, field_name="Page", required=True).lower()
    if page not in ("overview", "scenarios"):
        return jsonify({"success": False, "error": "Invalid page; must be 'overview' or 'scenarios'"}), 400
    reset = bool(data.get("reset"))
    reorder_only = bool(data.get("reorder_only"))
    raw_ids = None if reset else (data.get("active_ids") if isinstance(data.get("active_ids"), list) else [])
    saved_ids = save_household_widget_ids(family_id, page, raw_ids)
    if reorder_only:
        forecast_cache.clear_l1_only()
    else:
        forecast_cache.invalidate_family_cache(family_id, domains=["balance_sheet"] if page == "overview" else ["scenarios"])
    return jsonify({"success": True, "page": page, "active_ids": saved_ids})


@scenarios_bp.route("/api/widgets/collapsed_charts", methods=["POST"])
@editor_required
def api_save_collapsed_chart():
    if session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"):
        return jsonify({"status": "error", "error": "Chart state cannot be changed in demo mode."}), 403
    from ssr.widgets_charts import save_collapsed_chart_state

    family_id = get_current_family_id()
    data = request.get_json() or {}
    chart_id = sanitize_text(str(data.get("chart_id") or ""), max_length=60, field_name="Chart ID", required=True)
    collapsed = bool(data.get("collapsed"))
    updated = save_collapsed_chart_state(family_id, chart_id, collapsed)
    return jsonify({"status": "ok", "collapsed_charts": updated})


