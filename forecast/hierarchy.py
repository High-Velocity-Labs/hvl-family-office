"""
forecast/hierarchy.py: Scenario Inheritance & Event Timeline Overlays.
Resolves parent-child scenario inheritance, timeline assumptions, override tracking,
and event set algebra (ancestor inheritance, additions, and exclusions).
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional


INHERITABLE_ASSUMPTION_KEYS = [
    "primary_retirement_age",
    "spouse_retirement_age",
    "annual_living_spend",
    "annual_savings",
    "inflation_rate",
    "equity_growth_preset",
    "equity_growth_presets",
    "custom_equity_growth_rate",
    "ss_claim_age",
    "primary_ss_claim_age",
    "spouse_ss_claim_age",
    "growth_us_equity",
    "growth_intl_equity",
    "growth_bonds",
    "growth_cash",
    "growth_private_investments",
    "growth_real_estate",
    "spending_guardrail_mode",
]


def resolve_scenario_hierarchy(
    scenarios_list: List[Dict[str, Any]],
    default_assumptions: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolves parent-child inheritance across scenarios:
    1. Child scenarios inherit events from ancestors, plus their own added_event_ids minus excluded_event_ids.
    2. Child scenarios inherit demographic & timeline assumptions from ancestors, unless explicitly overridden.
    3. Prevents circular references and gracefully handles missing parents.
    """
    if default_assumptions is None:
        default_assumptions = {}

    scens_by_id = {s["id"]: dict(s) for s in scenarios_list}
    resolved_cache: Dict[str, Dict[str, Any]] = {}
    visited_stack: set = set()

    def get_resolved(sid: str) -> Dict[str, Any]:
        if sid in resolved_cache:
            return resolved_cache[sid]

        raw = scens_by_id.get(sid, {})
        parent_id = raw.get("parent_id")

        # Guard against self-reference, cycles, or non-existent parent
        if (
            parent_id
            and parent_id != sid
            and parent_id in scens_by_id
            and parent_id not in visited_stack
        ):
            visited_stack.add(sid)
            parent_resolved = get_resolved(parent_id)
            visited_stack.remove(sid)
        else:
            parent_resolved = None

        resolved = dict(raw)
        resolved["parent_id"] = parent_id if parent_resolved else None
        resolved["parent_name"] = parent_resolved.get("name") if parent_resolved else None
        resolved["ancestor_ids"] = (
            parent_resolved.get("ancestor_ids", []) + [parent_id]
        ) if parent_resolved else []
        resolved["depth"] = len(resolved["ancestor_ids"])

        # 1. Resolve Events Hierarchy
        if parent_resolved:
            parent_events = list(parent_resolved.get("event_ids", []))
            parent_set = set(parent_events)

            if "event_ids" in raw and raw.get("event_ids") is not None:
                curr_events = list(raw.get("event_ids", []))
                curr_set = set(curr_events)
                explicit_excluded = {eid for eid in raw.get("excluded_event_ids", []) if eid not in curr_set}
                inferred_excluded = {eid for eid in parent_events if eid not in curr_set}
                excluded = explicit_excluded | inferred_excluded

                explicit_added = [eid for eid in raw.get("added_event_ids", []) if eid in curr_set]
                inferred_added = [eid for eid in curr_events if eid not in parent_set]
                added = list(dict.fromkeys(inferred_added + explicit_added))
            elif "added_event_ids" in raw or "excluded_event_ids" in raw:
                added = list(raw.get("added_event_ids", []))
                excluded = set(raw.get("excluded_event_ids", []))
            else:
                added = []
                excluded = set()

            inherited_events = [eid for eid in parent_events if eid not in excluded]
            effective_events = list(dict.fromkeys(inherited_events + [eid for eid in added if eid not in excluded]))
            resolved["event_ids"] = effective_events
            resolved["inherited_event_ids"] = inherited_events
            resolved["added_event_ids"] = added
            resolved["excluded_event_ids"] = list(excluded)
        else:
            effective_events = list(raw.get("event_ids", []))
            resolved["event_ids"] = effective_events
            resolved["inherited_event_ids"] = []
            resolved["added_event_ids"] = effective_events
            resolved["excluded_event_ids"] = []

        # 2. Resolve Assumptions Hierarchy & Track Overrides
        overrides = {}
        for key in INHERITABLE_ASSUMPTION_KEYS:
            val = raw.get(key)
            if key == "equity_growth_presets":
                parent_presets = dict(parent_resolved.get("equity_growth_presets") or {}) if parent_resolved else {}
                if isinstance(val, dict) and bool(val):
                    merged_presets = dict(parent_presets)
                    merged_presets.update(val)
                    resolved["equity_growth_presets"] = merged_presets
                    if parent_resolved and val != parent_presets:
                        overrides["equity_growth_presets"] = val
                elif parent_resolved and parent_presets:
                    resolved["equity_growth_presets"] = parent_presets
                else:
                    resolved["equity_growth_presets"] = None
                continue

            if val is not None:
                resolved[key] = val
                if parent_resolved and val != parent_resolved.get(key):
                    overrides[key] = val
            elif parent_resolved and parent_resolved.get(key) is not None:
                resolved[key] = parent_resolved.get(key)
            elif default_assumptions and default_assumptions.get(key) is not None:
                resolved[key] = default_assumptions.get(key)
            else:
                resolved[key] = None

        if "custom_equity_growth_rate" in overrides and overrides.get("equity_growth_preset") == "custom":
            overrides.pop("equity_growth_preset", None)
        resolved["overrides"] = overrides
        resolved_cache[sid] = resolved
        return resolved

    # Hierarchical tree ordering: Root scenarios first (Baseline at very top),
    # immediately followed by their children and grandchildren so child plans
    # are always placed next to their parent plan across all UI views and matrices.
    children_map: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for s in scenarios_list:
        p_id = s.get("parent_id")
        if p_id not in scens_by_id:
            p_id = None
        children_map.setdefault(p_id, []).append(s)

    ordered_resolved: List[Dict[str, Any]] = []
    visited_ids = set()

    def append_tree(node_id: str):
        if node_id in visited_ids:
            return
        visited_ids.add(node_id)
        ordered_resolved.append(get_resolved(node_id))
        for child in children_map.get(node_id, []):
            append_tree(child["id"])

    # 1. Place Baseline plan first, then other roots
    root_nodes = children_map.get(None, [])
    root_nodes_sorted = sorted(
        root_nodes,
        key=lambda r: (0 if r["id"] == "scen_baseline" or r.get("is_baseline") else 1)
    )
    for root in root_nodes_sorted:
        append_tree(root["id"])

    # 2. Append any remaining or disconnected nodes
    for s in scenarios_list:
        if s["id"] not in visited_ids:
            append_tree(s["id"])

    return ordered_resolved
