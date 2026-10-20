"""
Pane Bug Reporter & Admin Bug Queue Routes.
Handles user-facing bug triage requests, bug report submissions, and admin queue workflows.
"""

from __future__ import annotations

from typing import Any
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from db.bugs import get_bug_queue_counts, list_bug_reports, update_bug_report_status
from routes.auth import _is_site_admin_request
from routes.helpers import editor_required, get_current_db_path, get_current_family_id, is_sandbox_session, sanitize_text
from services.bug_reporter_service import format_antigravity_prompt, run_bug_triage_analysis, submit_bug_report

bugs_bp = Blueprint("bugs", __name__)


def _check_bugs_rate_limit(scope: str, limit_str: str = "10/min") -> tuple[bool, int]:
    """Evaluates rate limit using _default_limiter, allowing test overrides."""
    if current_app.config.get("TESTING") and not (
        current_app.config.get("TEST_BUG_RATE_LIMIT") or current_app.config.get("RATELIMIT_ENABLED")
    ):
        return True, 0
    from hvl_common.web.rate_limit import _default_limiter
    prev_enabled = current_app.config.get("RATELIMIT_ENABLED")
    if current_app.config.get("TEST_BUG_RATE_LIMIT"):
        current_app.config["RATELIMIT_ENABLED"] = True
    try:
        allowed, retry_after, _ = _default_limiter.evaluate(limit_str, scope=scope)
    finally:
        if current_app.config.get("TEST_BUG_RATE_LIMIT"):
            current_app.config["RATELIMIT_ENABLED"] = prev_enabled
    return allowed, retry_after


@bugs_bp.route("/api/bugs/analyze", methods=["POST"])
def api_bugs_analyze():
    """Performs first-line mathematical triage on a user-reported discrepancy."""
    if session.get("is_demo"):
        return jsonify({"success": False, "error": "Bug reporting is disabled in read-only demo mode."}), 403
    if not session.get("authenticated") and not is_sandbox_session():
        return jsonify({"success": False, "error": "Unauthorized", "login_required": True}), 401

    allowed, retry = _check_bugs_rate_limit("bugs.analyze", "10/min")
    if not allowed:
        return jsonify({"success": False, "error": f"Rate limit exceeded. Please wait {retry}s."}), 429

    data: dict[str, Any] = request.get_json(silent=True) or {}
    pane = sanitize_text(str(data.get("pane") or "")[:32], 32, "pane").lower() or "overview"
    category = sanitize_text(str(data.get("category") or "")[:32], 32, "category").lower() or "math"
    description = sanitize_text(str(data.get("description") or "")[:500], 500, "description")
    scale_factor = data.get("scale_factor")
    client_ctx = data.get("client_context") if isinstance(data.get("client_context"), dict) else {}

    fid = get_current_family_id()
    db_path = get_current_db_path(family_id=fid)
    triage = run_bug_triage_analysis(
        family_id=fid,
        pane=pane,
        category=category,
        description=description,
        client_context=client_ctx,
        scale_factor=scale_factor,
        db_path=db_path,
    )
    triage.pop("_token_map", None)
    return jsonify({"success": True, **triage})


@bugs_bp.route("/api/bugs/submit", methods=["POST"])
def api_bugs_submit():
    """Persists an anonymized bug report and triage snapshot into global.db."""
    if session.get("is_demo"):
        return jsonify({"success": False, "error": "Bug reporting is disabled in read-only demo mode."}), 403
    if not session.get("authenticated") and not is_sandbox_session():
        return jsonify({"success": False, "error": "Unauthorized", "login_required": True}), 401

    allowed, retry = _check_bugs_rate_limit("bugs.submit", "10/min")
    if not allowed:
        return jsonify({"success": False, "error": f"Rate limit exceeded. Please wait {retry}s."}), 429

    data: dict[str, Any] = request.get_json(silent=True) or {}
    pane = sanitize_text(str(data.get("pane") or "")[:32], 32, "pane").lower() or "overview"
    category = sanitize_text(str(data.get("category") or "")[:32], 32, "category").lower() or "math"
    description = sanitize_text(str(data.get("description") or "")[:500], 500, "description")
    followup = sanitize_text(str(data.get("followup_notes") or "")[:400], 400, "followup_notes")
    scale_factor = data.get("scale_factor")
    client_ctx = data.get("client_context") if isinstance(data.get("client_context"), dict) else {}

    fid = get_current_family_id()
    db_path = get_current_db_path(family_id=fid)
    res = submit_bug_report(
        family_id=fid,
        pane=pane,
        category=category,
        description=description,
        followup_notes=followup,
        scale_factor=scale_factor,
        client_context=client_ctx,
        db_path=db_path,
    )
    return jsonify({"success": True, **res})


@bugs_bp.route("/admin/bugs", methods=["GET"])
def admin_bugs_view():
    """Renders the administrative bug triage queue for site administrators."""
    if not _is_site_admin_request():
        if not session.get("authenticated"):
            return redirect(url_for("auth.login_view", next=request.path))
        return jsonify({"error": "Forbidden: Site administrator access required"}), 403

    status = sanitize_text(str(request.args.get("status") or "")[:32], 32, "status") or None
    universe = sanitize_text(str(request.args.get("universe") or "")[:32], 32, "universe") or None
    project = sanitize_text(str(request.args.get("project") or "")[:32], 32, "project") or None
    reports = list_bug_reports(status=status, universe=universe, project=project)
    counts = get_bug_queue_counts(project=project)
    for r in reports:
        r["antigravity_prompt"] = format_antigravity_prompt(r)

    return render_template(
        "admin_bugs.html",
        reports=reports,
        counts=counts,
        selected_status=status or "all",
        selected_universe=universe or "all",
        selected_project=project or "all",
    )


@bugs_bp.route("/api/admin/bugs", methods=["GET"])
def api_admin_bugs():
    """Returns bug reports and queue counts as JSON for site administrators."""
    if not _is_site_admin_request():
        if not session.get("authenticated"):
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        return jsonify({"error": "Forbidden: Site administrator access required"}), 403

    status = sanitize_text(str(request.args.get("status") or "")[:32], 32, "status") or None
    universe = sanitize_text(str(request.args.get("universe") or "")[:32], 32, "universe") or None
    project = sanitize_text(str(request.args.get("project") or "")[:32], 32, "project") or None
    reports = list_bug_reports(status=status, universe=universe, project=project)
    counts = get_bug_queue_counts(project=project)
    for r in reports:
        r["antigravity_prompt"] = format_antigravity_prompt(r)

    return jsonify({"success": True, "reports": reports, "counts": counts})


@bugs_bp.route("/api/admin/bugs/<int:bug_id>/status", methods=["POST"])
@editor_required
def api_admin_bugs_status(bug_id: int):
    """Updates bug report status and admin notes."""
    if not _is_site_admin_request():
        return jsonify({"error": "Forbidden: Site administrator access required"}), 403

    data: dict[str, Any] = request.get_json(silent=True) or {}
    status = sanitize_text(data.get("status"), 32, "status").lower()
    admin_notes = sanitize_text(data.get("admin_notes"), 500, "admin_notes") if "admin_notes" in data else None
    if status not in ("open", "investigating", "resolved", "dismissed"):
        return jsonify({"success": False, "error": "Invalid status value"}), 400

    ok = update_bug_report_status(bug_id=bug_id, status=status, admin_notes=admin_notes)
    if not ok:
        return jsonify({"success": False, "error": "Bug report not found"}), 404
    return jsonify({"success": True, "bug_id": bug_id, "status": status})
