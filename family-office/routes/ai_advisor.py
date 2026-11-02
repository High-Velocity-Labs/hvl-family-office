"""
AI Financial Advisor Blueprint.
Thin HTTP route layer for the omnipresent, page-aware fiduciary advisor.
Delegates structured Gemini tools, context assembly, and chat execution to services.advisor.
"""

from __future__ import annotations
import logging
import uuid
from flask import Blueprint, jsonify, request

from services import background_jobs
import config
import db
from services.advisor import (
    ALL_ADVISOR_TOOLS,
    _clean_history_text,
    _format_fiduciary_system_prompt,
    _format_off_topic_refusal,
    _generate_conversation_title,
    _generate_follow_up_suggestions,
    _generate_rule_based_response,
    _get_conversation_history_for_gemini,
    _get_family_advisor_context,
    _is_off_topic_query,
    _resolve_tool_family_id,
    estimate_equity_exercise_tax,
    get_accounts_and_balance_sheet,
    get_cash_flow_summary,
    get_compensation_and_tax_withholding,
    get_education_529_plan,
    get_equity_schedule,
    get_estate_tax_summary,
    get_family_gifting_summary,
    get_monte_carlo_stress_test,
    get_philanthropy_and_daf_summary,
    get_portfolio_allocation,
    get_scenarios_and_forecast_plan,
    get_state_tax_arbitrage,
    simulate_financial_scenario,
)
from hvl_common.ai import generate_content_with_tools
from hvl_common.web import rate_limit
from routes.context import (
    DB_PATH,
    editor_required,
    get_current_family_id,
    get_current_universe,
    login_required,
    sanitize_text,
)
from services.advisor.conversation_ownership import (
    bulk_delete_owned_conversations,
    caller_identity,
    delete_owned_conversation,
    update_owned_conversation,
)
from services.advisor import (
    build_advisor_context_response,
    handle_demo_chat_turn,
    is_advisor_demo_session,
    prepare_and_dispatch_chat,
)

logger = logging.getLogger(__name__)

ai_advisor_bp = Blueprint("ai_advisor", __name__)

_is_demo_session = is_advisor_demo_session


def _check_shared_ai_limit(ai_limits: dict[str, Any]):
    from hvl_common.ai import enforce_ai_rate_limit
    from db.telemetry import record_portal_telemetry_event

    return enforce_ai_rate_limit(
        ai_limits,
        scope="routes.ai_advisor.api_ai_advisor_chat",
        bypass=_is_demo_session(),
        only_shared=True,
        settings_hint="Settings → Account Connections",
        on_limited=lambda p, _: record_portal_telemetry_event(
            get_current_universe(), "rate_limit_hit", feature_key=f"ai_{p.get('tier', 'shared')}"
        ),
    )


@ai_advisor_bp.route("/api/ai-advisor/chat", methods=["POST"])
@rate_limit("30/min", "300/hr")
@login_required
def api_ai_advisor_chat():
    """Omnipresent, page-aware AI Financial Advisor chat endpoint."""
    family_id = get_current_family_id()
    ai_limits = config.get_household_ai_limits(family_id=family_id, db_path=DB_PATH)
    limited = _check_shared_ai_limit(ai_limits)
    if limited:
        return limited

    data = request.get_json() or {}
    try:
        max_Key = "AI_ADVISOR_BYO_MAX_INPUT_CHARS" if ai_limits.get("tier") in ("byo", "local") else "AI_ADVISOR_MAX_INPUT_CHARS"
        default_max = 8000 if ai_limits.get("tier") in ("byo", "local") else 2000
        user_message = sanitize_text(data.get("message"), max_length=int(getattr(config, max_Key, default_max)), field_name="Message", required=True, multiline=True)
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400

    active_tab = sanitize_text(data.get("active_tab", "section-overview"), max_length=100, field_name="Active Tab")
    if _is_demo_session():
        payload, status_code = handle_demo_chat_turn(family_id, user_message, active_tab, data.get("conversation_id"))
        return jsonify(payload), status_code

    payload, status_code = prepare_and_dispatch_chat(
        family_id=family_id,
        data=data,
        user_message=user_message,
        active_tab=active_tab,
        generate_fn=generate_content_with_tools,
    )
    from db.telemetry import record_portal_telemetry_event
    record_portal_telemetry_event(
        get_current_universe(),
        "action",
        feature_key="ai_advisor",
        action="ask_advisor",
        tab=str(active_tab).replace("section-", ""),
    )
    return jsonify(payload), status_code


@ai_advisor_bp.route("/api/ai-advisor/jobs/<job_id>", methods=["GET"])
@rate_limit("300/min")
@login_required
def api_ai_advisor_job_status(job_id: str):
    """Fast (<2ms) status lookup for an asynchronous AI Advisor generation job."""
    family_id = get_current_family_id()
    clean_job_id = sanitize_text(job_id, max_length=64)
    job = background_jobs.get_job(clean_job_id, family_id=family_id)
    if not job:
        return jsonify({"success": False, "error": "Advisor job not found"}), 404

    status = job.get("status")
    if status == "completed" and isinstance(job.get("result"), dict):
        out = dict(job["result"])
        out["job_id"] = clean_job_id
        out["status"] = "completed"
        return jsonify(out)

    if status != "processing":
        # failed, a completed ticket without a result, or an unknown status: terminal, so the client stops polling.
        error = job.get("error") if status == "failed" else f"Advisor job ended in an unexpected state ({status!r})"
        return jsonify({
            "success": False,
            "status": "failed",
            "job_id": clean_job_id,
            "error": error or "Advisor generation failed",
        })

    return jsonify({
        "success": True,
        "status": "processing",
        "job_id": clean_job_id,
        "conversation_id": job.get("conversation_id", ""),
        "conversation_title": job.get("conversation_title", ""),
        "is_new_conversation": job.get("is_new_conversation", False),
        "family_id": family_id,
        "active_tab": job.get("active_tab", "section-overview"),
    })


