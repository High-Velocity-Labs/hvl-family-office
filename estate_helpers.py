"""
estate_helpers.py: Statutory estate tax brackets, exemptions, tables, and state/federal
tax calculation routines for the HVL Family Office Estate Engine.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


class _EstateDbPathProxy(os.PathLike):
    """Dynamically resolves to the database for the active request universe."""
    def _path(self) -> Path:
        try:
            from routes.helpers import get_current_db_path
            return get_current_db_path()
        except Exception:
            from config import get_db_path_for_universe
            return get_db_path_for_universe()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def exists(self) -> bool:
        return self._path().exists()


DB_PATH = _EstateDbPathProxy()


# =============================================================================
# STATUTORY TAX BRACKETS & EXEMPTIONS
# =============================================================================

# 2026 Federal Unified Gift & Estate Tax Parameters (OBBBA 2026 statutory exemption)
FEDERAL_ESTATE_EXEMPTION_2026_SINGLE = 15_000_000.0
FEDERAL_ESTATE_EXEMPTION_2026_MFJ = 30_000_000.0  # with DSUE portability (IRC § 2010(c)(5))

# Legislative Rollback / Stress-Test Scenario (~$7.0M single / ~$14.0M MFJ inflation-adjusted)
# Note: OBBBA made the $15M/$30M exemption permanent; this toggle (apply_tcja_sunset) now models a
# "Legislative Rollback / Stress-Test Scenario (~$7M/$14M)" rather than an automatic TCJA sunset.
FEDERAL_ESTATE_EXEMPTION_SUNSET_SINGLE = 7_000_000.0
FEDERAL_ESTATE_EXEMPTION_SUNSET_MFJ = 14_000_000.0

FEDERAL_TOP_ESTATE_RATE = 0.40  # 40% statutory federal estate tax


# Washington State Estate Tax (RCW 83.100)
# Effective July 1, 2025 under WA law, indexed to Seattle CPI, with the 10–20% table. WA has NO state gift tax.
WA_ESTATE_EXCLUSION_SINGLE = 3_000_000.0
WA_ESTATE_EXCLUSION_MFJ = 6_000_000.0  # with AB trust / QTIP credit shelter planning

WA_ESTATE_TAX_TABLE = [
    # (Bracket threshold above exclusion, rate)
    (1_000_000.0, 0.100),
    (2_000_000.0, 0.140),
    (3_000_000.0, 0.150),
    (4_000_000.0, 0.160),
    (6_000_000.0, 0.170),
    (7_000_000.0, 0.180),
    (9_000_000.0, 0.190),
    (float("inf"), 0.200),
]


# New York State Estate Tax (NY Tax Law § 952)
# NY exclusion is $6,940,000. If estate exceeds 105% ($7,287,000), exclusion is 100% eliminated (cliff).
NY_ESTATE_EXCLUSION = 6_940_000.0
NY_CLIFF_MULTIPLIER = 1.05  # $7,287,000

NY_ESTATE_TAX_TABLE = [
    (500_000.0, 0.0306),
    (1_000_000.0, 0.0500),
    (1_500_000.0, 0.0550),
    (2_100_000.0, 0.0650),
    (2_600_000.0, 0.0700),
    (3_100_000.0, 0.0800),
    (3_600_000.0, 0.0850),
    (4_100_000.0, 0.0900),
    (5_100_000.0, 0.1000),
    (6_100_000.0, 0.1100),
    (7_100_000.0, 0.1200),
    (8_100_000.0, 0.1300),
    (9_100_000.0, 0.1400),
    (10_100_000.0, 0.1500),
    (float("inf"), 0.1600),
]


# Massachusetts Estate Tax (M.G.L. c. 65C)
MA_ESTATE_EXCLUSION = 2_000_000.0

# Oregon Estate Tax (ORS 118.010)
OR_ESTATE_EXCLUSION = 1_000_000.0


# =============================================================================
# CALCULATION FUNCTIONS
# =============================================================================

def calculate_wa_estate_tax(taxable_estate_above_exclusion: float) -> float:
    """Computes Washington state graduated estate tax under RCW 83.100."""
    if taxable_estate_above_exclusion <= 0:
        return 0.0

    tax = 0.0
    rem = taxable_estate_above_exclusion
    prev_thresh = 0.0

    for thresh, rate in WA_ESTATE_TAX_TABLE:
        chunk_cap = thresh - prev_thresh
        chunk = min(rem, chunk_cap)
        if chunk > 0:
            tax += chunk * rate
            rem -= chunk
        prev_thresh = thresh
        if rem <= 0:
            break

    return round(tax, 2)


def calculate_ny_estate_tax(gross_estate: float) -> float:
    """Computes New York state estate tax including the 105% cliff penalty."""
    if gross_estate <= NY_ESTATE_EXCLUSION:
        return 0.0

    # NY Cliff: If gross estate > 105% of exclusion, exemption is wiped out
    if gross_estate > (NY_ESTATE_EXCLUSION * NY_CLIFF_MULTIPLIER):
        taxable = gross_estate
    else:
        # Rapid phaseout between 100% and 105%
        ratio = (gross_estate - NY_ESTATE_EXCLUSION) / (NY_ESTATE_EXCLUSION * (NY_CLIFF_MULTIPLIER - 1.0))
        allowable_exclusion = NY_ESTATE_EXCLUSION * (1.0 - ratio)
        taxable = max(0.0, gross_estate - allowable_exclusion)

    tax = 0.0
    rem = taxable
    prev_thresh = 0.0
    for thresh, rate in NY_ESTATE_TAX_TABLE:
        chunk_cap = thresh - prev_thresh
        chunk = min(rem, chunk_cap)
        if chunk > 0:
            tax += chunk * rate
            rem -= chunk
        prev_thresh = thresh
        if rem <= 0:
            break

    return round(tax, 2)


def calculate_state_estate_tax(
    gross_estate: float,
    state: str = "WA",
    is_mfj: bool = True,
    has_ab_trust: bool = True,
) -> Dict[str, Any]:
    """Calculates state-level estate tax liability based on jurisdiction."""
    st = (state or "WA").upper().strip()

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
            "notes": "RCW 83.100 $3.0M threshold (indexed to Seattle CPI). No WA gift tax (lifetime gifts pass tax-free).",
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
            "notes": "NY Tax Law § 952. Estates exceeding 105% ($7.29M) lose 100% of exclusion retroactively.",
        }

    if st == "MA":
        exclusion = MA_ESTATE_EXCLUSION
        taxable_above = max(0.0, gross_estate - exclusion)
        tax = round(taxable_above * 0.12, 2) if taxable_above > 0 else 0.0
        return {
            "state": "MA",
            "state_name": "Massachusetts",
            "exclusion": exclusion,
            "has_estate_tax": True,
            "has_cliff": False,
            "taxable_estate": taxable_above,
            "tax_liability": tax,
            "top_rate": 0.16,
            "notes": "M.G.L. c. 65C graduated up to 16% on balances above $2.0M.",
        }

    if st == "OR":
        exclusion = OR_ESTATE_EXCLUSION
        taxable_above = max(0.0, gross_estate - exclusion)
        tax = round(taxable_above * 0.13, 2) if taxable_above > 0 else 0.0
        return {
            "state": "OR",
            "state_name": "Oregon",
            "exclusion": exclusion,
            "has_estate_tax": True,
            "has_cliff": False,
            "taxable_estate": taxable_above,
            "tax_liability": tax,
            "top_rate": 0.16,
            "notes": "ORS 118.010 with lowest threshold in the nation ($1.0M).",
        }

    # Zero estate tax states (CA, TX, FL, NV, WY, AZ, etc.)
    zero_tax_names = {
        "CA": "California",
        "TX": "Texas",
        "FL": "Florida",
        "NV": "Nevada",
        "WY": "Wyoming",
        "AZ": "Arizona",
        "CO": "Colorado",
        "TN": "Tennessee",
    }
    return {
        "state": st,
        "state_name": zero_tax_names.get(st, st),
        "exclusion": None,
        "has_estate_tax": False,
        "has_cliff": False,
        "taxable_estate": 0.0,
        "tax_liability": 0.0,
        "top_rate": 0.0,
        "notes": f"{st} imposes zero state estate or inheritance tax.",
    }


def calculate_comprehensive_estate_tax(
    gross_estate: float,
    state: str = "WA",
    is_mfj: bool = True,
    apply_tcja_sunset: bool = False,
    has_ab_trust: bool = True,
) -> Dict[str, Any]:
    """
    Computes combined Federal and State estate taxes, applying IRC § 2058 deduction.
    """
    if gross_estate <= 0:
        return {
            "gross_estate": 0.0,
            "state_estate_tax": 0.0,
            "federal_estate_tax": 0.0,
            "total_estate_tax": 0.0,
            "effective_tax_rate": 0.0,
            "net_estate_to_heirs": 0.0,
        }

    # 1. State Estate Tax
    state_res = calculate_state_estate_tax(
        gross_estate=gross_estate,
        state=state,
        is_mfj=is_mfj,
        has_ab_trust=has_ab_trust,
    )
    state_tax = state_res["tax_liability"]

    # 2. Federal Unified Exemption
    if apply_tcja_sunset:
        fed_exemption = FEDERAL_ESTATE_EXEMPTION_SUNSET_MFJ if is_mfj else FEDERAL_ESTATE_EXEMPTION_SUNSET_SINGLE
    else:
        fed_exemption = FEDERAL_ESTATE_EXEMPTION_2026_MFJ if is_mfj else FEDERAL_ESTATE_EXEMPTION_2026_SINGLE

    # 3. IRC § 2058 Deduction: State death taxes paid reduce federal gross estate
    adjusted_gross_for_fed = max(0.0, gross_estate - state_tax)
    fed_taxable = max(0.0, adjusted_gross_for_fed - fed_exemption)
    fed_tax = round(fed_taxable * FEDERAL_TOP_ESTATE_RATE, 2)

    total_tax = round(state_tax + fed_tax, 2)
    effective_rate = round((total_tax / gross_estate * 100), 2) if gross_estate > 0 else 0.0
    net_heirs = round(max(0.0, gross_estate - total_tax), 2)

    return {
        "gross_estate": round(gross_estate, 2),
        "state": state.upper(),
        "is_mfj": is_mfj,
        "apply_tcja_sunset": apply_tcja_sunset,
        "federal_exemption": fed_exemption,
        "federal_taxable_estate": fed_taxable,
        "irc_2058_state_tax_deduction": state_tax,
        "federal_estate_tax": fed_tax,
        "state_tax_details": state_res,
        "state_estate_tax": state_tax,
        "total_estate_tax": total_tax,
        "effective_tax_rate": effective_rate,
        "net_estate_to_heirs": net_heirs,
    }
