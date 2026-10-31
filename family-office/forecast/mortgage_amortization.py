"""
forecast/mortgage_amortization.py: Fixed-rate loan amortization for the event loans and the baseline mortgage.
Pure math: balance after N payments and principal retired in a given year, from rate, term, and original balance,
plus the year-by-year payoff of the loan on the starting balance sheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Rate and remaining term assumed for the starting mortgage only when the household has entered none (Settings) and
# the balance sheet reports none: the same 6.5% / 30 years the debt service has always used.
DEFAULT_BASELINE_MORTGAGE_RATE = 0.065
DEFAULT_BASELINE_MORTGAGE_TERM_YEARS = 30.0


@dataclass
class BaselineLoan:
    """The mortgage on the starting balance sheet. Refinance events replace its rate and balance."""
    balance: float
    annual_rate: float = DEFAULT_BASELINE_MORTGAGE_RATE
    term_years: float = DEFAULT_BASELINE_MORTGAGE_TERM_YEARS

    def level_annual_service(self) -> float:
        """Twelve level payments that retire `balance` at `annual_rate` over the remaining `term_years`."""
        return monthly_payment(self.balance, self.annual_rate, round(self.term_years * 12)) * 12.0


def monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
    """Level monthly payment on `principal` over `term_months` at `annual_rate`."""
    if principal <= 0 or term_months <= 0:
        return 0.0
    r = annual_rate / 12.0
    if r == 0:
        return principal / term_months
    return principal * (r * (1.0 + r) ** term_months) / ((1.0 + r) ** term_months - 1.0)


def balance_after(principal: float, annual_rate: float, term_months: int, months_paid: int) -> float:
    """Remaining balance after `months_paid` level payments."""
    if principal <= 0 or months_paid >= term_months:
        return 0.0
    if months_paid <= 0:
        return principal
    r = annual_rate / 12.0
    if r == 0:
        return principal * (1.0 - months_paid / term_months)
    growth_n, growth_k = (1.0 + r) ** term_months, (1.0 + r) ** months_paid
    return principal * (growth_n - growth_k) / (growth_n - 1.0)


def principal_paid_in_year(principal: float, annual_rate: float, term_months: int, loan_year: int) -> float:
    """Principal retired during `loan_year` (1 = the first 12 payments)."""
    start = balance_after(principal, annual_rate, term_months, (loan_year - 1) * 12)
    end = balance_after(principal, annual_rate, term_months, loan_year * 12)
    return max(0.0, start - end)


def pay_year(balance: float, annual_rate: float, annual_service: float) -> Tuple[float, float]:
    """
    Twelve monthly payments of `annual_service / 12` on `balance`. Returns (balance after, total paid): the
    last year pays only what is left, and a payment below the monthly interest leaves the balance flat.
    """
    if balance <= 0 or annual_service <= 0:
        return max(0.0, balance), 0.0
    r, monthly = annual_rate / 12.0, annual_service / 12.0
    bal, paid = balance, 0.0
    for _ in range(12):
        if bal <= 0:
            break
        interest = bal * r
        pay = min(monthly, bal + interest)
        bal -= max(0.0, pay - interest)
        paid += pay
    return max(0.0, bal), paid


def baseline_mortgage_rate(mortgage_accounts: List[Dict[str, Any]]) -> Optional[float]:
    """
    Balance-weighted annual rate (decimal) of the snapshot's mortgage accounts that report one in percent,
    or None when none does (the caller then uses DEFAULT_BASELINE_MORTGAGE_RATE).
    """
    weighted = [(abs(float(a.get("balance") or 0.0)), float(a.get("interest_rate") or 0.0)) for a in mortgage_accounts]
    rated = [(bal, rate) for bal, rate in weighted if bal > 0 and rate > 0]
    total = sum(bal for bal, _ in rated)
    return sum(bal * rate for bal, rate in rated) / total / 100.0 if total > 0 else None
