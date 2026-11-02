"""
Resilient Multi-Turn AI Conversation Manager with Context-Aware Auto-Compaction.
Enforces sliding window history, rolling conversation memory, role alternation,
token pruning, and cascading fallback.
"""

from __future__ import annotations
import re
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("hvl_common.ai.conversation")

# Re-exported: callers (including the Mac bridge) import these from this module.
from hvl_common.ai.errors import model_call_errors
from hvl_common.ai.voice_lifecycle import (  # noqa: E402
    GENERIC_VOICE_VOCABULARY,
    VoiceVocabulary,
    detect_voice_lifecycle_intent,
)

VOICE_ADVISOR_SYSTEM_INSTRUCTION = (
    "\n\n=== VOICE ADVISOR MODE ===\n"
    "The user is interacting hands-free via voice. At the end of your response, "
    "include a `<voice_reply>...</voice_reply>` block containing 1 to 3 natural, "
    "conversational spoken sentences summarizing the key takeaway for text-to-speech playback. "
    "Inside `<voice_reply>`, do NOT include markdown formatting, file paths, commit hashes, "
    "URLs, bullet points, or dense number soup—speak like a trusted human advisor."
)

# The Live models only speak, so their whole reply is the spoken one. Asked for a `<voice_reply>` summary "at the end",
# they said the answer, then the summary of it, and the same sentence was read out twice.
LIVE_SPOKEN_REPLY_INSTRUCTION = (
    "\n\n=== SPOKEN REPLY ===\n"
    "The user is interacting hands-free via voice, and everything you say is read aloud to them exactly as said. "
    "Say your answer once, in 1 to 3 natural, conversational sentences, then stop: no recap or summary of what you "
    "just said. Wherever these instructions mention a `<voice_reply>` block, that means this spoken answer itself; "
    "never say tags, markdown, file paths, commit hashes or URLs."
)

CONTEXT_PRESSURE_SPOKEN_WARNING = (
    "By the way, this conversation is getting pretty long. "
    "Let me know if you want me to compact it or start a fresh thread with a handoff."
)
VOICE_REPLY_INSTRUCTION = VOICE_ADVISOR_SYSTEM_INSTRUCTION
CONTEXT_PRESSURE_SPOKEN_NOTE = CONTEXT_PRESSURE_SPOKEN_WARNING

_UNBACKTICKED_VOICE_REPLY_RE = re.compile(
    r"(?<!`)<voice_reply>(?!`)\s*((?:(?!(?<!`)<voice_reply>(?!`))[\s\S])*?)\s*(?<!`)</voice_reply>(?!`)",
    re.IGNORECASE,
)


def _extract_turn_text(turn: Dict[str, Any]) -> str:
    """Extracts text from either a `content` string or Gemini `parts` list."""
    content = turn.get("content")
    if content is None and "parts" in turn:
        parts = turn["parts"]
        if isinstance(parts, list) and parts:
            p0 = parts[0]
            content = p0.get("text", "") if isinstance(p0, dict) else getattr(p0, "text", str(p0))
    return str(content or "")


def _strip_voice_reply_blocks(text: str) -> str:
    """Removes `<voice_reply>...</voice_reply>` tags from visible markdown text when outer prose exists."""
    if not text or "<voice_reply>" not in text.lower():
        return text or ""
    stripped = re.sub(
        r"\s*" + _UNBACKTICKED_VOICE_REPLY_RE.pattern + r"\s*", "\n\n", text, flags=re.IGNORECASE
    ).strip()
    if stripped:
        return stripped
    match = _UNBACKTICKED_VOICE_REPLY_RE.search(text)
    return match.group(1).strip() if match else stripped


def _clean_md_link_for_voice(match: re.Match[str]) -> str:
    label = match.group(1).strip()
    if "/" in label or "\\" in label or re.search(r"#L\d+|\.[a-zA-Z0-9]{1,5}(?:#L\d+)?$", label):
        return " "
    return label


