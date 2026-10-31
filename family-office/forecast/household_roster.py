"""
forecast/household_roster.py: Who is in the household each year, for the ACA poverty line and per-adult coverage.
Pure data: the spouse's birth year and the dependent children's birth years.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# A child counts as a tax dependent (and so in the ACA household) through the year they turn 23 (full-time student).
DEPENDENT_MAX_AGE = 23


@dataclass(frozen=True)
class HouseholdRoster:
    """The primary plus an optional spouse and the dependent children (by birth year)."""
    spouse_birth_year: Optional[int] = None
    dependent_birth_years: Tuple[int, ...] = ()

    def spouse_age(self, year: int) -> Optional[int]:
        return None if self.spouse_birth_year is None else year - self.spouse_birth_year

    def dependents(self, year: int) -> int:
        return sum(1 for b in self.dependent_birth_years if 0 <= year - b <= DEPENDENT_MAX_AGE)

    def household_size(self, year: int) -> int:
        """Adults (the primary and any spouse, whatever their age) plus dependents in `year`."""
        return 1 + (1 if self.spouse_birth_year is not None else 0) + self.dependents(year)


SENIOR_AGE = 65


def seniors_65_plus(age_primary: int, age_spouse: int, has_spouse: bool) -> int:
    """How many of the household's adults are 65 or older (the tax engine's senior deductions count them)."""
    return (1 if age_primary >= SENIOR_AGE else 0) + (1 if has_spouse and age_spouse >= SENIOR_AGE else 0)
