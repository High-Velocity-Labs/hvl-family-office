"""
Resilient Multi-Turn AI Conversation Manager with Context-Aware Auto-Compaction.
Enforces sliding window history, rolling conversation memory, role alternation,
token pruning, and cascading fallback.
"""

from __future__ import annotations
import re
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("hvl_common.ai.conversation")


def clean_history_text(text: str, max_chars: int = 2500) -> str:
    """
    Cleans and bounds conversation history turns for LLM context:
    - Strips null bytes and ASCII control characters (preserving tabs, newlines, carriage returns).
    - Prunes repetitive markdown disclaimers/footers (e.g. \\n+---\\s*\\n+\\*Disclaimer:).
    - Truncates cleanly on word boundaries if exceeding max_chars.
    """
    if not text:
        return ""
    # Strip null bytes and non-printable ASCII control chars (\x00-\x08, \x0b-\x0c, \x0e-\x1f, \x7f)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text)).strip()
    # Prune repetitive disclaimers
    s = re.split(r"(?:^|\n+)---\s*\n+\*+Disclaimer:", s, flags=re.IGNORECASE, maxsplit=1)[0].strip()
    if len(s) > max_chars:
        if s[max_chars] == " ":
            truncated = s[:max_chars].rstrip()
        else:
            truncated = s[:max_chars]
            if " " in truncated:
                truncated = truncated.rsplit(" ", 1)[0]
        s = truncated.rstrip() + "..."
    return s


def normalize_chat_history(
    raw_turns: List[Dict[str, Any]],
    max_turns: int = 8,
    max_input_chars: int = 8000,
    max_history_chars: int = 2500,
) -> List[Dict[str, Any]]:
    """
    Normalizes a list of conversational turns into strict Gemini format:
    - Enforces sliding window (latest max_turns turns).
    - Normalizes roles into 'user' | 'model' with parts: [{'text': ...}].
    - Drops trailing user message if already present so history ends with 'model'
      prior to the active user prompt.
    - Enforces strict alternation starting with 'user'.
    """
    if not raw_turns or max_turns <= 0:
        return []

    turns = list(raw_turns)
    # If the last item in raw_turns is a user message (e.g. already inserted or echoed by client),
    # exclude it from history so history ends prior to the active user prompt
    if turns and str(turns[-1].get("role", "")).lower() in ("user", "human"):
        turns = turns[:-1]

    recent_turns = turns[-max_turns:]
    normalized_contents: List[Dict[str, Any]] = []
    user_turn_cap = min(max_input_chars, max_history_chars)
    model_turn_cap = max_history_chars

    for turn in recent_turns:
        raw_role = str(turn.get("role", "")).lower()
        role = "user" if raw_role in ("user", "human") else "model"

        content = turn.get("content")
        if content is None and "parts" in turn:
            parts = turn["parts"]
            if isinstance(parts, list) and parts:
                p0 = parts[0]
                if isinstance(p0, dict):
                    content = p0.get("text", "")
                elif hasattr(p0, "text"):
                    content = p0.text
                else:
                    content = str(p0)

        max_c = user_turn_cap if role == "user" else model_turn_cap
        cleaned = clean_history_text(str(content or ""), max_chars=max_c)
        if not cleaned:
            continue

        # History must start with 'user'
        if not normalized_contents and role != "user":
            continue

        # Enforce strict alternation: if consecutive same role, update to latest
        if normalized_contents and normalized_contents[-1]["role"] == role:
            normalized_contents[-1] = {"role": role, "parts": [{"text": cleaned}]}
        else:
            normalized_contents.append({"role": role, "parts": [{"text": cleaned}]})

    # The last turn in history before our new user message must be 'model'
    if normalized_contents and normalized_contents[-1]["role"] == "user":
        normalized_contents.pop()

    return normalized_contents


def summarize_history_turns(
    turns: List[Dict[str, Any]],
    client: Optional[Any] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    existing_summary: Optional[str] = None,
) -> str:
    """
    Summarizes older conversation turns into dense, actionable bullet points.
    Preserves user constraints, preferences, key decisions, and discussed entities.
    Executes via fast flash-lite cascade with graceful fallback on failure.
    """
    if not turns and not existing_summary:
        return ""

    formatted_lines: List[str] = []
    if existing_summary:
        formatted_lines.append(f"Prior Context Memory:\n{existing_summary.strip()}\n")

    for t in turns:
        raw_role = str(t.get("role", "")).lower()
        speaker = "User" if raw_role in ("user", "human") else "Assistant"
        content = t.get("content")
        if content is None and "parts" in t:
            parts = t["parts"]
            if isinstance(parts, list) and parts:
                p0 = parts[0]
                content = p0.get("text", "") if isinstance(p0, dict) else (getattr(p0, "text", str(p0)))
        cleaned = clean_history_text(str(content or ""))
        if cleaned:
            formatted_lines.append(f"{speaker}: {cleaned}")

    if not formatted_lines:
        return ""

    transcript = "\n".join(formatted_lines)
    prompt = (
        "Summarize the following earlier conversation history into 2 to 4 dense, concise bullet points.\n"
        "Focus strictly on: user preferences/constraints, key strategic decisions made, and specific entities discussed.\n"
        "Do not include filler or pleasantries.\n\n"
        f"Conversation History:\n{transcript}"
    )

    try:
        from google.genai import types
        from hvl_common.ai.gemini import generate_content_with_fallback

        cfg = types.GenerateContentConfig(
            temperature=0.0,
            system_instruction="You are an expert conversation memory summarizer.",
        )
        primary = model or "gemini-3.1-flash-lite"
        resp = generate_content_with_fallback(
            contents=prompt,
            client=client,
            api_key=api_key,
            primary_model=primary,
            fallback_models=["gemini-3.5-flash", "gemini-3.8-flash"],
            config=cfg,
        )
        return (getattr(resp, "text", "") or "").strip()
    except Exception as e:
        logger.warning("Conversation auto-compaction failed (%s); falling back to sliding window.", e)
        return ""


