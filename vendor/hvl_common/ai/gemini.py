"""
Resilient Google GenAI Client with Cascading Fallback & Quota Protection.
"""

from __future__ import annotations
import hashlib
import os
import time
import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger("hvl_common.ai.gemini")

DEFAULT_MODEL_TIER = "lite"
DEFAULT_PRIMARY_MODEL = "gemini-3.5-flash-lite"
DEFAULT_FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3-flash-preview", "gemini-3.8-flash", "gemini-3.1-flash-lite", "gemma-4-26b-a4b-it", "gemma-4-31b-it"]
QUOTA_COOLDOWN_SECONDS = 300.0

_QUOTA_COOLDOWN_UNTIL: dict[tuple[str, str], float] = {}


def _cooldown_key_scope(api_key: Optional[str] = None) -> str:
    clean = (api_key or "").strip()
    if not clean:
        return "default"
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]

MODEL_TIER_REGISTRY: dict[str, dict[str, Any]] = {
    "lite": {"tier": "lite", "label": "Gemini Lite (High Quota)", "short_label": "Lite", "icon": "evt-rocket", "primary_model": "gemini-3.5-flash-lite", "fallback_models": ["gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3-flash-preview", "gemma-4-26b-a4b-it", "gemma-4-31b-it"], "description": "Default high-quota tier for fast everyday requests"},
    "flash": {"tier": "flash", "label": "Gemini Flash (Balanced)", "short_label": "Flash", "icon": "pulse", "primary_model": "gemini-3.6-flash", "fallback_models": ["gemini-3.8-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-26b-a4b-it"], "description": "Balanced reasoning and low latency"},
    "pro": {"tier": "pro", "label": "Gemini Pro (Deep Reasoning)", "short_label": "Pro", "icon": "advisor", "primary_model": "gemini-2.5-pro", "fallback_models": ["gemini-3.1-pro", "gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-26b-a4b-it"], "description": "Complex synthesis, financial what-ifs, and trip planning"},
    "auto": {"tier": "auto", "label": "Gemini Auto (Best Available)", "short_label": "Auto", "icon": "sparkles", "primary_model": "gemini-2.5-pro", "fallback_models": ["gemini-3.1-pro", "gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-26b-a4b-it"], "description": "Starts at Pro and automatically steps down on 429 quota cooldowns"},
}


def mark_model_quota_exhausted(
    model_id: str,
    cooldown_seconds: float = QUOTA_COOLDOWN_SECONDS,
    api_key: Optional[str] = None,
) -> None:
    """Marks a model ID as temporarily quota-exhausted (scoped to the API key) so cascades skip it without a 429 round-trip."""
    if model_id:
        _QUOTA_COOLDOWN_UNTIL[(_cooldown_key_scope(api_key), model_id)] = time.monotonic() + cooldown_seconds


def is_model_quota_exhausted(model_id: str, api_key: Optional[str] = None) -> bool:
    """Returns True if the model ID is currently within its quota exhaustion cooldown window for the given key."""
    key_tuple = (_cooldown_key_scope(api_key), model_id)
    until = _QUOTA_COOLDOWN_UNTIL.get(key_tuple, 0.0)
    if until <= 0.0:
        return False
    if time.monotonic() >= until:
        _QUOTA_COOLDOWN_UNTIL.pop(key_tuple, None)
        return False
    return True


def clear_model_quota_cooldowns() -> None:
    """Clears all in-memory model quota cooldowns."""
    _QUOTA_COOLDOWN_UNTIL.clear()


def get_model_tier_options() -> List[dict[str, Any]]:
    """Returns ordered list of available Gemini model tiers for UI selectors (Lite default first)."""
    return [dict(MODEL_TIER_REGISTRY[k]) for k in ("lite", "flash", "pro", "auto")]


