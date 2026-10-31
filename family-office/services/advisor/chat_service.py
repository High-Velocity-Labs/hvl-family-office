"""
Service layer for AI Financial Advisor chat execution, demo sandbox handling,
background job orchestration, and context/conversation helpers.
"""

from __future__ import annotations
import logging
import os
import uuid
from typing import Any, Callable, Dict, Optional
from flask import session

from services import background_jobs
import config
import db
from hvl_common.ai import (
    VOICE_ADVISOR_SYSTEM_INSTRUCTION,
    build_carryover_seed_message,
    check_conversation_context_pressure,
    detect_voice_lifecycle_intent,
    extract_human_voice_reply,
    format_model_badge,
    generate_content_with_tools as _default_generate_with_tools,
    resolve_model_tier,
)
from hvl_common.ai.conversation import _strip_voice_reply_blocks
from services.request_context import DB_PATH, get_current_universe, is_beta_non_admin, sanitize_text
from services.advisor.context import (
    _format_fiduciary_system_prompt,
    _format_off_topic_refusal,
    _generate_conversation_title,
    _generate_follow_up_suggestions,
    _get_conversation_history_for_gemini,
    _get_family_advisor_context,
    _is_off_topic_query,
    get_initial_tab_suggestions,
)
from services.advisor.fallback import _generate_rule_based_response
from services.advisor.conversation_ownership import (
    caller_identity, history_trust, require_access,
)
from services.advisor.tool_permissions import AdvisorTurn, TurnTrust
from services.advisor.tools_tabs import ALL_ADVISOR_TOOLS

logger = logging.getLogger(__name__)


def is_advisor_demo_session() -> bool:
    """True when the caller gets the canned demo reply instead of a live advisor turn (demo persona or beta non-admin; sandbox exempt).
    Viewers get live turns with write tools withheld (see `tool_permissions.AdvisorTurn`)."""
    if session.get("is_sandbox"):
        return False
    return bool(session.get("is_demo") or is_beta_non_admin())


