"""
services/scenario_overlay_service.py: Stackable Baseline Overlays Service.
Manages household active baseline overlay layers, layer order transitions,
state persistence, forecast cache invalidation, and scenario event management.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from forecast import cache as forecast_cache
from forecast import engine as forecast_engine


def _baseline_scenario(scenarios: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The Baseline Plan, the one scenario that stores `active_baseline_layers`."""
    return next((s for s in scenarios if s.get("id") in ("scen_baseline", "baseline") or s.get("is_baseline")), None)


def _stored_ids(baseline: Optional[Dict[str, Any]], key: str) -> List[str]:
    """A list of scenario ids stored on the Baseline Plan under `key` (`active_baseline_layers` or
    `suspended_baseline_layers`)."""
    ids = baseline.get(key) if baseline else None
    return [str(x) for x in (ids if isinstance(ids, list) else []) if str(x).strip()]


def get_active_baseline_layers(
    family_id: int,
    engine: Any = None,
) -> List[str]:
    """Retrieves the household's merged baseline overlay scenario IDs in stack order (switched-off ones included)."""
    eng = engine or forecast_engine
    state = eng.load_scenario_state(family_id=family_id)
    return _stored_ids(_baseline_scenario(state.get("scenarios", [])), "active_baseline_layers")


def get_suspended_baseline_layers(
    family_id: int,
    engine: Any = None,
) -> List[str]:
    """Retrieves the merged overlays that are switched off: they keep their place in the stack but are not applied."""
    eng = engine or forecast_engine
    state = eng.load_scenario_state(family_id=family_id)
    return _stored_ids(_baseline_scenario(state.get("scenarios", [])), "suspended_baseline_layers")


def toggle_baseline_layer(
    family_id: int,
    scenario_id: str,
    active: Optional[bool] = None,
    engine: Any = None,
    cache: Any = None,
    db_module: Any = None,
    db_path: Any = None,
    user_name: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Tuple[bool, Optional[str], bool, List[str]]:
    """
    Toggles or sets the active baseline overlay status of a scenario.
    Prevents toggling 'scen_baseline' into its own baseline layers.
    Saves updated state and invalidates household forecast cache.
    """
    if not scenario_id or scenario_id in ("scen_baseline", "baseline"):
        return False, "Cannot toggle the Baseline Plan as an overlay onto itself", False, []

    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    scenarios = state.get("scenarios", [])

    existing = next((s for s in scenarios if s.get("id") == scenario_id), None)
    if not existing:
        return False, f"Scenario '{scenario_id}' not found", False, []

    current_layers = get_active_baseline_layers(family_id=family_id, engine=eng)
    is_currently_active = scenario_id in current_layers
    new_active = (not is_currently_active) if active is None else bool(active)

    if new_active:
        if scenario_id not in current_layers:
            current_layers.append(scenario_id)
    else:
        current_layers = [lid for lid in current_layers if lid != scenario_id]

    baseline = _baseline_scenario(scenarios)
    if baseline is not None:
        baseline["active_baseline_layers"] = list(current_layers)
        # A fresh merge starts switched on, and an unmerged plan has nothing left to switch.
        baseline["suspended_baseline_layers"] = [
            lid for lid in _stored_ids(baseline, "suspended_baseline_layers") if lid != scenario_id
        ]

    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id, domains=["scenarios"])

    if db_module and db_path:
        scen_name = existing.get("name") or scenario_id
        action = "merged into Baseline" if new_active else "unmerged from Baseline"
        db_module.notifications.emit_family_notification(
            db_path,
            family_id=family_id,
            category="collaboration",
            dedupe_key=f"collab:baseline_overlay:{scenario_id}:{new_active}",
            deep_link="/scenarios",
            title=f"Baseline overlay updated: {scen_name}",
            body=f"{user_name or 'A household member'} {action} scenario '{scen_name}'.",
            sender_email=str(user_email or ""),
            sender_name=str(user_name or ""),
        )

    return True, None, new_active, current_layers


