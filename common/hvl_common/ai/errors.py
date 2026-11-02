"""Exceptions an upstream model call raises, so callers catch exactly those and let programming errors surface."""

from __future__ import annotations


class ModelCascadeExhausted(RuntimeError):
    """Every model in a fallback cascade was tried or skipped and none produced a response."""


class GeminiNotConfigured(ValueError):
    """No Gemini API key (or no usable client) is configured, so no model call can be made."""


def model_call_errors() -> tuple[type[BaseException], ...]:
    """
    What a Gemini REST or Live call raises when the service, the network, or the cascade fails:
    the genai API error (quota, sunset, bad request), the HTTP and websocket transports, OS-level
    socket errors and timeouts, an exhausted cascade, and a missing API key.
    Imported lazily so `google.genai` stays optional until a call is made.
    """
    import httpx
    from google.genai import errors as genai_errors
    from websockets.exceptions import WebSocketException

    return (
        genai_errors.APIError,
        httpx.HTTPError,
        WebSocketException,
        OSError,
        TimeoutError,
        ModelCascadeExhausted,
        GeminiNotConfigured,
    )


# What a model-requested tool call raises when the model's arguments are wrong or name something that does not exist.
TOOL_INPUT_ERRORS = (TypeError, ValueError, LookupError, PermissionError)