def _handle_advisor_lifecycle_intent(
    intent: str,
    family_id: int,
    target_db_path: Any,
    conv_id: str,
    conv_title: str,
    active_tab: str,
    history: Any,
    context: Dict[str, Any],
    voice_mode: bool = False,
    caller: str = "",
) -> Dict[str, Any]:
    """Handles spoken/text conversation lifecycle commands (`compact`, `carryover`, `new_conversation`, `doctor`)."""
    gemini_key = config.get_household_gemini_api_key(family_id=family_id, db_path=target_db_path)
    normalized_turns = _get_conversation_history_for_gemini(
        conv_id=conv_id, family_id=family_id, client_history=history if isinstance(history, list) else None,
    )
    follow_ups = _generate_follow_up_suggestions("", active_tab, context)
    if intent == "doctor":
        turn_count = len(normalized_turns)
        pressure = check_conversation_context_pressure(normalized_turns) or "Context window is healthy with plenty of headroom."
        reply_text = f"**Advisor Health & Context Status**\n\n- **Active Turns:** {turn_count}\n- **Context Status:** {pressure}"
        voice_reply = f"Voice advisor is online with {turn_count} turns in this thread. {pressure}"
        return {
            "success": True, "status": "completed", "lifecycle_action": "doctor",
            "reply": reply_text, "voice_reply": voice_reply, "voice_mode": bool(voice_mode),
            "conversation_id": conv_id, "conversation_title": conv_title, "is_new_conversation": False,
            "family_id": family_id, "family_name": context.get("family_name"), "active_tab": active_tab,
            "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"),
            "follow_up_suggestions": follow_ups, "is_fallback": False, "engine": "lifecycle",
        }
    if intent == "compact":
        seed_msg = build_carryover_seed_message(normalized_turns, api_key=gemini_key)
        reply_text = f"**Conversation Compacted**\n\n{seed_msg or 'Conversation history is already concise.'}"
        voice_reply = "I've compacted our conversation history so we can keep going smoothly."
        if family_id and target_db_path and target_db_path.exists() and conv_id:
            try:
                existing = db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=target_db_path)
                db.conversations.delete_conversation(conv_id=conv_id, family_id=family_id, db_path=target_db_path)
                db.conversations.create_conversation(
                    conv_id=conv_id,
                    family_id=family_id,
                    page_section=(existing or {}).get("page_section") or active_tab,
                    title=(existing or {}).get("title") or conv_title or "Advisory Thread",
                    created_by=(existing or {}).get("created_by") or caller or "Family Member",
                    db_path=target_db_path,
                )
                if (existing or {}).get("is_pinned"):
                    db.conversations.update_conversation(conv_id=conv_id, family_id=family_id, is_pinned=True, db_path=target_db_path)
                db.conversations.add_message(conv_id=conv_id, family_id=family_id, role="model", content=reply_text, db_path=target_db_path)
            except Exception:
                pass
        return {
            "success": True, "status": "completed", "lifecycle_action": "compact",
            "reply": reply_text, "voice_reply": voice_reply, "voice_mode": bool(voice_mode),
            "conversation_id": conv_id,
            "conversation_title": conv_title, "is_new_conversation": False, "family_id": family_id,
            "family_name": context.get("family_name"), "active_tab": active_tab,
            "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"),
            "follow_up_suggestions": follow_ups, "is_fallback": False, "engine": "lifecycle",
        }

    new_conv_id = uuid.uuid4().hex[:16]
    if intent == "carryover":
        seed_msg = build_carryover_seed_message(normalized_turns, api_key=gemini_key)
        new_title = f"{conv_title or 'Advisory Thread'} (Continued)"[:120]
        reply_text = f"I've started a fresh conversation and carried over our context.\n\n{seed_msg}".strip()
        voice_reply = "I've started a fresh conversation and carried over our context. What's next?"
    else:
        new_title = "New Advisory Thread"
        reply_text = "I've started a fresh conversation. How can I help with your household financial plan?"
        voice_reply = "I've started a fresh conversation. What's next?"

    if family_id and target_db_path and target_db_path.exists():
        try:
            db.conversations.create_conversation(
                conv_id=new_conv_id, family_id=family_id, page_section=active_tab,
                title=new_title, created_by=caller or "Family Member", db_path=target_db_path,
            )
            db.conversations.add_message(
                conv_id=new_conv_id, family_id=family_id, role="model", content=reply_text, db_path=target_db_path,
            )
        except Exception as e:
            logger.warning("Could not persist %s conversation: %s", intent, e)

    return {
        "success": True, "status": "completed", "lifecycle_action": intent,
        "previous_conversation_id": conv_id, "reply": reply_text, "voice_reply": voice_reply,
        "voice_mode": bool(voice_mode), "conversation_id": new_conv_id,
        "conversation_title": new_title, "is_new_conversation": True,
        "family_id": family_id, "family_name": context.get("family_name"), "active_tab": active_tab,
        "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"),
        "follow_up_suggestions": follow_ups, "is_fallback": False, "engine": "lifecycle",
    }


