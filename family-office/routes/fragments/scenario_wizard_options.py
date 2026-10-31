"""Server-rendered `<option>` lists for the scenario event wizard, plus the preset tables its templates read.

The context processor exposes the benchmark tables (education/eldercare/grad costs, Roth presets, superfund amounts,
state income tax rates) to every template; the fragment fills the selects that depend on the household's members.
"""

from __future__ import annotations

from datetime import date

from flask import abort, render_template, request

import db
import security
from routes.context import DB_PATH, login_required
from routes.fragments import ui_fragments_bp
from services import scenario_benchmarks
from services.request_context import get_current_family_id

_DEPENDENT_RELATIONSHIPS = ("parent", "dependent", "relative")
_KINDS = ("children", "parents", "college_children")


@ui_fragments_bp.app_context_processor
def scenario_wizard_tables():
    return scenario_benchmarks.wizard_tables(date.today().year)


@ui_fragments_bp.route("/fragments/scenario_wizard_options")
@login_required
def scenario_wizard_options_fragment():
    """Options for one household-dependent wizard select: `kind` is children, parents or college_children."""
    kind = request.args.get("kind", "")
    if kind not in _KINDS:
        abort(400)
    family_id = get_current_family_id()
    if kind == "college_children":
        payload = db.education.build_college_education_payload(family_id=family_id, db_path=DB_PATH)
        people = payload.get("children") or []
    else:
        members = security.get_family_members(DB_PATH, family_id=family_id)
        wanted = ("child",) if kind == "children" else _DEPENDENT_RELATIONSHIPS
        people = [m for m in members if m.get("relationship") in wanted]
    return render_template("fragments/scenario_wizard_options.html", kind=kind, people=people)