def compact_conversation_history(
    raw_turns: List[Dict[str, Any]],
    max_context_chars: int = 6000,
    max_turns: int = 8,
    recent_turns_to_keep: int = 4,
    client: Optional[Any] = None,
    api_key: Optional[str] = None,
    summary_model: Optional[str] = None,
    existing_summary: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Context-aware conversation compaction:
    Evaluates history volume by total character count and turn length.
    If history exceeds max_context_chars or max_turns, older turns are compacted
    into a concise bulleted memory block, preserving the most recent turns verbatim.
    """
    if not raw_turns:
        return [], existing_summary

    turns = list(raw_turns)
    if turns and str(turns[-1].get("role", "")).lower() in ("user", "human"):
        turns = turns[:-1]

    if not turns:
        return [], existing_summary

    total_chars = sum(len(str(t.get("content") or "")) for t in turns)
    needs_compaction = (len(turns) > max_turns) or (total_chars > max_context_chars)

    if not needs_compaction:
        return turns, existing_summary

    # Ensure recent_turns_to_keep is within bounds
    keep_count = min(max(2, recent_turns_to_keep), len(turns))
    older_turns = turns[:-keep_count]
    recent_turns = turns[-keep_count:]

    if not older_turns:
        return recent_turns, existing_summary

    summary = summarize_history_turns(
        turns=older_turns,
        client=client,
        api_key=api_key,
        model=summary_model,
        existing_summary=existing_summary,
    )

    return recent_turns, (summary or existing_summary)


def send_conversational_message(
    prompt: str,
    history: Optional[List[Dict[str, Any]]] = None,
    system_instruction: Optional[str] = None,
    client: Optional[Any] = None,
    api_key: Optional[str] = None,
    primary_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
    max_turns: int = 8,
    temperature: float = 0.1,
    max_input_chars: int = 8000,
    max_history_chars: int = 2500,
    enable_auto_compact: bool = True,
    max_context_chars: int = 6000,
    recent_turns_to_keep: int = 4,
    existing_summary: Optional[str] = None,
    tools: Optional[Sequence[Any]] = None,
    model_tier: Optional[str] = None,
    return_metadata: bool = False,
) -> Any:
    """
    Sends a conversational multi-turn prompt with context-aware auto-compaction,
    normalized sliding-window history, optional tool declarations, and resilient cascading fallback.
    When return_metadata=True, returns a dict with text, model_used, fallback_occurred, and badge.
    """
    from google.genai import types
    from hvl_common.ai.gemini import format_model_badge, generate_content_with_fallback

    if not prompt or not str(prompt).strip():
        if return_metadata:
            badge = format_model_badge("", False)
            return {"text": "", **badge}
        return ""

    raw_history = history or []
    effective_instruction = system_instruction or ""

    # 1. Context-aware auto-compaction of older turns
    if enable_auto_compact and raw_history:
        turns_to_use, memory_summary = compact_conversation_history(
            raw_turns=raw_history,
            max_context_chars=max_context_chars,
            max_turns=max_turns,
            recent_turns_to_keep=recent_turns_to_keep,
            client=client,
            api_key=api_key,
            existing_summary=existing_summary,
        )
        if memory_summary:
            memory_block = f"\n\n=== EARLIER CONVERSATION MEMORY ===\n{memory_summary.strip()}"
            effective_instruction = f"{effective_instruction.strip()}{memory_block}".strip()
    else:
        turns_to_use = raw_history

    # 2. Normalize sliding-window history for Gemini
    norm_history = normalize_chat_history(
        raw_turns=turns_to_use,
        max_turns=max_turns,
        max_input_chars=max_input_chars,
        max_history_chars=max_history_chars,
    )

    # 3. Assemble contents: normalized history turns + active user prompt
    contents: List[Dict[str, Any]] = list(norm_history)
    contents.append({"role": "user", "parts": [{"text": str(prompt)}]})

    # 4. Configure system instruction, temperature, and callable tools
    config_kwargs: Dict[str, Any] = {}
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if effective_instruction:
        config_kwargs["system_instruction"] = effective_instruction
    if tools:
        config_kwargs["tools"] = list(tools)

    content_config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    # 5. Execute cascading fallback
    response = generate_content_with_fallback(
        contents=contents,
        api_key=api_key,
        client=client,
        primary_model=primary_model,
        fallback_models=fallback_models,
        config=content_config,
        model_tier=model_tier,
    )
    text_out = getattr(response, "text", "") or ""
    if return_metadata:
        resp_model = getattr(response, "model_used", None)
        if not isinstance(resp_model, str) or not resp_model:
            from hvl_common.ai.gemini import resolve_model_tier
            resp_model = resolve_model_tier(model_tier or primary_model)["primary_model"]
        resp_fb = getattr(response, "fallback_occurred", False)
        fallback_occurred = resp_fb if isinstance(resp_fb, bool) else False
        badge = format_model_badge(resp_model, fallback_occurred)
        return {
            "text": text_out,
            **badge,
        }
    return text_out