def execute_advisor_generation(
    family_id: int,
    target_db_path: Any,
    conv_id: str,
    conv_title: str,
    is_new_conv: bool,
    user_message: str,
    active_tab: str,
    history: Any,
    context: Optional[Dict[str, Any]] = None,
    generate_fn: Optional[Callable[..., Any]] = None,
    model_tier: Optional[str] = None,
    voice_mode: bool = False,
    caller: str = "",
    prior_trust: Optional[TurnTrust] = None,
) -> Dict[str, Any]:
    """Executes Gemini tool-calling generation (or deterministic fallback) with all 25 household tools.
    `prior_trust` is decided from thread ownership by the request; a stored thread with no verdict is tainted."""
    if context is None:
        context = _get_family_advisor_context(family_id, active_tab=active_tab)

    lifecycle_intent = detect_voice_lifecycle_intent(user_message)
    if lifecycle_intent:
        return _handle_advisor_lifecycle_intent(
            lifecycle_intent, family_id, target_db_path, conv_id, conv_title, active_tab, history, context,
            voice_mode=voice_mode, caller=caller,
        )

    if _is_off_topic_query(user_message, history=history):
        refusal_text = _format_off_topic_refusal(context)
        follow_up_suggestions = _generate_follow_up_suggestions("", active_tab, context)
        if family_id and target_db_path and target_db_path.exists() and conv_id and refusal_text:
            try:
                db.conversations.add_message(conv_id=conv_id, family_id=family_id, role="model", content=refusal_text, db_path=target_db_path)
            except Exception as e:
                logger.warning("Could not persist advisor refusal turn: %s", e)
        return {
            "success": True, "status": "completed", "reply": refusal_text, "conversation_id": conv_id,
            "conversation_title": conv_title, "is_new_conversation": is_new_conv, "family_id": family_id,
            "family_name": context.get("family_name"), "active_tab": active_tab,
            "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"),
            "follow_up_suggestions": follow_up_suggestions, "is_fallback": False,
            "off_topic_blocked": True, "engine": "guardrail", "model_used": None, "fallback_reason": None,
        }

    gemini_key = config.get_household_gemini_api_key(family_id=family_id, db_path=target_db_path)
    reply_text = ""
    active_model = None
    last_model_error = None
    effective_generate_fn = generate_fn or _default_generate_with_tools
    normalized_turns = _get_conversation_history_for_gemini(
        conv_id=conv_id, family_id=family_id, client_history=history if isinstance(history, list) else None,
    )

    if gemini_key:
        try:
            trust = prior_trust if prior_trust is not None else (TurnTrust.TAINTED if conv_id else TurnTrust.CLEAN)
            tools = AdvisorTurn(trust).authorize(ALL_ADVISOR_TOOLS)
            tool_names_str = ", ".join(t.__name__ for t in tools)
            system_context = _format_fiduciary_system_prompt(context)
            system_instruction = (
                f"{system_context}\n"
                f"Use your available tools ({tool_names_str}) to query the household's actual accounts, balance sheet, "
                f"holdings/IPS drift, equity grants (NSOs + RSUs), multi-scenario longevity forecasts, W-2 compensation & "
                f"Safe Harbor tax withholding, IRS transcripts, multi-state tax arbitrage, 529 education plans, "
                f"philanthropy/DAF grants, family gifting (Form 709), estate taxes, dynamic what-if simulations, "
                f"and live web search (`search_live_web`, `fetch_web_page`) for enacted tax laws, court rulings, or market facts.\n"
                f"IMPORTANT GUARDRAIL: You must ONLY answer questions related to personal finance, wealth management, "
                f"taxes, equity compensation, investments, retirement forecasting, or estate planning. "
                f"If the user's question is unrelated to finance, politely refuse to answer and remind them that you "
                f"exclusively assist with financial planning for {context.get('family_name', 'their household')}."
            )
            if voice_mode:
                system_instruction = f"{system_instruction}{VOICE_ADVISOR_SYSTEM_INSTRUCTION}"

            history_block = ""
            if normalized_turns:
                lines = [
                    f"{'User' if t.get('role') == 'user' else 'Advisor'}: {(t.get('parts') or [{}])[0].get('text', '')}"
                    for t in normalized_turns if (t.get("parts") or [{}])[0].get("text")
                ]
                if lines:
                    history_block = "\n=== RECENT CONVERSATION HISTORY ===\n" + "\n\n".join(lines) + "\n"

            fiduciary_prompt = f"{system_instruction}{history_block}\n\nUser Question: {user_message}"
            if model_tier:
                resolved = resolve_model_tier(model_tier)
                primary_model = resolved["primary_model"]
                fallback_models = resolved["fallback_models"]
            else:
                primary_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
                fallback_models = ["gemini-3.1-flash-lite", "gemini-3.7-flash"]
            response = effective_generate_fn(
                prompt=fiduciary_prompt, tools=tools, api_key=gemini_key,
                primary_model=primary_model, fallback_models=fallback_models,
                temperature=0.1, system_instruction=system_instruction,
            )
            if response and getattr(response, "text", ""):
                reply_text = response.text
                resp_model = getattr(response, "model_used", None)
                active_model = resp_model if isinstance(resp_model, str) and resp_model else primary_model
                logger.info("AI Advisor generated response using tool calling via Gemini.")
        except Exception as e:
            last_model_error = str(e)
            logger.warning("Gemini tool-calling generation failed (%s); falling back to fiduciary rules engine.", e)

    is_fallback = False
    fallback_reason = None
    if not reply_text:
        is_fallback = True
        reply_text = _generate_rule_based_response(user_message, context, history=history)
        if not gemini_key:
            fallback_reason = "GEMINI_API_KEY is not set. Operating in offline fiduciary rules engine."
        elif last_model_error and any(k in last_model_error.lower() for k in ("429", "quota", "resourceexhausted", "rate", "exhausted")):
            fallback_reason = "Google AI Studio free-tier quota reached (15 RPM / 20 RPD). Temporarily answering from deterministic fiduciary engine."
        elif last_model_error and any(k in last_model_error.lower() for k in ("503", "unavailable", "high demand")):
            fallback_reason = "Gemini API temporarily unavailable due to Google Cloud demand spikes. Answering from deterministic fiduciary engine."
        else:
            fallback_reason = "Gemini API temporarily unavailable. Answering from deterministic fiduciary engine."

    voice_reply = extract_human_voice_reply(reply_text)
    if voice_mode:
        pressure_warning = check_conversation_context_pressure(normalized_turns)
        if pressure_warning and pressure_warning not in voice_reply:
            voice_reply = f"{voice_reply.rstrip()} {pressure_warning}".strip()
    reply_text = _strip_voice_reply_blocks(reply_text)

    follow_up_suggestions = _generate_follow_up_suggestions(user_message, active_tab, context)
    if family_id and target_db_path and target_db_path.exists() and conv_id and reply_text:
        try:
            db.conversations.add_message(conv_id=conv_id, family_id=family_id, role="model", content=reply_text, db_path=target_db_path)
        except Exception as e:
            logger.warning("Could not persist advisor reply turn: %s", e)

    if not is_fallback and active_model:
        try:
            from db.telemetry import record_portal_telemetry_event
            tier = config.get_household_ai_limits(family_id=family_id, db_path=target_db_path).get("tier", "shared")
            record_portal_telemetry_event(get_current_universe(), f"ai_{tier}_call", feature_key=str(active_model))
        except Exception:
            pass

    badge_info = format_model_badge(active_model or "", False) if (not is_fallback and active_model) else None
    return {
        "success": True, "status": "completed", "reply": reply_text, "voice_reply": voice_reply,
        "voice_mode": bool(voice_mode), "conversation_id": conv_id,
        "conversation_title": conv_title, "is_new_conversation": is_new_conv, "family_id": family_id,
        "family_name": context.get("family_name"), "active_tab": active_tab,
        "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"),
        "follow_up_suggestions": follow_up_suggestions, "is_fallback": is_fallback,
        "engine": "gemini" if not is_fallback else "rule_based",
        "model_used": active_model if not is_fallback else None,
        "model_badge": badge_info["badge_text"] if badge_info else None,
        "model_tier": (model_tier or "auto").lower(),
        "fallback_reason": fallback_reason,
    }


