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
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_FALLBACK_MODELS,
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
    "DEFAULT_PRIMARY_MODEL",
    "DEFAULT_FALLBACK_MODELS",
    "clean_history_text",
    "normalize_chat_history",
    "summarize_history_turns",
    "compact_conversation_history",
    "send_conversational_message",
]
