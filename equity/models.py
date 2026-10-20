"""
Equity domain models, valuation constants, and DB path resolution.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import os
import sys

import tax_engine


class _EngineDbPathProxy(os.PathLike):
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
    eng = sys.modules.get("equity_engine")
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
        prior_income: float = 500000.0,
    ) -> Dict[str, Any]:
        """Calculates value, strike cost, tax drag, and net proceeds for this grant at any share price."""
        options = self.unexercised_vested
        gtype = str(self.grant_type).lower()
        is_rsu = gtype == "rsu"
        is_iso = gtype == "iso"
        eff_strike = 0.0 if is_rsu else self.strike_price
        strike_cost = 0.0 if is_rsu else (options * eff_strike)
        gross_option_value = options * share_price
        spread = gross_option_value if is_rsu else max(0.0, (share_price - eff_strike) * options)

        # Tax on option exercise or RSU vesting:
        # - NSO: ordinary income spread
        # - RSU: ordinary income on full share value upon vest
        # - ISO: Long-Term Capital Gains rates (20% Fed + 3.8% NIIT) for qualifying disposition
        if is_iso:
            wa_cg_tax = round(tax_engine.calculate_wa_capital_gains_tax(spread), 2) if include_wa_tax else 0.0
            fed_tax = round(spread * 0.20, 2)
            med_tax = round(spread * 0.038, 2)
            iso_tax = round(fed_tax + med_tax + wa_cg_tax, 2)
            effective_rate = round((iso_tax / spread * 100), 1) if spread > 0 else 0.0
            opt_tax = {
                "federal_tax": fed_tax,
                "medicare_tax": med_tax,
                "state_tax": wa_cg_tax,
                "total_tax": iso_tax,
                "amt_exercise_tax": round(spread * 0.28, 2),
                "effective_rate": effective_rate,
                "is_iso": True,
            }
        else:
            opt_tax = tax_engine.calculate_nso_exercise_tax(
                spread=spread,
                prior_ordinary_income=prior_income,
                include_wa_millionaire_tax=include_wa_tax,
            )

        net_option_cashless = spread - opt_tax["total_tax"]

        # Owned Stock (already exercised shares held)
        owned_gross = self.owned_exercised * share_price
        total_basis = self.owned_exercised * self.historical_cost_basis
        stock_tax = tax_engine.calculate_stock_sale_tax(
            sale_proceeds=owned_gross,
            cost_basis=total_basis,
            holding_period_days=366,
            other_income=prior_income,
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


def get_default_equity_grants() -> List[EquityGrant]:
    """Returns empty grant list fallback."""
    return []