def _ensure_or_append_user_turn(
    family_id: int,
    raw_conv_id: Any,
    user_message: str,
    active_tab: str,
    created_by: str,
    target_db_path: Any,
) -> tuple[str, str, bool, TurnTrust]:
    """Resolves or creates a conversation record and appends the user turn.
    Callers may only append to conversations they created (PermissionError otherwise)."""
    conv_id = sanitize_text(str(raw_conv_id), max_length=64) if raw_conv_id and str(raw_conv_id).lower() != "new" else ""
    conv_title = ""
    is_new = False
    prior_trust = TurnTrust.CLEAN
    if family_id and target_db_path.exists():
        if conv_id:
            conv = db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=target_db_path)
            if conv:
                prior_trust = history_trust(require_access(conv))
                conv_title = conv.get("title", "")
                max_msgs = int(getattr(config, "MAX_ADVISOR_MESSAGES_PER_CONV", 200))
                if len(conv.get("messages") or []) >= max_msgs:
                    raise ValueError(f"Maximum of {max_msgs} messages per conversation reached. Please start a new conversation.")
            else:
                conv_id = ""
        if not conv_id:
            conv_id = uuid.uuid4().hex[:16]
            conv_title = _generate_conversation_title(user_message, active_tab)
            db.conversations.create_conversation(
                conv_id=conv_id, family_id=family_id, page_section=active_tab,
                title=conv_title, created_by=created_by, db_path=target_db_path,
            )
            is_new = True
        db.conversations.add_message(conv_id=conv_id, family_id=family_id, role="user", content=user_message, db_path=target_db_path)
    return conv_id, conv_title, is_new, prior_trust


