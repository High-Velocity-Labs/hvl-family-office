"""
State estate tax schedules: Washington (RCW 83.100), New York (Tax Law § 952 cliff), Massachusetts (M.G.L. c. 65C),
Oregon (ORS 118.010), and the states with no estate or inheritance tax.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


# Washington State Estate Tax (RCW 83.100), as amended by SB 6347 for deaths on or after 2026-07-01: a $3.0M
# exclusion and the 10–20% table (the 10–35% table applied only to deaths 2025-07-01..2026-06-30). WA has NO gift tax.
WA_ESTATE_EXCLUSION_SINGLE = 3_000_000.0
WA_ESTATE_EXCLUSION_MFJ = 6_000_000.0  # with AB trust / QTIP credit shelter planning

WA_ESTATE_TAX_TABLE = [
    # (Bracket threshold above exclusion, rate)
    (1_000_000.0, 0.100),
    (2_000_000.0, 0.140),
    (3_000_000.0, 0.150),
    (4_000_000.0, 0.160),
    (6_000_000.0, 0.180),
    (7_000_000.0, 0.190),
    (9_000_000.0, 0.195),
    (float("inf"), 0.200),
]


# New York State Estate Tax (NY Tax Law § 952). Basic exclusion amount for deaths in 2026 (indexed yearly).
# The credit (the tax on the exclusion) phases out between 100% and 105% of it and is gone above (the "cliff").
NY_ESTATE_EXCLUSION = 7_350_000.0
NY_CLIFF_MULTIPLIER = 1.05  # $7,717,500

NY_ESTATE_TAX_TABLE = [
    (500_000.0, 0.0306),
    (1_000_000.0, 0.0500),
    (1_500_000.0, 0.0550),
    (2_100_000.0, 0.0650),
    (2_600_000.0, 0.0800),
    (3_100_000.0, 0.0880),
    (3_600_000.0, 0.0960),
    (4_100_000.0, 0.1040),
    (5_100_000.0, 0.1120),
    (6_100_000.0, 0.1200),
    (7_100_000.0, 0.1280),
    (8_100_000.0, 0.1360),
    (9_100_000.0, 0.1440),
    (10_100_000.0, 0.1520),
    (float("inf"), 0.1600),
]


# Massachusetts Estate Tax (M.G.L. c. 65C § 2A, deaths from 2023): the old IRC § 2011(b) state death tax credit on
# the adjusted taxable estate (taxable estate - $60,000), less a $99,600 credit; no tax at or below $2.0M.
MA_ESTATE_EXCLUSION = 2_000_000.0
MA_ESTATE_ADJUSTMENT = 60_000.0
MA_ESTATE_CREDIT = 99_600.0
MA_STATE_DEATH_TAX_CREDIT_TABLE = [
    # (adjusted taxable estate from, base credit, rate on the excess)
    (0.0, 0.0, 0.0), (40_000.0, 0.0, 0.008), (90_000.0, 400.0, 0.016), (140_000.0, 1_200.0, 0.024),
    (240_000.0, 3_600.0, 0.032), (440_000.0, 10_000.0, 0.040), (640_000.0, 18_000.0, 0.048),
    (840_000.0, 27_600.0, 0.056), (1_040_000.0, 38_800.0, 0.064), (1_540_000.0, 70_800.0, 0.072),
    (2_040_000.0, 106_800.0, 0.080), (2_540_000.0, 146_800.0, 0.088), (3_040_000.0, 190_800.0, 0.096),
    (3_540_000.0, 238_800.0, 0.104), (4_040_000.0, 290_800.0, 0.112), (5_040_000.0, 402_800.0, 0.120),
    (6_040_000.0, 522_800.0, 0.128), (7_040_000.0, 650_800.0, 0.136), (8_040_000.0, 786_800.0, 0.144),
    (9_040_000.0, 930_800.0, 0.152), (10_040_000.0, 1_082_800.0, 0.160),
]

# Oregon Estate Tax (ORS 118.010): a filing threshold (not a deduction) of $1.0M, then base + rate on the excess.
OR_ESTATE_EXCLUSION = 1_000_000.0
OR_ESTATE_TAX_TABLE = [
    # (bracket from, base tax, rate on the excess)
    (1_000_000.0, 0.0, 0.1000), (1_500_000.0, 50_000.0, 0.1025), (2_500_000.0, 152_500.0, 0.1050),
    (3_500_000.0, 257_500.0, 0.1100), (4_500_000.0, 367_500.0, 0.1150), (5_500_000.0, 482_500.0, 0.1200),
    (6_500_000.0, 602_500.0, 0.1300), (7_500_000.0, 732_500.0, 0.1400), (8_500_000.0, 872_500.0, 0.1500),
    (9_500_000.0, 1_022_500.0, 0.1600),
]


# =============================================================================
# CALCULATION FUNCTIONS
# =============================================================================

def _graduated_tax(amount: float, table: List[Tuple[float, float]]) -> float:
    """Applies a (bracket ceiling, rate) table to `amount`."""
    tax = 0.0
    prev_thresh = 0.0
    for thresh, rate in table:
        if amount <= prev_thresh:
            break
        tax += (min(amount, thresh) - prev_thresh) * rate
        prev_thresh = thresh
    return tax


def calculate_wa_estate_tax(taxable_estate_above_exclusion: float) -> float:
    """Computes Washington state graduated estate tax under RCW 83.100."""
    if taxable_estate_above_exclusion <= 0:
        return 0.0
    return round(_graduated_tax(taxable_estate_above_exclusion, WA_ESTATE_TAX_TABLE), 2)


def calculate_ny_estate_tax(gross_estate: float) -> float:
    """NY Tax Law § 952: the tax on the whole estate less the applicable credit. The credit is the tax on the basic
    exclusion amount; between 100% and 105% of that amount it shrinks in a straight line, and above 105% it is zero."""
    if gross_estate <= NY_ESTATE_EXCLUSION:
        return 0.0
    cliff = NY_ESTATE_EXCLUSION * NY_CLIFF_MULTIPLIER
    full_credit = _graduated_tax(NY_ESTATE_EXCLUSION, NY_ESTATE_TAX_TABLE)
    credit = 0.0 if gross_estate >= cliff else full_credit * (1.0 - (gross_estate - NY_ESTATE_EXCLUSION) / (cliff - NY_ESTATE_EXCLUSION))
    return round(max(0.0, _graduated_tax(gross_estate, NY_ESTATE_TAX_TABLE) - credit), 2)


def _base_plus_rate(amount: float, table: List[Tuple[float, float, float]]) -> float:
    """Applies a (bracket from, base, rate on the excess) table to `amount`."""
    floor, base, rate = max((row for row in table if row[0] <= amount), key=lambda row: row[0])
    return base + rate * (amount - floor)


def calculate_ma_estate_tax(taxable_estate: float) -> float:
    """M.G.L. c. 65C § 2A: § 2011(b) credit on (taxable estate - $60,000), less the $99,600 credit; $0 at or below $2.0M."""
    if taxable_estate <= MA_ESTATE_EXCLUSION:
        return 0.0
    credit = _base_plus_rate(taxable_estate - MA_ESTATE_ADJUSTMENT, MA_STATE_DEATH_TAX_CREDIT_TABLE)
    return round(max(0.0, credit - MA_ESTATE_CREDIT), 2)


def calculate_or_estate_tax(taxable_estate: float) -> float:
    """ORS 118.010: graduated 10%–16% from the first dollar above $1.0M."""
    if taxable_estate <= OR_ESTATE_EXCLUSION:
        return 0.0
    return round(_base_plus_rate(taxable_estate, OR_ESTATE_TAX_TABLE), 2)


def calculate_state_estate_tax(
    gross_estate: float,
    state: str = "",
    is_mfj: bool = True,
    has_ab_trust: bool = True,
) -> Dict[str, Any]:
    """Calculates state-level estate tax liability based on jurisdiction (zero, and labelled, when no state is set)."""
    st = (state or "").upper().strip()

    if not st:
        return {
            "state": "",
            "state_name": "State not set",
            "exclusion": None,
            "has_estate_tax": False,
            "has_cliff": False,
            "taxable_estate": 0.0,
            "tax_liability": 0.0,
            "top_rate": 0.0,
            "notes": "No state of residence is set, so no state estate tax is applied.",
        }

    if st == "WA":
        exclusion = WA_ESTATE_EXCLUSION_MFJ if (is_mfj and has_ab_trust) else WA_ESTATE_EXCLUSION_SINGLE
        taxable_above = max(0.0, gross_estate - exclusion)
        tax = calculate_wa_estate_tax(taxable_above)
        return {
            "state": "WA",
            "state_name": "Washington",
            "exclusion": exclusion,
            "has_estate_tax": True,
            "has_cliff": False,
            "taxable_estate": taxable_above,
            "tax_liability": tax,
            "top_rate": 0.20,
            "notes": "RCW 83.100 $3.0M exclusion and 10–20% table (deaths from 2026-07-01, SB 6347). No WA gift tax (lifetime gifts pass tax-free).",
        }

    if st == "NY":
        tax = calculate_ny_estate_tax(gross_estate)
        taxable_above = max(0.0, gross_estate - NY_ESTATE_EXCLUSION)
        has_fallen_off_cliff = gross_estate > (NY_ESTATE_EXCLUSION * NY_CLIFF_MULTIPLIER)
        return {
            "state": "NY",
            "state_name": "New York",
            "exclusion": NY_ESTATE_EXCLUSION,
            "has_estate_tax": True,
            "has_cliff": True,
            "fell_off_cliff": has_fallen_off_cliff,
            "taxable_estate": gross_estate if has_fallen_off_cliff else taxable_above,
            "tax_liability": tax,
            "top_rate": 0.16,
            "notes": f"NY Tax Law § 952. Estates above 105% of the ${NY_ESTATE_EXCLUSION / 1e6:.2f}M exclusion (${NY_ESTATE_EXCLUSION * NY_CLIFF_MULTIPLIER / 1e6:.2f}M) lose the whole credit.",
        }

    if st == "MA":
        exclusion = MA_ESTATE_EXCLUSION
        taxable_above = max(0.0, gross_estate - exclusion)
        tax = calculate_ma_estate_tax(gross_estate)
        return {
            "state": "MA",
            "state_name": "Massachusetts",
            "exclusion": exclusion,
            "has_estate_tax": True,
            "has_cliff": False,
            "taxable_estate": taxable_above,
            "tax_liability": tax,
            "top_rate": 0.16,
            "notes": "M.G.L. c. 65C: graduated up to 16% less a $99,600 credit; no tax at or below $2.0M.",
        }

    if st == "OR":
        exclusion = OR_ESTATE_EXCLUSION
        taxable_above = max(0.0, gross_estate - exclusion)
        tax = calculate_or_estate_tax(gross_estate)
        return {
            "state": "OR",
            "state_name": "Oregon",
            "exclusion": exclusion,
            "has_estate_tax": True,
            "has_cliff": False,
            "taxable_estate": taxable_above,
            "tax_liability": tax,
            "top_rate": 0.16,
            "notes": "ORS 118.010: graduated 10%–16% from $1.0M, the lowest threshold in the nation.",
        }

    # States with neither an estate nor an inheritance tax. Any other state is not modeled, and says so.
    zero_tax_names = {
        "CA": "California",
        "TX": "Texas",
        "FL": "Florida",
        "NV": "Nevada",
        "WY": "Wyoming",
        "AZ": "Arizona",
        "CO": "Colorado",
        "TN": "Tennessee",
        "VA": "Virginia",
        "OH": "Ohio",
    }
    is_zero_state = st in zero_tax_names
    return {
        "state": st,
        "state_name": zero_tax_names.get(st, st),
        "exclusion": None,
        "has_estate_tax": False,
        "has_cliff": False,
        "taxable_estate": 0.0,
        "tax_liability": 0.0,
        "top_rate": 0.0,
        "notes": (
            f"{zero_tax_names[st]} has no state estate or inheritance tax." if is_zero_state
            else f"{st} estate and inheritance taxes are not modeled here, so no state tax is included."
        ),
    }
