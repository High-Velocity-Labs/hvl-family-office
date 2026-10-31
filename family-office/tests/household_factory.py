"""
Deterministic test household, built from tracked fixtures (`tests/fixtures/household_*.json`).

The suite never reads a private household. Tests that assert specific balances, equity grants, gifting, philanthropy,
tuition or compensation bind `HOUSEHOLD_FAMILY_ID` in the 'test' universe, where `conftest.py` builds this household
beside the seven demo personas.

The household ("The Sample Test Household", WA, MFJ) is synthetic: every name and figure is invented, round, and unrelated
to any real household. It is seeded through the same code path as the demo personas
(`scripts.seed_demo_families.seed_jones_family`), with its fixture loader pointed at `tests/fixtures/`:
- Company equity: one 409A at $500 and three NSO grants (strikes $10/$50/$120; 20,000 shares granted, 2,000 exercised).
- Spending $600,000/yr; gifting to 7 groups of 19 people, $90,000 in 2026; philanthropy 2019-2026;
  compensation 2017-2026 for both spouses; 23 tuition rows; 12 private investments; 529s of $220,000.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import security
from hvl_common.db import get_db_connection
from scripts import seed_demo_families

HOUSEHOLD_FAMILY_ID = 8
PUBLIC_HOUSEHOLD_FAMILY_ID = 9  # the same household in the 'public' universe; another id so it never shares state with family 8
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_FIXTURE_FOR = {
    "demo_jones_profile.json": "household_profile.json",
    "demo_jones_accounts.json": "household_accounts.json",
    "demo_jones_equity.json": "household_equity.json",
}

# (key, first name, college start year, 529 balance, account name). `user_id` comes from the seeded members.
_CHILDREN_529 = (
    ("maya", "Riley", 2028, 60000.0, "529 Plan - Riley (High School)"),
    ("ethan", "Avery", 2035, 120000.0, "529 Plan - Avery (Middle School)"),
    ("chloe", "Quinn", 2040, 40000.0, "529 Plan - Quinn (Grade School)"),
)
_BIRTHDATES = {"maya": "2010-01-01", "ethan": "2017-01-01", "chloe": "2022-01-01"}


def _fixture_loader(demo_loader):
    """Returns a fixture loader that serves the test household's files in place of the Jones demo fixtures."""

    def load(filename: str) -> Any:
        name = _FIXTURE_FOR.get(filename)
        if name is None:
            return demo_loader(filename)
        return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    return load


def _member_ids(global_db: Path, family_id: int) -> dict[str, int]:
    """Maps each fixture member key ("sarah", "maya", ...) to its user_id; members are created in fixture order."""
    keys = [m["key"] for m in json.loads((FIXTURE_DIR / "household_profile.json").read_text(encoding="utf-8"))["members"]]
    fam_db = global_db.parent / "families" / f"{family_id}.db"
    with get_db_connection(fam_db) as conn:
        user_ids = [int(r[0]) for r in conn.execute("SELECT user_id FROM users WHERE family_id = ? ORDER BY user_id", (family_id,))]
    return dict(zip(keys, user_ids, strict=True))


def build_household(global_db: Path, family_id: int = HOUSEHOLD_FAMILY_ID) -> None:
    """Seeds the test household as `family_id` into the universe whose global.db is `global_db`."""
    demo_loader = seed_demo_families._load_fixture
    seed_demo_families._load_fixture = _fixture_loader(demo_loader)
    try:
        seed_demo_families.seed_jones_family(global_db, family_id=family_id, verbose=False)
    finally:
        seed_demo_families._load_fixture = demo_loader

    ids = _member_ids(global_db, family_id)
    reserves = [
        {
            "user_id": ids[key], "name": f"{first} Sample", "first_name": first, "birthdate": _BIRTHDATES[key],
            "birth_year": int(_BIRTHDATES[key][:4]), "college_start": start, "current_529_balance": balance,
            "accounts": [{"name": account, "balance": balance}],
        }
        for key, first, start, balance, account in _CHILDREN_529
    ]
    fam_db = global_db.parent / "families" / f"{family_id}.db"
    security.db_save_encrypted(fam_db, "children_education_reserves", "education", reserves, family_id=family_id)
