"""
Scenario Archival Service.
Manages scenario archival state transitions, baseline/active plan protection,
and forecast cache invalidation.
"""

from __future__ import annotations

from typing import Any

import forecast_cache
import forecast_engine


def toggle_scenario_archived(
    family_id: int,
    scenario_id: str,
    archived: bool | None = None,
    engine: Any = None,
    cache: Any = None,
) -> tuple[bool, str | None, bool]:
    """
    Toggles or sets the archived status of a scenario.
    Prevents archiving 'scen_baseline' and the current active plan of record.
    Invalidates the household forecast cache upon state change.
    """
    if scenario_id == "scen_baseline":
        return False, "Cannot archive the Baseline Plan", False

    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    active_id = state.get("active_scenario_id", "scen_baseline")
    scenarios = state.get("scenarios", [])

    existing = next((s for s in scenarios if s.get("id") == scenario_id), None)
    if not existing:
        return False, f"Scenario '{scenario_id}' not found", False

    current_archived = bool(existing.get("is_archived", False))
    new_state = (not current_archived) if archived is None else bool(archived)

    if new_state and scenario_id == active_id:
        return False, "Cannot archive the active Plan of Record. Set another plan as active first.", False

    existing["is_archived"] = new_state
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)
    return True, None, new_state
