"""
Tenant resolution shared by every AI Financial Advisor tool module (`tools_*.py`):
a tool's household always comes from the trusted request or background context.
"""

from __future__ import annotations

from services.request_context import get_current_family_id


def _resolve_tool_family_id(family_id: int = 0) -> int:
    """
    Resolves the household from the trusted request or background context only.
    The model-supplied `family_id` argument is ignored so a tool call can never pick its own tenant.
    """
    return max(get_current_family_id(), 0)
