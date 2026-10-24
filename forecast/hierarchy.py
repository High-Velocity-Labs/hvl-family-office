"""
forecast/hierarchy.py: Scenario Inheritance & Event Timeline Overlays.
Resolves parent-child scenario inheritance, timeline assumptions, override tracking,
and event set algebra (ancestor inheritance, additions, and exclusions).
Supports stackable baseline overlay layers to dynamically merge candidate plans
into the baseline projection and propagate downstream to all child plans.
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


def _extract_layer_overrides(layer_raw: Dict[str, Any], baseline_raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts explicit non-null assumption overrides defined by a candidate overlay layer."""
    overrides: Dict[str, Any] = {}
    raw_overrides = layer_raw.get("overrides")
    if isinstance(raw_overrides, dict) and raw_overrides:
        for k, v in raw_overrides.items():
            if k in INHERITABLE_ASSUMPTION_KEYS and v is not None and v != "":
                overrides[k] = v

    for k in INHERITABLE_ASSUMPTION_KEYS:
        if k in overrides:
            continue
        v = layer_raw.get(k)
        if v is not None and v != "":
            if layer_raw.get("parent_id"):
                if v != baseline_raw.get(k):
                    overrides[k] = v
            else:
                overrides[k] = v
    return overrides


def resolve_scenario_hierarchy(
    scenarios_list: List[Dict[str, Any]],
    default_assumptions: Optional[Dict[str, Any]] = None,
    active_baseline_layers: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolves parent-child inheritance across scenarios:
    1. Child scenarios inherit events from ancestors, plus their own added_event_ids minus excluded_event_ids.
    2. Child scenarios inherit demographic & timeline assumptions from ancestors, unless explicitly overridden.
    3. Merges stackable baseline overlay layers (active_baseline_layers) onto the Baseline Plan in order,
       propagating composite baseline events and assumptions to all downstream children.
    4. Prevents circular references and gracefully handles missing parents.
    """
    if default_assumptions is None:
        default_assumptions = {}

    scens_by_id = {s["id"]: dict(s) for s in scenarios_list if s.get("id")}
    resolved_cache: Dict[str, Dict[str, Any]] = {}
    visited_stack: set = set()

    # Identify Baseline plan
    baseline_raw = next(
        (s for s in scenarios_list if s.get("id") in ("scen_baseline", "baseline") or s.get("is_baseline")),
        scenarios_list[0] if scenarios_list else None,
    )
    baseline_id = baseline_raw["id"] if baseline_raw else "scen_baseline"

    # Resolve active_baseline_layers if not explicitly passed
    if active_baseline_layers is None:
        for s in scenarios_list:
            if s.get("id") == baseline_id or s.get("is_baseline"):
                if isinstance(s.get("active_baseline_layers"), list):
                    active_baseline_layers = s.get("active_baseline_layers")
                    break
        if active_baseline_layers is None:
            for s in scenarios_list:
                if isinstance(s.get("active_baseline_layers"), list):
                    active_baseline_layers = s.get("active_baseline_layers")
                    break

    clean_layers = [
        str(x).strip() for x in (active_baseline_layers or [])
        if str(x).strip() and str(x).strip() != baseline_id and str(x).strip() in scens_by_id
    ]
    clean_layers = list(dict.fromkeys(clean_layers))

    # Pre-resolve composite baseline if baseline exists
    applied_layer_ids: List[str] = []
    applied_layer_names: List[str] = []
    applied_layers_meta: List[Dict[str, Any]] = []

    if baseline_raw and baseline_id in scens_by_id:
        raw_base = scens_by_id[baseline_id]
        base_event_ids = list(raw_base.get("event_ids") or [])
        base_assumptions: Dict[str, Any] = {}

        # Initial baseline assumptions from raw baseline + defaults
        for key in INHERITABLE_ASSUMPTION_KEYS:
            val = raw_base.get(key)
            if val is not None:
                base_assumptions[key] = val
            elif default_assumptions and default_assumptions.get(key) is not None:
                base_assumptions[key] = default_assumptions.get(key)
            else:
                base_assumptions[key] = None

        # Apply stackable baseline overlays in specified order
        composite_applied_overrides: Dict[str, Any] = {}
        for lid in clean_layers:
            layer_raw = scens_by_id[lid]
            applied_layer_ids.append(lid)
            applied_layer_names.append(layer_raw.get("name") or lid)
            applied_layers_meta.append({
                "id": lid,
                "name": layer_raw.get("name") or lid,
                "color": layer_raw.get("color") or "#3b82f6",
            })

            # 1. Union layer's added_event_ids (and event_ids) into Baseline's event_ids
            layer_added = list(layer_raw.get("added_event_ids") or [])
            for eid in (layer_raw.get("event_ids") or []):
                if eid and eid not in layer_added:
                    layer_added.append(eid)
            layer_excluded = set(layer_raw.get("excluded_event_ids") or [])

            for eid in layer_added:
                if eid not in base_event_ids and eid not in layer_excluded:
                    base_event_ids.append(eid)
            if layer_excluded:
                base_event_ids = [eid for eid in base_event_ids if eid not in layer_excluded]

            # 2. Apply layer's non-null assumption overrides onto Baseline
            overrides = _extract_layer_overrides(layer_raw, raw_base)
            for k, v in overrides.items():
                if k == "equity_growth_presets":
                    current_presets = dict(base_assumptions.get("equity_growth_presets") or {})
                    if isinstance(v, dict):
                        current_presets.update(v)
                        base_assumptions["equity_growth_presets"] = current_presets
                        composite_applied_overrides["equity_growth_presets"] = current_presets
                else:
                    base_assumptions[k] = v
                    composite_applied_overrides[k] = v

        resolved_base = dict(raw_base)
        resolved_base["parent_id"] = None
        resolved_base["parent_name"] = None
        resolved_base["ancestor_ids"] = []
        resolved_base["depth"] = 0
        resolved_base["event_ids"] = base_event_ids
        resolved_base["inherited_event_ids"] = []
        resolved_base["added_event_ids"] = list(base_event_ids)
        resolved_base["excluded_event_ids"] = []
        for k, v in base_assumptions.items():
            resolved_base[k] = v
        resolved_base["overrides"] = composite_applied_overrides
        resolved_base["active_baseline_layers"] = applied_layer_ids
        resolved_base["has_baseline_layers"] = bool(applied_layer_ids)
        resolved_base["applied_layer_names"] = applied_layer_names
        resolved_base["baseline_layer_names"] = applied_layer_names
        resolved_base["baseline_layers"] = applied_layers_meta
        resolved_base["is_baseline_layer"] = False

        resolved_cache[baseline_id] = resolved_base

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
        resolved["is_baseline_layer"] = sid in applied_layer_ids

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

        # For merged baseline layers, preserve their explicit overrides so plan cards reflect what was merged
        if resolved.get("is_baseline_layer") and baseline_raw:
            explicit_layer_overrides = _extract_layer_overrides(raw, baseline_raw)
            if explicit_layer_overrides:
                overrides.update(explicit_layer_overrides)

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
        key=lambda r: (0 if r["id"] == baseline_id or r.get("is_baseline") else 1)
    )
    for root in root_nodes_sorted:
        append_tree(root["id"])

    # 2. Append any remaining or disconnected nodes
    for s in scenarios_list:
        if s["id"] not in visited_ids:
            append_tree(s["id"])

    return ordered_resolved
