"""Server-rendered AI advisor drawer fragments: bubbles, welcome, thread list, saved conversation, chips, quota."""

from __future__ import annotations

import logging

from flask import jsonify, render_template, request

import db
from routes.context import DB_PATH, get_current_family_id, login_required, sanitize_text
from routes.fragments import ui_fragments_bp
from services import background_jobs
from services.advisor.chat_service import build_demo_reply_text
from ssr.advisor_fragments import (
    CONV_FILTERS, DEFAULT_TAB, DEMO_NOTICE, build_conversation_cards, build_message_vm, build_quota_vm,
    build_welcome_vm,
)

logger = logging.getLogger(__name__)

MAX_DEMO_PROMPT = 1000  # the demo reply only needs the start of the question; keeps the GET well under request-line limits
MAX_NOTICE_TEXT = 500
MAX_CHIPS = 12


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _tab_arg(source) -> str:
    return _clip(source.get("tab"), 100) or DEFAULT_TAB


def _saved_conversations(family_id: int) -> list[dict]:
    if not family_id or not DB_PATH.exists():
        return []
    return db.conversations.list_conversations(family_id=family_id, db_path=DB_PATH)


@ui_fragments_bp.route("/fragments/advisor/welcome", methods=["GET"])
@login_required
def advisor_welcome_fragment():
    """`part=body` returns the greeting body only; otherwise the whole welcome bubble."""
    body_only = request.args.get("part") == "body"
    tpl = "fragments/advisor_welcome_body.html" if body_only else "fragments/advisor_welcome.html"
    return render_template(tpl, welcome=build_welcome_vm(_tab_arg(request.args)))


@ui_fragments_bp.route("/fragments/advisor/message", methods=["GET"])
@login_required
def advisor_message_fragment():
    """Renders one chat bubble; bot text is Markdown rendered and sanitized on the server and never sent by the browser.

    Exactly one source per request: `job` (the household's completed advisor job), `demo_for` (the start of the
    message a demo guest asked; the fixed demo reply is rendered), or `notice` (a short client-side status such as a
    network error). The person's own bubble is the drawer's `#advisor-user-bubble` template, so no message is ever
    sent in a URL."""
    args = request.args
    if args.get("job"):
        job = background_jobs.get_job(_clip(args.get("job"), 64), family_id=get_current_family_id())
        result = job.get("result") if job and job.get("status") == "completed" else None
        if not isinstance(result, dict) or not result.get("reply"):
            return jsonify({"success": False, "error": "Advisor job not found"}), 404
        vm = build_message_vm(
            "bot", result["reply"], demo=bool(result.get("demo_mode")), fallback=bool(result.get("is_fallback")),
            reason=_clip(result.get("fallback_reason"), 400), badge=_clip(result.get("model_badge") or result.get("model_used"), 60),
        )
    elif args.get("demo_for"):
        vm = build_message_vm("bot", build_demo_reply_text(_clip(args.get("demo_for"), MAX_DEMO_PROMPT)), demo=True)
    elif args.get("notice"):
        vm = build_message_vm("bot", _clip(args.get("notice"), MAX_NOTICE_TEXT))
    else:
        return jsonify({"success": False, "error": "No message source"}), 400
    return render_template("fragments/advisor_message.html", m=vm)


@ui_fragments_bp.route("/fragments/advisor/conversations", methods=["GET"])
@login_required
def advisor_conversations_fragment():
    """Thread cards for the conversations panel plus an out-of-band refresh of the saved-threads count badge."""
    args = request.args
    saved = _saved_conversations(get_current_family_id())
    view = args.get("filter", "all")
    cards = build_conversation_cards(
        saved,
        view=view if view in CONV_FILTERS else "all",
        query=args.get("q", ""),
        tab=_tab_arg(args),
        active_id=args.get("active", ""),
    )
    return render_template("fragments/advisor_conversations.html", cards=cards, total=len(saved))


@ui_fragments_bp.route("/fragments/advisor/conversation/<conv_id>", methods=["GET"])
@login_required
def advisor_conversation_fragment(conv_id: str):
    """A saved transcript as bubbles (or the welcome message when empty) plus its state carrier element."""
    family_id = get_current_family_id()
    conv_id = sanitize_text(conv_id, max_length=64, field_name="Conversation ID")
    if not family_id or not DB_PATH.exists():
        return jsonify({"success": False, "error": "Family not found"}), 404
    conv = db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=DB_PATH)
    if not conv:
        return jsonify({"success": False, "error": "Conversation not found"}), 404
    messages = conv.get("messages") or []
    bubbles = [build_message_vm("user" if m["role"] == "user" else "bot", m["content"]) for m in messages]
    history = [{"role": m["role"], "content": m["content"]} for m in messages]
    welcome = build_welcome_vm(conv.get("page_section") or _tab_arg(request.args)) if not messages else None
    return render_template(
        "fragments/advisor_conversation.html", conv=conv, bubbles=bubbles, history=history, welcome=welcome
    )


@ui_fragments_bp.route("/fragments/advisor/chips", methods=["GET"])
@login_required
def advisor_chips_fragment():
    """Suggestion chips for the suggestions drawer, with the same chips swapped into the welcome message."""
    prompts = [_clip(s, 300) for s in request.args.getlist("s")[:MAX_CHIPS]]
    return render_template("fragments/advisor_chips.html", prompts=[p for p in prompts if p])


@ui_fragments_bp.route("/fragments/advisor/quota", methods=["GET"])
@login_required
def advisor_quota_fragment():
    tier = request.args.get("tier", "")
    label = _clip(request.args.get("label"), 60)
    return render_template("fragments/advisor_quota.html", q=build_quota_vm(tier, label))


@ui_fragments_bp.route("/fragments/advisor/demo", methods=["GET"])
@login_required
def advisor_demo_fragment():
    """`part=badge` is the header badge bar; otherwise the guard banner bubble."""
    if request.args.get("part") == "badge":
        return render_template("fragments/advisor_demo_badge.html")
    notice = _clip(request.args.get("notice"), 400) or DEMO_NOTICE
    return render_template("fragments/advisor_demo_banner.html", notice=notice)
