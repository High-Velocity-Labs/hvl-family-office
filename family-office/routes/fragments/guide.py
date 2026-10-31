"""Server-rendered page-guide drawer content."""

from __future__ import annotations

from flask import render_template

from routes.context import login_required
from routes.fragments import ui_fragments_bp
from ssr.guide_fragments import build_guide_vm


@ui_fragments_bp.route("/fragments/guide/<section_id>", methods=["GET"])
@login_required
def guide_content_fragment(section_id: str):
    """The guide body for one section plus out-of-band title and badge updates."""
    return render_template("fragments/guide_content.html", guide=build_guide_vm(section_id[:64]))
