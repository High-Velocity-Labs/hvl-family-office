"""
forecast/event_schema_migration.py: one-off migration of stored scenario state to the current event schema.

Two legacy shapes are rewritten when a household's state is loaded (and persisted by the next save):
- A child scenario that stores only a full `event_ids` list (no `added_event_ids` / `excluded_event_ids`) gets
  the two lists that express the same selection relative to its parent; one that stores only `excluded_event_ids`
  gets the `added_event_ids` its `event_ids` imply. The hierarchy resolver reads only the lists.
- `active_baseline_layers` stored at the top of the state (as well as on the Baseline Plan) moves onto the
  Baseline Plan, the single place the resolver reads it from.
Both steps are idempotent: migrated state is left alone.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

BASELINE_IDS = ("scen_baseline", "baseline")


def _id_list(scen: Dict[str, Any], key: str) -> List[str]:
    value = scen.get(key)
    return [eid for eid in value if eid] if isinstance(value, list) else []


def _base_events(
    sid: str, by_id: Dict[str, Dict[str, Any]], memo: Dict[str, List[str]], trail: frozenset
) -> List[str]:
    """The events scenario `sid` runs with before baseline overlays, from its (already migrated) stored lists."""
    if sid in memo:
        return memo[sid]
    scen = by_id[sid]
    parent_id = scen.get("parent_id")
    own = _id_list(scen, "event_ids")
    if parent_id and parent_id != sid and parent_id in by_id and parent_id not in trail:
        parent_events = _base_events(parent_id, by_id, memo, trail | {sid})
        curr = set(own)
        added = [eid for eid in _id_list(scen, "added_event_ids") if not curr or eid in curr]
        added_set = set(added)
        excluded = {
            eid
            for eid in _id_list(scen, "excluded_event_ids")
            if eid not in added_set and (not curr or eid not in curr)
        }
        kept = [e for e in parent_events if e not in excluded]
        events = list(dict.fromkeys(kept + [e for e in added if e not in excluded]))
    else:
        events = own
    memo[sid] = events
    return events


def _migrate_scenario(sid: str, by_id: Dict[str, Dict[str, Any]], memo: Dict[str, List[str]], trail: frozenset) -> bool:
    scen = by_id[sid]
    parent_id = scen.get("parent_id")
    if not parent_id or parent_id == sid or parent_id not in by_id or parent_id in trail:
        return False
    # A legacy parent first: its lists define what it passes down.
    changed = _migrate_scenario(parent_id, by_id, memo, trail | {sid})
    added_missing = not isinstance(scen.get("added_event_ids"), list)
    excluded_missing = not isinstance(scen.get("excluded_event_ids"), list)
    if not (added_missing or excluded_missing):
        return changed
    parent_events = _base_events(parent_id, by_id, memo, trail | {sid})
    curr_events = _id_list(scen, "event_ids")
    curr = set(curr_events)
    parent_set = set(parent_events)
    if added_missing:
        scen["added_event_ids"] = list(dict.fromkeys(eid for eid in curr_events if eid not in parent_set))
    if excluded_missing:
        # Only the full-list form (neither list stored) derives exclusions from what the child left out. An empty
        # event_ids carries no selection (storage writes [] for a missing key): the child inherits every event.
        left_out = [eid for eid in parent_events if curr and eid not in curr] if added_missing else []
        scen["excluded_event_ids"] = [eid for eid in left_out if eid not in set(scen["added_event_ids"])]
    return True


def migrate_legacy_event_lists(scenarios: List[Dict[str, Any]]) -> bool:
    """Gives every legacy child scenario its added/excluded lists, parents first. Returns True when anything changed."""
    by_id = {s["id"]: s for s in scenarios if s.get("id")}
    memo: Dict[str, List[str]] = {}
    changed = False
    for sid in by_id:
        changed |= _migrate_scenario(sid, by_id, memo, frozenset())
    return changed


def migrate_layers_to_baseline(state: Dict[str, Any]) -> bool:
    """Moves a state-level `active_baseline_layers` onto the Baseline Plan (which wins when it already has one)."""
    if "active_baseline_layers" not in state:
        return False
    top = state.pop("active_baseline_layers")
    baseline: Optional[Dict[str, Any]] = next(
        (s for s in state.get("scenarios", []) if s.get("id") in BASELINE_IDS or s.get("is_baseline")), None
    )
    if baseline is not None and not isinstance(baseline.get("active_baseline_layers"), list) and isinstance(top, list):
        baseline["active_baseline_layers"] = list(top)
    return True


def migrate_scenario_state(state: Dict[str, Any]) -> bool:
    """Applies every one-off scenario-state migration in place. Returns True when the stored form changed."""
    scenarios = [s for s in state.get("scenarios", []) if isinstance(s, dict)]
    changed = migrate_legacy_event_lists(scenarios)
    return migrate_layers_to_baseline(state) or changed
