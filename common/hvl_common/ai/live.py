"""
Gemini 3.8 Live (`gemini-3.8-live`) Unlimited-RPD Session & Tool Runner.
Streams low-latency conversational turns over WebSocket with `output_audio_transcription`
enabled, executes function calls, and discards raw PCM audio bytes so
custom household TTS voices (`RyanNeural`/`Oliver`/`EmilyNeural`/`Moira`) remain canonical.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
import typing
from typing import Any, Callable, Optional, Sequence

from hvl_common.ai.errors import TOOL_INPUT_ERRORS
from hvl_common.ai.gemini import get_gemini_client
from hvl_common.ai.web import resolve_callable_tool_annotations

logger = logging.getLogger("hvl_common.ai.live")

DEFAULT_LIVE_MODEL = "gemini-3.8-live"
EXTENDED_THINKING_LIVE_MODEL = "gemini-3.8-live-extended-thinking"
TRANSCRIBE_LIVE_MODEL = "gemini-3.5-transcribe-live"

# The Live models answer only in AUDIO. The transcript is complete seconds before the audio is
# (measured 2026-10-27: a 244-character reply was fully transcribed at 3.4s, generation_complete at
# 14.8s, turn_complete at 101s), and Live sends no signal for that. So a reply counts as finished once
# its transcript has been quiet this long: briefly after a sentence end, longer mid-sentence.
TRANSCRIPT_SETTLE_SEC = 0.5
TRANSCRIPT_SETTLE_MID_SENTENCE_SEC = 1.5
_SENTENCE_END = (".", "!", "?", "…", '"', "'", ")", ">")
_CONNECT_GRACE_SEC = 1.0
# At the deadline a reply with no full sentence yet is only a fragment ("Queued ship for your", 2026-10-30 19:38): the
# session waits this much longer for its first sentence to finish rather than speak and store the fragment.
_FIRST_SENTENCE_GRACE_SEC = 3.0
# Our own tool time moves the deadline (it is not the model's latency), up to this much in all.
_MAX_TOOL_EXTENSION_SEC = 10.0
# Everything the session may legitimately add to `timeout_sec`; the outer caps include it so they never cut a reply
# the session itself would still have trimmed and returned.
_SESSION_EXTENSIONS_SEC = _FIRST_SENTENCE_GRACE_SEC + _MAX_TOOL_EXTENSION_SEC


def _settle_window(spoken_so_far: str) -> float:
    return TRANSCRIPT_SETTLE_SEC if spoken_so_far.rstrip().endswith(_SENTENCE_END) else TRANSCRIPT_SETTLE_MID_SENTENCE_SEC


# A first sentence is complete once more speech follows it; 12+ characters so "Sure." or "Dr." never count alone.
_FIRST_SENTENCE_RE = re.compile(r"^(.{12,}?[.!?\u2026])[\"')\]]?\s+\S", re.DOTALL)
_VOICE_REPLY_OPEN = "<voice_reply>"


def first_spoken_sentence(text: str) -> str:
    """The reply's first complete spoken sentence, or "" while it is still arriving. Text before a
    `<voice_reply>` tag is not spoken, so only what follows the tag counts."""
    spoken = text or ""
    open_at = spoken.lower().find(_VOICE_REPLY_OPEN)
    if open_at >= 0:
        spoken = spoken[open_at + len(_VOICE_REPLY_OPEN):]
    elif "<" in spoken:
        return ""
    match = _FIRST_SENTENCE_RE.match(spoken.lstrip())
    return match.group(1).strip() if match and "<" not in match.group(1) else ""


def _trim_to_last_sentence(text: str) -> str:
    """A reply cut off by the deadline is spoken up to its last full sentence, never mid-word."""
    stripped = text.strip()
    if not stripped or stripped.endswith(_SENTENCE_END):
        return stripped
    cut = max(stripped.rfind(p) for p in (". ", "! ", "? "))
    return stripped[: cut + 1] if cut > 0 else stripped


def _has_full_sentence(text_chunks: list[str], transcript_chunks: list[str]) -> bool:
    """True once the reply so far holds a finished sentence (what `_trim_to_last_sentence` would keep)."""
    spoken = ("".join(text_chunks) or "".join(transcript_chunks)).strip()
    return bool(spoken) and _trim_to_last_sentence(spoken).endswith(_SENTENCE_END)


def _python_type_to_schema_type(py_type: Any) -> str:
    origin = typing.get_origin(py_type)
    if origin is typing.Union:
        args = [a for a in typing.get_args(py_type) if a is not type(None)]
        if len(args) == 1:
            return _python_type_to_schema_type(args[0])
    target = origin or py_type
    if target is bool:
        return "BOOLEAN"
    if target is int:
        return "INTEGER"
    if target is float:
        return "NUMBER"
    if target in (list, tuple, set):
        return "ARRAY"
    if target is dict:
        return "OBJECT"
    return "STRING"


def _param_schema(types: Any, py_type: Any) -> Any:
    """The Schema for one parameter. An ARRAY must say what it holds: the Live API refuses the whole tool list (close
    1007) when an array schema has no `items`, so `list[str]` is ARRAY of STRING (a bare `list` is ARRAY of STRING)."""
    if typing.get_origin(py_type) is typing.Union:
        args = [a for a in typing.get_args(py_type) if a is not type(None)]
        if len(args) == 1:
            return _param_schema(types, args[0])
    schema_type = _python_type_to_schema_type(py_type)
    if schema_type != "ARRAY":
        return types.Schema(type=schema_type)
    args = typing.get_args(py_type)
    return types.Schema(type="ARRAY", items=_param_schema(types, args[0] if args else str))


def _callable_to_function_declaration(fn: Callable[..., Any]) -> Any:
    from google.genai import types

    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except (NameError, TypeError, AttributeError):
        hints = getattr(fn, "__annotations__", {}) or {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls") or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        hint = hints.get(param_name, str)
        properties[param_name] = _param_schema(types, hint)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    params_schema = (
        types.Schema(type="OBJECT", properties=properties, required=required or None)
        if properties
        else None
    )
    doc = (inspect.getdoc(fn) or f"Execute {fn.__name__}").strip()
    decl_kwargs: dict[str, Any] = {
        "name": fn.__name__,
        "description": doc,
    }
    if params_schema is not None:
        decl_kwargs["parameters"] = params_schema

    return types.FunctionDeclaration(**decl_kwargs)


def build_live_function_declarations(
    tools: Optional[Sequence[Any]] = None,
) -> tuple[list[Any], dict[str, Callable[..., Any]]]:
    """
    Inspects Python callables in `tools`, converts each into a `types.FunctionDeclaration`,
    and returns `([types.Tool(function_declarations=...)], tool_map)`.
    Declarations keep the default blocking behavior, so the model answers from the tool's result rather than ahead of
    it. Non-blocking only pays off when Live's own audio plays during a slow tool; the audio is discarded here and the
    tools return in milliseconds.
    """
    if not tools:
        return [], {}

    from google.genai import types

    resolved_tools = resolve_callable_tool_annotations(tools)
    declarations: list[Any] = []
    passthrough_tools: list[Any] = []
    tool_map: dict[str, Callable[..., Any]] = {}

    for item in resolved_tools:
        if callable(item):
            fn_name = getattr(item, "__name__", "")
            if fn_name:
                tool_map[fn_name] = item
                declarations.append(_callable_to_function_declaration(item))
        elif isinstance(item, types.FunctionDeclaration):
            declarations.append(item)
        elif isinstance(item, types.Tool):
            passthrough_tools.append(item)

    result_tools: list[Any] = []
    if declarations:
        result_tools.append(types.Tool(function_declarations=declarations))
    result_tools.extend(passthrough_tools)
    return result_tools, tool_map


def _normalize_live_turns(history: Optional[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
    if not history:
        return []
    normalized: list[dict[str, Any]] = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        raw_role = str(turn.get("role") or "user").strip().lower()
        role = "model" if raw_role in ("assistant", "model") else "user"
        raw_parts = turn.get("parts")
        parts: list[dict[str, Any]] = []
        if isinstance(raw_parts, list):
            for p in raw_parts:
                if isinstance(p, dict) and p.get("text") is not None:
                    txt = str(p["text"]).strip()
                    if txt:
                        parts.append({"text": txt})
                elif isinstance(p, str) and p.strip():
                    parts.append({"text": p.strip()})
        if not parts and turn.get("content") is not None:
            txt = str(turn["content"]).strip()
            if txt:
                parts.append({"text": txt})
        if parts:
            normalized.append({"role": role, "parts": parts})
    return normalized


async def async_send_live_conversational_turn(
    prompt: str,
    *,
    history: Optional[Sequence[dict[str, Any]]] = None,
    system_instruction: Optional[str] = None,
    client: Optional[Any] = None,
    api_key: Optional[str] = None,
    model: str = DEFAULT_LIVE_MODEL,
    tools: Optional[Sequence[Any]] = None,
    temperature: Optional[float] = 0.1,
    timeout_sec: float = 4.5,
    on_first_sentence: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """
    Executes a single conversational turn over a Gemini 3.8 Live WebSocket session
    (`client.aio.live.connect`), collecting `output_audio_transcription` + text parts,
    discarding raw PCM audio bytes, and executing tool calls.
    `on_first_sentence(sentence)` is called once, on the session's event loop (keep it quick), as soon as
    the first spoken sentence is complete and no tool has run yet, so the caller can start voicing it.
    """
    from google.genai import types

    ai_client = client or get_gemini_client(api_key=api_key)
    if not ai_client:
        raise ValueError("GEMINI_API_KEY is not configured or client initialization failed.")

    live_tools, tool_map = build_live_function_declarations(tools)
    norm_turns = _normalize_live_turns(history)
    effective_sys = (system_instruction or "").strip()
    if norm_turns:
        hist_lines: list[str] = []
        for turn in norm_turns:
            speaker = "Assistant" if turn.get("role") == "model" else "User"
            txt = " ".join(
                str(p.get("text") or "").strip()
                for p in (turn.get("parts") or [])
                if isinstance(p, dict) and str(p.get("text") or "").strip()
            ).strip()
            if txt:
                hist_lines.append(f"{speaker}: {txt}")
        if hist_lines:
            hist_block = "=== RECENT CONVERSATION HISTORY ===\n" + "\n".join(hist_lines)
            effective_sys = f"{effective_sys}\n\n{hist_block}".strip() if effective_sys else hist_block

    config_kwargs: dict[str, Any] = {
        "response_modalities": [types.Modality.AUDIO],
        "output_audio_transcription": types.AudioTranscriptionConfig(),
    }
    if effective_sys:
        config_kwargs["system_instruction"] = effective_sys
    if live_tools:
        config_kwargs["tools"] = live_tools
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if "extended-thinking" in (model or "").lower() and hasattr(types, "ThinkingConfig"):
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")

    live_config = types.LiveConnectConfig(**config_kwargs)

    async def _run_session() -> dict[str, Any]:
        transcript_chunks: list[str] = []
        text_chunks: list[str] = []
        tool_calls_executed = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.5, float(timeout_sec))
        tool_extension = 0.0
        timed_out = False
        settled = False
        first_sentence = ""
        # Characters of transcript heard between tool calls, so callers can log the turn's shape without its words.
        segment_starts: list[int] = [0]
        # How the model's reply arrived, so a doubled reply shows whether it was spoken as two separate takes.
        stream_events = {"generation_complete": 0, "turn_complete": 0, "interrupted": 0}

        async with ai_client.aio.live.connect(model=model, config=live_config) as session:
            if hasattr(session, "send_realtime_input"):
                await session.send_realtime_input(text=prompt)
            else:
                await session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": prompt}]}],
                    turn_complete=True,
                )

            for _round in range(4):
                round_tool_calls = 0
                got_any_msg = False
                # Words received since the last tool response: only those can settle the reply.
                answer_started = False
                stream = session.receive().__aiter__()
                next_message: Optional[asyncio.Future] = None  # survives a timeout: waiting must not cancel the stream
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0 and answer_started and not _has_full_sentence(text_chunks, transcript_chunks):
                        remaining = deadline + _FIRST_SENTENCE_GRACE_SEC - loop.time()
                    if remaining <= 0:
                        timed_out = True
                        break
                    wait = remaining
                    if answer_started:
                        wait = min(wait, _settle_window("".join(text_chunks) or "".join(transcript_chunks)))
                    if next_message is None:
                        next_message = asyncio.ensure_future(stream.__anext__())
                    done, _ = await asyncio.wait({next_message}, timeout=wait)
                    if not done:
                        waited_to_deadline = loop.time() >= deadline - 1e-3
                        if answer_started and wait < remaining:
                            spoken = "".join(text_chunks) or "".join(transcript_chunks)
                            if not spoken.rstrip().endswith(_SENTENCE_END):
                                # quiet mid-sentence is not an ending ("...reroute it, or", 2026-10-30 20:24): keep
                                # waiting; the deadline then trims to the last full sentence
                                continue
                            settled = True
                        elif waited_to_deadline and answer_started and not _has_full_sentence(
                            text_chunks, transcript_chunks
                        ):
                            continue  # a fragment at the deadline: the top of the loop grants the grace
                        else:
                            timed_out = True
                        break
                    finished, next_message = next_message, None
                    try:
                        message = finished.result()
                    except StopAsyncIteration:
                        break
                    got_any_msg = True
                    pending_tool_calls = False
                    tool_call = getattr(message, "tool_call", None)
                    fcs = getattr(tool_call, "function_calls", None) or [] if tool_call else []
                    if fcs:
                        pending_tool_calls = True
                        responses: list[Any] = []
                        tools_started = loop.time()
                        for call in fcs:
                            fn_name = getattr(call, "name", "") or ""
                            call_id = getattr(call, "id", None)
                            raw_args = getattr(call, "args", None) or {}
                            fn = tool_map.get(fn_name)
                            if fn is not None:
                                try:
                                    res = fn(**dict(raw_args))
                                except TOOL_INPUT_ERRORS as exc:
                                    # The model chose the arguments: a rejected call goes back to it as the result.
                                    logger.warning("Live tool %s rejected its arguments: %s", fn_name, exc)
                                    res = f"Error: {exc}"
                            else:
                                res = f"Unknown tool: {fn_name}"
                            tool_calls_executed += 1
                            round_tool_calls += 1
                            resp_kwargs: dict[str, Any] = {
                                "name": fn_name,
                                "response": {"result": res},
                            }
                            if call_id is not None:
                                resp_kwargs["id"] = call_id
                            responses.append(types.FunctionResponse(**resp_kwargs))
                        # our tool time is not the model's latency (bounded, see `_MAX_TOOL_EXTENSION_SEC`)
                        added = min(loop.time() - tools_started, _MAX_TOOL_EXTENSION_SEC - tool_extension)
                        tool_extension += added
                        deadline += added
                        segment_starts.append(sum(len(c) for c in transcript_chunks))
                        if responses:
                            await session.send_tool_response(function_responses=responses)
                        pending_tool_calls = False
                        answer_started = False

                    server_content = getattr(message, "server_content", None)
                    if server_content is not None:
                        out_trans = getattr(server_content, "output_transcription", None)
                        trans_text = getattr(out_trans, "text", None) if out_trans is not None else None
                        if trans_text:
                            transcript_chunks.append(str(trans_text))
                            answer_started = True

                        model_turn = getattr(server_content, "model_turn", None)
                        for part in getattr(model_turn, "parts", None) or []:
                            # Intentionally discard part.inline_data (raw PCM audio bytes)
                            p_text = getattr(part, "text", None)
                            if p_text:
                                text_chunks.append(str(p_text))
                                answer_started = True

                        if on_first_sentence is not None and not first_sentence and tool_calls_executed == 0:
                            first_sentence = first_spoken_sentence("".join(text_chunks) or "".join(transcript_chunks))
                            if first_sentence:
                                on_first_sentence(first_sentence)

                    interaction_status = getattr(message, "interaction_status", None)
                    turn_complete = bool(
                        server_content is not None and getattr(server_content, "turn_complete", False)
                    )
                    gen_complete = bool(
                        server_content is not None and getattr(server_content, "generation_complete", False)
                    )
                    stream_events["generation_complete"] += int(gen_complete)
                    stream_events["turn_complete"] += int(turn_complete)
                    stream_events["interrupted"] += int(bool(server_content is not None and getattr(server_content, "interrupted", False)))
                    if interaction_status == "IDLE" or (
                        (turn_complete or (gen_complete and (transcript_chunks or text_chunks)))
                        and not pending_tool_calls
                        and round_tool_calls == 0
                    ):
                        break
                if next_message is not None:
                    next_message.cancel()
                if settled or timed_out:
                    break
                if not got_any_msg or round_tool_calls == 0 or transcript_chunks or text_chunks:
                    break

        joined_transcript = "".join(transcript_chunks).strip()
        joined_text = "".join(text_chunks).strip()
        bounds = segment_starts + [sum(len(c) for c in transcript_chunks)]
        transcript_segments = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        final_text = joined_text or joined_transcript
        if timed_out:
            final_text = _trim_to_last_sentence(final_text)
            joined_transcript = _trim_to_last_sentence(joined_transcript)
        return {
            "text": final_text,
            "transcript": joined_transcript or final_text,
            "model_used": model,
            "fallback_occurred": False,
            "tool_calls_executed": tool_calls_executed,
            "timed_out": timed_out,
            "first_sentence": first_sentence,
            "transcript_segments": transcript_segments,
            "stream_events": stream_events,
        }

    # The session keeps its own deadline and returns what it has; this cap only covers a hung connect.
    cap = max(0.5, float(timeout_sec)) + _SESSION_EXTENSIONS_SEC + _CONNECT_GRACE_SEC
    return await asyncio.wait_for(_run_session(), timeout=cap)


def send_live_conversational_turn(
    prompt: str,
    *,
    history: Optional[Sequence[dict[str, Any]]] = None,
    system_instruction: Optional[str] = None,
    client: Optional[Any] = None,
    api_key: Optional[str] = None,
    model: str = DEFAULT_LIVE_MODEL,
    tools: Optional[Sequence[Any]] = None,
    temperature: Optional[float] = 0.1,
    timeout_sec: float = 4.5,
    on_first_sentence: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Synchronous wrapper around `async_send_live_conversational_turn`."""
    coro_fn = lambda: async_send_live_conversational_turn(
        prompt,
        history=history,
        system_instruction=system_instruction,
        client=client,
        api_key=api_key,
        model=model,
        tools=tools,
        temperature=temperature,
        timeout_sec=timeout_sec,
        on_first_sentence=on_first_sentence,
    )
    try:
        asyncio.get_running_loop()
        running_in_loop = True
    except RuntimeError:
        running_in_loop = False

    if not running_in_loop:
        return asyncio.run(coro_fn())

    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["result"] = asyncio.run(coro_fn())
        except Exception as exc:
            box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=max(1.0, float(timeout_sec) + _SESSION_EXTENSIONS_SEC + _CONNECT_GRACE_SEC + 1.0))
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise TimeoutError("Gemini Live session timed out.")
    return box["result"]


__all__ = [
    "DEFAULT_LIVE_MODEL",
    "EXTENDED_THINKING_LIVE_MODEL",
    "TRANSCRIBE_LIVE_MODEL",
    "build_live_function_declarations",
    "first_spoken_sentence",
    "async_send_live_conversational_turn",
    "send_live_conversational_turn",
]
