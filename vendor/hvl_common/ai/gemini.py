"""
Resilient Google GenAI Client with Cascading Fallback & Quota Protection.
"""

from __future__ import annotations
import os
import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger("hvl_common.ai.gemini")

DEFAULT_PRIMARY_MODEL = "gemini-3.5-flash-lite"
DEFAULT_FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-3.7-flash"]


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
) -> Any:
    """
    Calls client.models.generate_content cascading from primary_model through fallback_models.
    Handles 429 quota exhaustion and 404 model sunset automatically.
    """
    ai_client = client or get_gemini_client(api_key=api_key)
    if not ai_client:
        raise ValueError("GEMINI_API_KEY is not configured or client initialization failed.")

    models_to_try: List[str] = []
    p_model = primary_model or os.getenv("GEMINI_MODEL", DEFAULT_PRIMARY_MODEL)
    models_to_try.append(p_model)

    fallbacks = list(fallback_models) if fallback_models is not None else DEFAULT_FALLBACK_MODELS
    for fb in fallbacks:
        if fb not in models_to_try:
            models_to_try.append(fb)

    from google.genai import types

    call_config = config
    if call_config is None and temperature is not None:
        call_config = types.GenerateContentConfig(temperature=temperature)

    last_error: Optional[Exception] = None
    for model_id in models_to_try:
        try:
            logger.info(f"Invoking Gemini model: {model_id}")
            response = ai_client.models.generate_content(
                model=model_id,
                contents=contents,
                config=call_config,
            )
            return response
        except Exception as e:
            last_error = e
            if _is_retryable_quota_or_sunset_error(e):
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
    )
