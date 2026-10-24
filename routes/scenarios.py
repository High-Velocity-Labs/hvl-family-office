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
    DB_PATH, editor_required, get_current_family_id, get_current_universe,
    login_required, sanitize_text,
)
from services.scenario_archive_service import toggle_scenario_archived
from services.scenario_clone_service import clone_scenario, delete_scenario_hierarchy
from services.scenario_overlay_service import (
    apply_scenario_extra_fields, delete_scenario_event, get_active_baseline_layers,
    reorder_baseline_layers, save_scenario_event, toggle_baseline_layer,
)
from services.scenario_reorder_service import emit_reorder_notification, reorder_scenarios
from services.scenario_service import (
    export_forecast_csv, get_or_compute_monte_carlo, get_or_compute_scenarios,
    save_scenario, serialize_forecast_csv,
)

# Preserve backward compatibility for tests or callers that import _serialize_forecast_csv
_serialize_forecast_csv = serialize_forecast_csv

# Bind multi-tenant/multi-universe DB path proxy so forecast_engine isolates demo vs public data
forecast_engine.DB_PATH = DB_PATH

scenarios_bp = Blueprint("scenarios", __name__)
rate_limit("120/min")(scenarios_bp)


def _is_demo_blocked() -> bool:
    return bool(session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"))


def _emit_scenario_collab(family_id: int, key: str, title: str, body: str) -> None:
    db.notifications.emit_family_notification(
        DB_PATH, family_id=family_id, category="collaboration",
        dedupe_key=key, deep_link="/scenarios", title=title, body=body,
        sender_email=str(session.get("user_email") or ""),
        sender_name=str(session.get("user") or ""),
    )


@scenarios_bp.route("/api/scenarios", methods=["GET"])
@login_required
def api_get_scenarios():
    family_id = get_current_family_id()
    universe = get_current_universe()
    res = get_or_compute_scenarios(
        family_id=family_id, universe=universe, args=request.args,
        engine=forecast_engine, cache=forecast_cache,
    )
    return jsonify(res)


@scenarios_bp.route("/api/scenarios/export_csv", methods=["GET"])
@login_required
def api_export_scenarios_csv():
    """Exports the multi-year forecast & tax projection schedule as a downloadable CSV."""
    from flask import Response

    family_id = get_current_family_id()
    csv_data = export_forecast_csv(family_id=family_id, args=request.args, engine=forecast_engine)
    return Response(
        csv_data, mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="family_office_forecast_projection.csv"', "Cache-Control": "no-store"},
    )


@scenarios_bp.route("/api/scenarios/monte-carlo", methods=["GET"])
@login_required
def api_get_monte_carlo():
    """Stochastic Monte Carlo simulation & sequence-of-returns crisis stress testing."""
    family_id = get_current_family_id()
    universe = get_current_universe()
    res = get_or_compute_monte_carlo(
        family_id=family_id, universe=universe, args=request.args,
        engine=forecast_engine, cache=forecast_cache,
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
        family_id=family_id, data=data, engine=forecast_engine,
        cache=forecast_cache, db_module=db, db_path=DB_PATH,
    )
    if not success:
        return jsonify({"success": False, "error": err_msg}), 400
    apply_scenario_extra_fields(family_id, data, engine=forecast_engine, cache=forecast_cache)
    scen_label = sanitize_text(str(data.get("name") or data.get("id") or "Scenario"), max_length=100)
    user_label = session.get("user") or "A household member"
    _emit_scenario_collab(
        family_id, f"collab:scenario:{data.get('id') or scen_label}",
        f"Scenario updated: {scen_label}", f"{user_label} updated scenario '{scen_label}'.",
    )
    return jsonify({"success": True})


@scenarios_bp.route("/api/scenarios/baseline_layers", methods=["GET"])
@login_required
def api_get_baseline_layers():
    """Retrieves active baseline overlay scenario IDs for the active household."""
    family_id = get_current_family_id()
    layers = get_active_baseline_layers(family_id=family_id, engine=forecast_engine)
    return jsonify({"success": True, "active_baseline_layers": layers, "active_layers": layers})


@scenarios_bp.route("/api/scenarios/<scenario_id>/toggle_baseline_layer", methods=["POST"])
@editor_required
def api_toggle_baseline_layer(scenario_id: str):
    """Toggles or sets a scenario as an active stackable baseline overlay."""
    if _is_demo_blocked():
        return jsonify({"success": False, "error": "Baseline overlays cannot be modified in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    active = data.get("active") if "active" in data else None
    ok, err, is_active, layers = toggle_baseline_layer(
        family_id=family_id, scenario_id=scenario_id, active=active,
        engine=forecast_engine, cache=forecast_cache, db_module=db, db_path=DB_PATH,
        user_name=session.get("user"), user_email=session.get("user_email"),
    )
    if not ok:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({
        "success": True, "scenario_id": scenario_id,
        "is_active": is_active, "active_baseline_layers": layers, "active_layers": layers,
    })


@scenarios_bp.route("/api/scenarios/baseline_layers/reorder", methods=["POST"])
@editor_required
def api_reorder_baseline_layers():
    """Reorders the stackable baseline overlay layers."""
    if _is_demo_blocked():
        return jsonify({"success": False, "error": "Baseline overlays cannot be reordered in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    layer_ids = data.get("layer_ids") or data.get("order") or []
    ok, err, layers = reorder_baseline_layers(
        family_id=family_id, layer_ids=layer_ids,
        engine=forecast_engine, cache=forecast_cache,
    )
    if not ok:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True, "active_baseline_layers": layers, "active_layers": layers})


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
    if _is_demo_blocked():
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
    if _is_demo_blocked():
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
        family_id=family_id, source_id=source_id,
        engine=forecast_engine, cache=forecast_cache,
    )
    if not success:
        return jsonify({"success": False, "error": result}), status_code
    cloned_name = result.get("name", source_id) if isinstance(result, dict) else source_id
    user_label = session.get("user") or "A household member"
    _emit_scenario_collab(
        family_id, f"collab:scenario:{cloned_name}",
        f"Scenario cloned: {cloned_name}", f"{user_label} cloned scenario '{cloned_name}'.",
    )
    return jsonify({"success": True, "scenario": result})


@scenarios_bp.route("/api/scenarios/<scenario_id>", methods=["DELETE"])
@editor_required
def api_delete_scenario(scenario_id: str):
    if scenario_id == "scen_baseline":
        return jsonify({"success": False, "error": "Cannot delete Baseline Plan"}), 400
    family_id = get_current_family_id()
    deleted_ids = delete_scenario_hierarchy(
        family_id=family_id, scenario_id=scenario_id,
        engine=forecast_engine, cache=forecast_cache,
    )
    return jsonify({"success": True, "deleted_ids": deleted_ids})


@scenarios_bp.route("/api/scenarios/<scenario_id>/archive", methods=["POST"])
@editor_required
def api_toggle_scenario_archive(scenario_id: str):
    """Archives or unarchives a scenario plan."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    archived = data.get("archived") if "archived" in data else None
    success, err, new_state = toggle_scenario_archived(
        family_id=family_id, scenario_id=scenario_id, archived=archived,
        engine=forecast_engine, cache=forecast_cache,
    )
    if not success:
        return jsonify({"success": False, "error": err}), 400
    action = "archived" if new_state else "unarchived"
    user_label = session.get("user") or "A household member"
    _emit_scenario_collab(
        family_id, f"collab:scenario:{scenario_id}:{action}",
        f"Scenario {action}: {scenario_id}", f"{user_label} {action} scenario '{scenario_id}'.",
    )
    return jsonify({"success": True, "scenario_id": scenario_id, "is_archived": new_state})


@scenarios_bp.route("/api/scenarios/reorder", methods=["POST"])
@editor_required
def api_reorder_scenarios():
    family_id = get_current_family_id()
    order = (request.get_json(silent=True) or {}).get("order")
    ok, err = reorder_scenarios(family_id, order, engine=forecast_engine, cache=forecast_cache)
    if not ok:
        return jsonify({"success": False, "error": err}), 400
    emit_reorder_notification(DB_PATH, family_id, session.get("user") or "", session.get("user_email") or "")
    return jsonify({"success": True, "order": order})


@scenarios_bp.route("/api/events", methods=["POST"])
@editor_required
def api_save_event():
    family_id = get_current_family_id()
    data = request.get_json() or {}
    ok, err = save_scenario_event(family_id, data, engine=forecast_engine, cache=forecast_cache)
    if not ok:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True})


@scenarios_bp.route("/api/events/<event_id>", methods=["DELETE"])
@editor_required
def api_delete_event(event_id: str):
    family_id = get_current_family_id()
    delete_scenario_event(family_id, event_id, engine=forecast_engine, cache=forecast_cache)
    return jsonify({"success": True})


@scenarios_bp.route("/api/scenarios/settings", methods=["POST"])
@editor_required
def api_save_scenario_settings():
    if _is_demo_blocked():
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    state = forecast_engine.load_scenario_state(family_id=family_id)
    if "equity_growth_preset" in data:
        state["equity_growth_preset"] = data.get("equity_growth_preset")
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

    if _is_demo_blocked():
        return jsonify({"success": False, "error": "Widget preferences cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    page = sanitize_text(str(data.get("page") or ""), max_length=20, field_name="Page", required=True).lower()
    if page not in ("overview", "scenarios"):
        return jsonify({"success": False, "error": "Invalid page; must be 'overview' or 'scenarios'"}), 400
    reset = bool(data.get("reset"))
    raw_ids = None if reset else (data.get("active_ids") if isinstance(data.get("active_ids"), list) else [])
    saved_ids = save_household_widget_ids(family_id, page, raw_ids)
    if bool(data.get("reorder_only")):
        forecast_cache.clear_l1_only()
    else:
        forecast_cache.invalidate_family_cache(family_id, domains=["balance_sheet"] if page == "overview" else ["scenarios"])
    return jsonify({"success": True, "page": page, "active_ids": saved_ids})


@scenarios_bp.route("/api/widgets/collapsed_charts", methods=["POST"])
@editor_required
def api_save_collapsed_chart():
    if _is_demo_blocked():
        return jsonify({"status": "error", "error": "Chart state cannot be changed in demo mode."}), 403
    from ssr.widgets_charts import save_collapsed_chart_state

    family_id = get_current_family_id()
    data = request.get_json() or {}
    chart_id = sanitize_text(str(data.get("chart_id") or ""), max_length=60, field_name="Chart ID", required=True)
    collapsed = bool(data.get("collapsed"))
    updated = save_collapsed_chart_state(family_id, chart_id, collapsed)
    return jsonify({"status": "ok", "collapsed_charts": updated})
