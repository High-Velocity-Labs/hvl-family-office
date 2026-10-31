"""
View-models for the AI advisor drawer fragments (message bubbles, welcome message, thread cards, suggestion chips,
quota label, demo notices). The browser only swaps the rendered HTML; no markup is built in JS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from markupsafe import Markup, escape

from ssr.advisor_greetings import ADVISOR_TAB_GREETINGS
from ssr.advisor_markdown import render_advisor_markdown

DEFAULT_TAB = "section-overview"
DEMO_NOTICE = (
    "To protect API quotas, the AI Advisor is in demo mode and will not give you real financial answers. "
    "Sign in with an authorized household account for personalized guidance."
)
FALLBACK_REASON = (
    "Gemini free-tier rate limit or offline mode active. Answering from local deterministic calculation engine."
)
TAB_PRETTY_NAMES = {
    "section-overview": "Overview", "section-equity": "Equity", "section-scenarios": "Forecasting",
    "section-holdings": "Investments", "section-arbitrage": "Tax Arbitrage", "section-withholding": "Withholding",
    "section-philanthropy": "Philanthropy", "section-gifting": "Gifting", "section-college": "Education",
    "section-transcripts": "Transcripts", "section-compensation": "Compensation", "section-accounts": "Accounts",
    "section-estate": "Estate",
}
CONV_FILTERS = ("all", "current-page", "pinned")


def build_message_vm(
    sender: str, text: str, *, demo: bool = False, fallback: bool = False, reason: str = "", badge: str = ""
) -> dict[str, Any]:
    """One chat bubble. Users' text is escaped with line breaks kept; bot text is rendered Markdown."""
    is_user = sender == "user"
    kind = "user" if is_user else ("demo" if demo else ("fallback" if fallback else "bot"))
    body = escape(text or "").replace("\n", Markup("<br>")) if is_user else render_advisor_markdown(text)
    return {
        "is_user": is_user,
        "kind": kind,
        "body": body,
        "fallback_reason": (reason or FALLBACK_REASON) if (fallback and not is_user) else "",
        "badge": badge if not is_user else "",
    }


def build_welcome_vm(tab: str) -> dict[str, Any]:
    info = ADVISOR_TAB_GREETINGS.get(tab) or ADVISOR_TAB_GREETINGS[DEFAULT_TAB]
    return {"text": Markup(info["text"]), "prompt": info["prompt"]}


def relative_time(stamp: str | None, now: datetime | None = None) -> str:
    """'Just now' / '5m ago' / '3h ago' / '2d ago' / 'Oct 4' for a UTC timestamp; empty when absent or unparseable."""
    if not stamp:
        return ""
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return str(stamp)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = int(((now or datetime.now(timezone.utc)) - then).total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 604800:
        return f"{seconds // 86400}d ago"
    return f"{then.strftime('%b')} {then.day}"


def build_conversation_cards(
    conversations: Iterable[dict[str, Any]], *, view: str, query: str, tab: str, active_id: str
) -> list[dict[str, Any]]:
    """Filters the saved threads (this page / pinned / search over title, last message, section) into card rows."""
    needle = (query or "").strip().lower()
    cards = []
    for conv in conversations:
        if view == "current-page" and conv.get("page_section") != tab:
            continue
        if view == "pinned" and not conv.get("is_pinned"):
            continue
        haystack = (conv.get("title"), conv.get("last_message"), conv.get("page_section"))
        if needle and not any(needle in str(part).lower() for part in haystack if part):
            continue
        cards.append({
            "id": conv["conversation_id"],
            "active": conv["conversation_id"] == active_id,
            "pinned": bool(conv.get("is_pinned")),
            "title": conv.get("title") or "",
            "snippet": conv.get("last_message") or "",
            "page_label": TAB_PRETTY_NAMES.get(conv.get("page_section"), "General"),
            "time_ago": relative_time(conv.get("updated_at")),
        })
    return cards


def build_quota_vm(tier: str, label: str) -> dict[str, Any]:
    byo = tier == "byo"
    return {
        "byo": byo,
        "label": label or ("30/min · 300/hr" if byo else "5/min · 30/hr"),
        "link_text": "Manage Key →" if byo else "BYO Key for higher limits →",
    }
