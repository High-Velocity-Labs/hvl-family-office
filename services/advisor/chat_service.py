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

import background_jobs
import config
import db
from hvl_common.ai import generate_content_with_tools as _default_generate_with_tools
from routes.helpers import DB_PATH, get_current_universe, sanitize_text
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
from services.advisor.tools_tabs import ALL_ADVISOR_TOOLS

logger = logging.getLogger(__name__)


def is_advisor_demo_session() -> bool:
    """Returns True if the active session is a demo session or viewer-restricted."""
    if session.get("is_sandbox"):
        return False
    if session.get("is_demo") or session.get("role") == "viewer":
        return True
    return bool(get_current_universe() == "beta" and session.get("role") != "admin")


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
) -> Dict[str, Any]:
    """Executes Gemini tool-calling generation (or deterministic fallback) with all 14 household tools."""
    if context is None:
        context = _get_family_advisor_context(family_id, active_tab=active_tab)

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

    if gemini_key:
        try:
            tools = list(ALL_ADVISOR_TOOLS)
            tool_names_str = ", ".join(t.__name__ for t in tools)
            system_context = _format_fiduciary_system_prompt(context)
            system_instruction = (
                f"{system_context}\n"
                f"Use your available tools ({tool_names_str}) to query the household's actual accounts, balance sheet, "
                f"holdings/IPS drift, equity grants (NSOs + RSUs), multi-scenario longevity forecasts, W-2 compensation & "
                f"Safe Harbor tax withholding, IRS transcripts, multi-state tax arbitrage, 529 education plans, "
                f"philanthropy/DAF grants, family gifting (Form 709), estate taxes, and dynamic what-if simulations.\n"
                f"IMPORTANT GUARDRAIL: You must ONLY answer questions related to personal finance, wealth management, "
                f"taxes, equity compensation, investments, retirement forecasting, or estate planning. "
                f"If the user's question is unrelated to finance, politely refuse to answer and remind them that you "
                f"exclusively assist with financial planning for {context.get('family_name', 'their household')}."
            )

            normalized_turns = _get_conversation_history_for_gemini(
                conv_id=conv_id, family_id=family_id, client_history=history if isinstance(history, list) else None,
            )
            history_block = ""
            if normalized_turns:
                lines = [
                    f"{'User' if t.get('role') == 'user' else 'Advisor'}: {(t.get('parts') or [{}])[0].get('text', '')}"
                    for t in normalized_turns if (t.get("parts") or [{}])[0].get("text")
                ]
                if lines:
                    history_block = "\n=== RECENT CONVERSATION HISTORY ===\n" + "\n\n".join(lines) + "\n"

            fiduciary_prompt = f"{system_instruction}{history_block}\n\nUser Question: {user_message}"
            primary_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
            response = effective_generate_fn(
                prompt=fiduciary_prompt, tools=tools, api_key=gemini_key,
                primary_model=primary_model, fallback_models=["gemini-3.1-flash-lite", "gemini-3.7-flash"],
                temperature=0.1, system_instruction=system_instruction,
            )
            if response and getattr(response, "text", ""):
                reply_text = response.text
                active_model = primary_model
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

    return {
        "success": True, "status": "completed", "reply": reply_text, "conversation_id": conv_id,
        "conversation_title": conv_title, "is_new_conversation": is_new_conv, "family_id": family_id,
        "family_name": context.get("family_name"), "active_tab": active_tab,
        "policy_anchor": context.get("investment_policy", {}).get("anchor_preset"),
        "follow_up_suggestions": follow_up_suggestions, "is_fallback": is_fallback,
        "engine": "gemini" if not is_fallback else "rule_based",
        "model_used": active_model if not is_fallback else None, "fallback_reason": fallback_reason,
    }


def _ensure_or_append_user_turn(
    family_id: int,
    raw_conv_id: Any,
    user_message: str,
    active_tab: str,
    created_by: str,
    target_db_path: Any,
) -> tuple[str, str, bool]:
    """Resolves or creates a conversation record and appends the user turn."""
    conv_id = sanitize_text(str(raw_conv_id), max_length=64) if raw_conv_id and str(raw_conv_id).lower() != "new" else ""
    conv_title = ""
    is_new = False
    if family_id and target_db_path.exists():
        if conv_id:
            conv = db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=target_db_path)
            if conv:
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
    return conv_id, conv_title, is_new


def handle_demo_chat_turn(
    family_id: int,
    user_message: str,
    active_tab: str,
    raw_demo_id: Any,
) -> tuple[Dict[str, Any], int]:
    """Handles demo-mode chat requests without consuming any Gemini API quota."""
    context = _get_family_advisor_context(family_id, active_tab=active_tab)
    reply_text = (
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
    demo_conv_id, demo_conv_title, demo_is_new = "", "", False
    try:
        demo_conv_id, demo_conv_title, demo_is_new = _ensure_or_append_user_turn(
            family_id, raw_demo_id, user_message, active_tab, "Demo Visitor", DB_PATH,
        )
        if demo_conv_id and DB_PATH.exists():
            try:
                db.conversations.add_message(conv_id=demo_conv_id, family_id=family_id, role="model", content=reply_text, db_path=DB_PATH)
            except ValueError:
                pass
    except ValueError as ve:
        return {"success": False, "error": str(ve)}, 400
    except Exception as e:
        logger.warning("Could not persist demo advisor conversation: %s", e)

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
    user_name = session.get("user") or session.get("email") or "Family Member"
    try:
        conv_id, conv_title, is_new_conv = _ensure_or_append_user_turn(
            family_id, data.get("conversation_id"), user_message, active_tab, user_name, target_db_path,
        )
    except ValueError as ve:
        return {"success": False, "error": str(ve)}, 400
    except Exception as e:
        logger.warning("Could not persist advisor conversation turn: %s", e)

    history = data.get("history")
    if background_jobs.should_run_synchronously(data):
        result = execute_advisor_generation(
            family_id=family_id, target_db_path=target_db_path, conv_id=conv_id, conv_title=conv_title,
            is_new_conv=is_new_conv, user_message=user_message, active_tab=active_tab, history=history, generate_fn=generate_fn,
        )
        return result, 200

    job_id = background_jobs.submit_job(
        lambda: execute_advisor_generation(
            family_id=family_id, target_db_path=target_db_path, conv_id=conv_id, conv_title=conv_title,
            is_new_conv=is_new_conv, user_message=user_message, active_tab=active_tab, history=history, generate_fn=generate_fn,
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
    }
