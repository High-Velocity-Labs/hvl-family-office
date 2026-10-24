"""
SSR Builders for Multi-Scenario Scorecard Comparison Rows.
Re-exports assumption and override helpers from `ssr.scenarios_overrides`.
"""

from __future__ import annotations
from typing import Any, Dict, List

from ssr.formatting import fmt_short_currency
from ssr.scenarios_overrides import (
    _OVERRIDE_LABEL_MAP,
    _EQUITY_PRESET_LABELS,
    format_equity_preset_label,
    format_override_value,
    build_assumptions_and_overrides,
)
from ssr.scenarios_shelf import cat_badge, cat_border

_SCORECARD_EQ_BADGE_MAP: Dict[str, str] = {
    "baseline_curve": "Baseline Curve 409A",
    "aggressive": "Aggressive 409A",
    "moderate": "Moderate 409A",
    "conservative": "Conservative 409A",
    "flat": "Flat 409A",
    "custom": "Custom 409A",
}


def build_scorecard_rows(
    scorecard_items: List[Dict[str, Any]],
    catalog: Dict[Any, Dict[str, Any]],
    scen_name_by_id: Dict[Any, Any],
    active_scen_id: str,
    default_scen_id: str,
    p_cur_age: int,
    s_cur_age: int,
) -> List[Dict[str, Any]]:
    """Builds the side-by-side scenario scorecard comparison table rows."""
    active_layer_ids = set()
    for sc in scorecard_items:
        if not isinstance(sc, dict):
            continue
        if sc.get("is_baseline") or sc.get("id") == "scen_baseline":
            for lyr in (sc.get("active_baseline_layers") or []):
                active_layer_ids.add(str(lyr))
            for lyr in (sc.get("baseline_layers") or []):
                if isinstance(lyr, dict) and lyr.get("id"):
                    active_layer_ids.add(str(lyr["id"]))
                elif isinstance(lyr, str):
                    active_layer_ids.add(lyr)
        if sc.get("is_baseline_layer"):
            active_layer_ids.add(str(sc.get("id")))

    scorecard_rows: List[Dict[str, Any]] = []
    for sc in scorecard_items:
        if not isinstance(sc, dict):
            continue
        sc_id = sc.get("id") or ""
        sc_readiness = sc.get("retirement_readiness") or {}
        sc_is_dep = bool(sc.get("is_depleted"))
        sc_is_sust = (sc_readiness.get("is_sustainable") is True) and not sc_is_dep
        sc_can_now = sc_is_sust and (sc_readiness.get("can_retire_today") is True)

        sc_p_plan_age = sc_readiness.get("primary_planned_age") or sc.get("primary_retirement_age") or 50
        sc_p_plan_yr = sc_readiness.get("primary_planned_year") or sc.get("primary_retirement_year") or 2027
        sc_p_ear_age = sc_readiness.get("earliest_primary_age")
        sc_s_plan_age = sc_readiness.get("spouse_planned_age") or sc.get("spouse_retirement_age") or 52
        sc_s_plan_yr = sc_readiness.get("spouse_planned_year") or sc.get("spouse_retirement_year") or 2031
        sc_s_ear_age = sc_readiness.get("earliest_spouse_age")
        sc_ear_joint_yr = sc_readiness.get("earliest_joint_year")

        if sc_can_now:
            p_ret_badge = "badge-green"
            p_ret_text = f"Now (Age {p_cur_age})"
            p_ret_sub = f"Plan: Age {sc_p_plan_age} ({sc_p_plan_yr})"
            p_ret_sub_red = False
            p_ret_tooltip = f"Financially independent today at Age {p_cur_age} (Planned target: Age {sc_p_plan_age} in {sc_p_plan_yr})"
        elif sc_is_sust:
            p_ret_badge = "badge-blue"
            p_ret_text = f"Age {sc_p_plan_age} ({sc_p_plan_yr})"
            p_ret_sub = "Sustainable"
            p_ret_sub_red = False
            p_ret_tooltip = f"Planned retirement at Age {sc_p_plan_age} ({sc_p_plan_yr}) is fully sustainable through Age 100"
        elif sc_p_ear_age:
            p_ret_badge = "badge-orange"
            p_ret_text = f"Age {sc_p_ear_age} ({sc_ear_joint_yr})"
            p_ret_sub = f"Plan Age {sc_p_plan_age}: Depleted"
            p_ret_sub_red = True
            p_ret_tooltip = f"Planned retirement at Age {sc_p_plan_age} depletes portfolio. Earliest sustainable retirement is Age {sc_p_ear_age} ({sc_ear_joint_yr})"
        else:
            p_ret_badge = "badge-red"
            p_ret_text = "Infeasible"
            p_ret_sub = f"Plan Age {sc_p_plan_age}: Depleted"
            p_ret_sub_red = False
            p_ret_tooltip = "Current spending & events exceed portfolio capacity at any retirement age"

        if sc_can_now:
            s_ret_badge = "badge-green"
            s_ret_text = f"Now (Age {s_cur_age})"
            s_ret_sub = f"Plan: Age {sc_s_plan_age} ({sc_s_plan_yr})"
            s_ret_sub_red = False
            s_ret_tooltip = f"Financially independent today at Age {s_cur_age} (Planned target: Age {sc_s_plan_age} in {sc_s_plan_yr})"
        elif sc_is_sust:
            s_ret_badge = "badge-blue"
            s_ret_text = f"Age {sc_s_plan_age} ({sc_s_plan_yr})"
            s_ret_sub = "Sustainable"
            s_ret_sub_red = False
            s_ret_tooltip = f"Planned retirement at Age {sc_s_plan_age} ({sc_s_plan_yr}) is fully sustainable through Age 100"
        elif sc_s_ear_age:
            s_ret_badge = "badge-orange"
            s_ret_text = f"Age {sc_s_ear_age} ({sc_ear_joint_yr})"
            s_ret_sub = f"Plan Age {sc_s_plan_age}: Depleted"
            s_ret_sub_red = True
            s_ret_tooltip = f"Planned retirement at Age {sc_s_plan_age} depletes portfolio. Earliest sustainable retirement is Age {sc_s_ear_age} ({sc_ear_joint_yr})"
        else:
            s_ret_badge = "badge-red"
            s_ret_text = "Infeasible"
            s_ret_sub = f"Plan Age {sc_s_plan_age}: Depleted"
            s_ret_sub_red = False
            s_ret_tooltip = "Current spending & events exceed portfolio capacity at any retirement age"

        sc_ev_raw = sc.get("events_details") or [catalog[eid] for eid in (sc.get("events_included") or []) if eid in catalog]
        sc_ev_chips = []
        for sev in sc_ev_raw:
            if not isinstance(sev, dict):
                continue
            sey = sev.get("year")
            seend = sev.get("end_year")
            st_range = f" ({sey}{f'–{seend}' if seend and seend > sey else ''})" if sey else ""
            samt = sev.get("amount")
            samt_str = f": ${round(float(samt) / 1000.0):,}k/yr" if samt else ""
            scat = sev.get("category") or "other"
            sen = str(sev.get("name") or "")
            sc_ev_chips.append({
                "id": sev.get("id") or "",
                "name": sen,
                "category": scat,
                "icon": sev.get("icon") or "",
                "cat_badge": cat_badge(scat),
                "border_color": cat_border(scat),
                "tooltip": f"{sen}{st_range}{samt_str}",
                "short_name": f"{sen[:15]}…" if len(sen) > 16 else sen,
            })

        sc_parent_id = sc.get("parent_id")
        sc_parent_name = sc.get("parent_name") or (scen_name_by_id.get(sc_parent_id, "Base Plan") if sc_parent_id else None)
        sc_overrides = sc.get("overrides") if isinstance(sc.get("overrides"), dict) else {}
        has_custom_rate_ov = sc_overrides.get("custom_equity_growth_rate") is not None
        sc_overrides_count = sum(
            1
            for k, v in sc_overrides.items()
            if v is not None
            and not (isinstance(v, dict) and not v)
            and not (has_custom_rate_ov and k == "equity_growth_preset" and str(v).strip().lower() == "custom")
        )
        sc_blended = sc.get("blended_liquid_growth")
        sc_eq_preset = sc.get("equity_growth_preset")
        sc_has_eq_override = bool(sc_overrides.get("equity_growth_preset") or sc_overrides.get("custom_equity_growth_rate") is not None)
        if sc.get("custom_equity_growth_rate") is not None and (sc_eq_preset == "custom" or sc_overrides.get("custom_equity_growth_rate") is not None):
            sc_eq_badge = f"{float(sc['custom_equity_growth_rate']) * 100:.1f}% 409A"
        elif sc_eq_preset:
            sc_eq_badge = _SCORECARD_EQ_BADGE_MAP.get(str(sc_eq_preset).strip().lower(), f"{sc_eq_preset} 409A")
        else:
            sc_eq_badge = None

        sc_mc = sc.get("monte_carlo_solvency")
        if sc_mc is not None:
            sc_mc_fmt = int(sc_mc) if isinstance(sc_mc, float) and sc_mc.is_integer() else sc_mc
            sc_solv_badge = "badge-green" if sc_mc >= 90 else ("badge-orange" if sc_mc >= 75 else "badge-red")
            sc_solv_text = f"{sc_mc_fmt}% MC"
            sc_solv_title = f"{sc_mc_fmt}% of 1,000 Monte Carlo paths solvent through Age 100"
        elif sc_is_dep:
            sc_solv_badge = "badge-red"
            sc_solv_text = f"Depleted ({sc.get('depletion_year') or ''})"
            sc_solv_title = ""
        else:
            sc_solv_badge = "badge-green"
            sc_solv_text = "Solvent @ 100"
            sc_solv_title = ""

        sc_is_baseline = bool(sc.get("is_baseline")) or sc_id == "scen_baseline"
        sc_is_layer = bool(sc.get("is_baseline_layer") or (sc_id and sc_id in active_layer_ids))
        sc_baseline_layers: List[Dict[str, Any]] = []
        if sc_is_baseline:
            raw_lyrs = sc.get("baseline_layers") or sc.get("active_baseline_layers") or []
            for lyr in raw_lyrs:
                if isinstance(lyr, dict):
                    sc_baseline_layers.append({
                        "id": str(lyr.get("id") or ""),
                        "name": str(lyr.get("name") or scen_name_by_id.get(lyr.get("id"), "Overlay")),
                        "color": str(lyr.get("color") or "#8B5CF6"),
                    })
                elif isinstance(lyr, str):
                    matched = next((s for s in scorecard_items if isinstance(s, dict) and s.get("id") == lyr), None)
                    lyr_name = str(matched.get("name") if matched else scen_name_by_id.get(lyr, lyr))
                    lyr_color = str(matched.get("color") if matched else "#8B5CF6")
                    sc_baseline_layers.append({
                        "id": lyr,
                        "name": lyr_name,
                        "color": lyr_color,
                    })

        scorecard_rows.append({
            "id": sc_id,
            "name": sc.get("name") or "Scenario",
            "description": sc.get("description") or "",
            "color": sc.get("color") or "#3B82F6",
            "is_current_view": sc_id == active_scen_id,
            "is_active": sc_id == default_scen_id,
            "is_baseline": sc_is_baseline,
            "is_baseline_layer": sc_is_layer,
            "baseline_layers": sc_baseline_layers,
            "is_archived": bool(sc.get("is_archived", False)),
            "is_child": bool(sc_parent_id),
            "parent_id": sc_parent_id or "",
            "parent_name": sc_parent_name or "Base Plan",
            "overrides_count": sc_overrides_count,
            "blended_liquid_pct": f"{float(sc_blended) * 100:.1f}" if sc_blended else None,
            "equity_growth_preset": sc_eq_preset,
            "equity_growth_badge": sc_eq_badge,
            "has_equity_override": sc_has_eq_override,
            "events": sc_ev_chips,
            "primary_ret_badge": p_ret_badge,
            "primary_ret_text": p_ret_text,
            "primary_ret_sub": p_ret_sub,
            "primary_ret_sub_red": p_ret_sub_red,
            "primary_ret_tooltip": p_ret_tooltip,
            "spouse_ret_badge": s_ret_badge,
            "spouse_ret_text": s_ret_text,
            "spouse_ret_sub": s_ret_sub,
            "spouse_ret_sub_red": s_ret_sub_red,
            "spouse_ret_tooltip": s_ret_tooltip,
            "nw65": fmt_short_currency(sc.get("net_worth_65")),
            "nw85": fmt_short_currency(sc.get("net_worth_85")),
            "nw95": fmt_short_currency(sc.get("net_worth_95")),
            "is_depleted": sc_is_dep,
            "solv_badge": sc_solv_badge,
            "solv_text": sc_solv_text,
            "solv_title": sc_solv_title,
            "solv_earliest_yr": sc_ear_joint_yr if sc_is_dep else None,
        })

    return scorecard_rows
