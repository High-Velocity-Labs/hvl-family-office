"""
Resilient Google GenAI Client with Cascading Fallback & Quota Protection.
"""

from __future__ import annotations
import os
import time
import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger("hvl_common.ai.gemini")

DEFAULT_MODEL_TIER = "lite"
DEFAULT_PRIMARY_MODEL = "gemini-3.5-flash-lite"
DEFAULT_FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-3.7-flash"]
QUOTA_COOLDOWN_SECONDS = 300.0

_QUOTA_COOLDOWN_UNTIL: dict[str, float] = {}

MODEL_TIER_REGISTRY: dict[str, dict[str, Any]] = {
    "lite": {
        "tier": "lite",
        "label": "Gemini Lite (High Quota)",
        "short_label": "Lite",
        "icon": "evt-rocket",
        "primary_model": "gemini-3.5-flash-lite",
        "fallback_models": [
            "gemini-3.1-flash-lite",
        ],
        "description": "Default high-quota tier for fast everyday requests",
    },
    "flash": {
        "tier": "flash",
        "label": "Gemini Flash (Balanced)",
        "short_label": "Flash",
        "icon": "pulse",
        "primary_model": "gemini-2.5-flash",
        "fallback_models": [
            "gemini-3.7-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ],
        "description": "Balanced reasoning and low latency",
    },
    "pro": {
        "tier": "pro",
        "label": "Gemini Pro (Deep Reasoning)",
        "short_label": "Pro",
        "icon": "advisor",
        "primary_model": "gemini-2.5-pro",
        "fallback_models": [
            "gemini-3.1-pro",
            "gemini-2.5-flash",
            "gemini-3.7-flash",
            "gemini-3.5-flash-lite",
        ],
        "description": "Complex synthesis, financial what-ifs, and trip planning",
    },
    "auto": {
        "tier": "auto",
        "label": "Gemini Auto (Best Available)",
        "short_label": "Auto",
        "icon": "sparkles",
        "primary_model": "gemini-2.5-pro",
        "fallback_models": [
            "gemini-3.1-pro",
            "gemini-2.5-flash",
            "gemini-3.7-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ],
        "description": "Starts at Pro and automatically steps down on 429 quota cooldowns",
    },
}


def mark_model_quota_exhausted(model_id: str, cooldown_seconds: float = QUOTA_COOLDOWN_SECONDS) -> None:
    """Marks a model ID as temporarily quota-exhausted so Auto/cascades skip it without a 429 round-trip."""
    if model_id:
        _QUOTA_COOLDOWN_UNTIL[model_id] = time.monotonic() + cooldown_seconds


def is_model_quota_exhausted(model_id: str) -> bool:
    """Returns True if the model ID is currently within its quota exhaustion cooldown window."""
    until = _QUOTA_COOLDOWN_UNTIL.get(model_id, 0.0)
    if until <= 0.0:
        return False
    if time.monotonic() >= until:
        _QUOTA_COOLDOWN_UNTIL.pop(model_id, None)
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
        resolved_fallbacks = (
            list(fallback_models)
            if fallback_models is not None
            else list(entry["fallback_models"])
        )
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
    resolved_fallbacks = (
        list(fallback_models)
        if fallback_models is not None
        else list(DEFAULT_FALLBACK_MODELS)
    )
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
        short = "Pro"
        tier = "pro"
        icon_name = "advisor"
    elif "lite" in lower:
        short = "Lite"
        tier = "lite"
        icon_name = "evt-rocket"
    elif "flash" in lower:
        short = "Flash"
        tier = "flash"
        icon_name = "pulse"
    else:
        short = clean
        tier = "custom"
        icon_name = "sparkles"

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
    timeout: int = 10000,
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

    healthy_candidates = [m for m in raw_candidates if not is_model_quota_exhausted(m)]
    cooled_candidates = [m for m in raw_candidates if is_model_quota_exhausted(m)]
    models_to_try = healthy_candidates + cooled_candidates

    from google.genai import types

    call_config = config
    if call_config is None and temperature is not None:
        call_config = types.GenerateContentConfig(temperature=temperature)

    last_error: Optional[Exception] = None
    for idx, model_id in enumerate(models_to_try):
        try:
            logger.info(f"Invoking Gemini model: {model_id}")
            response = ai_client.models.generate_content(
                model=model_id,
                contents=contents,
                config=call_config,
            )
            try:
                setattr(response, "model_used", model_id)
                setattr(response, "fallback_occurred", model_id != p_model or idx > 0)
            except Exception:
                pass
            return response
        except Exception as e:
            last_error = e
            if _is_retryable_quota_or_sunset_error(e):
                mark_model_quota_exhausted(model_id)
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
    """
    Sends a prompt and returns response text with automatic model cascade.
    """
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

    config_kwargs: dict[str, Any] = {
        "tools": list(tools),
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