def reorder_baseline_layers(
    family_id: int,
    layer_ids: List[str],
    engine: Any = None,
    cache: Any = None,
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Reorders active baseline overlay layers according to layer_ids.
    Filters out invalid or missing scenario IDs, saves state, and invalidates cache.
    """
    if not isinstance(layer_ids, list):
        return False, "Layer IDs must be a list", []

    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    scenarios = state.get("scenarios", [])
    valid_ids = {s.get("id") for s in scenarios if s.get("id") and s.get("id") not in ("scen_baseline", "baseline")}

    ordered = [str(lid).strip() for lid in layer_ids if str(lid).strip() in valid_ids]
    # Deduplicate while preserving order
    ordered = list(dict.fromkeys(ordered))

    baseline = _baseline_scenario(scenarios)
    if baseline is not None:
        baseline["active_baseline_layers"] = list(ordered)
        baseline["suspended_baseline_layers"] = [
            lid for lid in _stored_ids(baseline, "suspended_baseline_layers") if lid in ordered
        ]

    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id, domains=["scenarios"])
    return True, None, ordered


def set_baseline_layer_suspended(
    family_id: int,
    scenario_id: str,
    suspended: Optional[bool] = None,
    engine: Any = None,
    cache: Any = None,
) -> Tuple[bool, Optional[str], bool, List[str]]:
    """
    Switches a merged overlay off (or back on) without unmerging it: it keeps its place in the stack,
    and the Baseline Plan and its children resolve without it while it is off.
    `suspended=None` flips the current setting. Returns (ok, error, is_suspended, suspended_ids).
    """
    eng = engine or forecast_engine
    cch = cache or forecast_cache

    state = eng.load_scenario_state(family_id=family_id)
    baseline = _baseline_scenario(state.get("scenarios", []))
    stacked = _stored_ids(baseline, "active_baseline_layers")
    if baseline is None or scenario_id not in stacked:
        return False, f"Scenario '{scenario_id}' is not merged into the Baseline Plan", False, []

    current = [lid for lid in _stored_ids(baseline, "suspended_baseline_layers") if lid in stacked]
    new_suspended = (scenario_id not in current) if suspended is None else bool(suspended)
    if new_suspended and scenario_id not in current:
        current.append(scenario_id)
    elif not new_suspended:
        current = [lid for lid in current if lid != scenario_id]

    baseline["suspended_baseline_layers"] = current
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id, domains=["scenarios"])
    return True, None, new_suspended, current


def apply_scenario_extra_fields(
    family_id: int,
    data: Dict[str, Any],
    engine: Any = None,
    cache: Any = None,
) -> None:
    """Applies secondary scenario metadata (drawdown order, LP calls, archival flags)."""
    if not any(k in data for k in ("drawdown_order", "accelerate_lp_calls", "is_archived")):
        return
    eng = engine or forecast_engine
    cch = cache or forecast_cache
    state = eng.load_scenario_state(family_id=family_id)
    scen_id = data.get("id")
    scen = next((s for s in state.get("scenarios", []) if s.get("id") == scen_id), None)
    if not scen:
        return
    if "drawdown_order" in data:
        scen["drawdown_order"] = str(data["drawdown_order"]).lower().strip()
    if "accelerate_lp_calls" in data:
        scen["accelerate_lp_calls"] = bool(data["accelerate_lp_calls"])
    if "is_archived" in data:
        val = bool(data["is_archived"])
        active_id = state.get("active_scenario_id")
        scen["is_archived"] = False if (val and (scen_id in ("scen_baseline", active_id))) else val
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id, domains=["scenarios"])


def save_scenario_event(
    family_id: int,
    data: Dict[str, Any],
    engine: Any = None,
    cache: Any = None,
) -> Tuple[bool, Optional[str]]:
    """Validates and persists a forecast event, updating existing records or appending new ones."""
    import config
    from forecast.event_amounts import resolve_amount_basis
    from services.request_context import sanitize_text

    try:
        evt_id = sanitize_text(data.get("id"), max_length=100, field_name="Event id", required=True)
        name = sanitize_text(data.get("name"), max_length=100, field_name="Event name", required=True)
        description = sanitize_text(data.get("description", ""), max_length=500, field_name="Event description", multiline=True)
        category = sanitize_text(data.get("category", ""), max_length=50, field_name="Event category")
        icon = sanitize_text(data.get("icon", ""), max_length=60, field_name="Event icon")
    except ValueError as e:
        return False, str(e)

    data["id"] = evt_id
    data["name"] = name
    data["description"] = description
    data["icon"] = icon
    if category:
        data["category"] = category

    eng = engine or forecast_engine
    cch = cache or forecast_cache
    state = eng.load_scenario_state(family_id=family_id)
    events = state.get("events", [])

    existing = next((e for e in events if e.get("id") == evt_id), None)
    if "amount_basis" in data:
        effective_category = data.get("category") or (existing or {}).get("category") or ""
        data["amount_basis"] = resolve_amount_basis(data["amount_basis"], effective_category)
    if existing:
        existing.update(data)
    else:
        if len(events) >= config.MAX_FORECAST_EVENTS:
            return False, f"Maximum of {config.MAX_FORECAST_EVENTS} forecast events per household reached."
        events.append(data)

    state["events"] = events
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id, domains=["scenarios"])
    return True, None


def delete_scenario_event(
    family_id: int,
    event_id: str,
    engine: Any = None,
    cache: Any = None,
) -> None:
    """Removes a forecast event and unbinds it from all scenarios."""
    eng = engine or forecast_engine
    cch = cache or forecast_cache
    state = eng.load_scenario_state(family_id=family_id)
    state["events"] = [e for e in state.get("events", []) if e.get("id") != event_id]
    for scen in state.get("scenarios", []):
        scen["event_ids"] = [eid for eid in scen.get("event_ids", []) if eid != event_id]
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id, domains=["scenarios"])