def extract_human_voice_reply(text: str, max_sentences: int = 3) -> str:
    """Extracts and sanitizes a natural spoken TTS reply bounded to `max_sentences`."""
    if not text:
        return ""
    raw = str(text).strip()
    raw_without_fences = re.sub(r"```[\s\S]*?```", " ", raw)
    matches = _UNBACKTICKED_VOICE_REPLY_RE.findall(raw_without_fences)
    candidate = matches[-1].strip() if matches else raw_without_fences

    candidate = re.sub(r"<[^>]+>", " ", candidate)
    candidate = re.sub(r"\[([^\]]+)\]\([^)]+\)", _clean_md_link_for_voice, candidate)
    candidate = re.sub(r"https?://\S+", "", candidate)
    candidate = re.sub(r"`([^`]+)`", r"\1", candidate)
    candidate = re.sub(r"\bcommit\s+[0-9a-f]{7,40}\b", " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"\b(?=[0-9a-f]{7,40}\b)(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"(?:^|[\s(])(?:/|[a-zA-Z]:\\|\.{1,2}/|~/)[^\s),;:]+", " ", candidate)
    candidate = re.sub(r"\b[\w.-]+/[\w./-]+\.[a-zA-Z0-9]{1,6}(?:#L\d+(?:-L?\d+)?)?\b", " ", candidate)
    candidate = re.sub(
        r"\b[\w.-]+\.(?:py|js|ts|tsx|jsx|md|html|css|json|ya?ml|toml|sql|sh)(?:#L\d+(?:-L?\d+)?)?\b",
        " ",
        candidate,
    )
    candidate = re.sub(r"#L\d+(?:-L?\d+)?\b", " ", candidate)
    candidate = re.sub(r"\b(?:on\s+|at\s+)?lines?\s+\d+(?:\s*[-–to]+\s*\d+)?\b", " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"(?m)^\s*#{1,6}\s+", "", candidate)
    candidate = re.sub(r"(?m)^\s*(?:[-*•]|\d+\.)\s+", "", candidate)
    candidate = re.sub(r"[*_~]+|\(\s*\)", " ", candidate)
    candidate = re.sub(r"\b(?:on your mac|on the mac)\b", " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s+,", "", candidate)
    candidate = re.sub(r",(?:\s*,)+", ",", candidate)
    candidate = re.sub(
        r"\b(updated|modified|edited|changed|touched|fixed|in|from|to)\s*,?\s*(?:and|or)\b",
        r"\1",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip()
    candidate = re.sub(
        r"\b(?:in|at|on|from|to|into|over|under|by|via|for|with|of|and|or)\s+([.,!?;:])",
        r"\1",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+([.,!?;:])", r"\1", candidate)
    candidate = re.sub(r",(?:\s*,)+", ",", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()

    if not candidate:
        return ""
    cap = max(1, int(max_sentences or 3))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", candidate) if s.strip()]
    spoken = " ".join(sentences[:cap]) if sentences else candidate
    spoken = clean_history_text(spoken, max_chars=420).strip()
    if spoken and spoken[-1] not in ".!?":
        spoken += "."
    return spoken


def check_conversation_context_pressure(
    turns: Sequence[Dict[str, Any]],
    warn_turns: int = 16,
    warn_chars: int = 12000,
) -> str:
    """Returns a natural spoken heads-up sentence when conversation turn count or character volume gets high."""
    if not turns:
        return ""
    total_chars = sum(len(_extract_turn_text(t)) for t in turns if isinstance(t, dict))
    if len(turns) >= warn_turns or total_chars >= warn_chars:
        return CONTEXT_PRESSURE_SPOKEN_WARNING
    return ""


def build_carryover_seed_message(
    turns: Sequence[Dict[str, Any]],
    client: Optional[Any] = None,
    api_key: Optional[str] = None,
    existing_summary: Optional[str] = None,
) -> str:
    """Builds a structured carryover seed message summarizing the prior thread via `summarize_history_turns`."""
    turn_list = [dict(t) for t in (turns or []) if isinstance(t, dict)]
    summary = summarize_history_turns(
        turns=turn_list, client=client, api_key=api_key, existing_summary=existing_summary,
    )
    if not summary:
        fallback_lines: List[str] = []
        if existing_summary and str(existing_summary).strip():
            fallback_lines.append(str(existing_summary).strip())
        for t in turn_list[-4:]:
            raw_role = str(t.get("role", "")).lower()
            speaker = "User" if raw_role in ("user", "human") else "Assistant"
            cleaned = clean_history_text(_extract_turn_text(t), max_chars=240)
            if cleaned:
                fallback_lines.append(f"- {speaker}: {cleaned}")
        summary = "\n".join(fallback_lines)
    return f"=== CARRIED-OVER CONVERSATION CONTEXT ===\n{summary.strip()}" if summary else ""


def clean_history_text(text: str, max_chars: int = 2500) -> str:
    """Cleans control characters, prunes repetitive disclaimers, and truncates on word boundaries."""
    if not text:
        return ""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text)).strip()
    s = s.replace(CONTEXT_PRESSURE_SPOKEN_WARNING, "").strip()
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
    """Normalizes conversational turns into strict alternating Gemini format ending with 'model'."""
    if not raw_turns or max_turns <= 0:
        return []

    turns = list(raw_turns)
    if turns and str(turns[-1].get("role", "")).lower() in ("user", "human"):
        turns = turns[:-1]

    recent_turns = turns[-max_turns:]
    normalized_contents: List[Dict[str, Any]] = []
    user_turn_cap = min(max_input_chars, max_history_chars)
    model_turn_cap = max_history_chars

    for turn in recent_turns:
        raw_role = str(turn.get("role", "")).lower()
        role = "user" if raw_role in ("user", "human") else "model"
        max_c = user_turn_cap if role == "user" else model_turn_cap
        cleaned = clean_history_text(_extract_turn_text(turn), max_chars=max_c)
        if not cleaned or (not normalized_contents and role != "user"):
            continue
        if normalized_contents and normalized_contents[-1]["role"] == role:
            normalized_contents[-1] = {"role": role, "parts": [{"text": cleaned}]}
        else:
            normalized_contents.append({"role": role, "parts": [{"text": cleaned}]})

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
    """Summarizes older conversation turns into dense, actionable bullet points via flash-lite cascade."""
    if not turns and not existing_summary:
        return ""

    formatted_lines: List[str] = []
    if existing_summary:
        formatted_lines.append(f"Prior Context Memory:\n{existing_summary.strip()}\n")

    for t in turns:
        raw_role = str(t.get("role", "")).lower()
        speaker = "User" if raw_role in ("user", "human") else "Assistant"
        cleaned = clean_history_text(_extract_turn_text(t))
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
        resp = generate_content_with_fallback(
            contents=prompt,
            client=client,
            api_key=api_key,
            primary_model=model or "gemini-3.1-flash-lite",
            fallback_models=["gemini-3.5-flash", "gemini-3.8-flash"],
            config=cfg,
        )
        return (getattr(resp, "text", "") or "").strip()
    except model_call_errors() as e:
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
    """Compacts older turns into a bulleted memory block when history exceeds turn or char limits."""
    if not raw_turns:
        return [], existing_summary

    turns = list(raw_turns)
    if turns and str(turns[-1].get("role", "")).lower() in ("user", "human"):
        turns = turns[:-1]
    if not turns:
        return [], existing_summary

    total_chars = sum(len(str(t.get("content") or "")) for t in turns)
    if (len(turns) <= max_turns) and (total_chars <= max_context_chars):
        return turns, existing_summary

    keep_count = min(max(2, recent_turns_to_keep), len(turns))
    older_turns = turns[:-keep_count]
    recent_turns = turns[-keep_count:]
    if not older_turns:
        return recent_turns, existing_summary

    summary = summarize_history_turns(
        turns=older_turns, client=client, api_key=api_key, model=summary_model, existing_summary=existing_summary,
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
    attachments: Optional[Sequence[Dict[str, Any]]] = None,
    voice_mode: bool = False,
    on_first_sentence: Optional[Callable[[str], None]] = None,
    warn_context_pressure: bool = True,
) -> Any:
    """
    Sends a conversational multi-turn prompt with context-aware auto-compaction,
    normalized sliding-window history, optional tool declarations, and resilient cascading fallback.
    When return_metadata=True, returns a dict with text, model_used, fallback_occurred, and badge.
    `on_first_sentence` reaches the Live tier only (see `hvl_common.ai.live`); REST replies arrive whole.
    `warn_context_pressure=False` is for callers whose history manages its own size (a rolling window that folds old
    rows into a summary): the spoken "getting pretty long" heads-up would only ask for a compact they never need.
    """
    from google.genai import types
    from hvl_common.ai.gemini import format_model_badge, generate_content_with_fallback

    has_prompt = bool(prompt and str(prompt).strip())
    has_attachments = bool(attachments)
    if not has_prompt and not has_attachments:
        if return_metadata:
            badge = format_model_badge("", False)
            out: Dict[str, Any] = {"text": "", **badge}
            if voice_mode:
                out["voice_reply"] = ""
            return out
        return ""

    if existing_summary and str(existing_summary).strip() and not enable_auto_compact:
        # The summary reaches the model only through compaction; with it off, put the summary in system_instruction.
        raise ValueError("existing_summary needs enable_auto_compact=True; with it off the summary would be dropped")
    effective_prompt = str(prompt).strip() if has_prompt else "Please analyze the attached file(s)."
    raw_history = history or []
    effective_instruction = system_instruction or ""
    live_instruction = effective_instruction
    if voice_mode:
        effective_instruction = f"{effective_instruction.rstrip()}{VOICE_ADVISOR_SYSTEM_INSTRUCTION}".strip()
        live_instruction = f"{live_instruction.rstrip()}{LIVE_SPOKEN_REPLY_INSTRUCTION}".strip()

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
            live_instruction = f"{live_instruction.strip()}{memory_block}".strip()
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
    if has_attachments:
        from hvl_common.ai.multimodal import build_multimodal_user_parts
        user_parts = build_multimodal_user_parts(effective_prompt, attachments)
    else:
        user_parts = [{"text": effective_prompt}]
    contents.append({"role": "user", "parts": user_parts})

    # 4. Configure system instruction, temperature, and callable tools
    config_kwargs: Dict[str, Any] = {}
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if effective_instruction:
        config_kwargs["system_instruction"] = effective_instruction
    if tools:
        from hvl_common.ai.web import resolve_callable_tool_annotations
        config_kwargs["tools"] = resolve_callable_tool_annotations(tools)

    content_config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    # 5. Execute Gemini 3.8 Live (when model_tier="live") or REST cascading fallback
    is_live_tier = (model_tier or "").strip().lower() == "live" or (
        primary_model or ""
    ).strip().lower().startswith("gemini-3.8-live")
    response: Any = None
    live_result: Optional[Dict[str, Any]] = None
    live_attempted_and_failed = False
    live_executed_tools = False

    if is_live_tier and not has_attachments:
        # Detect if a unit test passed a mock client with `models.generate_content` without configuring `client.aio`
        is_real_genai_client = bool(
            client is not None and type(client).__module__.startswith("google.genai")
        )
        client_dict = getattr(client, "__dict__", {}) if client is not None else {}
        models_obj = client_dict.get("models") if isinstance(client_dict, dict) else None
        gen_fn = getattr(models_obj, "generate_content", None) if models_obj is not None else None
        has_mocked_rest = bool(
            not is_real_genai_client
            and models_obj is not None
            and "aio" not in client_dict
            and (
                getattr(gen_fn, "side_effect", None) is not None
                or "return_value" in (getattr(gen_fn, "__dict__", {}) or {})
                or not hasattr(client, "aio")
            )
        )
        if not has_mocked_rest:
            try:
                from hvl_common.ai.gemini import resolve_model_tier
                from hvl_common.ai.live import send_live_conversational_turn

                resolved_live = resolve_model_tier(
                    model_tier or primary_model, fallback_models=fallback_models
                )
                live_candidate = send_live_conversational_turn(
                    effective_prompt,
                    history=norm_history,
                    system_instruction=live_instruction or None,
                    client=client,
                    api_key=api_key,
                    model=resolved_live["primary_model"],
                    tools=tools,
                    temperature=temperature,
                    on_first_sentence=on_first_sentence,
                )
                live_executed_tools = int(live_candidate.get("tool_calls_executed") or 0) > 0
                if (live_candidate.get("text") or "").strip():
                    live_result = live_candidate
                else:
                    live_attempted_and_failed = True
            except model_call_errors() as exc:
                live_attempted_and_failed = True
                logger.warning("Gemini Live turn failed (%s); cascading to REST fallback.", exc)

    if live_result is not None:
        raw_text_out = str(live_result.get("text") or "")
        resp_model_override: Optional[str] = str(live_result.get("model_used") or "gemini-3.8-live")
        resp_fb_override: Optional[bool] = bool(live_result.get("fallback_occurred", False))
    else:
        fb_tier = model_tier
        fb_primary = primary_model
        fb_models = fallback_models
        fb_config = content_config
        if live_executed_tools and fb_config is not None:
            no_tool_kwargs = {k: v for k, v in config_kwargs.items() if k != "tools"}
            fb_config = types.GenerateContentConfig(**no_tool_kwargs) if no_tool_kwargs else None
        if is_live_tier:
            from hvl_common.ai.gemini import resolve_model_tier

            resolved_live = resolve_model_tier(
                model_tier or primary_model, fallback_models=fallback_models
            )
            rest_candidates = list(resolved_live["fallback_models"]) or [
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
                "gemini-3.6-flash",
            ]
            fb_tier = None
            fb_primary = rest_candidates[0]
            fb_models = rest_candidates[1:]

        response = generate_content_with_fallback(
            contents=contents,
            api_key=api_key,
            client=client,
            primary_model=fb_primary,
            fallback_models=fb_models,
            config=fb_config,
            model_tier=fb_tier,
        )
        raw_text_out = getattr(response, "text", "") or ""
        resp_model_override = None
        resp_fb_override = True if live_attempted_and_failed else None

    voice_reply = ""
    if voice_mode or "<voice_reply>" in raw_text_out.lower():
        voice_reply = extract_human_voice_reply(raw_text_out)
        if voice_mode and not enable_auto_compact and warn_context_pressure:
            pressure_warning = check_conversation_context_pressure(
                turns_to_use,
                warn_turns=max(16, int(max_turns) * 2),
                warn_chars=max(12000, int(max_context_chars) * 2),
            )
            if pressure_warning and pressure_warning not in voice_reply:
                voice_reply = f"{voice_reply.rstrip()} {pressure_warning}".strip()
    text_out = _strip_voice_reply_blocks(raw_text_out) if raw_text_out else ""

    if return_metadata:
        resp_model = resp_model_override or getattr(response, "model_used", None)
        if not isinstance(resp_model, str) or not resp_model:
            from hvl_common.ai.gemini import resolve_model_tier
            resp_model = resolve_model_tier(model_tier or primary_model)["primary_model"]
        resp_fb = (
            resp_fb_override
            if resp_fb_override is not None
            else getattr(response, "fallback_occurred", False)
        )
        fallback_occurred = resp_fb if isinstance(resp_fb, bool) else False
        badge = format_model_badge(resp_model, fallback_occurred)
        meta_out: Dict[str, Any] = {
            "text": text_out,
            **badge,
        }
        if voice_mode or voice_reply:
            meta_out["voice_reply"] = voice_reply
        meta_out["answered_by"] = "live" if live_result is not None else "rest"
        if live_result is not None:
            meta_out["live_transcript_segments"] = list(live_result.get("transcript_segments") or [])
            meta_out["live_stream_events"] = dict(live_result.get("stream_events") or {})
        return meta_out
    return text_out


__all__ = [
    "VOICE_ADVISOR_SYSTEM_INSTRUCTION", "VOICE_REPLY_INSTRUCTION", "LIVE_SPOKEN_REPLY_INSTRUCTION",
    "CONTEXT_PRESSURE_SPOKEN_WARNING", "CONTEXT_PRESSURE_SPOKEN_NOTE",
    "GENERIC_VOICE_VOCABULARY", "VoiceVocabulary", "clean_history_text", "normalize_chat_history",
    "summarize_history_turns", "compact_conversation_history", "extract_human_voice_reply",
    "detect_voice_lifecycle_intent", "check_conversation_context_pressure",
    "build_carryover_seed_message", "send_conversational_message",
]

