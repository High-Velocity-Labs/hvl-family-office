"""
Shared vs. BYO Household Gemini API Key Resolution, Quota Policy, and Rate Limiting.
Provides unified key masking, tier resolution ('shared', 'byo', 'local'),
input length caps, and multi-worker rate-limit enforcement across HVL apps.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Sequence, Tuple
from flask import jsonify
from hvl_common.web.rate_limit import _default_limiter

DEFAULT_SHARED_RATE_LIMITS: Tuple[str, ...] = ("5/min", "30/hr")
DEFAULT_BYO_RATE_LIMITS: Tuple[str, ...] = ("30/min", "300/hr")
DEFAULT_SHARED_MAX_INPUT_CHARS: int = 2000
DEFAULT_BYO_MAX_INPUT_CHARS: int = 8000


def _parse_env_limits(env_keys: Sequence[str], default: Sequence[str]) -> Tuple[str, ...]:
    for key in env_keys:
        raw = os.getenv(key, "").strip()
        if raw:
            parts = tuple(s.strip() for s in raw.split(",") if s.strip())
            if parts:
                return parts
    return tuple(default)


def _parse_env_int(env_keys: Sequence[str], default: int) -> int:
    for key in env_keys:
        raw = os.getenv(key, "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
    return int(default)


def mask_gemini_api_key(api_key: Optional[str]) -> str:
    """Masks a Gemini API key for safe UI display (e.g. '••••abcd')."""
    clean = (api_key or "").strip()
    if not clean:
        return ""
    if len(clean) >= 4:
        return f"••••{clean[-4:]}"
    return "••••"


def resolve_household_ai_policy(
    custom_key: Optional[str] = None,
    *,
    has_custom_key: Optional[bool] = None,
    server_key: Optional[str] = None,
    is_local_mode: bool = False,
    shared_rate_limits: Optional[Sequence[str]] = None,
    byo_rate_limits: Optional[Sequence[str]] = None,
    shared_max_input_chars: Optional[int] = None,
    byo_max_input_chars: Optional[int] = None,
) -> dict[str, Any]:
    """
    Resolves the effective Gemini API key, rate-limit tier, and prompt char caps for a household:
    - 'local' (`is_local_mode=True`) or 'byo' (`custom_key` present):
      30/min · 300/hr rate limits and 8,000 max input chars.
    - 'shared' (server default `GEMINI_API_KEY`):
      5/min · 30/hr rate limits and 2,000 max input chars to protect shared quota.
    """
    clean_custom = (custom_key or "").strip()
    clean_server = (
        server_key.strip()
        if server_key is not None
        else os.getenv("GEMINI_API_KEY", "").strip()
    )
    effective_key = clean_custom or clean_server
    has_custom = bool(clean_custom) if has_custom_key is None else bool(has_custom_key)
    has_server = bool(clean_server)

    eff_shared_limits = (
        tuple(shared_rate_limits)
        if shared_rate_limits is not None
        else _parse_env_limits(
            ("AI_SHARED_RATE_LIMITS", "AI_ADVISOR_SHARED_RATE_LIMITS"),
            DEFAULT_SHARED_RATE_LIMITS,
        )
    )
    eff_byo_limits = (
        tuple(byo_rate_limits)
        if byo_rate_limits is not None
        else _parse_env_limits(
            ("AI_BYO_RATE_LIMITS", "AI_ADVISOR_BYO_RATE_LIMITS"),
            DEFAULT_BYO_RATE_LIMITS,
        )
    )
    eff_shared_chars = (
        int(shared_max_input_chars)
        if shared_max_input_chars is not None
        else _parse_env_int(
            ("AI_MAX_INPUT_CHARS", "AI_ADVISOR_MAX_INPUT_CHARS"),
            DEFAULT_SHARED_MAX_INPUT_CHARS,
        )
    )
    eff_byo_chars = (
        int(byo_max_input_chars)
        if byo_max_input_chars is not None
        else _parse_env_int(
            ("AI_BYO_MAX_INPUT_CHARS", "AI_ADVISOR_BYO_MAX_INPUT_CHARS"),
            DEFAULT_BYO_MAX_INPUT_CHARS,
        )
    )

    if is_local_mode:
        tier = "local"
        active_limits = eff_byo_limits
        max_chars = eff_byo_chars
    elif has_custom:
        tier = "byo"
        active_limits = eff_byo_limits
        max_chars = eff_byo_chars
    else:
        tier = "shared"
        active_limits = eff_shared_limits
        max_chars = eff_shared_chars

    shared_label = " · ".join(eff_shared_limits)
    byo_label = " · ".join(eff_byo_limits)
    active_label = " · ".join(active_limits)

    return {
        "api_key": effective_key,
        "has_custom_key": has_custom,
        "masked_key": mask_gemini_api_key(clean_custom),
        "has_server_key": has_server,
        "is_local_mode": bool(is_local_mode),
        "tier": tier,
        "rate_limits": active_limits,
        "rate_limit_label": active_label,
        "max_input_chars": int(max_chars),
        "shared_rate_limits": eff_shared_limits,
        "byo_rate_limits": eff_byo_limits,
        "shared_rate_limit_label": shared_label,
        "byo_rate_limit_label": byo_label,
        "shared_max_input_chars": int(eff_shared_chars),
        "byo_max_input_chars": int(eff_byo_chars),
    }


def evaluate_ai_quota_limit(
    ai_policy: dict[str, Any],
    *,
    scope: str = "ai.chat",
    client_key: Optional[str] = None,
    bypass: bool = False,
    only_shared: bool = False,
    settings_hint: str = "Settings",
) -> Tuple[bool, int, str]:
    """
    Evaluates the active household AI rate-limit policy.
    Returns `(allowed, retry_after_seconds, error_message)`.
    """
    tier = str(ai_policy.get("tier") or "shared")
    if bypass or (only_shared and tier != "shared"):
        return True, 0, ""

    limits = ai_policy.get("rate_limits") or DEFAULT_SHARED_RATE_LIMITS
    allowed, retry_after, _ = _default_limiter.evaluate(
        *limits,
        scope=f"{scope}:{tier}",
        client_key=client_key,
    )
    if allowed:
        return True, 0, ""

    if tier == "shared":
        err_msg = (
            f"Rate limit exceeded for the shared server AI key ({ai_policy.get('rate_limit_label', '5/min · 30/hr')}). "
            f"Supply your own Google Gemini API key in {settings_hint} to unlock "
            f"higher BYO-key limits ({ai_policy.get('byo_rate_limit_label', '30/min · 300/hr')})."
        )
    else:
        err_msg = (
            f"Rate limit exceeded ({ai_policy.get('rate_limit_label', '30/min · 300/hr')}). "
            f"Please wait {retry_after}s and try again."
        )
    return False, retry_after, err_msg


def enforce_ai_rate_limit(
    ai_policy: dict[str, Any],
    *,
    scope: str = "ai.chat",
    client_key: Optional[str] = None,
    bypass: bool = False,
    only_shared: bool = False,
    settings_hint: str = "Settings",
    on_limited: Optional[Any] = None,
) -> Optional[Any]:
    """
    Flask route helper that evaluates `ai_policy` rate limits and returns a
    `(Response, 429, headers)` tuple when exceeded, or `None` when allowed.
    """
    allowed, retry_after, err_msg = evaluate_ai_quota_limit(
        ai_policy,
        scope=scope,
        client_key=client_key,
        bypass=bypass,
        only_shared=only_shared,
        settings_hint=settings_hint,
    )
    if allowed:
        return None

    if callable(on_limited):
        try:
            on_limited(ai_policy, retry_after)
        except Exception:
            pass

    tier = str(ai_policy.get("tier") or "shared")
    return (
        jsonify({
            "success": False,
            "error": err_msg,
            "reply": err_msg,
            "retry_after": retry_after,
            "tier": tier,
        }),
        429,
        {"Retry-After": str(retry_after)},
    )
