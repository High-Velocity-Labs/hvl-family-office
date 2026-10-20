"""
forecast/catalog.py: Reusable Event Catalog, Growth Presets & Scenario Templates.
Provides calibrated presets for liquidity reinvestment, company valuation trajectories, and scenario templates.
"""

from __future__ import annotations
from typing import Dict, Any, List

# Reinvestment Destination Presets for Liquidity Events
REINVESTMENT_PRESETS: Dict[str, Dict[str, Any]] = {
    "index_mirror": {
        "id": "index_mirror",
        "name": "Liquid Index Portfolio Mirror",
        "description": "Weighted by core index holdings (~85% US/Intl Equities, 10% Bonds, 5% Cash)",
        "nominal_return": 0.072,  # 7.2% nominal
        "real_return": 0.047,     # 4.7% real (net of 2.5% inflation)
    },
    "vanguard_mirror": {
        "id": "index_mirror",
        "name": "Liquid Index Portfolio Mirror",
        "description": "Weighted by core index holdings (~85% US/Intl Equities, 10% Bonds, 5% Cash)",
        "nominal_return": 0.072,
        "real_return": 0.047,
    },
    "boglehead_70_30": {
        "id": "boglehead_70_30",
        "name": "Boglehead 70/30 Balanced",
        "description": "70% Total Stock Market, 30% Total Bond Market",
        "nominal_return": 0.065,  # 6.5% nominal
        "real_return": 0.040,     # 4.0% real
    },
    "all_equities": {
        "id": "all_equities",
        "name": "100% Total Equities (Global Index)",
        "description": "Maximum long-term compounding in diversified global equities",
        "nominal_return": 0.078,  # 7.8% nominal
        "real_return": 0.053,     # 5.3% real
    },
    "cash_sweeps": {
        "id": "cash_sweeps",
        "name": "Cash & Treasury Sweeps",
        "description": "Short-term Treasuries & High Yield Money Market for capital preservation",
        "nominal_return": 0.040,  # 4.0% nominal
        "real_return": 0.015,     # 1.5% real
    },
    "private_funds": {
        "id": "private_funds",
        "name": "Direct Private Equity & Angel Funds",
        "description": "Venture capital, buyout funds, and early-stage syndicates",
        "nominal_return": 0.120,  # 12.0% nominal
        "real_return": 0.095,     # 9.5% real
    },
}

# Equity Share Price Trajectory Presets
COMPANY_GROWTH_PRESETS: Dict[str, Dict[str, Any]] = {
    "baseline_curve": {
        "id": "baseline_curve",
        "name": "Baseline Company Valuation Model (+10.5% / yr)",
        "short_name": "Baseline (+10.5%/yr)",
        "description": "Baseline valuation trajectory matching historical S&P/company baseline (+10.5%/yr)",
        "growth_rate": 0.105,
    },
    "workbook_curve": {
        "id": "baseline_curve",
        "name": "Baseline Company Valuation Model (+10.5% / yr)",
        "short_name": "Baseline (+10.5%/yr)",
        "description": "Baseline valuation trajectory matching historical S&P/company baseline (+10.5%/yr)",
        "growth_rate": 0.105,
    },
    "conservative": {
        "id": "conservative",
        "name": "Conservative (+5.0% / yr)",
        "short_name": "Conservative (+5.0%/yr)",
        "description": "Modest growth trailing historical averages",
        "growth_rate": 0.050,
    },
    "moderate": {
        "id": "moderate",
        "name": "Moderate Tech Benchmark (+8.0% / yr)",
        "short_name": "Moderate (+8.0%/yr)",
        "description": "Steady high-performing tech enterprise compounding",
        "growth_rate": 0.080,
    },
    "aggressive": {
        "id": "aggressive",
        "name": "Aggressive Tech Benchmark (+14.0% / yr)",
        "short_name": "Aggressive (+14.0%/yr)",
        "description": "Rapid market expansion and multiple expansion",
        "growth_rate": 0.140,
    },
    "flat": {
        "id": "flat",
        "name": "Flat Valuation (Current FMV fixed)",
        "short_name": "Flat (0.0%/yr)",
        "description": "Zero growth above current 409A valuation",
        "growth_rate": 0.000,
    },
}

EQUITY_GROWTH_PRESETS = COMPANY_GROWTH_PRESETS

SCENARIO_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "template_opt_travel",
        "name": "Scenario: Option Exercise + Travel",
        "description": "Exercise stock options to diversify into liquid index portfolios and fund leisure travel.",
        "event_ids": ["evt_company_equity_exercise_custom"],
        "color": "#1D4ED8",
        "annual_living_spend": 90000.0,
        "equity_growth_preset": "moderate",
    },
    {
        "id": "template_re_vacation",
        "name": "Scenario: Vacation Property Purchase",
        "description": "Purchase secondary vacation property with 20% down payment and ongoing carrying costs.",
        "event_ids": ["evt_vacation_home"],
        "color": "#D97706",
        "annual_living_spend": 90000.0,
        "equity_growth_preset": "conservative",
    },
    {
        "id": "template_opt_re",
        "name": "Scenario: Option Exercise + Vacation Property",
        "description": "Liquidate stock options and purchase vacation property without adding debt pressure.",
        "event_ids": ["evt_company_equity_exercise_custom", "evt_vacation_home"],
        "color": "#059669",
        "annual_living_spend": 90000.0,
        "equity_growth_preset": "aggressive",
    },
    {
        "id": "template_liquidity_debt",
        "name": "Scenario: Liquidity & Debt Payoff",
        "description": "Full option repurchase and pay off primary mortgage loan balance.",
        "event_ids": ["evt_company_equity_exercise_custom", "evt_mortgage_payoff"],
        "color": "#0284C7",
        "annual_living_spend": 90000.0,
        "equity_growth_preset": "moderate",
    },
    {
        "id": "template_budget_lean",
        "name": "Budget Preset: Lean Living",
        "description": "Conservative lean baseline spending scenario maximizing multi-generational legacy.",
        "event_ids": [],
        "annual_living_spend": 60000.0,
        "color": "#0D9488",
        "equity_growth_preset": "conservative",
    },
    {
        "id": "template_budget_target",
        "name": "Budget Preset: Target Living",
        "description": "Target balanced lifestyle spending across retirement years.",
        "event_ids": [],
        "annual_living_spend": 90000.0,
        "color": "#1D4ED8",
        "equity_growth_preset": "moderate",
    },
    {
        "id": "template_budget_stretch",
        "name": "Budget Preset: Stretch Living",
        "description": "Expanded lifestyle spending scenario with higher discretionary travel and living buffer.",
        "event_ids": [],
        "annual_living_spend": 120000.0,
        "color": "#C75D6E",
        "equity_growth_preset": "moderate",
    },
]