def build_demo_reply_text(user_message: str) -> str:
    """The fixed demo-mode reply (Markdown); the browser asks the server to render it from the user's own message."""
    return (
        f"### 🔒 Demo Mode — No Real Answer Provided\n\n"
        f'You asked: *"{user_message}"*\n\n'
        f"> **Notice:** The AI Financial Advisor is currently operating in **Demo Mode**. To conserve API quotas, "
        f"**the AI Advisor will not provide real financial answers or execute live portfolio calculations** in this demo sandbox.\n\n"
        f"#### Why is this simulated?\n"
        f"- **API Quota Protection:** Live LLM advisory reasoning (Gemini Flash) is restricted to authenticated primary household accounts.\n"
        f"- **Simulated Persona:** This session is browsing simulated sample household data.\n\n"
        f"#### How to get real financial answers:\n"
        f"Please sign in with an authorized household account to receive real-time, live advisory guidance using your authentic family balance sheet, equity grants (RSUs + NSOs), and Investment Policy Statement."
    )


def handle_demo_chat_turn(
    family_id: int,
    user_message: str,
    active_tab: str,
    raw_demo_id: Any,
) -> tuple[Dict[str, Any], int]:
    """Handles demo-mode chat requests without consuming any Gemini API quota."""
    context = _get_family_advisor_context(family_id, active_tab=active_tab)
    reply_text = build_demo_reply_text(user_message)
    # Demo personas never write: the turn lives only in this response, no conversation rows are saved.
    raw_id = sanitize_text(str(raw_demo_id), max_length=64) if raw_demo_id and str(raw_demo_id).lower() != "new" else ""
    demo_is_new = not raw_id
    demo_conv_id = raw_id or uuid.uuid4().hex[:16]
    demo_conv_title = _generate_conversation_title(user_message, active_tab) if demo_is_new else ""

    return {
        "success": True, "demo_mode": True, "reply": reply_text, "conversation_id": demo_conv_id,
        "conversation_title": demo_conv_title, "is_new_conversation": demo_is_new, "family_id": family_id,
        "family_name": context.get("family_name", "Demo Household"), "active_tab": active_tab,
        "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"), "follow_up_suggestions": [],
    }, 200


