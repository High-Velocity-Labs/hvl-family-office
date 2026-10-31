"""Planning benchmarks behind the scenario event wizard's preset dropdowns.

The templates render these as `<option data-annual-cost=...>`; the browser reads the number off the selected option,
so no cost table lives in JavaScript. Superfund amounts derive from the statutory annual gift exclusion.
"""

from __future__ import annotations

from typing import Any, Dict, List

from services import statutory_limits

# (option value, label, annual cost in dollars)
K12_TIERS = (("k12_private", "Private K-12 Benchmark", 40_000),)
COLLEGE_TIERS = (
    ("in_state", "In-State Public Benchmark", 35_000),
    ("out_of_state", "Out-of-State Public Benchmark", 75_000),
    ("private", "Private University Benchmark", 85_000),
    ("elite", "Elite Private Benchmark", 95_000),
)
DEFAULT_COLLEGE_TIER = "private"
ELDERCARE_TIERS = (
    ("in_home", "In-Home Supportive Care", 48_000),
    ("assisted_living", "Assisted Living Community", 90_000),
    ("memory_care", "Memory Care / Nursing Facility", 144_000),
)
DEFAULT_ELDERCARE_TIER = "assisted_living"
# (option value, label, event name, annual cost, program years)
GRAD_PROGRAMS = (
    ("mba", "2-Yr MBA Program", "Graduate MBA Tuition (2-Yr)", 95_000, 2),
    ("law", "3-Yr Law School JD", "Law School JD Tuition (3-Yr)", 95_000, 3),
    ("med", "4-Yr Medical School MD", "Medical School MD Tuition (4-Yr)", 95_000, 4),
    ("masters", "2-Yr Master's Program", "Master's Degree Tuition (2-Yr)", 75_000, 2),
)
# (option value, label, event name, annual amount or None, marginal tax rate %, ladder years)
ROTH_PRESETS = (
    ("auto_bracket_24", "Auto-Fill 24% Bracket in Gap Years (Dynamic Headroom)",
     "Auto-Fill 24% Bracket Roth Conversion Ladder", 200_000, 24, 8),
    ("auto_bracket_22", "Auto-Fill 22% Bracket in Gap Years (Dynamic Headroom)",
     "Auto-Fill 22% Bracket Roth Conversion Ladder", 150_000, 22, 8),
    ("auto_bracket_12", "Auto-Fill 12% Bracket in Gap Years (Dynamic Headroom)",
     "Auto-Fill 12% Bracket Roth Conversion Ladder", 90_000, 12, 8),
    ("bracket_24", "Fixed Annual — 24% Bracket", "Annual Roth Conversion Ladder", 150_000, 24, 5),
    ("bracket_32", "Fixed Annual — 32% Bracket", "Annual Roth Conversion Ladder (32% Bracket)", 250_000, 32, 5),
    ("rule_72t_sepp", "Rule 72(t) SEPP Penalty-Free Pre-59½ Bridge",
     "Rule 72(t) SEPP Pre-59½ Retirement Bridge", 120_000, 22, 10),
    ("custom", "Custom Annual Conversion / SEPP", "Annual Roth Conversion Ladder", None, None, 5),
)


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


def _tier_rows(tiers) -> List[Dict[str, Any]]:
    return [{"value": v, "label": f"{label} ({_money(cost)} / yr)", "cost": cost} for v, label, cost in tiers]


def superfund_tiers(tax_year: int) -> List[Dict[str, Any]]:
    """Five-year gift election totals; the option value is the dollar amount."""
    per_donor = statutory_limits.section_529_superfund_limit(tax_year)
    rows = (
        ("Married Split-Gift 5-Yr Election", per_donor * 2),
        ("Single Donor 5-Yr Election", per_donor),
        ("Two Beneficiaries Married", per_donor * 4),
    )
    return [
        {"value": f"{amount:.0f}", "label": f"{label} ({_money(amount)})", "cost": amount} for label, amount in rows
    ]


def wizard_tables(tax_year: int) -> Dict[str, Any]:
    from services.tax_calculations import state_income_tax_rates

    return {
        "wizard_k12_tiers": _tier_rows(K12_TIERS),
        "wizard_college_tiers": _tier_rows(COLLEGE_TIERS),
        "wizard_college_default": DEFAULT_COLLEGE_TIER,
        "wizard_eldercare_tiers": _tier_rows(ELDERCARE_TIERS),
        "wizard_eldercare_default": DEFAULT_ELDERCARE_TIER,
        "wizard_grad_programs": [
            {"value": v, "label": f"{label} ({_money(cost)} / yr)", "name": name, "cost": cost, "years": years}
            for v, label, name, cost, years in GRAD_PROGRAMS
        ],
        "wizard_roth_presets": [
            {"value": v, "label": label, "name": name, "cost": cost, "rate": rate, "years": years}
            for v, label, name, cost, rate, years in ROTH_PRESETS
        ],
        "wizard_superfund_tiers": superfund_tiers(tax_year),
        "wizard_state_rates": dict(sorted(state_income_tax_rates().items())),
    }
