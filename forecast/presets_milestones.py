"""
forecast/presets_milestones.py: Lifestyle, property, windfall, and milestone event catalog builders.
Extracted from forecast/presets.py.
"""

from __future__ import annotations
from typing import Dict, Any, List


def build_standard_milestone_events() -> List[Dict[str, Any]]:
    """Returns standard windfall and milestone event catalog."""
    events: List[Dict[str, Any]] = []

    # One-Time Capital Outflow / Withdrawal (Large Family Gift)
    events.append({
        "id": "evt_large_family_gift",
        "name": "One-Time Family Wealth Transfer Gift ($500k)",
        "category": "capital_outflow",
        "event_type": "single_spike",
        "icon": "evt-gifting",
        "year": 2028,
        "end_year": 2028,
        "amount": 500000.0,
        "annual_amount": 500000.0,
        "is_outflow": True,
        "outflow_purpose": "large_gift",
        "funding_source": "taxable_brokerage",
        "description": "Lump-sum generational family wealth transfer gift or trust funding out of taxable liquid assets.",
    })

    # One-Time Capital Inflow / Windfall
    events.append({
        "id": "evt_capital_windfall",
        "name": "One-Time Liquidity Windfall / Asset Sale ($500k)",
        "category": "capital_inflow",
        "event_type": "single_spike",
        "icon": "evt-business-sale",
        "year": 2029,
        "end_year": 2029,
        "amount": 500000.0,
        "annual_amount": 500000.0,
        "is_outflow": False,
        "inflow_source_type": "asset_sale",
        "funding_source": "taxable_brokerage",
        "description": "One-time private asset sale, executive bonus windfall, or estate distribution injected into taxable brokerage.",
    })

    # Buy / Upgrade Primary Residence
    events.append({
        "id": "evt_buy_primary_home",
        "name": "Buy / Upgrade Primary Residence ($2.5M)",
        "category": "real_estate",
        "re_action": "buy_primary",
        "event_type": "single_spike",
        "icon": "evt-real-estate",
        "year": 2028,
        "end_year": 2028,
        "purchase_price": 2500000.0,
        "down_payment_pct": 0.25,
        "mortgage_term": "30_fixed",
        "interest_rate": 0.055,
        "annual_ongoing_carrying_cost": 35000.0,
        "funding_source": "taxable_brokerage",
        "description": "Purchase or upgrade to a $2.5M primary residence with 25% down payment ($625k) and 30-year fixed financing.",
    })

    # Downsize / Sell Residence
    events.append({
        "id": "evt_home_sale_downsize",
        "name": "Downsize / Sell Residence (+$1.2M Net)",
        "category": "real_estate",
        "re_action": "downsize",
        "event_type": "single_spike",
        "icon": "evt-home-sale",
        "year": 2036,
        "end_year": 2036,
        "sale_price": 2200000.0,
        "replacement_price": 850000.0,
        "selling_cost_pct": 0.06,
        "mortgage_payoff_amount": 0.0,
        "amount": 1218000.0,
        "is_outflow": False,
        "funding_source": "taxable_brokerage",
        "description": "Sell primary residence ($2.2M) and downsize into $850k property, unlocking ~$1.22M net equity into liquid investments.",
    })

    # Major Home Renovation / Remodel
    events.append({
        "id": "evt_home_renovation",
        "name": "Major Home Renovation / Remodel ($300k)",
        "category": "home_renovation",
        "event_type": "single_spike",
        "icon": "evt-renovation",
        "year": 2028,
        "end_year": 2028,
        "amount": 300000.0,
        "annual_amount": 300000.0,
        "value_retention_pct": 0.60,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "Major architectural remodel, ADU, or home addition ($300k cash outlay with ~60% recaptured in property equity).",
    })

    # Wedding / Milestone Celebration
    events.append({
        "id": "evt_wedding_celebration",
        "name": "Pay for Wedding / Milestone Celebration ($125k)",
        "category": "capital_outflow",
        "outflow_purpose": "wedding",
        "event_type": "single_spike",
        "icon": "evt-wedding",
        "year": 2032,
        "end_year": 2032,
        "amount": 125000.0,
        "annual_amount": 125000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "Family wedding, destination celebration, or milestone family reunion ($125k one-time expenditure).",
    })

    # Child First-Home Down Payment Gift
    events.append({
        "id": "evt_child_home_downpayment",
        "name": "Child First-Home Down Payment Gift ($250k)",
        "category": "capital_outflow",
        "outflow_purpose": "child_home_gift",
        "event_type": "single_spike",
        "icon": "evt-house-key",
        "year": 2034,
        "end_year": 2034,
        "amount": 250000.0,
        "annual_amount": 250000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "Lump-sum down payment assistance to help a child purchase their first home ($250k).",
    })

    # Graduate / Med / Law School Tuition
    events.append({
        "id": "evt_grad_school",
        "name": "Graduate / Med / Law School Tuition (3-Yr)",
        "category": "grad_school",
        "event_type": "duration",
        "icon": "evt-grad-school",
        "year": 2033,
        "end_year": 2035,
        "annual_amount": 95000.0,
        "amount": 95000.0,
        "use_529_reserves": True,
        "is_outflow": True,
        "funding_source": "529_education_reserve",
        "description": "3-year graduate, medical, law, or MBA program (~$95k/yr). Draws from remaining 529 reserves first, then liquid accounts.",
    })

    # 1-Year Career Sabbatical & World Travel
    events.append({
        "id": "evt_sabbatical_break",
        "name": "1-Year Career Sabbatical & World Travel",
        "category": "sabbatical",
        "income_mode": "sabbatical",
        "event_type": "duration",
        "icon": "evt-briefcase",
        "year": 2029,
        "end_year": 2029,
        "income_multiplier_pct": 0.0,
        "annual_amount": 75000.0,
        "amount": 75000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "1-year career sabbatical (0% earned salary during break plus $75k global travel budget).",
    })

    # Donor-Advised Fund (DAF) Front-Load
    events.append({
        "id": "evt_philanthropy_daf",
        "name": "Donor-Advised Fund (DAF) Front-Load ($250k)",
        "category": "philanthropy_daf",
        "event_type": "single_spike",
        "icon": "evt-philanthropy",
        "year": 2028,
        "end_year": 2028,
        "amount": 250000.0,
        "annual_amount": 250000.0,
        "tax_deduction_rate": 0.35,
        "include_tax_offset": True,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "Front-load $250k into a Donor-Advised Fund in a high-income year (~35% charitable tax deduction offset).",
    })

    # Luxury / Electric Vehicle Purchase
    events.append({
        "id": "evt_vehicle_purchase",
        "name": "Luxury / Electric Vehicle Purchase ($110k)",
        "category": "capital_outflow",
        "outflow_purpose": "vehicle_purchase",
        "event_type": "single_spike",
        "icon": "evt-car",
        "year": 2028,
        "end_year": 2028,
        "amount": 110000.0,
        "annual_amount": 110000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "One-time purchase of a luxury, performance, or electric vehicle ($110k cash outlay).",
    })

    # Rental Property / Consulting Income Stream
    events.append({
        "id": "evt_rental_income_stream",
        "name": "Rental Property / Consulting Income (+$60k/yr)",
        "category": "capital_inflow",
        "inflow_source_type": "rental_income",
        "event_type": "duration",
        "icon": "evt-rental-income",
        "year": 2028,
        "end_year": 2038,
        "annual_amount": 60000.0,
        "amount": 60000.0,
        "is_outflow": False,
        "funding_source": "taxable_brokerage",
        "description": "11-year recurring net rental income, board advisory retainer, or consulting cash flow (+$60k/yr).",
    })

    # State Tax Domicile Relocation (Inter-State Tax Arbitrage)
    events.append({
        "id": "evt_state_relocation",
        "name": "State Tax Domicile Relocation (CA → WA/TX/NV)",
        "category": "state_relocation",
        "event_type": "point",
        "icon": "evt-relocation",
        "year": 2028,
        "end_year": 2028,
        "origin_state": "CA",
        "target_state": "WA",
        "moving_cost": 35000.0,
        "state_tax_savings_rate": 0.093,
        "amount": 35000.0,
        "annual_amount": 35000.0,
        "is_outflow": False,
        "funding_source": "taxable_brokerage",
        "description": "Relocate primary tax domicile to eliminate state income tax drag ahead of major liquidity or retirement distributions (-$35k moving cost; ~9.3% ongoing state tax savings).",
    })

    # Multi-Year Roth Conversion Ladder
    events.append({
        "id": "evt_roth_conversion_ladder",
        "name": "Multi-Year Roth Conversion Ladder ($150k/yr)",
        "category": "roth_conversion",
        "event_type": "duration",
        "icon": "evt-roth-ladder",
        "year": 2030,
        "end_year": 2035,
        "annual_conversion": 150000.0,
        "marginal_tax_rate": 0.24,
        "amount": 150000.0,
        "annual_amount": 150000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "6-year systematic conversion of $150k/yr from Traditional 401(k)/IRA to tax-free Roth during low-income bridge years prior to age-73/75 RMDs (24% conversion tax paid from taxable brokerage).",
    })

    # 529 Plan 5-Year Superfund (Accelerated Gift Tax Front-Loading)
    events.append({
        "id": "evt_529_superfund",
        "name": "529 Plan 5-Year Superfund ($190k Front-Load)",
        "category": "superfund_529",
        "event_type": "point",
        "icon": "evt-529-superfund",
        "year": 2027,
        "end_year": 2027,
        "amount": 190000.0,
        "annual_amount": 190000.0,
        "beneficiary_count": 1,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "Front-load 5 years of joint annual gift tax exclusions ($190,000 per child under IRC §529(c)(2)(B)) to maximize tax-free education compounding.",
    })

    # Private Equity / Venture Capital Call Schedule (J-Curve)
    events.append({
        "id": "evt_pe_capital_call",
        "name": "PE / Venture Fund Capital Call ($125k/yr × 4 yrs → 2.2x)",
        "category": "pe_capital_call",
        "event_type": "duration",
        "icon": "evt-j-curve",
        "year": 2027,
        "end_year": 2030,
        "annual_call": 125000.0,
        "amount": 125000.0,
        "annual_amount": 125000.0,
        "harvest_year": 2035,
        "tvpi_multiple": 2.2,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "$500k LP commitment called at $125k/yr over 4 years, followed by a 2.2x TVPI J-curve harvest distribution in 2035 net of LTCG tax.",
    })

    # Long-Term Care (LTC) Hybrid Insurance Policy (10-Pay Shield)
    events.append({
        "id": "evt_ltc_hybrid_policy",
        "name": "LTC Hybrid Insurance Policy (10-Pay Shield)",
        "category": "ltc_insurance",
        "event_type": "duration",
        "icon": "evt-ltc-shield",
        "year": 2028,
        "end_year": 2037,
        "annual_premium": 18000.0,
        "amount": 18000.0,
        "annual_amount": 18000.0,
        "benefit_start_year": 2048,
        "benefit_end_year": 2052,
        "annual_benefit": 120000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "10-year hybrid life/LTC policy funding ($18k/yr) that provides a $120k/yr tax-free long-term care benefit pool during late-life care years.",
    })

    # Marital Asset Division / QDRO Settlement
    events.append({
        "id": "evt_marital_settlement",
        "name": "Marital Asset Division / QDRO Stress Test",
        "category": "marital_settlement",
        "event_type": "duration",
        "icon": "evt-asset-split",
        "year": 2029,
        "end_year": 2034,
        "asset_split_pct": 50.0,
        "legal_fee": 45000.0,
        "annual_alimony": 60000.0,
        "amount": 60000.0,
        "annual_amount": 60000.0,
        "is_outflow": True,
        "funding_source": "taxable_brokerage",
        "description": "Tail-risk stress test: 50% pro-rata division of liquid and retirement assets via QDRO plus 6 years of transitional support.",
    })

    return events