@ai_advisor_bp.route("/api/ai-advisor/context", methods=["GET"])
@login_required
def api_ai_advisor_context():
    """Returns prompt suggestions and active context chips based on the active tab and current family."""
    family_id = get_current_family_id()
    active_tab = sanitize_text(request.args.get("tab", "section-overview"), max_length=100)
    return jsonify(build_advisor_context_response(family_id=family_id, active_tab=active_tab))


@ai_advisor_bp.route("/api/ai-advisor/conversations", methods=["GET"])
@login_required
def api_list_conversations():
    """Returns saved conversations for the active family, optionally filtered by page_section or search."""
    family_id = get_current_family_id()
    if not family_id or not DB_PATH.exists():
        return jsonify({"success": True, "conversations": []})

    page_section = sanitize_text(request.args.get("page_section", ""), max_length=100)
    search_query = sanitize_text(request.args.get("search", ""), max_length=100).lower()
    pinned_only = request.args.get("pinned_only", "").strip().lower() in ("1", "true")

    conversations = db.conversations.list_conversations(
        family_id=family_id,
        page_section=page_section,
        search_query=search_query,
        pinned_only=pinned_only,
        db_path=DB_PATH,
    )
    return jsonify({"success": True, "conversations": conversations})


@ai_advisor_bp.route("/api/ai-advisor/conversations/<conv_id>", methods=["GET"])
@login_required
def api_get_conversation(conv_id: str):
    """Retrieves full transcript and metadata for a specific conversation."""
    family_id = get_current_family_id()
    if not family_id or not DB_PATH.exists():
        return jsonify({"success": False, "error": "Family not found"}), 404

    conv_id = sanitize_text(conv_id, max_length=64, field_name="Conversation ID")
    conv = db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=DB_PATH)
    if not conv:
        return jsonify({"success": False, "error": "Conversation not found"}), 404
    return jsonify({"success": True, "conversation": conv})


@ai_advisor_bp.route("/api/ai-advisor/conversations", methods=["POST"])
@login_required
@editor_required
def api_create_conversation():
    """Initializes a new blank conversation thread."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    page_section = sanitize_text(data.get("page_section", "section-overview"), max_length=100)
    title = sanitize_text(data.get("title", "New Advisory Thread"), max_length=150)
    conv_id = uuid.uuid4().hex[:16]

    try:
        created_by = caller_identity()
        created_id = db.conversations.create_conversation(
            conv_id=conv_id,
            family_id=family_id,
            page_section=page_section,
            title=title,
            created_by=created_by,
            db_path=DB_PATH,
        )
        return jsonify({"success": True, "conversation_id": created_id, "title": title, "page_section": page_section})
    except PermissionError as pe:
        return jsonify({"success": False, "error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400


@ai_advisor_bp.route("/api/ai-advisor/conversations/<conv_id>", methods=["PATCH", "PUT"])
@login_required
@editor_required
def api_update_conversation(conv_id: str):
    """Updates conversation title or pin/bookmark status."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    conv_id = sanitize_text(conv_id, max_length=64)

    title_val = sanitize_text(data.get("title", ""), max_length=150) if "title" in data else None
    is_pinned_val = data.get("is_pinned") if "is_pinned" in data else None

    if title_val is None and is_pinned_val is None:
        return jsonify({"success": False, "error": "No update fields provided"}), 400

    try:
        success = update_owned_conversation(conv_id, family_id, DB_PATH, title_val, is_pinned_val)
        if not success:
            return jsonify({"success": False, "error": "Conversation not found"}), 404
        return jsonify({"success": True, "conversation_id": conv_id})
    except PermissionError as pe:
        return jsonify({"success": False, "error": str(pe)}), 403


@ai_advisor_bp.route("/api/ai-advisor/conversations/<conv_id>", methods=["DELETE"])
@login_required
@editor_required
def api_delete_conversation(conv_id: str):
    """Deletes a single conversation and its associated messages."""
    family_id = get_current_family_id()
    conv_id = sanitize_text(conv_id, max_length=64)
    try:
        deleted = delete_owned_conversation(conv_id, family_id, DB_PATH)
        if not deleted:
            return jsonify({"success": False, "error": "Conversation not found"}), 404
        return jsonify({"success": True, "deleted": conv_id})
    except PermissionError as pe:
        return jsonify({"success": False, "error": str(pe)}), 403


@ai_advisor_bp.route("/api/ai-advisor/conversations/bulk-delete", methods=["POST"])
@login_required
@editor_required
def api_bulk_delete_conversations():
    """Deletes multiple conversations in a single transaction."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    conv_ids = data.get("conversation_ids") or []
    if not isinstance(conv_ids, list) or not conv_ids:
        return jsonify({"success": False, "error": "No conversation IDs provided"}), 400

    sanitized_ids = [sanitize_text(str(cid), max_length=64) for cid in conv_ids[:100] if cid]
    if not sanitized_ids:
        return jsonify({"success": False, "error": "Invalid conversation IDs"}), 400

    deleted_count = bulk_delete_owned_conversations(sanitized_ids, family_id, DB_PATH)
    return jsonify({"success": True, "deleted_count": deleted_count})
