"""
forecast/hierarchy.py: Scenario Inheritance & Event Timeline Overlays.
Resolves parent-child scenario inheritance, timeline assumptions, override tracking,
and event set algebra (ancestor inheritance, additions, and exclusions).
Supports stackable baseline overlay layers to dynamically merge candidate plans
into the baseline projection and propagate downstream to all child plans.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional


INHERITABLE_ASSUMPTION_KEYS = [
    "primary_retirement_age",
    "spouse_retirement_age",
    "annual_living_spend",
    "annual_savings",
    "inflation_rate",
    "education_inflation_rate",
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


GUARDRAIL_MODES = ("off", "moderate", "aggressive")


def normalize_guardrail_mode(raw: Any) -> str:
    """A valid spending-guardrail mode; anything unknown or empty is "off"."""
    mode = str(raw).lower().strip() if raw is not None else ""
    return mode if mode in GUARDRAIL_MODES else "off"


def _id_list(scen: Dict[str, Any], key: str) -> List[str]:
    """The non-empty ids stored under `key`; anything that is not a list counts as no ids."""
    value = scen.get(key)
    return [eid for eid in value if eid] if isinstance(value, list) else []


def _first_set(*values: Any) -> Any:
    """The first value that is not None or "". A deliberate 0 / 0.0 / False counts as set."""
    return next((v for v in values if v is not None and v != ""), None)


@dataclass(frozen=True)
class EffectivePlan:
    """The household-level assumptions one scenario actually runs with, resolved once by `resolve_effective_plan`."""

    primary_retirement_age: Any
    spouse_retirement_age: Any
    annual_living_spend: Any
    annual_savings: Any
    inflation_rate: Any
    primary_ss_claim_age: int
    spouse_ss_claim_age: int
    spending_guardrail_mode: str

    def simulation_kwargs(self) -> Dict[str, Any]:
        """The plan values `forecast.waterfall.run_scenario_simulation` takes; the engine has no defaults of its own."""
        return {
            "primary_retirement_age": self.primary_retirement_age,
            "spouse_retirement_age": self.spouse_retirement_age,
            "annual_spending": self.annual_living_spend,
            "annual_savings": self.annual_savings,
            "inflation_rate": self.inflation_rate,
            "primary_ss_claim_age": self.primary_ss_claim_age,
            "spouse_ss_claim_age": self.spouse_ss_claim_age,
        }


def resolve_effective_plan(
    scen: Dict[str, Any],
    base_params: Dict[str, Any],
    explicit_flags: Dict[str, bool],
    is_target: bool,
) -> EffectivePlan:
    """
    The single resolver for a scenario's run-time assumptions. `scen` is already hierarchy-resolved
    (parent values and profile defaults filled in); `base_params` are the run's profile values.
    Precedence: an explicit run argument on the target scenario, then the scenario's own value, then the
    base value. "Set" means not None: a deliberate 0 spend or savings is kept, never replaced by the base.
    """
    def pick(flag: str, key: str, *fallbacks: Any) -> Any:
        if is_target and explicit_flags.get(flag):
            return base_params[key]
        return _first_set(scen.get(key), *fallbacks, base_params[key])

    ss_generic = scen.get("ss_claim_age")
    guardrail = (
        base_params.get("spending_guardrail_mode")
        if is_target and explicit_flags.get("guardrails")
        else scen.get("spending_guardrail_mode")
    )
    return EffectivePlan(
        primary_retirement_age=pick("primary_ret", "primary_retirement_age"),
        spouse_retirement_age=pick("spouse_ret", "spouse_retirement_age"),
        annual_living_spend=pick("spending", "annual_living_spend"),
        annual_savings=pick("savings", "annual_savings"),
        inflation_rate=pick("inflation", "inflation_rate"),
        primary_ss_claim_age=int(pick("primary_ss", "primary_ss_claim_age", ss_generic)),
        spouse_ss_claim_age=int(pick("spouse_ss", "spouse_ss_claim_age", ss_generic)),
        spending_guardrail_mode=normalize_guardrail_mode(guardrail),
    )


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
    suspended_baseline_layers: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolves parent-child inheritance across scenarios:
    1. Child scenarios inherit events from ancestors, plus their own added_event_ids minus excluded_event_ids.
    2. Child scenarios inherit demographic & timeline assumptions from ancestors, unless explicitly overridden.
    3. Merges stackable baseline overlay layers (active_baseline_layers) onto the Baseline Plan in order,
       propagating composite baseline events and assumptions to all downstream children.
       A suspended layer (suspended_baseline_layers) keeps its place in the stack but is skipped,
       so it resolves like any other child plan until it is switched back on.
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

    # The Baseline Plan is the one place `active_baseline_layers` is stored.
    if active_baseline_layers is None and baseline_raw and isinstance(baseline_raw.get("active_baseline_layers"), list):
        active_baseline_layers = baseline_raw["active_baseline_layers"]

    clean_layers = [
        str(x).strip() for x in (active_baseline_layers or [])
        if str(x).strip() and str(x).strip() != baseline_id and str(x).strip() in scens_by_id
    ]
    clean_layers = list(dict.fromkeys(clean_layers))

    stored_suspended = baseline_raw.get("suspended_baseline_layers") if baseline_raw else None
    if suspended_baseline_layers is None and isinstance(stored_suspended, list):
        suspended_baseline_layers = stored_suspended
    suspended_ids = {str(x).strip() for x in (suspended_baseline_layers or [])} & set(clean_layers)

    # Pre-resolve composite baseline if baseline exists
    applied_layer_ids: List[str] = []
    applied_layer_names: List[str] = []
    stacked_layers_meta: List[Dict[str, Any]] = [
        {
            "id": lid,
            "name": scens_by_id[lid].get("name") or lid,
            "color": scens_by_id[lid].get("color") or "#3b82f6",
            "suspended": lid in suspended_ids,
        }
        for lid in clean_layers
    ]

    if baseline_raw and baseline_id in scens_by_id:
        raw_base = scens_by_id[baseline_id]
        raw_base_events = list(raw_base.get("event_ids") or [])
        base_event_ids = list(raw_base_events)
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
            if lid in suspended_ids:
                continue
            layer_raw = scens_by_id[lid]
            applied_layer_ids.append(lid)
            applied_layer_names.append(layer_raw.get("name") or lid)

            # 1. Union the layer's added_event_ids into Baseline's event_ids and drop its excluded_event_ids.
            # A layer stores both lists (forecast/event_schema_migration.py upgrades the legacy full-list form);
            # a root layer with no lists adds all of its events.
            if isinstance(layer_raw.get("added_event_ids"), list) or layer_raw.get("parent_id"):
                layer_added = _id_list(layer_raw, "added_event_ids")
            else:
                layer_added = _id_list(layer_raw, "event_ids")
            layer_excluded = set(_id_list(layer_raw, "excluded_event_ids")) - set(layer_added)

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
        resolved_base["raw_event_ids"] = raw_base_events
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
        # Every merged layer in stack order, switched-off ones flagged `suspended`.
        resolved_base["baseline_layers"] = stacked_layers_meta
        resolved_base["suspended_baseline_layers"] = [lid for lid in clean_layers if lid in suspended_ids]
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
        resolved["is_suspended_baseline_layer"] = sid in suspended_ids

        # 1. Resolve Events Hierarchy
        if parent_resolved:
            if resolved.get("is_baseline_layer") and parent_id == baseline_id and baseline_raw:
                parent_events = list(baseline_raw.get("event_ids", []))
                unoverlaid_parent_events = list(parent_events)
            else:
                parent_events = list(parent_resolved.get("event_ids", []))
                unoverlaid_parent_events = list(parent_resolved.get("raw_event_ids", parent_events))
            parent_set = set(parent_events)
            unoverlaid_parent_set = set(unoverlaid_parent_events)

            curr_events = _id_list(raw, "event_ids")
            curr_set = set(curr_events)
            # A child stores only its additions and exclusions (forecast/event_schema_migration.py upgrades the
            # legacy full-list form on load); a non-empty event_ids only narrows them to the saved selection.
            own_added = [eid for eid in _id_list(raw, "added_event_ids") if not curr_set or eid in curr_set]
            own_added_set = set(own_added)
            own_excluded = {
                eid for eid in _id_list(raw, "excluded_event_ids")
                if eid not in own_added_set and (not curr_set or eid not in curr_set)
            }

            raw_inherited = [eid for eid in unoverlaid_parent_events if eid not in own_excluded]
            resolved["raw_event_ids"] = list(dict.fromkeys(raw_inherited + [eid for eid in own_added if eid not in own_excluded]))

            added = [eid for eid in own_added if eid not in parent_set]
            excluded = {eid for eid in own_excluded if eid in parent_set}

            inherited_events = [eid for eid in parent_events if eid not in excluded]
            effective_events = list(dict.fromkeys(inherited_events + [eid for eid in added if eid not in excluded]))
            resolved["event_ids"] = effective_events
            resolved["inherited_event_ids"] = inherited_events
            resolved["added_event_ids"] = [eid for eid in added if eid not in excluded]
            resolved["excluded_event_ids"] = [eid for eid in excluded if eid in parent_set and eid not in effective_events]
        else:
            effective_events = list(raw.get("event_ids", []))
            resolved["raw_event_ids"] = list(effective_events)
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

        # A scenario's own generic ss_claim_age is its claim-age override for both spouses;
        # it must win over the claim age inherited from the parent for the per-person keys.
        own_ss = raw.get("ss_claim_age")
        if own_ss not in (None, ""):
            for person_key in ("primary_ss_claim_age", "spouse_ss_claim_age"):
                if raw.get(person_key) in (None, ""):
                    resolved[person_key] = own_ss
                    if parent_resolved and own_ss != parent_resolved.get(person_key):
                        overrides[person_key] = own_ss

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
