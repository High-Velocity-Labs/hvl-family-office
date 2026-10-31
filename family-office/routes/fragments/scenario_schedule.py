"""The forecasting page's year-by-year schedule table rows, loaded when the table is opened (htmx target)."""

from __future__ import annotations

from flask import render_template, request

from routes.context import get_current_family_id, login_required
from routes.fragments import ui_fragments_bp
from ssr.scenarios_plan_detail import build_schedule_table


@ui_fragments_bp.route("/fragments/scenarios/schedule")
@login_required
def scenario_schedule_fragment():
    rows = build_schedule_table(get_current_family_id(), request.args)
    return render_template("fragments/scenario_schedule_rows.html", rows=rows)
