"""
Estate Tax Profile tool for the AI Financial Advisor: federal vs. state death taxes,
the federal-exemption rollback stress test, and SLAT/IDGT/ILIT trusts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services import estate_engine
from services.advisor.tool_errors import ADVISOR_TOOL_ERRORS
from services.advisor.tools_core import _resolve_tool_family_id

logger = logging.getLogger(__name__)


def get_estate_tax_summary(
    family_id: int = 0,
    state_override: Optional[str] = None,
    apply_tcja_sunset: Optional[bool] = None,
) -> Dict[str, Any]:
    """Retrieves family estate tax calculations, federal vs. state death taxes, a federal-exemption rollback stress test, and SLAT/IDGT/ILIT trusts."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        kwargs: Dict[str, Any] = {"family_id": fam_id}
        if state_override:
            kwargs["state_override"] = str(state_override).strip().upper()
        if apply_tcja_sunset is not None:
            kwargs["apply_tcja_sunset"] = bool(apply_tcja_sunset)
        return estate_engine.get_family_estate_profile(**kwargs)
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error getting estate tax profile: %s", e)
        return {"error": str(e), "status": "unavailable"}