def resolve_model_tier(
    tier_or_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """
    Resolves a user-selected tier ('auto', 'pro', 'flash', 'lite') or explicit model ID
    into primary_model, fallback_models, and display metadata.
    """
    raw = (tier_or_model or "").strip()
    lowered = raw.lower()

    if lowered in MODEL_TIER_REGISTRY:
        entry = MODEL_TIER_REGISTRY[lowered]
        resolved_fallbacks = list(fallback_models) if fallback_models is not None else list(entry["fallback_models"])
        return {
            "tier": entry["tier"],
            "label": entry["label"],
            "short_label": entry["short_label"],
            "icon": entry["icon"],
            "primary_model": entry["primary_model"],
            "fallback_models": resolved_fallbacks,
        }

    # Explicit model ID or default fallback
    primary = raw or os.getenv("GEMINI_MODEL", DEFAULT_PRIMARY_MODEL)
    resolved_fallbacks = list(fallback_models) if fallback_models is not None else list(DEFAULT_FALLBACK_MODELS)
    badge = format_model_badge(primary)
    return {
        "tier": "custom" if raw else "lite",
        "label": primary,
        "short_label": badge["short_label"],
        "icon": badge["icon"],
        "primary_model": primary,
        "fallback_models": resolved_fallbacks,
    }


def format_model_badge(model_id: str, fallback_occurred: bool = False) -> dict[str, Any]:
    """Formats a model ID into a concise UI badge representation without emojis."""
    clean = (model_id or DEFAULT_PRIMARY_MODEL).strip()
    lower = clean.lower()
    if "pro" in lower:
        short, tier, icon_name = "Pro", "pro", "advisor"
    elif "lite" in lower:
        short, tier, icon_name = "Lite", "lite", "evt-rocket"
    elif "flash" in lower:
        short, tier, icon_name = "Flash", "flash", "pulse"
    else:
        short, tier, icon_name = clean, "custom", "sparkles"

    badge_text = f"{short} ({clean})"
    if fallback_occurred:
        badge_text = f"{badge_text} · fallback"

    return {
        "model_used": clean,
        "tier": tier,
        "short_label": short,
        "icon": icon_name,
        "badge_text": badge_text,
        "fallback_occurred": bool(fallback_occurred),
    }


def get_gemini_client(
    api_key: Optional[str] = None,
    timeout: int = 25000,
    attempts: int = 1,
) -> Optional[Any]:
    """
    Initializes and returns an authenticated Google GenAI client.
    Returns None if api_key is missing or google-genai is uninstalled.
    """
    key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
    if not key:
        return None

    try:
        from google import genai
        from google.genai import types

        return genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=timeout,
                retry_options=types.HttpRetryOptions(attempts=attempts),
            ),
        )
    except Exception as e:
        logger.error(f"Failed to initialize GenAI client: {e}")
        return None


def _is_retryable_quota_or_sunset_error(err: Exception) -> bool:
    """Detects HTTP 429 (rate/quota limit), 404 (model sunset/not found), 503 (high demand/unavailable), or resource exhausted."""
    err_str = str(err).lower()
    return any(k in err_str for k in ["429", "404", "503", "500", "502", "504", "quota", "rate limit", "resource exhausted", "not found", "unavailable", "high demand"])


def generate_content_with_fallback(
    contents: Any,
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    primary_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
    config: Optional[Any] = None,
    temperature: Optional[float] = None,
    model_tier: Optional[str] = None,
) -> Any:
    """
    Calls client.models.generate_content cascading from primary_model through fallback_models.
    Supports named model_tier ('auto', 'pro', 'flash', 'lite') and attaches
    `model_used` and `fallback_occurred` attributes to the returned response.
    Handles 429 quota exhaustion and 404 model sunset automatically.
    """
    ai_client = client or get_gemini_client(api_key=api_key)
    if not ai_client:
        raise ValueError("GEMINI_API_KEY is not configured or client initialization failed.")

    models_to_try: List[str] = []
    if model_tier or (primary_model and primary_model.strip().lower() in MODEL_TIER_REGISTRY):
        resolved = resolve_model_tier(model_tier or primary_model, fallback_models=fallback_models)
        p_model = resolved["primary_model"]
        fallbacks = resolved["fallback_models"]
    else:
        p_model = primary_model or os.getenv("GEMINI_MODEL", DEFAULT_PRIMARY_MODEL)
        fallbacks = list(fallback_models) if fallback_models is not None else DEFAULT_FALLBACK_MODELS

    raw_candidates: List[str] = [p_model]
    for fb in fallbacks:
        if fb not in raw_candidates:
            raw_candidates.append(fb)

    models_to_try = [m for m in raw_candidates if not is_model_quota_exhausted(m, api_key=api_key)] + [m for m in raw_candidates if is_model_quota_exhausted(m, api_key=api_key)]

    from google.genai import types

    call_config = config
    if call_config is None and temperature is not None:
        call_config = types.GenerateContentConfig(temperature=temperature)

    from hvl_common.ai.web import finalize_model_response, prepare_model_call_config

    last_error: Optional[Exception] = None
    for idx, model_id in enumerate(models_to_try):
        try:
            logger.info(f"Invoking Gemini model: {model_id}")
            response = ai_client.models.generate_content(
                model=model_id,
                contents=contents,
                config=prepare_model_call_config(model_id, call_config),
            )
            return finalize_model_response(ai_client, model_id, p_model, idx, contents, call_config, response)
        except Exception as e:
            last_error = e
            if _is_retryable_quota_or_sunset_error(e):
                cd = 3600.0 if "generaterequestsperday" in str(e).lower() else QUOTA_COOLDOWN_SECONDS
                mark_model_quota_exhausted(model_id, cooldown_seconds=cd, api_key=api_key)
                logger.warning(f"Model {model_id} hit recoverable error ({e}). Trying next fallback candidate...")
                continue
            # If it's a non-retryable error (e.g. invalid request argument), raise immediately
            raise e

    if last_error:
        raise last_error
    raise RuntimeError("All Gemini models in cascade failed.")


