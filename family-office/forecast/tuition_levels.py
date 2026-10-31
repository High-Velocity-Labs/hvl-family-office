"""
forecast/tuition_levels.py: Classifies tuition-ledger rows as pre-K, K-12, or college.
Pure: depends only on the row label (school name + notes) and the child's age that year.
"""

from __future__ import annotations

import re
from typing import Optional

PREK = "prek"
K12 = "k12"
COLLEGE = "college"

_COLLEGE_RE = re.compile(r"\b(college|universit\w*|undergrad\w*|campus|uc|csu|grad(uate)? school)\b", re.I)
_PREK_RE = re.compile(r"(pre[-\s]?k\b|pre[-\s]?school|nursery|toddler|daycare|day care|early childhood)", re.I)

# Ages (inclusive) used only when the ledger label says nothing about the level.
_PREK_MAX_AGE = 4
_K12_MAX_AGE = 17


def classify_tuition_level(label: str, child_age: Optional[int]) -> str:
    """Returns PREK, K12, or COLLEGE. The label wins over age; age decides unlabeled rows."""
    text = label or ""
    if _COLLEGE_RE.search(text):
        return COLLEGE
    if _PREK_RE.search(text):
        return PREK
    if re.search(r"kindergarten|grade|high school|middle school|elementary|k-?12", text, re.I):
        return K12
    if child_age is None:
        return K12
    if child_age <= _PREK_MAX_AGE:
        return PREK
    if child_age <= _K12_MAX_AGE:
        return K12
    return COLLEGE
