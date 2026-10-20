"""
forecast/presets.py: Event Catalog Synthesis, Scenario Presets & Budget Templates.
Generates reusable financial event catalog from database records (equity grants, tuition, college, debt)
and builds dynamic living budget / savings presets from Monarch Money benchmarks.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import monarch_service
from forecast.storage import (
    DB_PATH,
    get_db_path,
    load_children_k12_tuition,
    load_children_edu_reserves,
)
from db.session import resolve_db_path
from forecast.catalog import SCENARIO_TEMPLATES
from forecast.presets_equity_debt import (
    build_equity_grant_events,
    build_debt_and_mortgage_events,
    build_vacation_and_lifestyle_events,
)
from forecast.presets_family_edu import (
    build_education_events,
    build_family_care_and_gifting_events,
)
from forecast.presets_milestones import build_standard_milestone_events


def get_default_event_catalog(
    family_id: int = 0,
    children_k12: Optional[List[Dict[str, Any]]] = None,
    children_edu: Optional[List[Dict[str, Any]]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Returns reusable financial event catalog dynamically synthesized from household database records."""
    active_db = resolve_db_path(get_db_path(), family_id=family_id)
    events: List[Dict[str, Any]] = []

    # 1. Equity grants
    events.extend(build_equity_grant_events(family_id=family_id, active_db=active_db))

    # 2 & 3. Lifestyle & Vacation Home
    events.extend(build_vacation_and_lifestyle_events())

    # 4. Debt & Mortgage Payoff / Refinance
    events.extend(build_debt_and_mortgage_events(family_id=family_id, snapshot=snapshot))

    # 5. Education (K-12 & College)
    events.extend(build_education_events(family_id=family_id, children_k12=children_k12, children_edu=children_edu))

    # 6 & 7. Eldercare & Gifting
    events.extend(build_family_care_and_gifting_events(family_id=family_id, active_db=active_db))

    # 8-25. Standard Milestones & Financial Architecture
    events.extend(build_standard_milestone_events())

    return events



