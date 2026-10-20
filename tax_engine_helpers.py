"""Tax Engine Helpers: State Tax Profiles and Multi-State Arbitrage Modeling."""

from typing import Dict, Any, List, Optional

# State Tax Profiles & Living Cost Indices (Baseline WA Seattle COLI = 152.0)
STATE_TAX_PROFILES: Dict[str, Dict[str, Any]] = {
    "WA": {
        "name": "Washington (Current)",
        "ordinary_rate": 0.0,
        "cap_gains_rate": 0.07,
        "cap_gains_exemption": 278000.0,
        "cap_gains_surcharge_rate": 0.029,
        "cap_gains_surcharge_threshold": 1000000.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 1000000.0,
        "property_tax_rate": 0.0088,      # ~0.88% King County / Seattle effective rate
        "sales_tax_rate": 0.103,          # 10.3% Seattle / King Co composite
        "coli_index": 152.0,              # Seattle Metro (US avg = 100)
        "notes": "0% state wage income tax; 7% capital gains tax above $278k (+ 2.9% surcharge over $1M); ~0.88% King County property tax.",
    },
    "WA_2028": {
        "name": "Washington (With 9.9% Tax)",
        "ordinary_rate": 0.0,
        "cap_gains_rate": 0.07,
        "cap_gains_exemption": 278000.0,
        "cap_gains_surcharge_rate": 0.029,
        "cap_gains_surcharge_threshold": 1000000.0,
        "millionaire_tax_rate": 0.099,
        "millionaire_threshold": 1000000.0,
        "property_tax_rate": 0.0088,
        "sales_tax_rate": 0.103,
        "coli_index": 152.0,
        "notes": "Enacted SB 6346: 9.9% tax on taxable income > $1M plus 7% capital gains (+ 2.9% surcharge over $1M); ~0.88% property tax.",
    },
    "NV": {
        "name": "Nevada (0% Tax)",
        "ordinary_rate": 0.0,
        "cap_gains_rate": 0.0,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0058,      # ~0.58% Incline Village / Washoe Co effective rate; statutory 3% annual hike cap
        "sales_tax_rate": 0.08265,        # 8.265% Washoe County
        "coli_index": 118.0,              # ~22% lower non-housing living expenses than Seattle
        "notes": "Zero personal income tax, zero cap gains, low ~0.58% capped property tax, lower cost of living.",
    },
    "TX": {
        "name": "Texas (0% Tax)",
        "ordinary_rate": 0.0,
        "cap_gains_rate": 0.0,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0195,      # ~1.95% Austin / Dallas effective property tax (high reliance on property tax)
        "sales_tax_rate": 0.0825,         # 8.25% statewide + local
        "coli_index": 108.0,              # Lower goods & services index
        "notes": "0% state income tax, with ~1.95% average effective property tax rate.",
    },
    "FL": {
        "name": "Florida (0% Tax)",
        "ordinary_rate": 0.0,
        "cap_gains_rate": 0.0,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0098,      # ~0.98% statewide average property tax
        "sales_tax_rate": 0.070,          # 7.0% state + county
        "coli_index": 118.0,              # Florida average
        "notes": "0% state income tax, ~0.98% property tax, 7% sales tax (high coastal insurance premiums can add $30k+/yr).",
    },
    "WY": {
        "name": "Wyoming (0% Tax)",
        "ordinary_rate": 0.0,
        "cap_gains_rate": 0.0,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0061,      # ~0.61% Teton / Jackson Hole
        "sales_tax_rate": 0.054,          # 5.4% state + county
        "coli_index": 122.0,              # Jackson Hole luxury living
        "notes": "Zero income tax, zero cap gains, low ~0.61% property tax, low 5.4% sales tax.",
    },
    "CA": {
        "name": "California (13.3%)",
        "ordinary_rate": 0.133,
        "cap_gains_rate": 0.133,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0120,      # ~1.20% new purchase base reset under Prop 13 + local bonds
        "sales_tax_rate": 0.09875,        # 9.875% Bay Area composite
        "coli_index": 182.0,              # Highest living costs in US (+20% higher than Seattle)
        "notes": "Top 13.3% state bracket on ordinary & capital gains; 1.20% property tax; highest cost of living.",
    },
    "OR": {
        "name": "Oregon (9.9%)",
        "ordinary_rate": 0.099,
        "cap_gains_rate": 0.099,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0105,      # ~1.05% property tax
        "sales_tax_rate": 0.000,          # 0% sales tax
        "coli_index": 128.0,
        "notes": "Top 9.9% state bracket. Capital gains taxed as ordinary income; 0% sales tax.",
    },
    "NY": {
        "name": "New York (10.9%)",
        "ordinary_rate": 0.109,
        "cap_gains_rate": 0.109,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0165,      # ~1.65% Westchester / NYC metro property tax
        "sales_tax_rate": 0.08875,        # 8.875% NYC composite
        "coli_index": 175.0,
        "notes": "Top 10.9% state bracket; ~1.65% property tax; high living costs.",
    },
    "MA": {
        "name": "Massachusetts (9.0%)",
        "ordinary_rate": 0.05,
        "cap_gains_rate": 0.09,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.04,
        "millionaire_threshold": 1000000.0,
        "property_tax_rate": 0.0112,      # ~1.12% Greater Boston effective property tax
        "sales_tax_rate": 0.0625,         # 6.25% statewide sales tax
        "coli_index": 162.0,
        "notes": "5% base income tax + 4% surtax above $1M (9% top rate); ~1.12% property tax.",
    },
    "IL": {
        "name": "Illinois (4.95%)",
        "ordinary_rate": 0.0495,
        "cap_gains_rate": 0.0495,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0205,      # ~2.05% Cook / Lake County effective property tax
        "sales_tax_rate": 0.1025,         # 10.25% Chicago composite
        "coli_index": 124.0,
        "notes": "4.95% flat state income & capital gains tax; high ~2.05% effective property tax.",
    },
    "CO": {
        "name": "Colorado (4.4%)",
        "ordinary_rate": 0.044,
        "cap_gains_rate": 0.044,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0055,      # ~0.55% Denver / Boulder effective property tax
        "sales_tax_rate": 0.0881,         # ~8.81% Denver composite
        "coli_index": 136.0,
        "notes": "4.4% flat state income & capital gains tax; low ~0.55% effective property tax.",
    },
    "NJ": {
        "name": "New Jersey (10.75%)",
        "ordinary_rate": 0.1075,
        "cap_gains_rate": 0.1075,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0223,      # ~2.23% NJ suburban effective property tax
        "sales_tax_rate": 0.06625,        # 6.625% statewide sales tax
        "coli_index": 158.0,
        "notes": "Top 10.75% bracket above $1M; highest US property tax (~2.23%).",
    },
    "VA": {
        "name": "Virginia (5.75%)",
        "ordinary_rate": 0.0575,
        "cap_gains_rate": 0.0575,
        "cap_gains_exemption": 0.0,
        "millionaire_tax_rate": 0.0,
        "millionaire_threshold": 0.0,
        "property_tax_rate": 0.0095,      # ~0.95% Northern Virginia effective property tax
        "sales_tax_rate": 0.060,          # 6.0% NoVA composite
        "coli_index": 144.0,
        "notes": "5.75% top state bracket on ordinary income & capital gains; ~0.95% property tax.",
    },
}


