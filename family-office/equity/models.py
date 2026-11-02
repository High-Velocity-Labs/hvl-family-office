"""
Equity domain models, valuation constants, and DB path resolution.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import sys

from equity.iso_amt import amt_credit_recovery_years, iso_exercise_amt, iso_regular_income
from equity.state_tax import compensation_option_tax, resolve_state, stock_sale_tax_for_state
from services import tax_engine
from services.federal_capital_gains import long_term_gain_tax, niit_on_gain
from services.tax_calculations import state_capital_gains_tax, state_ordinary_income_tax


class _EngineDbPathProxy(os.PathLike):
    def _path(self) -> Path:
        from services.request_context import get_current_db_path
        return get_current_db_path()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"<EngineDbPathProxy: {self._path()}>"

    def exists(self) -> bool:
        return self._path().exists()

    @property
    def parent(self) -> Path:
        return self._path().parent


DB_PATH = _EngineDbPathProxy()

CURRENT_409A_PRICE = 100.0


def get_db_path() -> Any:
    """Returns active DB_PATH, respecting any test monkeypatching on equity_engine.DB_PATH."""
    eng = sys.modules.get("services.equity_engine") or sys.modules.get("equity_engine")
    if eng is not None and hasattr(eng, "DB_PATH") and eng.DB_PATH is not DB_PATH:
        return eng.DB_PATH
    return DB_PATH


@dataclass
class EquityGrant:
    grant_id: str
    nickname: str
    grant_date: str
    grant_type: str
    strike_price: float
    total_granted: float
    sold_quantity: float
    owned_exercised: float
    unexercised_vested: float
    unvested: float
    historical_cost_basis: float = 0.0  # Cost basis per share for owned stock
    fully_vested_date: str = ""
    company_id: int = 0
    company_name: str = ""

    @property
    def shares_granted(self) -> float:
        return self.total_granted

    @property
    def shares_vested(self) -> float:
        return self.unexercised_vested

    @property
    def shares_unvested(self) -> float:
        return self.unvested

    def calculate_at_price(
        self,
        share_price: float,
        include_wa_tax: bool = False,
        prior_income: float = 0.0,
        state: Optional[str] = None,
        tax_year: Optional[int] = None,
        filing_status: str = "MFJ",
        iso_disposition: str = "qualifying",
        exercise_fmv: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculates value, strike cost, tax drag, and net proceeds for this grant at any share price.
        `prior_income` is the household's other ordinary income; 0.0 (the default) means unknown, not an assumed salary.

        `state` is the household's state ("" when unset); None means no household, where only the
        `include_wa_tax` what-if stands in for WA. `iso_disposition` (qualifying, disqualifying, hold) and
        `exercise_fmv` (default: `share_price`) apply to ISOs only.
        """
        options = self.unexercised_vested
        gtype = str(self.grant_type).lower()
        is_rsu = gtype == "rsu"
        is_iso = gtype == "iso"
        eff_strike = 0.0 if is_rsu else self.strike_price
        strike_cost = 0.0 if is_rsu else (options * eff_strike)
        gross_option_value = options * share_price
        spread = gross_option_value if is_rsu else max(0.0, (share_price - eff_strike) * options)
        tax_state = resolve_state(state, include_wa_tax)

        # Tax on option exercise or RSU vesting:
        # - NSO / RSU: wages, taxed by federal, Medicare and the household's state income tax
        # - ISO: no regular tax at exercise; see equity/iso_amt.py for the disposition and AMT rules
        if is_iso:
            opt_tax = self._iso_tax(
                options, share_price, exercise_fmv if exercise_fmv is not None else share_price,
                iso_disposition, tax_state, prior_income, tax_year, filing_status,
            )
        else:
            opt_tax = compensation_option_tax(
                spread, prior_income, tax_state, include_wa_tax, tax_year, filing_status,
            )

        net_option_cashless = spread - opt_tax["total_tax"]

        # Owned Stock (already exercised shares held)
        owned_gross = self.owned_exercised * share_price
        total_basis = self.owned_exercised * self.historical_cost_basis
        stock_tax = stock_sale_tax_for_state(
            owned_gross, total_basis, prior_income, tax_state, tax_year, filing_status,
        )
        net_owned_stock = owned_gross - stock_tax["total_tax"]

        # Total for this grant
        nominal_gross = gross_option_value + owned_gross
        intrinsic_gross = spread + owned_gross
        total_tax = opt_tax["total_tax"] + stock_tax["total_tax"]
        net_value = net_option_cashless + net_owned_stock

        vesting_completion = "Fully Vested"
        if self.unvested > 0:
            vesting_completion = self.fully_vested_date or "In Vesting"

        return {
            "grant_id": self.grant_id,
            "nickname": self.nickname,
            "grant_date": self.grant_date,
            "grant_type": self.grant_type.upper(),
            "company_id": self.company_id,
            "company_name": self.company_name,
            "total_granted": self.total_granted,
            "strike_price": eff_strike,
            "share_price": share_price,
            "unexercised_options": options,
            "unvested_options": self.unvested,
            "vesting_completion": vesting_completion,
            "strike_cost": strike_cost,
            "spread": spread,
            "option_tax": opt_tax,
            "net_option_value": net_option_cashless,
            "owned_shares": self.owned_exercised,
            "owned_gross_value": owned_gross,
            "owned_cost_basis": total_basis,
            "stock_tax": stock_tax,
            "net_owned_value": net_owned_stock,
            "nominal_gross_value": nominal_gross,
            "total_gross_value": intrinsic_gross,
            "total_tax_drag": total_tax,
            "true_net_value": net_value,
        }


    def _iso_tax(
        self, options: float, sale_price: float, exercise_fmv: float, disposition: str, state: str,
        prior_income: float, tax_year: Optional[int], filing_status: str,
    ) -> Dict[str, Any]:
        """Regular tax for the disposition plus the AMT preference at exercise (see equity/iso_amt.py)."""
        strike = self.strike_price
        income = iso_regular_income(options, strike, exercise_fmv, sale_price, disposition)
        ordinary, gain = income["ordinary_income"], income["capital_gain"]

        std_ded = tax_engine.get_standard_deduction(filing_status)
        ordinary_fed = 0.0
        if ordinary > 0:  # disqualifying: wages for income tax, but not for FICA
            brackets = tax_engine.get_federal_brackets(filing_status)
            ordinary_fed = tax_engine.calculate_federal_ordinary_tax(
                max(0.0, prior_income + ordinary - std_ded), brackets,
            ) - tax_engine.calculate_federal_ordinary_tax(max(0.0, prior_income - std_ded), brackets)
        ordinary_state = state_ordinary_income_tax(state, prior_income, ordinary, tax_year)
        gain_state = state_capital_gains_tax(state, gain, tax_year, base_income=prior_income)

        # The gain stacks on ordinary taxable income in the 0/15/20% bands; NIIT applies above the MAGI threshold.
        gain_fed = long_term_gain_tax(gain, max(0.0, prior_income + ordinary - std_ded), filing_status)
        fed_tax = round(ordinary_fed + gain_fed, 2)
        med_tax = round(niit_on_gain(gain, prior_income + ordinary + gain, filing_status), 2)  # NIIT on the gain
        state_tax = round(ordinary_state + gain_state, 2)
        regular_tax = round(fed_tax + med_tax + state_tax, 2)

        preference = 0.0
        if disposition != "disqualifying":  # a same-year disqualifying sale erases the AMT preference
            preference = max(0.0, exercise_fmv - strike) * options
        amt = iso_exercise_amt(preference, prior_income, filing_status)
        # A held exercise owes only the AMT now; a qualifying sale's AMT was paid (and credited) at exercise.
        total_tax = round(amt["amt"], 2) if disposition == "hold" else regular_tax
        taxed = ordinary + gain
        return {
            "federal_tax": fed_tax,
            "medicare_tax": med_tax,
            "state_tax": state_tax,
            "total_tax": total_tax,
            "regular_tax": regular_tax,
            "iso_disposition": disposition,
            "amt_preference": round(amt["amt_preference"], 2),
            "amt_tentative_minimum_tax": round(amt["tentative_minimum_tax"], 2),
            "amt_exercise_tax": round(amt["amt"], 2),
            "amt_credit_carryforward": round(amt["amt_credit_carryforward"], 2),
            "amt_credit_recovery_years": amt_credit_recovery_years(
                amt["amt_credit_carryforward"], prior_income, filing_status, tax_year or 2026,
            ),
            "effective_rate": round((total_tax / taxed * 100), 1) if taxed > 0 else 0.0,
            "state_code": state,
            "is_iso": True,
        }


def get_default_equity_grants() -> List[EquityGrant]:
    """Returns empty grant list fallback."""
    return []