def send_chat_message(
    prompt: str,
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    primary_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
    temperature: float = 0.1,
) -> str:
    """Sends a prompt and returns response text with automatic model cascade."""
    resp = generate_content_with_fallback(
        contents=prompt,
        api_key=api_key,
        client=client,
        primary_model=primary_model,
        fallback_models=fallback_models,
        temperature=temperature,
    )
    return getattr(resp, "text", "") or ""


def generate_structured_content(
    prompt: str,
    response_schema: Any,
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    primary_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
) -> Any:
    """Calls generate_content with a structured Pydantic schema and automatic fallback."""
    from google.genai import types

    content_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
    )
    return generate_content_with_fallback(
        contents=prompt,
        api_key=api_key,
        client=client,
        primary_model=primary_model,
        fallback_models=fallback_models,
        config=content_config,
    )


def generate_content_with_tools(
    prompt: str,
    tools: Sequence[Any],
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    primary_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
    temperature: Optional[float] = 0.1,
    system_instruction: Optional[str] = None,
    model_tier: Optional[str] = None,
) -> Any:
    """
    Executes a prompt against Gemini with Python functions provided as callable tools.
    The SDK handles automatic function calling (AFC) by invoking the tools
    and feeding the results back into the model until a final answer is reached.
    Cascades through fallback models automatically on 429 or 404 errors.
    """
    from google.genai import types
    from hvl_common.ai.web import resolve_callable_tool_annotations

    config_kwargs: dict[str, Any] = {
        "tools": resolve_callable_tool_annotations(tools),
        "temperature": temperature,
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction

    tool_config = types.GenerateContentConfig(**config_kwargs)
    return generate_content_with_fallback(
        contents=prompt,
        api_key=api_key,
        client=client,
        primary_model=primary_model,
        fallback_models=fallback_models,
        config=tool_config,
        model_tier=model_tier,
    )


def search_web_grounded(
    query: str,
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    primary_model: str = "gemini-2.5-flash",
    fallback_models: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Executes a web-grounded search query using Gemini Google Search tool with model cascade."""
    clean_query = (query or "").strip()
    if not clean_query:
        return {
            "success": False, "query": query, "answer": "", "sources": [],
            "formatted_reply": "Web search unavailable: Query cannot be empty.", "error": "Query cannot be empty.",
        }

    try:
        from google.genai import types
        from hvl_common.ai.web import extract_grounding_sources

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
            system_instruction=(
                "Provide a concise, factual answer grounded in live web search. "
                "Always include specific names, pricing/details when relevant, and cite source URLs."
            ),
        )

        response = generate_content_with_fallback(
            contents=clean_query,
            api_key=api_key,
            client=client,
            primary_model=primary_model,
            fallback_models=fallback_models or ["gemini-3.6-flash", "gemini-3.5-flash-lite"],
            config=config,
        )

        text = (getattr(response, "text", "") or "").strip()
        sources = extract_grounding_sources(response)

        formatted_reply = text
        if sources and not any(s["url"] in text for s in sources):
            sources_text = "\n".join(f"- [{s['title']}]({s['url']})" for s in sources[:5])
            formatted_reply = f"{text}\n\nSources:\n{sources_text}" if text else f"Sources:\n{sources_text}"

        return {
            "success": True, "query": query, "answer": text, "sources": sources,
            "formatted_reply": formatted_reply, "model_used": getattr(response, "model_used", primary_model),
        }
    except Exception as exc:
        if _is_retryable_quota_or_sunset_error(exc) and client is None:
            from hvl_common.ai.web import fetch_live_web_search
            live_fallback = fetch_live_web_search(clean_query)
            if live_fallback.get("success"):
                return live_fallback
        logger.warning(f"Web-grounded search failed for query '{query}': {exc}")
        return {
            "success": False, "query": query, "answer": "", "sources": [],
            "formatted_reply": f"Web search unavailable: {exc}", "error": str(exc),
        }


from hvl_common.ai.web import fetch_direct_page_snapshot, fetch_web_page_grounded, normalize_public_url  # noqa: E402,F401

__all__ = ["fetch_direct_page_snapshot", "fetch_web_page_grounded", "normalize_public_url"]



