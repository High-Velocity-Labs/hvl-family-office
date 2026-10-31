"""
Voice lifecycle commands ("compact this", "start a new conversation", "carry this over", "health check").

The generic phrases work for every app; each app adds its own names and phrases through a `VoiceVocabulary`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class VoiceVocabulary:
    """
    One app's own words for voice lifecycle commands, on top of the generic phrases:
    - `assistant_names`: names the user may say before or after a command ("<name>, compact this").
    - `doctor_phrases`: extra regex fragments that ask for a health check.
    - `tail_phrases`: extra regex fragments allowed after "start a new conversation" without making it a task.
    """

    assistant_names: Tuple[str, ...] = ()
    doctor_phrases: Tuple[str, ...] = ()
    tail_phrases: Tuple[str, ...] = ()


GENERIC_VOICE_VOCABULARY = VoiceVocabulary()


def _alternation(fragments: Sequence[str]) -> str:
    return "".join(f"|{f}" for f in fragments)


def detect_voice_lifecycle_intent(text: str, vocabulary: Optional[VoiceVocabulary] = None) -> Optional[str]:
    """
    Detects natural spoken/typed lifecycle intents: `carryover`, `compact`, `new_conversation`, or `doctor`.
    `vocabulary` adds one app's own names and phrases to the generic ones.
    """
    vocab = vocabulary if vocabulary is not None else GENERIC_VOICE_VOCABULARY
    names = "|".join(re.escape(n) for n in vocab.assistant_names)
    cleaned_input = str(text or "").strip()
    if not cleaned_input:
        return None
    norm = re.sub(r"\s+", " ", cleaned_input.lower())
    if not norm or len(norm) > 220:
        return None
    if norm == "/compact":
        return "compact"
    if norm in ("/doctor", "doctor"):
        return "doctor"

    clean = re.sub(r"[^\w\s]", " ", norm)
    clean = re.sub(r"\s+", " ", clean).strip()

    if re.search(
        r"\b(?:voice\s+doctor|run\s+(?:voice\s+)?doctor|"
        r"voice\s+health(?:\s+check)?|"
        r"health\s+check|thread\s+status|context\s+status|"
        r"how\s+(?:heavy|long|full|big|large)\s+is\s+(?:this|the|our|my)\s+"
        r"(?:thread|conversation|chat|context)" + _alternation(vocab.doctor_phrases) + r")\b",
        clean,
    ):
        return "doctor"

    has_carryover = bool(
        re.search(
            r"\b(carry\s+(?:this|it|that|context|everything|our\s+\w+)?\s*over|"
            r"carryover|hand\s*off|handoff|bring\s+(?:this|the|our)?\s*context|"
            r"keep\s+(?:this|the|our)?\s*context|transfer\s+(?:this|the|our)?\s*context)\b",
            clean,
        )
    )
    _new_thread_re = re.compile(
        r"\b(?:start|open|begin|create|switch\s+to|make)\s+(?:a\s+)?(?:new|fresh|clean|another)\s+"
        r"(?:conversation|thread|chat|session|topic|workstream|one)\b|"
        r"\b(?:new|fresh)\s+(?:conversation|thread|chat|session|topic|workstream)\b"
    )
    new_thread_matches = list(_new_thread_re.finditer(clean))
    has_new_thread = bool(new_thread_matches)
    if has_carryover and (has_new_thread or any(k in clean for k in ("conversation", "thread", "chat"))):
        return "carryover"
    name_prefix = f"(?:(?:{names})\\s+)*" if names else ""
    if re.search(
        r"\b(?:compact|condense|compress)\s+(?:(?:this|that|the|our|my|current)\s+)?(?:conversation|thread|chat|context|history|memory|session)\b|"
        r"\b(?:compact|condense|compress)\s+(?:it|this|that|now|for\s+me|please)\b|"
        r"^(?:(?:hey|hi|ok|okay|yo|yes|yeah|sure|alright)\s+)*" + name_prefix +
        r"(?:(?:please|just|go\s+ahead\s+and|let\s*s|lets|can\s+you|could\s+you)\s+)*(?:compact|condense|compress)(?:\s+(?:it|this|that|now|please|for\s+me))*$",
        clean,
    ):
        return "compact"
    if has_new_thread:
        tail = clean[new_thread_matches[-1].end() :].strip()
        tail = re.sub(
            r"^(?:\s*(?:(?:a\s+)?(?:fresh|new|clean)\s+one|(?:in|for|on)\s+(?:the\s+)?[a-z0-9_-]+(?:\s+(?:workspace|repo|project))?|"
            r"right\s+now|now|for\s+me|please" + _alternation(vocab.tail_phrases) + (f"|{names}" if names else "") + r"))+\b\s*",
            "",
            tail,
        ).strip()
        if tail and (
            len(tail.split()) >= 5
            or re.match(
                r"^(?:(?:and|to)\s+)?(?:move|fix|update|change|add|remove|delete|implement|build|"
                r"refactor|debug|investigate|diagnose|audit|check|align|replace|rename|wire)\b",
                tail,
            )
        ):
            return None
        return "new_conversation"
    return None


__all__ = [
    "GENERIC_VOICE_VOCABULARY", "VoiceVocabulary", "detect_voice_lifecycle_intent",
]