def get_default_scenarios(
    family_id: int = 0,
    children_k12: Optional[List[Dict[str, Any]]] = None,
    children_edu: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Returns the default clean scenario list (starting strictly with Baseline Plan)."""
    active_db = resolve_db_path(get_db_path(), family_id=family_id)
    if children_k12 is None:
        children_k12 = load_children_k12_tuition(family_id=family_id)
    k12_ids = [f"evt_k12_{c['first_name'].lower()}" for c in children_k12] if children_k12 else []
    if children_edu is None:
        children_edu = load_children_edu_reserves(family_id=family_id)
    college_ids = [f"evt_college_{c['first_name'].lower()}" for c in children_edu] if children_edu else []

    has_gifting = False
    if family_id and active_db.exists():
        from db.gifting import count_gift_recipients
        has_gifting = bool(count_gift_recipients(family_id=family_id, db_path=active_db) > 0)

    gifting_ids = ["evt_family_gifting"] if has_gifting else []
    baseline_events = k12_ids + college_ids + gifting_ids

    desc_parts = []
    if k12_ids:
        desc_parts.append("per-child K-12 tuition")
    if college_ids:
        desc_parts.append("college 529 spend-downs")
    if gifting_ids:
        desc_parts.append("family gifting")

    if desc_parts:
        baseline_desc = f"Current trajectory with {', '.join(desc_parts)} without early option exercise."
    else:
        baseline_desc = "Current baseline trajectory without early option exercise."

    return [
        {
            "id": "scen_baseline",
            "name": "Baseline Plan",
            "description": baseline_desc,
            "event_ids": baseline_events,
            "color": "#94A3B8",
            "equity_growth_preset": "moderate",
            "is_baseline": True,
        }
    ]


def format_short_currency_spend(val: float) -> str:
    """Formats spending amount as $Xk or $X.XXM."""
    if abs(val) >= 1_000_000:
        millions = val / 1_000_000.0
        s = f"{millions:.2f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if abs(val) >= 1_000:
        return f"{int(round(val / 1000.0))}k"
    return f"{int(round(val))}"


def build_living_budget_presets(
    benchmarks: Dict[str, Any],
    baseline_spend: float = 0.0,
    target_spend: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Constructs dynamic living budget presets derived from actual spending benchmarks in the database.
    """
    presets = []

    # 1. Baseline
    b_val = float(benchmarks.get("baseline") or baseline_spend or 0.0)
    if b_val > 0:
        presets.append({
            "id": "preset_baseline",
            "label": f"Baseline (${format_short_currency_spend(b_val)})",
            "spend": round(b_val),
            "source": "baseline",
        })

    # Historical & Annualized Benchmarks
    if benchmarks.get("actual_2024") and float(benchmarks["actual_2024"]) > 0:
        act24 = float(benchmarks["actual_2024"])
        presets.append({
            "id": "preset_actual_2024",
            "label": f"2024 Actual (${format_short_currency_spend(act24)})",
            "spend": round(act24),
            "source": "actual_2024",
        })

    if benchmarks.get("three_year_average") and float(benchmarks["three_year_average"]) > 0:
        avg3 = float(benchmarks["three_year_average"])
        presets.append({
            "id": "preset_3yr_avg",
            "label": f"3-Yr Avg (${format_short_currency_spend(avg3)})",
            "spend": round(avg3),
            "source": "three_year_average",
        })

    if benchmarks.get("actual_2025") and float(benchmarks["actual_2025"]) > 0:
        act25 = float(benchmarks["actual_2025"])
        presets.append({
            "id": "preset_actual_2025",
            "label": f"2025 Actual (${format_short_currency_spend(act25)})",
            "spend": round(act25),
            "source": "actual_2025",
        })

    if benchmarks.get("annualized_2026") and float(benchmarks["annualized_2026"]) > 0:
        ann26 = float(benchmarks["annualized_2026"])
        presets.append({
            "id": "preset_annualized_2026",
            "label": f"2026 Annualized (${format_short_currency_spend(ann26)})",
            "spend": round(ann26),
            "source": "annualized_2026",
        })

    # 2. Target: only if distinct from all existing benchmark presets
    t_val = float(target_spend or 0.0)
    if t_val > 0 and all(abs(t_val - p["spend"]) >= 1000 for p in presets):
        presets.insert(min(1, len(presets)), {
            "id": "preset_target",
            "label": f"Target (${format_short_currency_spend(t_val)})",
            "spend": round(t_val),
            "source": "target",
        })

    return presets


def build_annual_savings_presets(
    baseline_savings: float = 0.0,
    annual_compensation: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Constructs dynamic annual savings presets derived from the database:
    - $0 (Retired / Sabbatical)
    - Standard Tax-Advantaged ($70k IRS limit benchmark)
    - Target Baseline (from household_profile in database if set)
    - Accelerated (1.5x baseline)
    """
    presets = [
        {"id": "savings_zero", "label": "$0 (Retired)", "savings": 0.0, "source": "zero"},
        {"id": "savings_tax_advantaged", "label": "Tax-Adv ($70k)", "savings": 70000.0, "source": "tax_advantaged"},
    ]

    b_val = float(baseline_savings or 0.0)
    if b_val > 1000 and abs(b_val - 70000.0) > 1000:
        presets.append({
            "id": "savings_baseline",
            "label": f"Target (${format_short_currency_spend(b_val)})",
            "savings": round(b_val),
            "source": "baseline",
        })
        accel = round(b_val * 1.5, -3)
        if accel > b_val:
            presets.append({
                "id": "savings_accelerated",
                "label": f"Accelerated (${format_short_currency_spend(accel)})",
                "savings": round(accel),
                "source": "accelerated",
            })

    return presets


def get_scenario_templates(
    family_id: int = 0,
    children_k12: Optional[List[Dict[str, Any]]] = None,
    children_edu: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Returns scenario templates with dynamically resolved per-child K-12 and college events,
    and dynamically calibrated living budget presets based on the family's actual spend."""
    active_db = resolve_db_path(get_db_path(), family_id=family_id)
    if children_k12 is None:
        children_k12 = load_children_k12_tuition(family_id=family_id)
    k12_ids = [f"evt_k12_{c['first_name'].lower()}" for c in children_k12] if children_k12 else []
    if children_edu is None:
        children_edu = load_children_edu_reserves(family_id=family_id)
    college_ids = [f"evt_college_{c['first_name'].lower()}" for c in children_edu] if children_edu else []

    has_gifting = False
    if family_id and active_db.exists():
        from db.gifting import count_gift_recipients
        has_gifting = bool(count_gift_recipients(family_id=family_id, db_path=active_db) > 0)

    # Determine user's actual spending baseline
    spending_meta = monarch_service.get_monarch_spending_history(family_id=family_id)
    benchmarks = spending_meta.get("benchmarks", {})
    user_spend = 0.0
    if benchmarks.get("recommended_budget") and float(benchmarks["recommended_budget"]) > 0:
        user_spend = float(benchmarks["recommended_budget"])
    elif benchmarks.get("baseline") and float(benchmarks["baseline"]) > 0:
        user_spend = float(benchmarks["baseline"])
    elif family_id and active_db.exists():
        from db.household import get_annual_spending
        user_spend = get_annual_spending(family_id=family_id, db_path=active_db)

    # Calibrate budget tiers based on actual spend (or clean defaults)
    if user_spend > 0:
        lean_spend = round(user_spend * 0.75, -3)
        target_spend = round(user_spend, -3)
        stretch_spend = round(user_spend * 1.25, -3)
    else:
        lean_spend = 60000.0
        target_spend = 90000.0
        stretch_spend = 120000.0

    templates = []
    for t in SCENARIO_TEMPLATES:
        t_copy = dict(t)
        ev_ids = list(t.get("event_ids", []))
        if "evt_k12_education" in ev_ids:
            idx = ev_ids.index("evt_k12_education")
            ev_ids = ev_ids[:idx] + k12_ids + college_ids + ev_ids[idx+1:]
        if not has_gifting and "evt_family_gifting" in ev_ids:
            ev_ids = [eid for eid in ev_ids if eid != "evt_family_gifting"]
        t_copy["event_ids"] = ev_ids

        t_id = t_copy.get("id")
        if t_id in ("template_budget_lean", "template_budget_250k"):
            t_copy["annual_living_spend"] = lean_spend
            t_copy["name"] = f"Budget Preset: Lean Living (${format_short_currency_spend(lean_spend)}/yr)"
            t_copy["description"] = f"Conservative lean baseline spending scenario (${format_short_currency_spend(lean_spend)}/yr) maximizing wealth accumulation."
        elif t_id in ("template_budget_target", "template_budget_350k"):
            t_copy["annual_living_spend"] = target_spend
            t_copy["name"] = f"Budget Preset: Target Living (${format_short_currency_spend(target_spend)}/yr)"
            t_copy["description"] = f"Target balanced lifestyle spending scenario (${format_short_currency_spend(target_spend)}/yr) calibrated to your living budget."
        elif t_id == "template_budget_stretch":
            t_copy["annual_living_spend"] = stretch_spend
            t_copy["name"] = f"Budget Preset: Stretch Living (${format_short_currency_spend(stretch_spend)}/yr)"
            t_copy["description"] = f"Expanded lifestyle spending scenario (${format_short_currency_spend(stretch_spend)}/yr) with higher travel and discretionary buffer."
        elif user_spend > 0:
            t_copy["annual_living_spend"] = target_spend

        templates.append(t_copy)

    # If family has verified historical Monarch benchmarks, dynamically append them!
    if benchmarks.get("three_year_average") and float(benchmarks["three_year_average"]) > 0:
        val = float(benchmarks["three_year_average"])
        templates.append({
            "id": "template_budget_3yr_avg",
            "name": f"Budget Preset: 3-Year Average (${format_short_currency_spend(val)}/yr)",
            "description": f"Historical 3-year living expenditure benchmark from Monarch actuals (${format_short_currency_spend(val)}/yr).",
            "event_ids": k12_ids + college_ids + (["evt_family_gifting"] if has_gifting else []),
            "annual_living_spend": round(val),
            "color": "#D97706",
            "equity_growth_preset": "moderate",
        })
    if benchmarks.get("actual_2025") and float(benchmarks["actual_2025"]) > 0:
        val = float(benchmarks["actual_2025"])
        templates.append({
            "id": "template_budget_2025_actual",
            "name": f"Budget Preset: 2025 Actuals (${format_short_currency_spend(val)}/yr)",
            "description": f"Calibrated directly to full calendar year 2025 actual living spend from Monarch Money (${format_short_currency_spend(val)}/yr).",
            "event_ids": k12_ids + college_ids + (["evt_family_gifting"] if has_gifting else []),
            "annual_living_spend": round(val),
            "color": "#0284C7",
            "equity_growth_preset": "moderate",
        })
    if benchmarks.get("annualized_2026") and float(benchmarks["annualized_2026"]) > 0:
        val = float(benchmarks["annualized_2026"])
        templates.append({
            "id": "template_budget_2026_ann",
            "name": f"Budget Preset: 2026 Annualized (${format_short_currency_spend(val)}/yr)",
            "description": f"Stress-test scenario running at full 2026 annualized peak spending pace from Monarch (${format_short_currency_spend(val)}/yr).",
            "event_ids": k12_ids + college_ids + (["evt_family_gifting"] if has_gifting else []),
            "annual_living_spend": round(val),
            "color": "#C75D6E",
            "equity_growth_preset": "aggressive",
        })

    return templates
