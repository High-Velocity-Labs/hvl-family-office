"""
Scenario Reorder Service.
Manages household scenario display order in comparison and scorecard panels,
preserving unlisted scenarios and invalidating forecast caches upon mutation.
"""

from __future__ import annotations

from typing import Any

import db
import forecast_cache
import forecast_engine


def reorder_scenarios(
    family_id: int,
    order_ids: list[str],
    engine: Any = None,
    cache: Any = None,
) -> tuple[bool, str | None]:
    """
    Reorders state["scenarios"] according to order_ids while preserving unlisted
    scenarios at the end. Saves state and invalidates household forecast cache.
    """
    if not isinstance(order_ids, list) or not order_ids:
        return False, "Scenario order list is required and cannot be empty"

    clean_order_ids = [str(x).strip() for x in order_ids if str(x).strip()]
    if not clean_order_ids:
        return False, "Scenario order list is required and cannot be empty"

    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    scenarios = state.get("scenarios", [])

    by_id = {s.get("id"): s for s in scenarios if s.get("id")}
    reordered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for oid in clean_order_ids:
        if oid in by_id and oid not in seen_ids:
            reordered.append(by_id[oid])
            seen_ids.add(oid)

    for s in scenarios:
        sid = s.get("id")
        if sid not in seen_ids:
            reordered.append(s)
            if sid:
                seen_ids.add(sid)

    state["scenarios"] = reordered
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)
    return True, None


def emit_reorder_notification(
    db_path: Any,
    family_id: int,
    user: str = "",
    user_email: str = "",
) -> None:
    """Emits collaboration notification for scenario reordering."""
    db.notifications.emit_family_notification(
        db_path,
        family_id=family_id,
        category="collaboration",
        dedupe_key="collab:scenarios:reorder",
        deep_link="/scenarios",
        title="Scenarios reordered",
        body=f"{user or 'A household member'} reordered scenarios.",
        sender_email=str(user_email or ""),
        sender_name=str(user or ""),
    )