def calculate_state_tax_for_state(
    state_code: str,
    ordinary_income: float,
    capital_gains: float = 0.0,
    is_mfj: bool = True,
    tax_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Calculates state ordinary income tax and state capital gains tax for any configured state."""
    profile = STATE_TAX_PROFILES.get(state_code, STATE_TAX_PROFILES["WA"])
    state_name = profile["name"]

    ord_tax = 0.0
    cg_tax = 0.0

    if state_code in ("WA", "WA_2028"):
        # WA Millionaire tax (SB 6346: 9.9% on income > $1M effective 2028+)
        if state_code == "WA_2028" or (state_code == "WA" and tax_year is not None and tax_year >= 2028):
            if tax_year is None or tax_year >= 2028:
                mil_rate = profile.get("millionaire_tax_rate", 0.099) or 0.099
                mil_thresh = profile.get("millionaire_threshold", 1000000.0)
                if ordinary_income > mil_thresh:
                    ord_tax = (ordinary_income - mil_thresh) * mil_rate

        # WA Capital Gains (RCW 82.87: 7% on taxable gains up to $1M above exemption, 9.9% above $1M)
        taxable_cg = max(0.0, capital_gains - profile["cap_gains_exemption"])
        surcharge_threshold = profile.get("cap_gains_surcharge_threshold", 1000000.0)
        surcharge_rate = profile.get("cap_gains_surcharge_rate", 0.029)
        base_rate = profile["cap_gains_rate"]
        if taxable_cg <= surcharge_threshold:
            cg_tax = taxable_cg * base_rate
        else:
            cg_tax = (surcharge_threshold * base_rate) + ((taxable_cg - surcharge_threshold) * (base_rate + surcharge_rate))
    elif state_code in ("NV", "TX", "FL", "WY"):
        # Zero tax states
        ord_tax = 0.0
        cg_tax = 0.0
    else:
        # Standard flat/top rate approximations for CA, OR, NY, MA, IL, CO, NJ, VA
        ord_tax = ordinary_income * profile["ordinary_rate"]
        if profile.get("millionaire_tax_rate", 0.0) > 0 and ordinary_income > profile.get("millionaire_threshold", 1000000.0):
            ord_tax += (ordinary_income - profile.get("millionaire_threshold", 1000000.0)) * profile["millionaire_tax_rate"]
        cg_tax = capital_gains * profile["cap_gains_rate"]

    total_state_tax = ord_tax + cg_tax
    total_income = ordinary_income + capital_gains
    effective_rate = total_state_tax / total_income if total_income > 0 else 0.0

    return {
        "state_code": state_code,
        "state_name": state_name,
        "ordinary_income_tax": ord_tax,
        "capital_gains_tax": cg_tax,
        "total_state_tax": total_state_tax,
        "effective_state_rate": effective_rate,
        "notes": profile["notes"],
    }


def compare_state_tax_arbitrage(
    ordinary_spread: float,
    capital_gains: float = 0.0,
    base_w2_salary: float = 0.0,
    home_value: float = 0.0,
    annual_household_spend: float = 0.0,
    states: Optional[List[str]] = None,
    home_state: str = "WA"
) -> Dict[str, Any]:
    """
    Compares total state tax liabilities and comprehensive lifestyle costs across jurisdictions:
    1. State Ordinary & Capital Gains Taxes on option exercise / liquidity event.
    2. Real Estate Property Taxes based on home value ($1,000,000 baseline).
    3. Cost of Living Index (COLI) living expenses adjusted relative to tenant's residence home_state.
    4. Sales Tax on taxable consumption (estimated at 40% of non-housing budget).
    5. 1-Year and 5-Year Cumulative True Arbitrage Savings relative to home_state.
    """
    home_state = str(home_state or "WA").upper().strip()
    if home_state not in STATE_TAX_PROFILES:
        home_state = "WA"

    if states is None:
        base_states = ["WA", "WA_2028", "NV", "TX", "FL", "CA", "WY", "OR", "NY"]
        if home_state not in base_states:
            states = [home_state] + base_states
        else:
            states = base_states

    total_ordinary = ordinary_spread + base_w2_salary
    state_results = {}

    home_profile = STATE_TAX_PROFILES.get(home_state, STATE_TAX_PROFILES["WA"])
    home_coli = home_profile.get("coli_index", 152.0)

    for s in states:
        res = calculate_state_tax_for_state(s, total_ordinary, capital_gains)
        profile = STATE_TAX_PROFILES.get(s, STATE_TAX_PROFILES["WA"])

        # Annual recurring living costs
        prop_rate = profile.get("property_tax_rate", 0.0088)
        annual_prop_tax = home_value * prop_rate

        coli = profile.get("coli_index", 152.0)
        annual_living_cost = annual_household_spend * (coli / home_coli)

        sales_rate = profile.get("sales_tax_rate", 0.103)
        annual_sales_tax = (annual_household_spend * 0.40) * sales_rate

        annual_recurring = annual_prop_tax + annual_living_cost + annual_sales_tax

        res["profile"] = profile
        res["property_tax_rate"] = prop_rate
        res["annual_property_tax"] = annual_prop_tax
        res["coli_index"] = coli
        res["annual_living_cost"] = annual_living_cost
        res["sales_tax_rate"] = sales_rate
        res["annual_sales_tax"] = annual_sales_tax
        res["annual_recurring_cost"] = annual_recurring
        state_results[s] = res

    # Baselines for savings comparison: WA (Current), WA_2028, and tenant home_state
    wa_cur_tax = state_results.get("WA", {}).get("total_state_tax", 0.0)
    wa_cur_recurring = state_results.get("WA", {}).get("annual_recurring_cost", 0.0)
    wa_cur_1yr = wa_cur_tax + wa_cur_recurring
    wa_cur_5yr = wa_cur_tax + (wa_cur_recurring * 5.0)

    wa_2028_tax = state_results.get("WA_2028", {}).get("total_state_tax", 0.0)
    wa_2028_recurring = state_results.get("WA_2028", {}).get("annual_recurring_cost", 0.0)
    wa_2028_1yr = wa_2028_tax + wa_2028_recurring
    wa_2028_5yr = wa_2028_tax + (wa_2028_recurring * 5.0)

    home_tax = state_results[home_state]["total_state_tax"]
    home_recurring = state_results[home_state]["annual_recurring_cost"]
    home_1yr = home_tax + home_recurring
    home_5yr = home_tax + (home_recurring * 5.0)

    comparison_table = []
    for s in states:
        item = state_results[s]
        tax = item["total_state_tax"]
        recurring = item["annual_recurring_cost"]
        tot_1yr = tax + recurring
        tot_5yr = tax + (recurring * 5.0)

        savings_tax_home = home_tax - tax
        recurring_diff_home = home_recurring - recurring
        savings_1yr_home = home_1yr - tot_1yr
        savings_5yr_home = home_5yr - tot_5yr

        savings_tax_wa_current = wa_cur_tax - tax
        savings_tax_wa_2028 = wa_2028_tax - tax
        recurring_diff_vs_wa = wa_cur_recurring - recurring
        savings_5yr_vs_wa_current = wa_cur_5yr - tot_5yr
        savings_5yr_vs_wa_2028 = wa_2028_5yr - tot_5yr

        comparison_table.append({
            "state_code": s,
            "state_name": item["state_name"],
            "is_home_state": (s == home_state),
            "total_state_tax": tax,
            "ordinary_income_tax": item.get("ordinary_income_tax", 0.0),
            "capital_gains_tax": item.get("capital_gains_tax", 0.0),
            "effective_rate": item["effective_state_rate"],
            "effective_state_rate": item["effective_state_rate"],
            "property_tax_rate": item["property_tax_rate"],
            "annual_property_tax": item["annual_property_tax"],
            "coli_index": item["coli_index"],
            "annual_living_cost": item["annual_living_cost"],
            "sales_tax_rate": item["sales_tax_rate"],
            "annual_sales_tax": item["annual_sales_tax"],
            "annual_recurring_cost": recurring,
            "annual_recurring_savings_vs_home": recurring_diff_home,
            "annual_recurring_savings_vs_wa": recurring_diff_vs_wa,
            "comprehensive_1yr_cost": tot_1yr,
            "comprehensive_5yr_cost": tot_5yr,
            "savings_vs_home": savings_tax_home,
            "savings_5yr_vs_home": savings_5yr_home,
            "savings_vs_wa_current": savings_tax_wa_current,
            "savings_vs_wa_2028": savings_tax_wa_2028,
            "savings_5yr_vs_wa_current": savings_5yr_vs_wa_current,
            "savings_5yr_vs_wa_2028": savings_5yr_vs_wa_2028,
            "notes": item["notes"],
        })

    nv_item = state_results.get("NV", {})
    tx_item = state_results.get("TX", {})
    ca_item = state_results.get("CA", {})

    return {
        "home_state": home_state,
        "home_state_name": home_profile["name"],
        "home_annual_recurring": home_recurring,
        "home_1yr_total": home_1yr,
        "home_5yr_total": home_5yr,
        "total_ordinary_income": total_ordinary,
        "capital_gains": capital_gains,
        "home_value": home_value,
        "annual_household_spend": annual_household_spend,
        "wa_current_annual_recurring": wa_cur_recurring,
        "nevada_arbitrage_savings_vs_wa_2028": wa_2028_tax - nv_item.get("total_state_tax", 0.0),
        "nevada_5yr_true_savings_vs_wa_2028": wa_2028_5yr - (nv_item.get("total_state_tax", 0.0) + nv_item.get("annual_recurring_cost", 0.0) * 5.0),
        "texas_property_tax_penalty_vs_wa": tx_item.get("annual_property_tax", 0.0) - state_results.get("WA", {}).get("annual_property_tax", 0.0),
        "california_penalty_vs_wa": ca_item.get("total_state_tax", 0.0) - wa_cur_tax,
        "states": comparison_table,
    }

__all__ = ["STATE_TAX_PROFILES", "calculate_state_tax_for_state", "compare_state_tax_arbitrage"]
