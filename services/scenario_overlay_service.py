"""
services/scenario_overlay_service.py: Stackable Baseline Overlays Service.
Manages household active baseline overlay layers, layer order transitions,
state persistence, forecast cache invalidation, and scenario event management.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import forecast_cache
import forecast_engine


def get_active_baseline_layers(
    family_id: int,
    engine: Any = None,
) -> List[str]:
    """Retrieves the list of active baseline overlay scenario IDs for the household."""
    eng = engine or forecast_engine
    state = eng.load_scenario_state(family_id=family_id)
    layers = state.get("active_baseline_layers")
    if not isinstance(layers, list):
        # Fallback: check if stored on baseline scenario
        for s in state.get("scenarios", []):
            if s.get("id") in ("scen_baseline", "baseline") or s.get("is_baseline"):
                bl_layers = s.get("active_baseline_layers")
                if isinstance(bl_layers, list):
                    layers = bl_layers
                    break
    return [str(x) for x in (layers or []) if str(x).strip()]


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

    state["active_baseline_layers"] = current_layers
    for s in scenarios:
        if s.get("id") in ("scen_baseline", "baseline") or s.get("is_baseline"):
            s["active_baseline_layers"] = list(current_layers)

    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)

    if db_module and db_path:
        scen_name = existing.get("name") or scenario_id
        action = "merged into Baseline" if new_active else "unmerged from Baseline"
        try:
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
        except Exception:
            pass

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

    state["active_baseline_layers"] = ordered
    for s in scenarios:
        if s.get("id") in ("scen_baseline", "baseline") or s.get("is_baseline"):
            s["active_baseline_layers"] = list(ordered)

    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)
    return True, None, ordered


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
    cch.invalidate_family_cache(family_id)


def save_scenario_event(
    family_id: int,
    data: Dict[str, Any],
    engine: Any = None,
    cache: Any = None,
) -> Tuple[bool, Optional[str]]:
    """Validates and persists a forecast event, updating existing records or appending new ones."""
    import config
    from routes.helpers import sanitize_text

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
    if existing:
        existing.update(data)
    else:
        if len(events) >= config.MAX_FORECAST_EVENTS:
            return False, f"Maximum of {config.MAX_FORECAST_EVENTS} forecast events per household reached."
        events.append(data)

    state["events"] = events
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)
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
    cch.invalidate_family_cache(family_id)
