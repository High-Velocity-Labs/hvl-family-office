"""
High Velocity Labs Resilient Gemini AI Client Module.
Provides automatic model cascading (primary -> fallbacks), quota resilience,
multi-turn conversation management with auto-compaction, and error handling across all HVL applications.
"""

from hvl_common.ai.gemini import (
    get_gemini_client,
    send_chat_message,
    generate_content_with_fallback,
    generate_structured_content,
    generate_content_with_tools,
    DEFAULT_MODEL_TIER,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_FALLBACK_MODELS,
    MODEL_TIER_REGISTRY,
    get_model_tier_options,
    resolve_model_tier,
    format_model_badge,
    mark_model_quota_exhausted,
    is_model_quota_exhausted,
    clear_model_quota_cooldowns,
)
from hvl_common.ai.conversation import (
    clean_history_text,
    normalize_chat_history,
    summarize_history_turns,
    compact_conversation_history,
    send_conversational_message,
)

__all__ = [
    "get_gemini_client",
    "send_chat_message",
    "generate_content_with_fallback",
    "generate_structured_content",
    "generate_content_with_tools",
    "DEFAULT_MODEL_TIER",
    "DEFAULT_PRIMARY_MODEL",
    "DEFAULT_FALLBACK_MODELS",
    "MODEL_TIER_REGISTRY",
    "get_model_tier_options",
    "resolve_model_tier",
    "format_model_badge",
    "mark_model_quota_exhausted",
    "is_model_quota_exhausted",
    "clear_model_quota_cooldowns",
    "clean_history_text",
    "normalize_chat_history",
    "summarize_history_turns",
    "compact_conversation_history",
    "send_conversational_message",
]
