"""Server-rendered chrome for the forecasting charts: lens toggle strips and captions (htmx targets)."""

from __future__ import annotations

from flask import jsonify, render_template, request

from routes.context import login_required
from routes.fragments import ui_fragments_bp
from ssr.chart_chrome import build_chart_caption, build_chart_toggles


@ui_fragments_bp.route("/fragments/chart_toggles/<lens>")
@login_required
def chart_toggles_fragment(lens: str):
    chart = build_chart_toggles(lens, request.args.get("mode"))
    if chart is None:
        return jsonify({"error": "Fragment not found"}), 404
    return render_template("fragments/chart_toggles.html", chart=chart)


@ui_fragments_bp.route("/fragments/chart_caption/<lens>")
@login_required
def chart_caption_fragment(lens: str):
    caption = build_chart_caption(lens, request.args.get("mode"))
    if caption is None:
        return jsonify({"error": "Fragment not found"}), 404
    return render_template("fragments/chart_caption_montecarlo.html", caption=caption)
