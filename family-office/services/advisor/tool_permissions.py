"""
services/advisor/tool_permissions.py: Per-turn advisor tool authorization.

Two rules are enforced here, at the one place the advisor's tool list is built for a turn:

1. A caller who may not change household data (`can_mutate()` is False) is never offered write tools.
2. Prompt-injection containment: once a tool that returns untrusted web content has run in a turn
   (`search_live_web`, `fetch_web_page`), every write tool refuses for the rest of that turn so the
   model must ask the user to confirm in their next message.

Tool classification reuses the MCP gateway scopes (`services.mcp_service`): anything the MCP registry
registers as `read` or `simulate` is non-mutating. Untrusted-content tools are not MCP tools. Every
other advisor tool is treated as a write tool (fail closed for newly added tools).
Turn state lives on an `AdvisorTurn` instance, never at module level.
"""

from __future__ import annotations

import functools
import re
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, List, Sequence, Set

from services.request_context import can_mutate

UNTRUSTED_CONTENT_TOOLS: FrozenSet[str] = frozenset({"search_live_web", "fetch_web_page"})

TAINTED_WRITE_REFUSAL = (
    "Refused: this turn already used untrusted web content, so changes to household data are blocked "
    "for the rest of the turn. Tell the user what you intended to change and ask them to confirm "
    "in their next message."
)


MAX_FETCHES_PER_TURN = 5

TAINTED_FETCH_REFUSAL = (
    "Refused: this turn is tainted by untrusted content, so only URLs that a web tool itself returned earlier"
    " can be fetched. Ask the user to confirm any other URL in their next message."
)
FETCH_LIMIT_REFUSAL = f"Refused: at most {MAX_FETCHES_PER_TURN} page fetches are allowed per turn."

_URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")


def _urls_in(text: Any) -> Set[str]:
    return {m.rstrip(".,;:") for m in _URL_PATTERN.findall(text)} if isinstance(text, str) else set()


def _remote_urls(result: Any, call_args: Sequence[Any]) -> Set[str]:
    """
    URLs the remote side produced: grounding `sources[].url` and URLs in the `answer` text.
    Anything the caller passed in as an argument is excluded (a search result must not launder a URL
    that the model, or an injection, supplied), and the echoed `query`/`url` fields are never read.
    """
    if not isinstance(result, dict):
        return set()
    from_sources = {
        str(src["url"]).strip() for src in (result.get("sources") or []) if isinstance(src, dict) and src.get("url")
    }
    echoed: Set[str] = set()
    for arg in call_args:
        echoed |= _urls_in(arg)
    return from_sources | (_urls_in(result.get("answer")) - echoed)


class TurnTrust(Enum):
    CLEAN = "clean"
    TAINTED = "tainted"


def non_mutating_tool_names() -> FrozenSet[str]:
    """Names of advisor tools the MCP gateway classifies as read or simulate, plus untrusted-content readers."""
    from services import mcp_service

    scoped = {name for name, _fn, _desc in (*mcp_service._READ_TOOLS, *mcp_service._SIMULATE_TOOLS)}
    return frozenset(scoped | UNTRUSTED_CONTENT_TOOLS)


def write_tool_names(tools: Sequence[Callable[..., Any]]) -> FrozenSet[str]:
    safe = non_mutating_tool_names()
    return frozenset(t.__name__ for t in tools if t.__name__ not in safe)


class AdvisorTurn:
    """Authorization state for exactly one advisor turn."""

    def __init__(self, trust: TurnTrust = TurnTrust.CLEAN) -> None:
        """`trust` starts TAINTED when the turn's loaded history may contain text from someone other than the caller."""
        self.trust: TurnTrust = trust
        self.fetch_count: int = 0
        self.seen_urls: Set[str] = set()

    def authorize(self, tools: Sequence[Callable[..., Any]]) -> List[Callable[..., Any]]:
        """Returns the turn-bound tool list: write tools dropped for read-only callers, guards on the rest."""
        writes = write_tool_names(tools)
        allow_writes = can_mutate()
        bound: List[Callable[..., Any]] = []
        for tool in tools:
            name = tool.__name__
            if name in writes:
                if allow_writes:
                    bound.append(self._guard_write(tool))
            elif name == "fetch_web_page":
                bound.append(self._guard_fetch(tool))
            elif name in UNTRUSTED_CONTENT_TOOLS:
                bound.append(self._taint_after(tool))
            else:
                bound.append(tool)
        return bound

    def _guard_fetch(self, tool: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(tool)
        def guarded_fetch(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            url = str(kwargs.get("url", args[0] if args else "")).strip()
            if self.fetch_count >= MAX_FETCHES_PER_TURN:
                return {"success": False, "status": "refused_fetch_limit", "answer": FETCH_LIMIT_REFUSAL, "sources": []}
            if self.trust is TurnTrust.TAINTED and url not in self.seen_urls:
                return {"success": False, "status": "refused_tainted_fetch", "answer": TAINTED_FETCH_REFUSAL, "sources": []}
            self.fetch_count += 1
            self.trust = TurnTrust.TAINTED
            result = tool(*args, **kwargs)
            self.seen_urls |= _remote_urls(result, (*args, *kwargs.values()))
            return result

        return guarded_fetch
    def _taint_after(self, tool: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(tool)
        def tainting_tool(*args: Any, **kwargs: Any) -> Any:
            self.trust = TurnTrust.TAINTED
            result = tool(*args, **kwargs)
            self.seen_urls |= _remote_urls(result, (*args, *kwargs.values()))
            return result

        return tainting_tool

    def _guard_write(self, tool: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(tool)
        def guarded_write(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            if self.trust is TurnTrust.TAINTED:
                return {"status": "refused_untrusted_context", "error": TAINTED_WRITE_REFUSAL}
            return tool(*args, **kwargs)

        return guarded_write