def prepare_and_dispatch_chat(
    family_id: int,
    data: Dict[str, Any],
    user_message: str,
    active_tab: str,
    generate_fn: Callable[..., Any],
) -> tuple[Dict[str, Any], int]:
    """Prepares conversation persistence and dispatches either synchronous or background chat execution."""
    target_db_path = DB_PATH.resolve()
    conv_id, conv_title, is_new_conv = "", "", False
    prior_trust = TurnTrust.CLEAN
    try:
        caller = caller_identity()
    except PermissionError as pe:
        return {"success": False, "error": str(pe)}, 403
    raw_conv_id = data.get("conversation_id")
    if detect_voice_lifecycle_intent(user_message):
        conv_id = sanitize_text(str(raw_conv_id), max_length=64) if raw_conv_id and str(raw_conv_id).lower() != "new" else ""
        if conv_id and family_id and target_db_path.exists():
            try:
                existing = db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=target_db_path)
                if existing:
                    prior_trust = history_trust(require_access(existing))
                    conv_title = existing.get("title", "")
                else:
                    conv_id = ""
            except PermissionError as pe:
                return {"success": False, "error": str(pe)}, 403
            except Exception:
                conv_id = ""
    else:
        try:
            conv_id, conv_title, is_new_conv, prior_trust = _ensure_or_append_user_turn(
                family_id, raw_conv_id, user_message, active_tab, caller, target_db_path,
            )
        except PermissionError as pe:
            return {"success": False, "error": str(pe)}, 403
        except ValueError as ve:
            return {"success": False, "error": str(ve)}, 400
        except Exception as e:
            logger.warning("Could not persist advisor conversation turn: %s", e)

    history = data.get("history")
    voice_mode = bool(data.get("voice_mode"))
    model_tier = sanitize_text(str(data.get("model_tier") or ""), max_length=32).lower() or session.get("preferred_model_tier") or "lite"
    if model_tier in ("lite", "flash", "pro", "auto"):
        session["preferred_model_tier"] = model_tier
    if background_jobs.should_run_synchronously(data):
        result = execute_advisor_generation(
            family_id=family_id, target_db_path=target_db_path, conv_id=conv_id, conv_title=conv_title,
            is_new_conv=is_new_conv, user_message=user_message, active_tab=active_tab, history=history,
            generate_fn=generate_fn, model_tier=model_tier, voice_mode=voice_mode, caller=caller, prior_trust=prior_trust,
        )
        return result, 200

    job_id = background_jobs.submit_job(
        lambda: execute_advisor_generation(
            family_id=family_id, target_db_path=target_db_path, conv_id=conv_id, conv_title=conv_title,
            is_new_conv=is_new_conv, user_message=user_message, active_tab=active_tab, history=history,
            generate_fn=generate_fn, model_tier=model_tier, voice_mode=voice_mode, caller=caller, prior_trust=prior_trust,
        ),
        family_id=family_id, universe=get_current_universe(), job_type="ai_advisor_chat",
        initial_meta={"conversation_id": conv_id, "conversation_title": conv_title, "is_new_conversation": is_new_conv, "active_tab": active_tab},
    )
    return {
        "success": True, "status": "processing", "job_id": job_id, "conversation_id": conv_id,
        "conversation_title": conv_title, "is_new_conversation": is_new_conv, "family_id": family_id, "active_tab": active_tab,
    }, 200


def build_advisor_context_response(family_id: int, active_tab: str) -> Dict[str, Any]:
    """Builds the JSON payload for GET /api/ai-advisor/context across all tabs."""
    context = _get_family_advisor_context(family_id, active_tab=active_tab)
    inv_pol = context.get("investment_policy", {})
    if is_advisor_demo_session():
        return {
            "success": True, "demo_mode": True, "family_id": family_id, "family_name": context.get("family_name"),
            "active_tab": active_tab, "policy_anchor": inv_pol.get("anchor_preset"),
            "drift_tolerance": inv_pol.get("drift_tolerance"), "deviations_rationale": inv_pol.get("deviations_rationale"),
            "suggestions": [
                "What is our investment policy anchor?",
                "What is the difference between RSUs and NSOs?",
                "How does multi-state tax arbitrage work?",
                "Are we on track for long-term solvency?",
            ],
            "notice": "Demo Mode Active: The AI Advisor will not provide real financial answers in this sandbox to protect API quotas.",
        }

    return {
        "success": True, "demo_mode": False, "family_id": family_id, "family_name": context.get("family_name"),
        "active_tab": active_tab, "policy_anchor": inv_pol.get("anchor_preset"),
        "drift_tolerance": inv_pol.get("drift_tolerance"), "deviations_rationale": inv_pol.get("deviations_rationale"),
        "suggestions": get_initial_tab_suggestions(active_tab, context),
        "ai_limits": config.get_household_ai_limits(family_id=family_id, db_path=DB_PATH),
        "preferred_model_tier": session.get("preferred_model_tier", "lite"),
    }
