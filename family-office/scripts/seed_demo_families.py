"""
Idempotent Demo Family Seeder for HVL Family Office.
Targets the 'demo' (or 'test') universe database without touching production (Family 1).

Seeds 'The Jones Family' (San Francisco, CA):
- Dual High-Earners: Dr. Sarah Jones, MD (University Hospital Surgeon) & Alex Jones (Principal AI Engineer)
- 3 Children across all tiers: Maya (College @ UC Berkeley), Ethan (High School @ a San Francisco private high school), Chloe (a San Francisco private day school)
- Multi-Company Equity: NSOs across Nexus AI Inc. and CloudFlow Systems
- 5-Year Compensation and IRS Wage & Tax Transcripts with Safe Harbor calculations
- Full Monarch-compatible balance sheet: SF home + mortgage, 401(k)/403(b), taxable brokerage, 529s
"""

from __future__ import annotations
import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
# Ensure the app directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hvl_common.db import get_db_connection
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

import config
import security
from services.scenario_clone_service import PLAN_COLORS


# Demo-universe Private Markets LP Commitment Book (seeded into demo households only)
DEFAULT_DEMO_LP_COMMITMENTS: List[Dict[str, Any]] = [
    {
        "id": "lp_demo_1",
        "fund_name": "Horizon Venture Partners VIII",
        "fund_type": "Venture",
        "vintage_year": 2021,
        "total_commitment": 500000.0,
        "capital_called": 425000.0,
        "unfunded_commitment": 75000.0,
        "distributions_received": 110000.0,
        "current_nav": 640000.0,
        "last_mark_date": "2026-06-30",
        "expected_call_horizon_years": 2,
        "k1_status": "Received",
        "notes": "Late-stage AI and cloud enterprise venture portfolio.",
    },
    {
        "id": "lp_demo_2",
        "fund_name": "Beacon Capital Buyout Fund VI",
        "fund_type": "Private Equity",
        "vintage_year": 2022,
        "total_commitment": 750000.0,
        "capital_called": 450000.0,
        "unfunded_commitment": 300000.0,
        "distributions_received": 45000.0,
        "current_nav": 520000.0,
        "last_mark_date": "2026-03-31",
        "expected_call_horizon_years": 3,
        "k1_status": "Sent to CPA",
        "notes": "B2B enterprise software buyout vintage.",
    },
    {
        "id": "lp_demo_3",
        "fund_name": "Pinnacle Real Estate Opportunity II",
        "fund_type": "Real Estate",
        "vintage_year": 2023,
        "total_commitment": 350000.0,
        "capital_called": 175000.0,
        "unfunded_commitment": 175000.0,
        "distributions_received": 18000.0,
        "current_nav": 190000.0,
        "last_mark_date": "2025-12-31",
        "expected_call_horizon_years": 3,
        "k1_status": "Expected",
        "notes": "Logistics and student housing acquisitions.",
    },
]

def _social_security_section(primary_monthly: Optional[float] = None, spouse_monthly: Optional[float] = None) -> dict:
    """The `social_security` assumptions section (annual PIA per person) from monthly full-retirement-age benefits."""
    from db.benefit_inputs import SECTION_KEY

    monthly = {"primary": primary_monthly, "spouse": spouse_monthly}
    return {SECTION_KEY: {f"{p}_annual_pia": m * 12.0 for p, m in monthly.items() if m is not None}}


def assert_family_row_is_demo_or_absent(db_path: Path, family_id: int) -> None:
    """Refuses to overwrite a `families` row that is not a demo persona (`families.is_demo` set)."""
    p = Path(db_path)
    if not p.exists():
        return
    security.init_db(p)  # families.is_demo exists only from alembic 0010 on
    with get_db_connection(p) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='families'").fetchone():
            return
        row = conn.execute("SELECT is_demo FROM families WHERE family_id = ?", (int(family_id),)).fetchone()
    if row is None:
        return
    if not row[0]:
        raise RuntimeError(
            f"Refusing to seed demo persona over family_id={family_id} in {p.name}: the existing household is not a demo persona."
        )


def assert_demo_slots_are_safe(db_path: Path, family_ids) -> None:
    """Checks every demo persona slot in `db_path` (and its `families/{id}.db`) before anything is written."""
    p = Path(db_path)
    for fid in family_ids:
        assert_family_row_is_demo_or_absent(p, fid)
        if p.name == "global.db":
            assert_family_row_is_demo_or_absent(p.parent / "families" / f"{int(fid)}.db", fid)


def _prepare_seed_target(db_path: Path, family_id: int) -> tuple[Path, Optional[Path]]:
    """Routes seeding to families/{family_id}.db when passed global.db while keeping global.db in sync."""
    p = Path(db_path)
    if p.name == "global.db":
        fam_db = p.parent / "families" / f"{int(family_id)}.db"
        fam_db.parent.mkdir(parents=True, exist_ok=True)
        security.init_db(p)
        security.init_db(fam_db)
        with get_db_connection(p) as gconn, get_db_connection(fam_db) as fconn:
            row = gconn.execute(
                "SELECT name, is_demo, encryption_key_enc, support_access_enabled FROM families WHERE family_id = ?",
                (int(family_id),),
            ).fetchone()
            if row and row[2]:
                fconn.execute(
                    "INSERT INTO families (family_id, name, is_demo, encryption_key_enc, support_access_enabled) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(family_id) DO UPDATE SET encryption_key_enc = excluded.encryption_key_enc",
                    (int(family_id), row[0], row[1], row[2], row[3]),
                )
                fconn.commit()
        return fam_db, p
    security.init_db(p)
    return p, (p.parent.parent / "global.db" if p.parent.name == "families" else None)


def _household_key(db_path: Path, family_id: int) -> bytes:
    """The household FEK a seeded encrypted-text column is written under (never the root KEK; F-SEC-11)."""
    return security.get_family_key(db_path, int(family_id))


def _sync_seeded_family_to_global(fam_db: Path, global_db: Optional[Path], family_id: int) -> None:
    """Synchronizes seeded family auth/metadata rows from families/{family_id}.db to global.db."""
    # The seeds write planning assumptions as legacy `assumptions_json`; this moves them into encrypted section rows,
    # replacing the rows of an earlier seed (a section row already there would otherwise win over the new seed).
    from db.household_assumptions import move_legacy_assumptions

    with get_db_connection(fam_db) as conn:
        with conn:
            conn.execute(
                "DELETE FROM household_assumption_sections WHERE family_id = ? AND EXISTS ("
                "SELECT 1 FROM household_profile WHERE family_id = ? "
                "AND assumptions_json IS NOT NULL AND assumptions_json NOT IN ('', '{}'))",
                (int(family_id), int(family_id)),
            )
    move_legacy_assumptions(fam_db)
    if global_db is None or fam_db.resolve() == global_db.resolve():
        return
    security.init_db(global_db)
    fid = int(family_id)
    with get_db_connection(fam_db) as fconn, get_db_connection(global_db) as gconn:
        frow = fconn.execute(
            "SELECT family_id, name, primary_state, tax_filing_status, is_demo, encryption_key_enc, "
            "support_access_enabled, created_at FROM families WHERE family_id = ?",
            (fid,),
        ).fetchone()
        if frow:
            gconn.execute(
                "INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, encryption_key_enc, "
                "support_access_enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state, "
                "tax_filing_status = excluded.tax_filing_status, is_demo = excluded.is_demo, "
                "encryption_key_enc = excluded.encryption_key_enc, "
                "support_access_enabled = excluded.support_access_enabled",
                tuple(frow),
            )
        gconn.execute("DELETE FROM users WHERE family_id = ?", (fid,))
        for urow in fconn.execute(
            "SELECT user_id, family_id, name, email, email_hash, birthdate, relationship, role, pending_fek_enc, google_vault_synced, created_at FROM users WHERE family_id = ?",
            (fid,),
        ).fetchall():
            gconn.execute(
                "INSERT OR REPLACE INTO users (user_id, family_id, name, email, email_hash, birthdate, relationship, role, pending_fek_enc, google_vault_synced, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(urow),
            )
        gconn.execute("DELETE FROM account_roles WHERE family_id = ?", (fid,))
        for arow in fconn.execute(
            "SELECT family_id, monarch_account_id, role, beneficiary_user_id, is_hidden_from_family_office, is_user_confirmed FROM account_roles WHERE family_id = ?",
            (fid,),
        ).fetchall():
            gconn.execute(
                "INSERT OR REPLACE INTO account_roles (family_id, monarch_account_id, role, beneficiary_user_id, is_hidden_from_family_office, is_user_confirmed) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                tuple(arow),
            )
        gconn.commit()


def _universe_of_db_path(db_path: Path) -> str:
    """The universe a seed target belongs to: its nearest enclosing `demo|beta|sandbox|test|public` directory name.

    Whole directory names only. A substring match ("test" in "/tmp/fo_pytest_data_x/public/global.db") put a public
    household in the test universe and let its seeding wipe the test household's rows.
    """
    for part in reversed(Path(db_path).resolve().parts[:-1]):
        name = part.lower()
        if name in ("demo", "beta", "sandbox", "test", "public"):
            return config.normalize_universe(name)
    return "public"


def _clear_family_users(db_path: Path, family_id: int) -> None:
    """Clears all users for a family across monolithic, dedicated family, and global databases."""
    uni = _universe_of_db_path(db_path)
    security.init_db(db_path)
    with get_db_connection(db_path) as conn:
        try:
            conn.execute("DELETE FROM users WHERE family_id = ?", (family_id,))
            conn.commit()
        except sqlite3.OperationalError:
            pass
    fam_db = config.get_family_db_path(family_id, universe=uni)
    if fam_db.exists() and fam_db.resolve() != db_path.resolve():
        security.init_db(fam_db)
        with get_db_connection(fam_db) as conn:
            try:
                conn.execute("DELETE FROM users WHERE family_id = ?", (family_id,))
                conn.commit()
            except sqlite3.OperationalError:
                pass
    glob_db = config.get_global_db_path(universe=uni)
    if glob_db.exists() and glob_db.resolve() != db_path.resolve():
        security.init_db(glob_db)
        with get_db_connection(glob_db) as conn:
            try:
                conn.execute("DELETE FROM users WHERE family_id = ?", (family_id,))
                conn.commit()
            except sqlite3.OperationalError:
                pass


def seed_family_scenarios(
    db_path: Path,
    family_id: int,
    scenarios: List[Dict[str, Any]],
    active_scenario_id: str = "scen_baseline",
    custom_events: Optional[List[Dict[str, Any]]] = None,
    description_replacements: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    """Seeds hierarchical scenarios (parent and child plans) and events into scenario_system_state."""
    from forecast import engine as forecast_engine

    orig_db_path = getattr(forecast_engine, "DB_PATH", None)
    try:
        forecast_engine.DB_PATH = db_path

        # 1. Base event catalog for this family
        catalog = forecast_engine.get_default_event_catalog(family_id=family_id)

        # 2. Merge or replace custom events if provided
        if custom_events:
            catalog_by_id = {e["id"]: idx for idx, e in enumerate(catalog)}
            for ce in custom_events:
                cid = ce["id"]
                if cid in catalog_by_id:
                    catalog[catalog_by_id[cid]] = ce
                else:
                    catalog.append(ce)
                    catalog_by_id[cid] = len(catalog) - 1

        # 2b. Household-specific wording fixes on catalog events: {event_id: {old_text: new_text}}
        for ev in catalog:
            for old_text, new_text in (description_replacements or {}).get(ev.get("id"), {}).items():
                ev["description"] = str(ev.get("description") or "").replace(old_text, new_text)

        # 3. Ensure baseline scenario has the default baseline event IDs if empty
        def_scens = forecast_engine.get_default_scenarios(family_id=family_id)
        def_base_events = def_scens[0].get("event_ids", []) if def_scens else []

        for s in scenarios:
            if s.get("id") == "scen_baseline" and not s.get("event_ids"):
                s["event_ids"] = list(def_base_events)

        state = {
            "events": catalog,
            "scenarios": scenarios,
            "active_scenario_id": active_scenario_id,
            "equity_growth_preset": "moderate",
            "view_mode": "real",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        security.db_save_encrypted(db_path, "scenario_system_state", "scenarios", state, family_id=family_id)
    finally:
        if orig_db_path is not None:
            forecast_engine.DB_PATH = orig_db_path


def seed_family_historical_forecast(
    db_path: Path,
    family_id: int,
    historical_ribbon: List[Dict[str, Any]],
    historical_cash_flows: List[Dict[str, Any]],
) -> None:
    """Seeds historical net worth ribbon (2018-2025) and cash flow series into family_encrypted_store."""
    payload = {
        "historical_ribbon": historical_ribbon,
        "historical_cash_flow_series": historical_cash_flows,
    }
    security.db_save_encrypted(db_path, "historical_forecast_actuals", "forecast", payload, family_id=family_id)


def normalize_and_save_accounts(
    db_path: Path,
    raw_accounts: List[Dict[str, Any]],
    family_id: int,
    default_beneficiary_user_id: Optional[int] = None,
    spouse_beneficiaries: Optional[Dict[str, int]] = None,
) -> None:
    """
    Normalizes account payload ensuring both camelCase and snake_case keys are present for 100% interoperability.

    `spouse_beneficiaries` maps an owner's first name (accounts are named "<First> ...") to the user_id of the
    other spouse, so no account lists its own owner as beneficiary. `default_beneficiary_user_id` covers accounts
    whose owner is not in that map (for example a single parent naming a child).
    """
    normalized = []
    for acc in raw_accounts:
        a = dict(acc)
        bal = float(a.get("currentBalance") if a.get("currentBalance") is not None else a.get("current_balance") or 0.0)
        name = (a.get("displayName") or a.get("name") or "").strip()
        a["currentBalance"] = bal
        a["current_balance"] = bal
        a["displayName"] = name
        a["name"] = name
        a["isManual"] = True
        a["includeInNetWorth"] = True
        a["includeBalanceInNetWorth"] = True
        normalized.append(a)
    security.db_save_encrypted(db_path, "accounts", "monarch_sync", normalized, family_id=family_id)

    # Persist explicit account roles and beneficiary designations into SQLite account_roles table
    if family_id and db_path.exists():
        ret_ids = [
            str(a.get("id") or "").strip()
            for a in raw_accounts
            if str(a.get("role") or "").strip() in ("retirement_tax_deferred", "retirement_roth")
        ]
        # Leave the last retirement account without a default beneficiary so the Survivorship Audit demos an
        # actionable warning
        unconfirmed_ret_id = ret_ids[-1] if len(ret_ids) >= 2 else None
        with get_db_connection(db_path) as conn:
            for acc in raw_accounts:
                acc_id = str(acc.get("id") or "").strip()
                role = str(acc.get("role") or "").strip()
                if not (acc_id and role):
                    continue
                ben_id = acc.get("beneficiary_user_id")
                is_retirement = role in ("retirement_tax_deferred", "retirement_roth")
                if ben_id is None and is_retirement and acc_id != unconfirmed_ret_id:
                    acc_name = str(acc.get("name") or acc.get("displayName") or "").lower()
                    if acc_name.startswith("dr. "):
                        acc_name = acc_name[4:]
                    owner_ben = next(
                        (uid for first, uid in (spouse_beneficiaries or {}).items()
                         if acc_name.startswith(first.lower())),
                        None,
                    )
                    if owner_ben is not None:
                        ben_id = owner_ben
                    else:
                        ben_id = None if spouse_beneficiaries else default_beneficiary_user_id
                is_conf = 1 if ben_id else 0
                conn.execute("""
                    INSERT INTO account_roles (
                        family_id, monarch_account_id, role, beneficiary_user_id, is_user_confirmed,
                        is_hidden_from_family_office)
                    VALUES (?, ?, ?, ?, ?, 0)
                    ON CONFLICT(family_id, monarch_account_id) DO UPDATE SET
                        role = excluded.role,
                        beneficiary_user_id = excluded.beneficiary_user_id,
                        is_user_confirmed = excluded.is_user_confirmed,
                        is_hidden_from_family_office = excluded.is_hidden_from_family_office
                """, (family_id, acc_id, role, ben_id, is_conf))
            conn.commit()


def seed_family_tax_checklist_progress(db_path: Path, family_id: int, tax_year: int = 2025) -> None:
    """Seeds realistic mid-tax-season document statuses (Sent to CPA, Received, Waiting) for demo households."""
    from services.tax_checklist_service import get_tax_document_checklist
    chk = get_tax_document_checklist(db_path=db_path, family_id=family_id, tax_year=tax_year)
    items = chk.get("items") or []
    if not items:
        return
    status_map: Dict[str, str] = {}
    for idx, it in enumerate(items):
        item_id = str(it.get("id") or "")
        cat = str(it.get("category") or "")
        if not item_id:
            continue
        if cat in ("Earned Income", "Liabilities", "Cash & Banking"):
            status_map[item_id] = "sent_to_cpa"
        elif cat in ("Education", "Equity Grants", "Philanthropy"):
            status_map[item_id] = "received"
        elif cat in ("Investments", "Private LP & Illiquid"):
            # Keep K-1s and brokerage 1099-Consolidated in Waiting (except first LP if multiple)
            if item_id.startswith("k1_lp_0_"):
                status_map[item_id] = "received"
            elif item_id.startswith("k1_lp_1_"):
                status_map[item_id] = "sent_to_cpa"
            else:
                status_map[item_id] = "waiting"
        else:
            status_map[item_id] = "received" if idx < len(items) - 1 else "waiting"
    # Ensure at least one item remains 'waiting' so Chief of Staff Radar highlights pending tax forms
    if status_map and all(v != "waiting" for v in status_map.values()):
        last_key = list(status_map.keys())[-1]
        status_map[last_key] = "waiting"
    security.db_save_encrypted(db_path, "tax_document_checklist", "tax_checklist", status_map, family_id=family_id)


def _get_demo_advisor_conversations(family_id: int) -> List[Any]:
    """Returns curated, persona-aligned, PII-free demo advisor conversations for each demo household."""
    all_conversations: Dict[int, List[Any]] = {
        # Family 1: The Jones Family (San Francisco, CA - High Earners, Multi-Company Equity, 3 Kids)
        1: [
            ("beta-conv-jones-00", family_id, "section-overview", "Chief of Staff Executive Radar & Action Briefing", "Primary Member", 1, "2026-10-15 08:30:00", "2026-10-15 08:32:00", [
                ("user", "Run our Chief of Staff Executive Radar briefing. What needs our attention across taxes, LP commitments, and estate readiness this quarter?", "2026-10-15 08:30:00"),
                ("model", "### 🧭 Chief of Staff Executive Radar Briefing\n\n1. **Survivorship & Probate Readiness "
                    "(50/100, Action Required):**\n   * **Titling Gaps:** The **SF Primary Residence ($2.45M)** is "
                    "flagged critical and the **Marcus High Yield Emergency Fund ($150k)** is flagged as a warning: "
                    "neither carries revocable living trust titling (`RLT`) or a `TOD`/`POD` designation, which "
                    "exposes them to California probate delays and statutory fees.\n   * **Beneficiary Gap:** "
                    "**Alex's Roth IRA ($195k)** has no confirmed primary or contingent beneficiary.\n   * **RSU "
                    "Withholding Gap:** Supplemental withholding on RSU vests is a flat 22%, below your higher "
                    "marginal rate.\n   * **Equity Concentration:** Nexus AI stock is about **16.6%** of net worth "
                    "after tax, below the 20% level at which the audit raises a concentration notice.\n2. "
                    "**Private Markets LP Commitment Book "
                    "($1.60M Committed | 1.45x TVPI):**\n   * **Unfunded Dry Powder:** **$550,000** across 3 funds "
                    "(your $218.5k of cash covers only about 0.40x of it, so future calls would draw on the taxable "
                    "brokerage or equity sales).\n   * **Stale Valuation Mark:** **Pinnacle Real Estate Opportunity "
                    "II** ($190k NAV) is still marked as of `2025-12-31` (>120 days stale) with Schedule K-1 "
                    "`Expected`.\n3. **Tax Season Checklist & Safe Harbor:**\n   * **Checklist Progress:** **10 "
                    "of 12** documents received or sent to CPA; still waiting on the **Vanguard 1099-Consolidated** "
                    "and the **Pinnacle Real Estate Schedule K-1**.\n   * **2026 Safe Harbor Target:** **$218,925**, "
                    "the lower of 110% of the $375,000 prior-year federal tax ($412,500) and 90% of the projected "
                    "2026 federal tax ($243,250). With **$187,500** withheld so far, the remaining shortfall is "
                    "**$31,425**, about **$2,619** of extra withholding or 1040-ES payments per remaining "
                    "paycheck.", "2026-10-15 08:32:00")
            ]),
            ("beta-conv-jones-01", family_id, "section-equity", "Option Exercise & Capital Requirements", "Primary Member", 1, "2026-10-10 14:20:00", "2026-10-10 14:22:00", [
                ("user", "What are my strike capital requirements and estimated tax liability if I exercise my vested NSO options this quarter?", "2026-10-10 14:20:00"),
                ("model", "### 💡 Equity Liquidity & Tax Analysis\n\nBased on your active **Nexus Founding NSO (NX-01)** grant:\n\n1. **Strike Capital Required:** At $1.75 strike price for the 30,000 options still unexercised (50,000 vested, 20,000 already exercised), your total exercise cost is **$52,500.00**.\n2. **Spread Taxation (Ordinary Income):** NSO exercise triggers ordinary income tax on the spread between Fair Market Value (FMV) of $24.00 and your $1.75 strike price ($667,500 spread on 30,000 options). At California's top marginal tax bracket plus federal ordinary income rates, ensure estimated federal and state withholding reserves are funded prior to exercise.\n3. **Liquidity Options:** Consider modeling a **cashless exercise** or utilizing cash reserves in your high-yield savings to avoid liquidating core index holdings.", "2026-10-10 14:22:00")
            ]),
            ("beta-conv-jones-02", family_id, "section-holdings", "Core & Satellite Portfolio Drift Analysis", "Primary Member", 1, "2026-10-11 09:15:00", "2026-10-11 09:18:00", [
                ("user", "Is our portfolio still inside our IPS tolerance band, or do we need to rebalance?", "2026-10-11 09:15:00"),
                ("model", "### 📊 IPS Portfolio Drift Assessment\n\nYour portfolio is anchored to **Core & Satellite (50/20/15/5/10)** with a **±5.0% tolerance band**, measured across **$3.82M** of investable accounts (taxable brokerage, cash, and the 403(b), 457(b), 401(k) and Roth IRAs; 529s and the home are excluded).\n\n* **US Equities:** 62.0% vs. 50.0% target (**+12.0%, outside the band**). The engine's rebalance step is to trim about **$458k**.\n* **International Equities:** 20.3% vs. 20.0% (+0.3%, within the band).\n* **Bonds & Fixed Income:** 12.0% vs. 15.0% (-3.0%, within the band).\n* **Cash & Money Market:** 5.7% vs. 5.0% (+0.7%, within the band).\n* **Private Investments & VC:** 0.0% vs. 10.0%, flagged. This view counts only accounts tagged as private investments, so your three LP commitments ($1.35M of NAV) are tracked in the LP book instead and do not offset the gap.\n* **Recommendation:** Rebalance inside the retirement accounts, where $1.22M of US index funds (Alex's 401(k) and Sarah's 403(b)) can be swapped into international or bond funds with no tax cost, and direct new contributions to underweight sleeves. Avoid selling appreciated lots in the taxable brokerage.", "2026-10-11 09:18:00")
            ]),
            ("beta-conv-jones-03", family_id, "section-scenarios", "Monte Carlo Longevity Stress Test", "Primary Member", 0, "2026-10-12 16:40:00", "2026-10-12 16:45:00", [
                ("user", "How does our retirement plan hold up in a severe market downturn, like the Great Depression or 2008?", "2026-10-12 16:40:00"),
                ("model", "### 📉 Longevity Stress Test Replay\n\nRunning a Monte Carlo of 1,000 trials on the "
                    "Executive Baseline Plan ($230k/yr living spend, $250k/yr savings target of which take-home pay "
                    "leaves about $216k, both of you retiring "
                    "at 65) with your current mix of about 62% US stocks, 20% international, 12% bonds and 6% cash "
                    "(6.6% expected return, 13.8% volatility):\n\n* **Simulated Plan Success Rate:** **91.3%** of "
                    "trials keep the liquid portfolio (cash, taxable brokerage and retirement accounts) solvent "
                    "through age 100; the rate is the same at ages 85 and 90. Home equity and company stock are not "
                    "counted as liquid. Terminal net worth in today's dollars, which does include them: 10th "
                    "percentile **$24.3M**, median **$36.8M**, 90th percentile **$79.2M**.\n* **How to Read the Low "
                    "End:** The 10th-percentile figure is a floor, not a worst case. It is the home equity plus "
                    "Nexus and CloudFlow company equity that the model carries on its fixed path, so in the roughly "
                    "9% of trials where the investable portfolio is used up before 100, the plan leans on that "
                    "equity.\n* **Historical Replays:** The 1929 Great Crash, 1973-74, 2000 and 2008 crisis "
                    "sequences all stay solvent. All 98 historical start-year cohorts survive (the "
                    "worst, starting in 1929, bottoms out at about $5.2M of net worth in 2028).\n* **Guardrails:** "
                    "This run has spending guardrails off. Switch the guardrail mode to moderate or aggressive on "
                    "the Scenarios tab to see how trimming spending during a drawdown improves the weak "
                    "tail.", "2026-10-12 16:45:00")
            ]),
            ("beta-conv-jones-04", family_id, "section-arbitrage", "State Tax Arbitrage & Domicile Planning", "Primary Member", 0, "2026-10-13 11:00:00", "2026-10-13 11:04:00", [
                ("user", "What are the primary residency criteria for establishing tax domicile in a 0% personal income tax state?", "2026-10-13 11:00:00"),
                ("model", "### 🏛️ Domicile & Statutory Residency Rules\n\nTo change tax domicile away from "
                    "California:\n\n1. **Domicile Is Intent Plus Ties, Not a Day Count:** Domicile is the place you "
                    "intend to make your permanent home. The California FTB weighs where your home, family, work, "
                    "doctors, bank accounts, driver license, voter registration, and valued possessions are, and the "
                    "days you spend in each place are only one factor.\n2. **Day Counts Are a Separate, Statutory "
                    "Test in Some States:** A few states (for example New York and Connecticut) tax anyone who keeps "
                    "a home there and spends more than 183 days there as a statutory resident, even if their "
                    "domicile is elsewhere. California presumes that someone present for more than nine months is a "
                    "resident. Do not rely on a single number of days.\n3. **Not Every Low-Tax State Is a 0% "
                    "State:** Texas, Nevada, and Florida have no personal income tax. Washington taxes no wages or "
                    "ordinary income below $1M, but it taxes long-term capital gains (7%, rising to 9.9% on gains "
                    "above $1M), and this app treats SB 6346 as enacted: a 9.9% tax on income over $1M from 2028. "
                    "Both matter for a household with large equity sales.\n4. **Audit Trail:** Keep contemporaneous "
                    "travel records, flight receipts, and credit card transaction logs to substantiate your physical "
                    "presence and ties against California FTB residency audits.", "2026-10-13 11:04:00")
            ]),
            ("beta-conv-jones-05", family_id, "section-education", "Tiered Education Funding: UC Berkeley vs Private Prep", "Primary Member", 0, "2026-10-14 09:30:00", "2026-10-14 09:33:00", [
                ("user", "With Maya at UC Berkeley and Ethan attending his private high school, how should we prioritize 529 withdrawals versus taxable cash flow?", "2026-10-14 09:30:00"),
                ("model", "### 🎓 Education Funding & 529 Tax Rules\n\n1. **Maya (UC Berkeley - Higher Education):** Fully qualified for ScholarShare 529 distributions covering tuition, mandatory fees, books, and on/off-campus room & board. Distributions are 100% tax-free at both federal and California state levels.\n2. **Ethan (private high school):** While federal law permits up to $20,000/year per student from a 529 for K-12 tuition, **California does not conform** to this provision. Any California 529 distribution used for K-12 tuition is treated as a non-qualified state distribution, subjecting earnings to CA state income tax plus a 2.5% state penalty.\n3. **Recommendation:** Fund Ethan's private high school tuition directly from taxable cash flow or bonus reserves, preserving 529 compounding for college and graduate education.", "2026-10-14 09:33:00")
            ])
        ],
        # Family 2: The Miller Family (WA State - FIRE Early Retired, $6.5M Liquid, Zero W-2)
        2: [
            ("beta-conv-miller-01", family_id, "section-scenarios", "FIRE Dynamic Safe Withdrawal Rate (SWR) & Guardrails", "Primary Member", 1, "2026-10-11 10:15:00", "2026-10-11 10:18:00", [
                ("user",
                    "With about $6.5M in liquid investments and our annual spending at $160k, what does "
                    "our safe withdrawal rate look like under a dynamic guardrail strategy?", "2026-10-11 10:15:00"),
                ("model", "### 🛡️ FIRE Decumulation & Guardrail Analysis\n\nBased on your liquid portfolio (about "
                    "$6.58M including cash and retirement accounts) and $160,000 baseline living expenses:\n\n* "
                    "**Initial Withdrawal Rate:** Your $160k of living spending is about **2.4%** of the portfolio, "
                    "below the conservative 3.25% early retirement ceiling. The plan engine also adds a retirement "
                    "travel allowance ($40k a year until Robert is 66), the $24k ACA premium bridge, $39k of family "
                    "gifts and about $20k of Roth-conversion tax, so total 2026 outflows are about **$283k, or "
                    "4.3%** of the $6.58M portfolio.\n* **Current Allocation:** roughly 63/34/3: **$4.15M equity** "
                    "(63%), **$2.25M bonds** (34%), and **$0.18M cash** (3%). The bond and cash sleeves cover about "
                    "15 years of $160k spending, a defensive buffer against sequence-of-returns risk.\n* **Spending "
                    "Guardrails:** The baseline uses the moderate guardrail: spending is cut 15% in any year the "
                    "portfolio sits more than 15% below its prior peak. This app models it as a custom drawdown "
                    "rule, not the published Guyton-Klinger rules.\n* **Monte Carlo (1,000 trials, to age 100):** "
                    "**94.4%** success (liquid assets only, through age 100), with terminal net worth of **$4.4M** "
                    "(10th percentile), **$12.8M** (median) and **$37.8M** (90th percentile) in today's dollars. All "
                        "98 historical start-year cohorts survive; the weakest, the 1937 late-Depression "
                        "cohort, bottoms out "
                    "near $5.1M.\n* **Longevity:** Robert was born in 1974, so the projection runs to his age 100 "
                    "(2074), and the success rate above counts solvency through that age.", "2026-10-11 10:18:00")
            ]),
            ("beta-conv-miller-02", family_id, "section-tax", "Roth Conversion Ladder & ACA MAGI Optimization", "Primary Member", 1, "2026-10-12 13:20:00", "2026-10-12 13:24:00", [
                ("user", "We want to execute an $80k annual Roth conversion from Robert's Traditional IRA. How does this impact our Affordable Care Act (ACA) health insurance premium tax credits?", "2026-10-12 13:20:00"),
                ("model", "### ⚖️ Roth Conversion vs. ACA Premium Tax Credit Trade-off\n\n* **No ACA Credit to Lose:** Your MAGI is already above 400% of the federal poverty line (about $84,600 for two) every year, because your ~$88k of qualified dividends alone exceeds it, and an $80k conversion takes MAGI to roughly $246k once the realized gains and bond interest below are counted. Above 400% there is no premium tax credit, so you pay full-price premiums with or without the conversion.\n* **Federal Tax Cost:** Assume the 2025 pattern repeats: $88k of qualified dividends, $54k of realized gains, and about $24k of ordinary interest on the $600k of taxable BND (assumed 4% yield; money market interest ignored). Without a conversion, the $32,200 standard deduction absorbs the interest and leaves about $133,800 of preferential income, so federal tax is about $5,235. With the $80,000 conversion, taxable ordinary income is $71,800 (about $8,120 of tax in the 10% and 12% brackets), and the 0% capital-gains bracket (up to $98,900 of taxable income) has only $27,100 of room left, so about $114,900 of the dividends and gains is taxed at 15% (about $17,235). Total about $25,355, an incremental federal cost of about $20,120, or roughly 25%, not 12% or 13.5%. MAGI of about $246k sits just under the $250k NIIT threshold, so a bigger conversion or more realized gains would add 3.8%.\n* **Washington State:** No state tax on wages, interest, dividends, or conversions; the state taxes only long-term capital gains above its threshold.\n* **Why Convert:** Filling the low brackets now reduces Required Minimum Distributions, which begin at age 75 for Robert.", "2026-10-12 13:24:00")
            ]),
            ("beta-conv-miller-03", family_id, "section-holdings", "Tax-Efficient Asset Location & Dividend Drag", "Primary Member", 0, "2026-10-13 15:45:00", "2026-10-13 15:48:00", [
                ("user", "Our taxable Schwab brokerage generates roughly $88k/year in qualified dividends. Should we reallocate fixed income to mitigate tax drag?", "2026-10-13 15:45:00"),
                ("model",
                    "### 📊 Asset Location Strategy (Taxable vs. Tax-Deferred)\n\n* **Current Placement:**"
                    " About $1.65M of bonds sit in Robert's Traditional Rollover IRA, which shields their"
                    " ordinary interest from annual tax. Your Roth IRAs hold equities, which is the right"
                    " place for the highest-growth assets.\n* **Taxable Drag:** The taxable Schwab "
                    "account holds $600k of BND, whose interest is taxed as ordinary income each year, "
                    "alongside $3.55M of VTI/VXUS. After the $32,200 standard deduction, most of your "
                    "~$88k of qualified dividends falls in the 0% federal bracket, with the rest at 15%; "
                    "realized gains and Roth conversions stack on top and push more into 15%. Washington "
                    "taxes none of these dividends.\n* **Options:** Hold the taxable bond sleeve in "
                    "Treasury or municipal funds, or shift it toward equities as Roth conversions shrink "
                    "the IRA and free up bond space there.\n* **Cash Cushion:** Your $180k cash reserve "
                    "($35k checking plus $145k government money market) covers about 13 months of $160k "
                    "spending and prevents forced selling during equity corrections.", "2026-10-13 15:48:00")
            ])
        ],
        # Family 3: The Chen Family (NYC - Series A Tech Founder, High Illiquidity, Toddler)
        3: [
            ("beta-conv-chen-01", family_id, "section-equity", "ISO Exercise & Alternative Minimum Tax (AMT) Exposure", "Primary Member", 1, "2026-10-10 11:10:00", "2026-10-10 11:14:00", [
                ("user", "If I exercise my 115,625 vested ISOs in Aether Robotics at the current $2.80 409A common "
                    "fair market value ($0.50 strike), what is our AMT exposure this year?", "2026-10-10 11:10:00"),
                ("model", "### ⚠️ ISO Exercise & Alternative Minimum Tax (AMT) Analysis\n\nBased on your Aether "
                    "Robotics incentive stock options (150,000 granted, 115,625 vested through the October 2026 "
                    "monthly vest):\n\n1. **Strike Capital Required:** 115,625 shares × $0.50 strike = **$57,813** "
                    "upfront cash.\n2. **FMV for the Spread:** The ISO spread uses the 409A value of the common "
                    "stock ($2.80), not the $8.50 Series A preferred price paid by investors.\n3. **AMT Preference "
                    "Spread:** ($2.80 − $0.50) × 115,625 = **$265,938** added to Alternative Minimum Taxable Income "
                    "(AMTI) in the year of exercise.\n4. **AMT Estimate:** Exercising and holding owes no regular "
                    "tax. Stacked on about $495,000 of 2026 household wages, the 2026 AMT exemption phases out and "
                    "the tentative minimum tax is about **$168,900** against about **$101,000** of regular tax, so "
                    "the AMT is about **$67,900**. This is a simple estimate (wages plus the preference, no other "
                    "Form 6251 adjustments, no state tax), so ask your CPA to run the full Form 6251 before you "
                    "exercise.\n5. **Form 8801 Minimum Tax Credit:** Any AMT paid on ISO exercise "
                    "generates a Minimum Tax Credit (about $67,900 here) that carries forward indefinitely to offset "
                    "regular tax in future years when regular tax exceeds tentative AMT.\n6. "
                    "**Timing:** Exercising earlier in the "
                    "year leaves time to react to valuation changes; a disqualifying disposition in the same "
                    "calendar year removes the AMT preference but turns the spread into ordinary income.",
                    "2026-10-10 11:14:00")
            ]),
            ("beta-conv-chen-02", family_id, "section-scenarios", "Section 1202 QSBS 5-Year Holding Period Strategy", "Primary Member", 1, "2026-10-12 14:00:00", "2026-10-12 14:05:00", [
                ("user", "How do our Aether Robotics founder shares qualify for Section 1202 QSBS, and what are the rules if the company raises a Series B next year?", "2026-10-12 14:00:00"),
                ("model", "### 📜 Section 1202 QSBS Tax Exemption Framework\n\n* **Federal Capital Gain Exclusion:** Your Aether Robotics founder stock was issued in 2023, before July 5, 2025, so the original rules apply: the exclusion is capped at the greater of **$10,000,000** or 10x adjusted basis per company.\n* **Statutory Requirements:** Stock must be acquired at original issuance from an active domestic C-Corporation with gross assets of $50M or less immediately before and after issuance.\n* **5-Year Holding Clock:** The holding period began on your initial issuance/83(b) filing date. For stock issued before July 5, 2025 only a full 5-year hold qualifies; the 3-year (50%) and 4-year (75%) tiers apply only to stock issued after that date, such as shares issued in a later round. A sale before the 5-year anniversary disqualifies the sold shares (or requires a Section 1045 rollover into another qualifying QSB within 60 days).\n* **NYS/NYC Tax Conformance:** New York State and City start from federal adjusted gross income, so the federal exclusion carries through; confirm the treatment with a New York tax professional.", "2026-10-12 14:05:00")
            ]),
            ("beta-conv-chen-03", family_id, "section-education", "529 Superfunding for Leo & NY State Tax Deduction", "Primary Member", 0, "2026-10-14 08:30:00", "2026-10-14 08:34:00", [
                ("user",
                    "We want to superfund Leo's college savings with a $190,000 contribution. How does "
                        "the 5-year gift forward election work, and what is our NY state tax deduction?",
                    "2026-10-14 08:30:00"),
                ("model",
                    "### 🎓 529 5-Year Forward Superfunding (Form 709)\n\n* **Annual Gift Exclusion "
                    "Forwarding:** Couples filing MFJ can contribute up to **$190,000** in a single year "
                    "($38,000 annual exclusion × 5 years) without triggering federal gift tax or tapping "
                    "lifetime unified gift exemptions, by electing 5-year averaging on IRS Form 709.\n* "
                    "**Compound Growth Horizon:** Superfunding at age 2 gives Leo 16 years of tax-free "
                    "compounding. At an assumed 6.5% net return, $190k projects to ~$520,000 by college "
                    "matriculation at age 18.\n* **New York State Tax Deduction Cap:** NY State limits "
                    "the income tax deduction to **$10,000/year** for married couples ($5,000 for "
                    "singles). The excess $180,000 does not carry forward for NY state tax deductions, "
                    "but all future growth and qualified withdrawals remain 100% tax-free at both federal"
                    " and NY state levels.", "2026-10-14 08:34:00")
            ])
        ],
        # Family 4: The Ramirez Family (Austin, TX - Middle-Class Working Household, TRS Pension, Electrical Contractor)
        4: [
            ("beta-conv-ramirez-01", family_id, "section-overview", "Texas TRS Pension Integration & Social Security", "Primary Member", 1, "2026-10-11 11:00:00", "2026-10-11 11:05:00", [
                ("user", "How does Sofia's Texas Teacher Retirement System (TRS) pension affect our Social Security benefits? We heard about the Windfall Elimination Provision (WEP).", "2026-10-11 11:00:00"),
                ("model",
                    "### 🏛️ Texas TRS & Social Security After WEP / GPO Repeal\n\n* **WEP and GPO No "
                    "Longer Apply:** The Social Security Fairness Act (signed January 5, 2025) repealed "
                    "the Windfall Elimination Provision and the Government Pension Offset for benefits "
                    "payable after December 2023. Sofia's non-covered TRS pension no longer reduces her "
                    "own Social Security benefit from earlier private-sector work, or any spousal or "
                    "survivor benefit.\n* **Carlos's Social Security Is Unaffected:** Carlos's primary "
                    "Social Security benefit from electrical contracting is 100% protected and based on "
                    "his full covered earnings history.\n* **Retirement Replacement Rate:** Sofia's TRS "
                    "pension (projected at 2.3% × years of service × final average salary = ~$48k/yr) "
                    "combined with Carlos's Social Security provides an exceptional guaranteed baseline, "
                    "reducing dependence on market withdrawals. The Settings tab takes each adult's "
                    "pension, and Sofia's is entered at $48k a year in today's dollars from age 62, so "
                    "the Scenarios tab counts it alongside your savings and Social Security.", "2026-10-11 11:05:00")
            ]),
            ("beta-conv-ramirez-02", family_id, "section-cashflow", "Roth IRA Contributions & the Pro-Rata Rule", "Primary Member", 1, "2026-10-13 14:10:00", "2026-10-13 14:15:00", [
                ("user", "Carlos earns about $94k from Ramirez Electric and Sofia earns $62k as a teacher, roughly $156k together. Carlos also has a $30k Traditional IRA. Should we do a backdoor Roth IRA?", "2026-10-13 14:10:00"),
                ("model", "### ⚡ Roth IRA Strategy & the Pro-Rata Rule\n\n**Recommendation: contribute directly to Roth IRAs; skip the backdoor.**\n\n1. **No Backdoor Needed:** The 2026 Roth IRA income phase-out for married couples filing jointly begins at $242,000 of MAGI. At roughly $156k you are well under it, so Carlos and Sofia can each contribute directly up to the 2026 IRA limit of $7,500.\n2. **Pro-Rata Rule:** Carlos's $30k pre-tax Traditional IRA would make a backdoor conversion mostly taxable. Under IRC Section 408(d)(2), all of a taxpayer's Traditional IRA balances at year-end are aggregated, so about 80% of a $7,500 conversion ($30,000 of $37,500) would be taxable rather than tax-free.\n3. **Clearing the Pro-Rata Balance:** Only if you later need a backdoor, rolling the $30k into a workplace plan that accepts incoming IRA rollovers removes it from the calculation.\n4. **Texas 0% State Tax:** With no state income tax, the choice between pre-tax and Roth turns on your 22% federal marginal bracket today versus your expected bracket in retirement.", "2026-10-13 14:15:00")
            ]),
            ("beta-conv-ramirez-03", family_id, "section-education", "Mortgage Prepayment (3.375%) vs. Texas 529 College Savings", "Primary Member", 0, "2026-10-14 10:20:00", "2026-10-14 10:24:00", [
                ("user", "We have an extra $450/month in cash flow. Should we make extra principal payments on our 3.375% mortgage or split it between Mateo and Camila's Texas 529 plans?", "2026-10-14 10:20:00"),
                ("model", "### ⚖️ Debt Prepayment vs. College Investment Trade-off\n\n* **Mortgage Rate Benchmark:** Your fixed 3.375% mortgage interest rate is historically low and well below current Treasury yields (~4.2%) and conservative diversified equity returns (~6.5–7.5%). Prepaying yields an after-tax guaranteed return of only 3.375%.\n* **College Tuition Horizon:** Mateo (age 13) is 5 years from college, and Camila (age 9) is 9 years away. In-state public tuition at UT Austin or Texas A&M currently averages ~$28k/year all-in (tuition, fees, room & board).\n* **Strategic Recommendation:** Direct $225/month each into Mateo and Camila's Texas College Savings 529 portfolios (age-based conservative tracks). Maintaining the 3.375% mortgage schedule preserves liquidity and provides superior compounding for their college horizon.", "2026-10-14 10:24:00")
            ])
        ],
        # Family 5: The Taylor Family (Columbus, OH - Young Accumulators, School-Age Child, Student Debt)
        5: [
            ("beta-conv-taylor-01", family_id, "section-cashflow", "Federal Student Loans vs. 403(b) Employer Match", "Primary Member", 1, "2026-10-12 12:00:00", "2026-10-12 12:04:00", [
                ("user", "We have $16,500 left on federal student loans at 4.65%. Should we accelerate payoff or invest more into Danielle's hospital 403(b)?", "2026-10-12 12:00:00"),
                ("model", "### 🎯 Student Loan Payoff vs. 403(b) Match Optimization\n\n1. **Rule 1: Always Capture 100% of Employer Match:** Danielle's hospital 403(b) provides a 50% match on the first 6% of salary. That is an immediate, risk-free **50% instant return**, vastly exceeding the 4.65% interest cost of the student loans.\n2. **Student Loan Interest Deduction:** At $131k MFJ income, your interest on the $16,500 balance is deductible above the line on Form 1040 (up to $2,500 a year, with the deduction phasing out only at higher incomes than yours), which lowers the effective borrowing cost to about 4.0% after federal and Ohio tax.\n3. **Action Plan:** Maintain standard monthly amortization ($210/mo) on the student loans while maximizing Danielle's 403(b) match and contributing to Roth IRAs.", "2026-10-12 12:04:00")
            ]),
            ("beta-conv-taylor-02", family_id, "section-education", "Ohio CollegeAdvantage 529 State Tax Deduction", "Primary Member", 1, "2026-10-13 16:30:00", "2026-10-13 16:34:00", [
                ("user", "How much can we deduct on our Ohio state tax return for contributing to Jordan's 529 college savings plan?", "2026-10-13 16:30:00"),
                ("model", "### 🌰 Ohio CollegeAdvantage (OTTA) 529 Tax Rules\n\n* **State Tax Deduction Limit:** Ohio allows married couples filing jointly to deduct up to **$4,000 per year, per beneficiary** from Ohio adjusted gross income for contributions to Ohio's 529 CollegeAdvantage plan.\n* **Unlimited Carryforward:** Any contribution exceeding $4,000 in a calendar year can be carried forward indefinitely and deducted in future tax years until fully exhausted.\n* **Net Savings:** At Ohio's top marginal bracket (~2.75%), a $4,000 annual contribution yields an immediate $110 in state tax savings, in addition to 100% tax-free growth and tax-free qualified distributions for Jordan's future education.", "2026-10-13 16:34:00")
            ]),
            ("beta-conv-taylor-03", family_id, "section-overview", "Emergency Fund Sizing With Childcare Costs", "Primary Member", 0, "2026-10-14 09:10:00", "2026-10-14 09:14:00", [
                ("user", "Jordan's before- and after-school care and summer camps cost $1,250/month ($15,000/yr). Should our emergency fund be 3 months or 6 months?", "2026-10-14 09:10:00"),
                ("model",
                    "### 🛡️ Emergency Reserve Calibration for Young Families\n\n* **Recommended Reserve: "
                    "6 Months ($34,000)**, based on $68,000 of annual spending. You hold $18,700 in "
                    "checking and savings today, about 3.3 months.\n* **Fixed Cost Inflexibility:** "
                    "Childcare ($1,250/mo) and the mortgage (about $997/mo of principal and interest on "
                    "the $192k, 4.25% loan with 27 years left, or $12.0k/yr of seeded debt service, on "
                    "top of the $68,000 of spending) are mandatory fixed expenses that cannot be quickly "
                    "eliminated if Marcus or Danielle experiences a career transition.\n* **Dual-Earner "
                    "Advantage:** Because Danielle is a healthcare RN and Marcus works in logistics "
                    "management, dual-income diversification reduces the odds of simultaneous "
                    "unemployment. However, keeping 6 months in a 4.5% high-yield savings account (HYSA) "
                    "provides peace of mind and prevents relying on high-interest credit cards or tapping"
                    " retirement funds.", "2026-10-14 09:14:00")
            ])
        ],
        # Family 6: The Foster Family (Denver, CO - Single-Parent Household, Sole Breadwinner, Estate Protection)
        6: [
            ("beta-conv-foster-01", family_id, "section-estate", "Sole-Earner Estate Planning & Legal Guardianship for Noah", "Primary Member", 1, "2026-10-11 14:00:00", "2026-10-11 14:05:00", [
                ("user", "As a single parent, what estate planning documents do I need to ensure Noah (age 12) is protected if something happens to me?", "2026-10-11 14:00:00"),
                ("model", "### 👨‍👦 Single-Parent Estate Protection Framework\n\n1. **Revocable Living Trust (RLT):** "
                    "Critical. Without a trust, your Denver bungalow ($540k) and accounts would pass through "
                    "Colorado probate court, and a court-appointed conservator would control assets until Noah turns "
                    "21 (a Colorado conservatorship created only because the protected person is a minor ends at 21, "
                    "C.R.S. 15-14-431). An RLT allows your appointed Successor Trustee to manage funds for Noah's "
                    "health, education, maintenance, and support (HEMS) well into adulthood (e.g., ages 25/30).\n2. "
                    "**Guardian Nomination:** Explicitly designates who will raise Noah. Under C.R.S. 15-14-202 a "
                    "parent can nominate a guardian in a will or in another signed writing; either one is enough, "
                    "and a will is the usual place for it.\n3. **Beneficiary Designations:** Ensure your 403(b), "
                    "Roth IRA, and life insurance name the Revocable Living Trust as the contingent beneficiary "
                    "(with appropriate look-through trust provisions), never a minor child directly.\n4. **Advance "
                    "Directives:** Medical Power of Attorney, HIPAA authorization, and Durable Financial Power of "
                    "Attorney.", "2026-10-11 14:05:00")
            ]),
            ("beta-conv-foster-02", family_id, "section-overview", "Life & Disability Insurance Adequacy for Noah's Future", "Primary Member", 1, "2026-10-13 10:15:00", "2026-10-13 10:20:00", [
                ("user", "I have 2x salary ($230k) in group life insurance through Mile High Pediatric Hospital. Is this enough to cover Noah?", "2026-10-13 10:15:00"),
                ("model", "### 🛡️ Life & Disability Protection Gap Analysis\n\n* **The 2x Salary Gap:** $230,000 is insufficient for a sole provider. Noah is 12; he has 6 years until college and 10 years until financial independence. Surviving mortgage debt ($315k) alone exceeds your employer group coverage.\n* **Coverage Recommendation:** Purchase a **15-year level term policy of $1,000,000 to $1,250,000**. Term rates for a healthy physical therapist in her late 30s/early 40s are very affordable (~$45–$65/month) and provide full income replacement plus college funding.\n* **Own-Occupation Disability:** As a pediatric physical therapist, physical mobility is essential to your W-2 earnings. Review whether hospital disability is 'any occupation' or 'own occupation', and consider a supplemental individual disability policy.", "2026-10-13 10:20:00")
            ]),
            ("beta-conv-foster-03", family_id, "section-education", "Colorado CollegeInvest 529 State Tax Benefit & Matching", "Primary Member", 0, "2026-10-14 11:30:00", "2026-10-14 11:34:00", [
                ("user", "How does the Colorado CollegeInvest 529 plan work for Head of Household filers, and is there a state tax deduction?", "2026-10-14 11:30:00"),
                # Sources (checked 2026-10-29): Colorado deduction caps ($39,200 joint, $26,200 single for 2026,
                # limited to Colorado taxable income): https://www.collegeinvest.org/blog/understanding-the-colorado-529-tax-deduction/
                # Matching Grant ($500/yr, child 8 or younger): https://www.collegeinvest.org/?p=29
                ("model",
                    "### 🏔️ Colorado CollegeInvest 529 Tax Rules\n"
                    "\n"
                    "* **100% State Tax Deduction:** Colorado offers one of the nation's most generous 529 "
                    "incentives: contributions to any Colorado CollegeInvest plan are **deductible "
                    "dollar-for-dollar** against Colorado state taxable income, up to $39,200 per beneficiary for "
                    "joint filers ($26,200 single) in 2026, and never more than your Colorado taxable income that "
                    "year.\n"
                    "* **Head of Household Savings:** At Colorado's 4.4% flat income tax rate, contributing "
                    "$6,000/year to Noah's Direct Portfolio CollegeInvest account saves an immediate **$264/year** "
                    "in Colorado state income taxes.\n"
                    "* **Matching Grants:** Ask CollegeInvest about its *Matching Grant Program*, which has offered "
                    "matches of up to $500/year to eligible Colorado residents whose child is 8 or younger when they "
                    "apply; the number of awards and the application window change, so confirm current terms at "
                    "collegeinvest.org."
                    , "2026-10-14 11:34:00")
            ])
        ]
    }
    return all_conversations.get(family_id, [])


def seed_demo_advisor_conversations(db_path: Path, family_id: int = 0) -> None:
    """Seeds realistic, PII-free demo conversations and messages for the specified family into the target database."""
    if not family_id:
        return

    conversations = _get_demo_advisor_conversations(family_id)
    if not conversations:
        return

    with get_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS advisor_conversations (
                conversation_id TEXT PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
                page_section TEXT NOT NULL,
                title TEXT NOT NULL,
                created_by TEXT,
                is_pinned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS advisor_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES advisor_conversations(conversation_id) ON DELETE CASCADE,
                family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Cleanly purge existing conversations for this family to ensure idempotent seeding
        conn.execute("DELETE FROM advisor_messages WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM advisor_conversations WHERE family_id = ?", (family_id,))

        for cid, fam_id, sec, title, author, pinned, cr, up, msgs in conversations:
            conn.execute(
                "INSERT INTO advisor_conversations (conversation_id, family_id, page_section, title, created_by, "
                "is_pinned, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, fam_id, sec, title, author, pinned, cr, up)
            )
            for role, content, msg_time in msgs:
                conn.execute(
                    "INSERT INTO advisor_messages (conversation_id, family_id, role, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cid, fam_id, role, content, msg_time)
                )
        conn.commit()


def _load_fixture(filename: str) -> Any:
    """Loads a JSON fixture from data/fixtures/."""
    fixture_path = BASE_DIR / "data" / "fixtures" / filename
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_jones_family(db_path: Path, family_id: int, verbose: bool = True) -> None:
    """Populates the specified database with the complete Jones family dataset from JSON fixtures."""
    db_path, global_db = _prepare_seed_target(db_path, family_id)

    if verbose:
        print(f"[SEED] Populating The Jones Family into {db_path.name} (family_id={family_id})...")

    profile_data = _load_fixture("demo_jones_profile.json")
    accounts_data = _load_fixture("demo_jones_accounts.json")
    equity_data = _load_fixture("demo_jones_equity.json")
    transcripts_data = _load_fixture("demo_jones_transcripts.json")

    fam = profile_data["family"]
    hp = profile_data["household_profile"]

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # 1. Families Table
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET
                name = excluded.name,
                primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status,
                is_demo = excluded.is_demo,
                support_access_enabled = 1
        """, (
            family_id,
            fam["name"],
            str(fam["settings"].get("primary_state") or ""),
            str(fam["settings"].get("tax_filing_status") or "MFJ"),
            1 if fam["settings"].get("is_demo") is True else 0,
        ))

        # 2. Household Profile Table
        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state,
                filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending,
                annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age,
                inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate,
                assumptions_json = excluded.assumptions_json
        """, (
            family_id,
            hp["state"],
            hp["filing_status"],
            hp["annual_spending"],
            hp["annual_savings"],
            hp["retirement_age"],
            hp["inflation_rate"],
            hp["real_growth_rate"],
            json.dumps(hp["assumptions"])
        ))

        conn.commit()
    _clear_family_users(db_path, family_id)

    # 3. Add Parents & Children
    member_ids: Dict[str, int] = {}
    for m in profile_data["members"]:
        uid = security.add_family_member(
            db_path=db_path,
            family_id=family_id,
            name=m["name"],
            email=m["email"],
            birthdate=m["birthdate"],
            relationship=m["relationship"],
            role=m.get("role", "viewer")
        )
        member_ids[m["key"]] = uid

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # 4. Tuition Records (College, High School, Elementary)
        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        tuition_records = [
            (
                family_id,
                member_ids[t["member_key"]],
                t["school_year"],
                t["school_name"],
                t["tuition_amount"],
                t["is_projected"],
                t["notes"]
            )
            for t in profile_data["tuition"]
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, tuition_records)

        # 5. Compensation Records (5 Years History for Both Spouses)
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        comp_records = [
            (
                family_id,
                member_ids[c["member_key"]],
                c["tax_year"],
                c["employer_name"],
                c["base_salary"],
                c["bonus"],
                c["equity_spread"],
                c["notes"]
            )
            for c in profile_data["compensation"]
        ]
        conn.executemany("""
            INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, comp_records)

        # 6. Multi-Company Equity & NSO Grants
        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        company_ids: Dict[str, int] = {}
        for comp in equity_data["companies"]:
            cur = conn.execute("""
                INSERT INTO equity_companies (family_id, company_name, ticker_or_private, current_fmv, fmv_date)
                VALUES (?, ?, ?, ?, ?)
            """, (family_id, comp["company_name"], comp["ticker_or_private"], comp["current_fmv"], comp["fmv_date"]))
            company_ids[comp["key"]] = cur.lastrowid

        fmv_points = [
            (company_ids[pt["company_key"]], pt["valuation_date"], pt["share_price"], pt["is_projected"], pt["notes"])
            for pt in equity_data["fmv_history"]
        ]
        conn.executemany("""
            INSERT INTO fmv_history (company_id, valuation_date, share_price, is_projected, notes)
            VALUES (?, ?, ?, ?, ?)
        """, fmv_points)

        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))
        grants = [
            (
                company_ids[g["company_key"]],
                family_id,
                g["grant_label"],
                g["grant_type"],
                g["strike_price"],
                g["shares_granted"],
                g["shares_vested"],
                g["shares_unvested"],
                g["shares_exercised"],
                g["cost_basis"],
                json.dumps(g["vesting_schedule"]),
                g["grant_date"],
                g["fully_vested_date"]
            )
            for g in equity_data["grants"]
        ]
        conn.executemany("""
            INSERT INTO equity_grants (
                company_id, family_id, grant_label, grant_type, strike_price,
                shares_granted, shares_vested, shares_unvested, shares_exercised,
                cost_basis, vesting_schedule_json, grant_date, fully_vested_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, grants)

        # 7. Family Gifting Program
        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        rec_ids: Dict[str, int] = {}
        for rec in profile_data["gifting"]["recipients"]:
            cur = conn.execute("""
                INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (family_id, rec["recipient_group_name"], rec["member_count"], rec["relationship"], rec["notes"]))
            rec_ids[rec["key"]] = cur.lastrowid

        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        gift_records = [
            (family_id, rec_ids[g["recipient_key"]], g["year"], g["amount"], g["notes"])
            for g in profile_data["gifting"]["gifts"]
        ]
        conn.executemany("""
            INSERT INTO gifts (family_id, recipient_id, year, amount, notes)
            VALUES (?, ?, ?, ?, ?)
        """, gift_records)
        conn.commit()

    # 8. Seed Encrypted Store Documents
    # A. Tax Transcripts (IRS Wage & Income Transcripts for both parents)
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", transcripts_data, family_id=family_id)

    # B. Seed Monarch-Compatible Accounts & Balances (with spousal beneficiary assignments)
    normalize_and_save_accounts(
        db_path,
        accounts_data["accounts"],
        family_id=family_id,
        spouse_beneficiaries={"Sarah": member_ids["alex"], "Alex": member_ids["sarah"]},
    )

    # C. Seed Holdings Breakdown
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", accounts_data["holdings"], family_id=family_id)

    # C2. Seed Private Markets LP Commitment Book ($1.6M across Venture, PE, and Real Estate)
    security.db_save_encrypted(db_path, "lp_commitments", "holdings", [dict(d) for d in DEFAULT_DEMO_LP_COMMITMENTS], family_id=family_id)

    # C3. Seed Children 529 Education Reserves
    jones_edu = [
        {"user_id": member_ids.get("maya"), "name": "Maya Jones", "first_name": "Maya", "birthdate": "2006-04-12", "birth_year": 2006, "college_start": 2024, "current_529_balance": 68000.0, "accounts": [{"name": "ScholarShare 529 - Maya (College)", "balance": 68000.0}]},
        {"user_id": member_ids.get("ethan"), "name": "Ethan Jones", "first_name": "Ethan", "birthdate": "2010-06-20", "birth_year": 2010, "college_start": 2028, "current_529_balance": 145000.0, "accounts": [{"name": "ScholarShare 529 - Ethan (High School)", "balance": 145000.0}]},
        {"user_id": member_ids.get("chloe"), "name": "Chloe Jones", "first_name": "Chloe", "birthdate": "2017-02-14", "birth_year": 2017, "college_start": 2035, "current_529_balance": 125000.0, "accounts": [{"name": "ScholarShare 529 - Chloe (Grade School)", "balance": 125000.0}]},
    ]
    security.db_save_encrypted(db_path, "children_education_reserves", "education", jones_edu, family_id=family_id)

    # D. Seed Private School Tuition Payload for Education Tab
    if "private_school" in profile_data:
        security.db_save_encrypted(db_path, "private_school_tuition", "education", profile_data["private_school"], family_id=family_id)

    # E. Seed Philanthropy & DAF Ledger
    security.db_save_encrypted(db_path, "annual_donations", "philanthropy", profile_data["philanthropy"], family_id=family_id)

    # E2. Seed Tax Season Readiness Checklist Progress
    seed_family_tax_checklist_progress(db_path, family_id=family_id)

    # F. Seed Hierarchical Parent & Child Scenarios
    seed_family_scenarios(db_path, family_id, profile_data["scenarios"], active_scenario_id="scen_baseline", custom_events=profile_data.get("custom_events"))

    # G. Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=profile_data["historical_ribbon"],
        historical_cash_flows=profile_data["historical_cash_flows"],
    )

    # H. Seed Demo AI Advisor Conversations
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] The Jones Family successfully seeded into {db_path.name}!")
        print(f"  - Dr. Sarah Jones, MD (Admin) & Alex Jones (Admin)")
        print(f"  - 3 Students: Maya (College), Ethan (High School), Chloe (Grade School)")
        print(f"  - Companies: Nexus AI Inc. ($24 FMV, NSO grants) & CloudFlow Systems")
        print(f"  - Net Worth: ~$6.5M across Real Estate, Taxable Brokerage, 401k/403b, 529s")


def seed_miller_family(db_path: Path, family_id: int = 2, verbose: bool = True) -> None:
    """Seeds The Miller Family (FIRE Early Retired, WA State, $6.5M Liquid, Zero W-2)."""
    db_path, global_db = _prepare_seed_target(db_path, family_id)
    if verbose:
        print(f"[SEED] Populating The Miller Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # Persona: Early Retired FIRE ($6.6M Liquid, No WA Wage Tax, Zero W-2)
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, 'The Miller Family', ?, ?, 1, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status, is_demo = 1, support_access_enabled = 1
        """, (family_id, "WA", "MFJ"))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'WA', 'MFJ', 160000.0, 0.0, 49, 0.024, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "notes": "Fully early-retired FIRE (Robert retired in 2023 at 49, Karen at 47). Annual $80k Roth conversion ladder strategy.",
            # No salary to estimate from: ssa.gov-style benefits at full retirement age. Robert: ~26 covered years at
            # or above the wage base (~$3.8k/mo before rounding down); Karen: ~25 years averaging ~$120k (~$3.0k/mo).
            **_social_security_section(primary_monthly=3700.0, spouse_monthly=2800.0),
            "investment_policy": {
                "anchor_preset": "glidepath_60_40",
                "drift_tolerance": 0.05,
                "deviations_rationale": "Strict adherence to 60/40 age-based glidepath for sequence-of-returns defense during early FIRE decumulation. Zero private investments or illiquid alternative assets."
            },
            "estate_planning": {
                "apply_tcja_sunset": False,
                "charitable_pct": 0.05,
                "trust_preferences": ["slat", "ilit"],
                "verified_audit_ids": ["probate_acc_miller_re_01"]
            }
        })))

        conn.commit()
    _clear_family_users(db_path, family_id)

    robert_id = security.add_family_member(db_path, family_id, "Robert Miller", "robert.miller.demo@example.com", "1974-06-18", "primary", "admin")
    karen_id = security.add_family_member(db_path, family_id, "Karen Miller", "karen.miller.demo@example.com", "1976-10-04", "spouse", "admin")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        # Retired in 2023 - 0 W-2 salary since!
        comp_records = [
            (family_id, robert_id, 2022, "Cascadia Software Corporation", 255000.0, 45000.0, 60000.0, "Final career year prior to early retirement"),
            (family_id, robert_id, 2023, "Retired", 0.0, 0.0, 0.0, "Early retirement commenced"),
            (family_id, robert_id, 2024, "Retired", 0.0, 0.0, 0.0, "Zero W-2 income"),
            (family_id, robert_id, 2025, "Retired", 0.0, 0.0, 0.0, "Zero W-2 income"),
            (family_id, robert_id, 2026, "Retired", 0.0, 0.0, 0.0, "Projected zero earned income"),
        ]
        conn.executemany("INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", comp_records)

        # Family Gifting Program (Direct to Family Members)
        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        cur1 = conn.execute("INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes) VALUES (?, 'Liam & Sophie Vance (Nieces/Nephews)', 2, 'nieces/nephews', 'Annual educational support gifts')", (family_id,))
        niece_id = cur1.lastrowid
        cur2 = conn.execute("INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes) VALUES (?, 'Eleanor Miller (Mother)', 1, 'parent', 'Living allowance & healthcare')", (family_id,))
        mom_id = cur2.lastrowid

        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        conn.executemany("INSERT INTO gifts (family_id, recipient_id, year, amount, notes) VALUES (?, ?, ?, ?, ?)", [
            (family_id, niece_id, 2025, 20000.0, "Annual gift to nieces/nephews"),
            (family_id, niece_id, 2026, 20000.0, "Annual gift to nieces/nephews"),
            (family_id, mom_id, 2025, 19000.0, "Annual gift to mother"),
            (family_id, mom_id, 2026, 19000.0, "Annual gift to mother"),
        ])
        conn.commit()

    # Accounts: $6.5M Liquid Portfolio in Schwab / Fidelity + Paid off home
    miller_accounts = [
        {"id": "acc_miller_cash_01", "name": "Chase Premier Platinum Checking", "type": "depository", "subtype": "checking", "current_balance": 35000.0, "mask": "1190", "role": "cash_reserve"},
        {"id": "acc_miller_cash_02", "name": "Fidelity Government Money Market (SPAXX)", "type": "depository", "subtype": "savings", "current_balance": 145000.0, "mask": "7802", "role": "cash_reserve"},
        {"id": "acc_miller_inv_01", "name": "Schwab Joint Taxable Index Portfolio", "type": "investment", "subtype": "brokerage", "current_balance": 4150000.0, "mask": "4420", "role": "liquid_portfolio"},
        {"id": "acc_miller_ret_01", "name": "Robert Miller Traditional Rollover IRA", "type": "investment", "subtype": "ira", "current_balance": 1650000.0, "mask": "9021", "role": "retirement_tax_deferred"},
        {"id": "acc_miller_ret_02", "name": "Robert Miller Roth IRA", "type": "investment", "subtype": "roth", "current_balance": 320000.0, "mask": "3110", "role": "retirement_roth"},
        {"id": "acc_miller_ret_03", "name": "Karen Miller Roth IRA", "type": "investment", "subtype": "roth", "current_balance": 280000.0, "mask": "3115", "role": "retirement_roth"},
        {"id": "acc_miller_re_01", "name": "Seattle Queen Anne Residence (Paid Off)", "type": "real_estate", "subtype": "home", "current_balance": 1850000.0, "mask": "WA01", "role": "real_estate"}
    ]
    normalize_and_save_accounts(db_path, miller_accounts, family_id=family_id, spouse_beneficiaries={"Robert": karen_id, "Karen": robert_id})

    # Holdings matching 60/40 Glidepath IPS (60% Global Equities in Taxable/Roth, 40% Fixed Income shielded in Rollover IRA)
    miller_holdings = [
        {"account_id": "acc_miller_inv_01", "security_name": "Vanguard Total Stock Market ETF (VTI)", "ticker": "VTI", "quantity": 9200.0, "total_value": 2650000.0, "asset_class": "equity"},
        {"account_id": "acc_miller_inv_01", "security_name": "Vanguard Total International Stock ETF (VXUS)", "ticker": "VXUS", "quantity": 14000.0, "total_value": 900000.0, "asset_class": "international"},
        {"account_id": "acc_miller_inv_01", "security_name": "Vanguard Total Bond Market ETF (BND)", "ticker": "BND", "quantity": 8200.0, "total_value": 600000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_miller_ret_01", "security_name": "Vanguard Total Bond Market Index (VBTLX)", "ticker": "VBTLX", "quantity": 165000.0, "total_value": 1650000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_miller_ret_02", "security_name": "Vanguard Total Stock Market ETF (VTI)", "ticker": "VTI", "quantity": 1110.0, "total_value": 320000.0, "asset_class": "equity"},
        {"account_id": "acc_miller_ret_03", "security_name": "Vanguard Total Stock Market ETF (VTI)", "ticker": "VTI", "quantity": 970.0, "total_value": 280000.0, "asset_class": "equity"},
    ]
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", miller_holdings, family_id=family_id)
    security.db_save_encrypted(db_path, "lp_commitments", "holdings", [], family_id=family_id)

    # Tax Transcripts: 0 W-2, high qualified dividend cash flow
    miller_transcripts = {
        "adults": ["Combined Household", "Robert Miller", "Karen Miller"],
        "safe_harbor_2026_target": 5759.0,
        "historical_summary": {
            "2023": {"combined_w2_income": 0.0, "federal_tax_withheld": 3800.0, "safe_harbor_required": 4200.0, "qualified_dividends": 78000.0, "realized_capital_gains": 42000.0},
            "2024": {"combined_w2_income": 0.0, "federal_tax_withheld": 4900.0, "safe_harbor_required": 4180.0, "qualified_dividends": 84000.0, "realized_capital_gains": 48000.0},
            "2025": {"combined_w2_income": 0.0, "federal_tax_withheld": 5235.0, "safe_harbor_required": 5390.0, "qualified_dividends": 88000.0, "realized_capital_gains": 54000.0}
        }
    }
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", miller_transcripts, family_id=family_id)
    # Philanthropy Ledger (Separate from Family Gifting)
    miller_philanthropy = {
        "total_lifetime_charity": 70000.0,
        "lifetime_history": [
            {"year": 2025, "total": 35000.0, "budget": 35000.0},
            {"year": 2026, "total": 35000.0, "budget": 35000.0}
        ],
        "annual_budgets": {"2025": 35000.0, "2026": 35000.0},
        "donations_by_year": {
            "2025": {
                "total": 35000.0,
                "budget": 35000.0,
                "donations": [
                    {"organization": "Miller Pacific NW Conservation Fund (Seattle Foundation DAF)", "amount": 25000.0, "date": "2025-10-15", "description": "Annual DAF endowment contribution"},
                    {"organization": "Cascade Land Conservancy", "amount": 10000.0, "date": "2025-11-20", "description": "Pacific NW trail protection"}
                ]
            },
            "2026": {
                "total": 35000.0,
                "budget": 35000.0,
                "donations": [
                    {"organization": "Miller Pacific NW Conservation Fund (Seattle Foundation DAF)", "amount": 25000.0, "date": "2026-10-15", "description": "Annual DAF endowment contribution"},
                    {"organization": "Cascade Land Conservancy", "amount": 10000.0, "date": "2026-11-20", "description": "Pacific NW trail protection"}
                ]
            }
        }
    }
    security.db_save_encrypted(db_path, "annual_donations", "philanthropy", miller_philanthropy, family_id=family_id)

    # Seed Hierarchical Parent & Child Scenarios
    miller_custom_events = [
        {
            "id": "evt_k12_education",
            "name": "K-12 Education (Childless Household)",
            "category": "education",
            "event_type": "duration",
            "icon": "",
            "year": 2099,
            "end_year": 2099,
            "annual_amount": 0.0,
            "funding_source": "cash_flow",
            "description": "Childless household (zero K-12 private school tuition).",
        },
        {
            "id": "evt_college_undergrad",
            "name": "College Education (Childless Household)",
            "category": "college",
            "event_type": "duration",
            "icon": "",
            "year": 2099,
            "end_year": 2099,
            "annual_amount": 0.0,
            "funding_source": "cash_flow",
            "use_529_reserves": True,
            "description": "Childless household (zero college tuition).",
        },
        {
            "id": "evt_family_gifting",
            "name": "Annual Family Gifting ($39k/yr: Nieces + Mother)",
            "category": "gifting",
            "event_type": "duration",
            "icon": "",
            "year": 2026,
            "end_year": 2045,
            "annual_amount": 39000.0,
            "funding_source": "cash_flow",
            "description": "Annual educational support gifts to nieces Liam & Sophie ($20k) and living allowance to mother Eleanor ($19k).",
        },
        {
            "id": "evt_roth_ladder_miller",
            "name": "Roth Conversion Ladder ($80k/yr)",
            "category": "roth_conversion",
            "event_type": "duration",
            "icon": "evt-roth-ladder",
            "year": 2026,
            "end_year": 2036,
            "annual_conversion": 80000.0,
            "marginal_tax_rate": 0.251,
            "amount": 80000.0,
            "annual_amount": 80000.0,
            "is_outflow": True,
            "funding_source": "taxable_brokerage",
            "description": "Fixed $80k/yr Traditional-to-Roth conversion from 2026 through 2036, during the "
                "zero-W-2 FIRE years. The engine charges a flat 25.1% assumed rate on each conversion"
                " ($20,080 of federal tax a year), paid from the taxable account. A hand calculation "
                "on the 2025 pattern ($88k qualified dividends, $54k realized gains, about $24k "
                "ordinary interest on $600k of taxable BND at an assumed 4% yield) gives an "
                "incremental federal cost of about $20,120: $71,800 of taxable ordinary income in the"
                " 10% and 12% brackets, and about $114,900 of dividends and gains pushed from 0% to "
                "15%. The household's own MAGI is above 400% of the poverty line (about $84,600 for "
                "two) from its dividends alone, so the conversions do not cost an ACA credit.",
        },
        {
            "id": "evt_miller_islands_cabin",
            "name": "Purchase San Juan Islands Waterfront Cabin ($2.5M)",
            "category": "real_estate",
            "re_action": "buy_vacation",
            "event_type": "single_spike",
            "icon": "evt-vacation-home",
            "year": 2028,
            "end_year": 2028,
            "purchase_price": 2500000.0,
            "down_payment_pct": 0.4,
            "mortgage_term": "30_fixed",
            "interest_rate": 0.055,
            "funding_source": "taxable_brokerage",
            "annual_ongoing_carrying_cost": 30000.0,
            "description": "Purchase a $2.5M San Juan Islands waterfront cabin in 2028 with a $1M (40%) down payment from the taxable brokerage and a $1.5M 30-year fixed mortgage at 5.5%, plus $30k/yr of carrying costs.",
        },
        {
            "id": "evt_aca_bridge_miller",
            "name": "Pre-65 ACA Healthcare Bridge",
            "category": "pre65_healthcare",
            "event_type": "duration",
            "icon": "evt-ltc-shield",
            "year": 2026,
            "end_year": 2039,
            "annual_premium": 24000.0,
            "annual_amount": 24000.0,
            "amount": 24000.0,
            "aca_subsidy_mode": "aca_magi",
            "is_outflow": True,
            "funding_source": "taxable_brokerage",
            "description": "Pre-Medicare ACA Silver plan bridge: $24k a year for the two of them, shrinking pro rata "
                "as each adult turns 65 (Robert in June 2039, Karen in October 2041). The event ends in 2039, so "
                "the engine charges half the premium in 2039 and nothing for Karen's 2040 and 2041. The engine "
                "estimates MAGI as earned income plus Roth conversions plus a 2% yield on liquid assets, about "
                    "$168k to $174k while the $80k conversions run (through 2036), which is above 400% of"
                    " the poverty line for "
                "two ($84,600 today, indexed), so premiums are charged in full. Once the conversions end, its MAGI "
                "estimate falls to about $90k to $92k and it applies a premium credit in 2037 to 2039 (net premium "
                "about $9k a year). It does not count the household's roughly $88k of dividends, so those years "
                "understate the premium a real household at that income would pay.",
        },
    ]
    miller_scenarios = [
        {
            "id": "scen_baseline",
            "name": "FIRE Lifestyle Baseline",
            "description":
                "Current early-retired trajectory with $160k/yr living spend funded entirely from the "
                "$6.58M liquid portfolio and annual Roth conversion ladder; first-year outflows are "
                "about $283k (4.3% of the portfolio) once retirement travel, the ACA bridge, family "
                "gifts and conversion tax are added. Social Security is entered in Settings: $3,700 a "
                "month for Robert and $2,800 a month for Karen at full retirement age, claimed at 67 "
                "($44k a year from 2041, $78k from 2043). Monte Carlo success is about 94.4%, and all "
                "98 historical start-year cohorts survive.",
            "color": PLAN_COLORS["slate"],
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 49,
            "spouse_retirement_age": 47,
            "annual_living_spend": 160000.0,
            "annual_savings": 0.0,
            "equity_growth_preset": "moderate",
            "spending_guardrail_mode": "moderate",
            "event_ids": ["evt_family_gifting", "evt_roth_ladder_miller", "evt_aca_bridge_miller"],
        },
        {
            "id": "scen_miller_global_travel",
            "name": "Global Travel & Sabbatical Years",
            "description":
                "Raises annual living spend from $160k to $200k for the whole projection; the engine "
                "does not limit it to a decade. Retirement travel is added on top: up to 25% of spend "
                "(capped at $60k) until Robert is 66, 12.5% (capped at $30k) from 66 to 75, and none "
                "after 75. The taxable account is used up around 2058 (age 84) while the retirement "
                "accounts last past age 100. Monte Carlo success is about 79.5%.",
            "color": PLAN_COLORS["sapphire"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_living_spend": 200000.0,
        },
        {
            "id": "scen_miller_islands_cabin",
            "name": "San Juan Islands Cabin & Travel",
            "description":
                "Branches from Global Travel to buy a $2.5M San Juan Islands waterfront cabin in "
                "2028: $1M (40%) down from the taxable brokerage, a $1.5M 30-year mortgage at 5.5%, "
                "and $30k/yr of carrying costs. About $1.10M of cash leaves in 2028; the taxable "
                "account is used up around 2037 (age 63) and the retirement accounts around 2045 (age "
                "71), after which the plan has unfunded spending beyond Social Security. This is the "
                "household's stretch plan: Monte Carlo success is about 25.8%.",
            "color": PLAN_COLORS["cerulean"],
            "is_baseline": False,
            "parent_id": "scen_miller_global_travel",
            "added_event_ids": ["evt_miller_islands_cabin"],
        },
        {
            "id": "scen_miller_conservative_guardrail",
            "name": "Bear Market Spending Guardrail",
            "description":
                "Defensive FIRE guardrail: cuts annual living spend to $125k/yr, uses the aggressive "
                "spending guardrail (withdrawals cut 25% when the portfolio is more than 15% below "
                "its peak, 15% when more than 10% below), and draws from pre-tax accounts first. "
                "Market return assumptions are unchanged. Monte Carlo success is about 99.7%.",
            "color": PLAN_COLORS["emerald"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_living_spend": 125000.0,
            "spending_guardrail_mode": "aggressive",
            "drawdown_order": "pretax_first",
        },
    ]
    seed_family_scenarios(
        db_path, family_id, miller_scenarios, active_scenario_id="scen_baseline", custom_events=miller_custom_events,
        # Robert (born 1974) and Karen (born 1976) have an RMD age of 75, not 73.
        description_replacements={"evt_roth_conversion_ladder": {"age-73/75 RMDs": "age-75 RMDs"}},
    )
    seed_family_tax_checklist_progress(db_path, family_id=family_id)

    # Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=[
            {"year": 2018, "true_net_worth": 4300000.0, "is_historical": True},
            {"year": 2019, "true_net_worth": 5050000.0, "is_historical": True},
            {"year": 2020, "true_net_worth": 5850000.0, "is_historical": True},
            {"year": 2021, "true_net_worth": 6900000.0, "is_historical": True},
            {"year": 2022, "true_net_worth": 6650000.0, "is_historical": True},
            {"year": 2023, "true_net_worth": 7400000.0, "is_historical": True},
            {"year": 2024, "true_net_worth": 7950000.0, "is_historical": True},
            {"year": 2025, "true_net_worth": 8200000.0, "is_historical": True},
        ],
        historical_cash_flows=[
            {"year": 2018, "is_historical": True, "age_primary": 44, "age_spouse": 42, "household_salary": 290000.0, "salary_savings": 145000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 290000.0, "living_core": 110000.0, "travel_gogo": 30000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 150000.0, "net_cash_flow": 140000.0},
            {"year": 2019, "is_historical": True, "age_primary": 45, "age_spouse": 43, "household_salary": 305000.0, "salary_savings": 150000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 305000.0, "living_core": 115000.0, "travel_gogo": 35000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 160000.0, "net_cash_flow": 145000.0},
            {"year": 2020, "is_historical": True, "age_primary": 46, "age_spouse": 44, "household_salary": 320000.0, "salary_savings": 160000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 320000.0, "living_core": 100000.0, "travel_gogo": 15000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 125000.0, "net_cash_flow": 195000.0},
            {"year": 2021, "is_historical": True, "age_primary": 47, "age_spouse": 45, "household_salary": 340000.0, "salary_savings": 170000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 340000.0, "living_core": 120000.0, "travel_gogo": 25000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 155000.0, "net_cash_flow": 185000.0},
            {"year": 2022, "is_historical": True, "age_primary": 48, "age_spouse": 46, "household_salary": 360000.0, "salary_savings": 180000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 360000.0, "living_core": 125000.0, "travel_gogo": 30000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 165000.0, "net_cash_flow": 195000.0},
            {"year": 2023, "is_historical": True, "age_primary": 49, "age_spouse": 47, "household_salary": 0.0, "salary_savings": 0.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 0.0, "living_core": 130000.0, "travel_gogo": 40000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 180000.0, "net_cash_flow": -180000.0},
            {"year": 2024, "is_historical": True, "age_primary": 50, "age_spouse": 48, "household_salary": 0.0, "salary_savings": 0.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 0.0, "living_core": 140000.0, "travel_gogo": 50000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 200000.0, "net_cash_flow": -200000.0},
            {"year": 2025, "is_historical": True, "age_primary": 51, "age_spouse": 49, "household_salary": 0.0, "salary_savings": 0.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 0.0, "living_core": 145000.0, "travel_gogo": 55000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 210000.0, "net_cash_flow": -210000.0},
        ],
    )

    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] The Miller Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_chen_family(db_path: Path, family_id: int = 3, verbose: bool = True) -> None:
    """Seeds The Chen Family (Series A Founder, NYC, ISO / AMT, Toddler 529 Superfunding)."""
    db_path, global_db = _prepare_seed_target(db_path, family_id)
    if verbose:
        print(f"[SEED] Populating The Chen Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # Persona: Startup Founder, ISO Planning, Tribeca Condo, Toddler 529
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, 'The Chen Family', ?, ?, 1, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status, is_demo = 1, support_access_enabled = 1
        """, (family_id, "NY", "MFJ"))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'NY', 'MFJ', 150000.0, 85000.0, 55, 0.026, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "mortgage": {"remaining_term_years": 25, "annual_rate": 0.03125},
            "notes": "NYC resident (high local tax). Series A Founder with large unexercised ISO block.",
            "investment_policy": {
                "anchor_preset": "all_equity_90_10",
                "drift_tolerance": 0.07,
                "deviations_rationale": "Overweight concentrated company equity (ISO/NSO) and venture holdings from previous founding journey; minimal bond allocation (<5%) due to long time horizon and high risk appetite."
            },
            "estate_planning": {
                "apply_tcja_sunset": False,
                "charitable_pct": 0.10,
                "trust_preferences": ["idgt", "grat"],
                "verified_audit_ids": ["equity_concentration_crit", "rsu_withholding_gap"]
            }
        })))

        conn.commit()
    _clear_family_users(db_path, family_id)

    david_id = security.add_family_member(db_path, family_id, "David Chen", "david.chen.demo@example.com", "1992-03-15", "primary", "admin")
    emily_id = security.add_family_member(db_path, family_id, "Emily Chen", "emily.chen.demo@example.com", "1994-08-22", "spouse", "admin")
    leo_id = security.add_family_member(db_path, family_id, "Leo Chen", "leo.chen.demo@example.com", "2024-05-10", "child", "viewer")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # Compensation
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        comp_records = [
            (family_id, david_id, 2024, "Aether Robotics Inc.", 225000.0, 25000.0, 0.0, "Founder & CEO salary post-Series A"),
            (family_id, david_id, 2025, "Aether Robotics Inc.", 250000.0, 30000.0, 0.0, "W-2 reported $280k"),
            (family_id, david_id, 2026, "Aether Robotics Inc.", 275000.0, 35000.0, 0.0, "Current year salary"),
            (family_id, emily_id, 2024, "Lakeshore Architects Group", 145000.0, 15000.0, 0.0, "Senior Architect"),
            (family_id, emily_id, 2025, "Lakeshore Architects Group", 155000.0, 20000.0, 0.0, "Associate Director"),
            (family_id, emily_id, 2026, "Lakeshore Architects Group", 165000.0, 20000.0, 0.0, "Current year salary"),
        ]
        conn.executemany("INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", comp_records)

        # Equity: Multi-Company (Aether Robotics Inc. Series A + Veritas AI RSUs)
        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        cur = conn.execute("INSERT INTO equity_companies (family_id, company_name, ticker_or_private, current_fmv, "
            "fmv_date) VALUES (?, 'Aether Robotics Inc.', 'private', 2.80, '2025-10-01')", (family_id,))
        aether_id = cur.lastrowid

        cur2 = conn.execute("INSERT INTO equity_companies (family_id, company_name, ticker_or_private, current_fmv, fmv_date) VALUES (?, 'Veritas AI', 'private', 12.00, '2025-10-01')", (family_id,))
        veritas_id = cur2.lastrowid

        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))
        grants = [
            (aether_id, family_id, "Founder Common Stock (83b Filed)", "common", 0.001,
             1500000.0, 1406250.0, 93750.0, 1500000.0, 0.001,
             json.dumps({"schedule": "4-year monthly, 1-year cliff", "cliff_months": 12}), "2023-01-01", "2027-01-01"),
            (aether_id, family_id, "Series Seed Incentive Stock Option (ISO)", "iso", 0.50,
             150000.0, 115625.0, 34375.0, 0.0, 0.50,
             json.dumps({"schedule": "4-year monthly", "cliff_months": 0}), "2023-09-01", "2027-09-01"),
            (veritas_id, family_id, "Veritas Technical Advisory RSUs (VAI-RSU)", "rsu", 0.0, 10000.0, 10000.0, 0.0, 0.0, 0.0,
             json.dumps({"schedule": "Fully vested advisor RSUs", "cliff_months": 0}), "2023-06-01", "2025-06-01"),
        ]
        conn.executemany("""
            INSERT INTO equity_grants (
                company_id, family_id, grant_label, grant_type, strike_price,
                shares_granted, shares_vested, shares_unvested, shares_exercised,
                cost_basis, vesting_schedule_json, grant_date, fully_vested_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, grants)

        # FMV points
        fmv_points = [
            (aether_id, "2023-01-01", 0.001, 0, "Incorporation"),
            (aether_id, "2023-09-01", 0.50, 0, "Seed Round"),
            (aether_id, "2025-10-01", 2.80, 0, "409A common FMV after the Series A (preferred price $8.50)"),
            (veritas_id, "2023-06-01", 4.00, 0, "Advisory Grant Date"),
            (veritas_id, "2025-10-01", 12.00, 0, "Series B Round ($12.00)"),
        ]
        conn.executemany("INSERT INTO fmv_history (company_id, valuation_date, share_price, is_projected, notes) VALUES (?, ?, ?, ?, ?)", fmv_points)
        # Family Gifting Program (Direct to Family Members)
        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        cur1 = conn.execute("INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes) VALUES (?, 'Michael & Mei Chen (Parents in Queens)', 2, 'parents', 'Annual family gift & parents support')", (family_id,))
        chen_parents_id = cur1.lastrowid

        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        conn.executemany("INSERT INTO gifts (family_id, recipient_id, year, amount, notes) VALUES (?, ?, ?, ?, ?)", [
            (family_id, chen_parents_id, 2025, 38000.0, "Annual exclusion gifts ($19k x 2)"),
            (family_id, chen_parents_id, 2026, 38000.0, "Current year budgeted gifts ($19k x 2)"),
        ])

        # Tuition & Education Expenses
        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        hh_key = _household_key(db_path, family_id)
        chen_tuition = [
            (
                family_id, leo_id, "2026-2027", "Tribeca Early Childhood (Nursery)",
                security.encrypt_field(28000.0, key=hh_key), 1, "Tribeca toddler program (2s)",
            ),
            (
                family_id, leo_id, "2027-2028", "Tribeca Montessori (Pre-K 3)",
                security.encrypt_field(32000.0, key=hh_key), 1, "Pre-K 3 nursery school",
            ),
            (
                family_id, leo_id, "2028-2029", "Tribeca Montessori (Pre-K 4)",
                security.encrypt_field(35000.0, key=hh_key), 1, "Pre-K 4 program",
            ),
            (
                family_id, leo_id, "2029-2030", "NYC Independent School (Kindergarten)",
                security.encrypt_field(54000.0, key=hh_key), 1, "Kindergarten tuition",
            ),
            (
                family_id, leo_id, "2030-2031", "NYC Independent School (1st Grade)",
                security.encrypt_field(56500.0, key=hh_key), 1, "1st Grade elementary",
            ),
            (
                family_id, leo_id, "2031-2032", "NYC Independent School (2nd Grade)",
                security.encrypt_field(59000.0, key=hh_key), 1, "2nd Grade elementary",
            ),
            (
                family_id, leo_id, "2042-2043", "Elite Private University (College Freshman)",
                security.encrypt_field(85000.0, key=hh_key), 1, "Projected college freshman year",
            ),
            (
                family_id, leo_id, "2043-2044", "Elite Private University (College Sophomore)",
                security.encrypt_field(88000.0, key=hh_key), 1, "Projected college sophomore year",
            ),
            (
                family_id, leo_id, "2044-2045", "Elite Private University (College Junior)",
                security.encrypt_field(92000.0, key=hh_key), 1, "Projected college junior year",
            ),
            (
                family_id, leo_id, "2045-2046", "Elite Private University (College Senior)",
                security.encrypt_field(96000.0, key=hh_key), 1, "Projected college senior year",
            ),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, chen_tuition)
        conn.commit()

    # Accounts
    chen_accounts = [
        {"id": "acc_chen_cash_01", "name": "SVB / First Citizens Checking", "type": "depository", "subtype": "checking", "current_balance": 95000.0, "mask": "5109", "role": "cash_reserve"},
        {"id": "acc_chen_cash_02", "name": "Ally High Yield Savings", "type": "depository", "subtype": "savings", "current_balance": 115000.0, "mask": "2280", "role": "cash_reserve"},
        {"id": "acc_chen_inv_01", "name": "Morgan Stanley Joint Brokerage", "type": "investment", "subtype": "brokerage", "current_balance": 940000.0, "mask": "8812", "role": "liquid_portfolio"},
        {"id": "acc_chen_ret_01", "name": "David Aether Robotics 401(k)", "type": "investment", "subtype": "401k", "current_balance": 210000.0, "mask": "7710", "role": "retirement_tax_deferred"},
        {"id": "acc_chen_ret_02", "name": "Emily Studio 401(k)", "type": "investment", "subtype": "401k", "current_balance": 185000.0, "mask": "6620", "role": "retirement_tax_deferred"},
        {"id": "acc_chen_529_leo", "name": "NY 529 Direct Plan - Leo", "type": "investment", "subtype": "529", "current_balance": 20000.0, "mask": "9901", "role": "education_529"},
        {"id": "acc_chen_re_01", "name": "Tribeca NYC Condo Loft", "type": "real_estate", "subtype": "home", "current_balance": 2150000.0, "mask": "NY01", "role": "real_estate"},
        {"id": "acc_chen_mort_01", "name": "Chase Jumbo Fixed Mortgage (3.125%)", "type": "loan", "subtype": "mortgage", "current_balance": -1250000.0, "mask": "4401", "role": "mortgage_liability"}
    ]
    normalize_and_save_accounts(db_path, chen_accounts, family_id=family_id, spouse_beneficiaries={"David": emily_id, "Emily": david_id})

    chen_edu = [
        {"user_id": leo_id, "name": "Leo Chen", "first_name": "Leo", "birthdate": "2024-05-10", "birth_year": 2024, "college_start": 2042, "current_529_balance": 20000.0, "accounts": [{"name": "NY 529 Direct Plan - Leo", "balance": 20000.0}]},
    ]
    security.db_save_encrypted(db_path, "children_education_reserves", "education", chen_edu, family_id=family_id)

    chen_holdings = [
        {"account_id": "acc_chen_inv_01", "ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "quantity": 2500.0, "totalValue": 640000.0, "asset_class": "us_equity"},
        {"account_id": "acc_chen_inv_01", "ticker": "VXUS", "name": "Vanguard Total International Stock ETF", "quantity": 3600.0, "totalValue": 215000.0, "asset_class": "intl_equity"},
        {"account_id": "acc_chen_inv_01", "ticker": "BND", "name": "Vanguard Total Bond Market ETF", "quantity": 1150.0, "totalValue": 85000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_chen_ret_01", "ticker": "VIIIX", "name": "Vanguard Institutional Index Fund", "quantity": 450.0, "totalValue": 210000.0, "asset_class": "us_equity"},
        {"account_id": "acc_chen_ret_02", "ticker": "FXAIX", "name": "Fidelity 500 Index Fund", "quantity": 950.0, "totalValue": 185000.0, "asset_class": "us_equity"},
    ]
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", chen_holdings, family_id=family_id)

    chen_lp_commitments = [
        {
            "id": "lp_chen_angel_synd_ii",
            "fund_name": "Founders Co-Invest Angel Syndicate II, LP",
            "fund_type": "Direct / Angel",
            "vintage_year": 2024,
            "total_commitment": 150000.0,
            "capital_called": 60000.0,
            "unfunded_commitment": 90000.0,
            "distributions_received": 0.0,
            "current_nav": 74000.0,
            "last_mark_date": "2026-09-30",
            "expected_call_horizon_years": 4,
            "k1_status": "Expected",
            "notes": "Operator angel syndicate investing in seed-stage AI & robotics startups.",
        },
        {
            "id": "lp_chen_deeptech_seed_iv",
            "fund_name": "DeepTech Seed Fund IV, LP",
            "fund_type": "Venture",
            "vintage_year": 2025,
            "total_commitment": 100000.0,
            "capital_called": 25000.0,
            "unfunded_commitment": 75000.0,
            "distributions_received": 0.0,
            "current_nav": 26500.0,
            "last_mark_date": "2026-09-30",
            "expected_call_horizon_years": 4,
            "k1_status": "Expected",
            "notes": "LP allocation granted as a portfolio founder scout.",
        },
    ]
    security.db_save_encrypted(db_path, "lp_commitments", "private_markets", chen_lp_commitments, family_id=family_id)

    chen_transcripts = {
        "adults": ["Combined Household", "David Chen", "Emily Chen"],
        "safe_harbor_2026_target": 126500.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 410000.0, "federal_tax_withheld": 88000.0, "safe_harbor_required": 85000.0},
            "2025": {"combined_w2_income": 455000.0, "federal_tax_withheld": 115000.0, "safe_harbor_required": 126500.0}
        }
    }
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", chen_transcripts, family_id=family_id)

    # Philanthropy Ledger (Separate from Family Gifting)
    chen_philanthropy = {
        "total_lifetime_charity": 90000.0,
        "lifetime_history": [
            {"year": 2025, "total": 45000.0, "budget": 45000.0},
            {"year": 2026, "total": 45000.0, "budget": 45000.0}
        ],
        "annual_budgets": {"2025": 45000.0, "2026": 45000.0},
        "donations_by_year": {
            "2025": {
                "total": 45000.0,
                "budget": 45000.0,
                "donations": [
                    {"organization": "Chen Family Innovation & Education Fund (Vanguard Charitable DAF)", "amount": 30000.0, "date": "2025-11-10", "description": "Appreciated startup shares gifted to DAF"},
                    {"organization": "Robin Hood Foundation NYC", "amount": 15000.0, "date": "2025-12-12", "description": "NYC poverty fighting grant"}
                ]
            },
            "2026": {
                "total": 45000.0,
                "budget": 45000.0,
                "donations": [
                    {"organization": "Chen Family Innovation & Education Fund (Vanguard Charitable DAF)", "amount": 30000.0, "date": "2026-11-10", "description": "Annual DAF contribution"},
                    {"organization": "Robin Hood Foundation NYC", "amount": 15000.0, "date": "2026-12-12", "description": "NYC community relief grant"}
                ]
            }
        }
    }
    security.db_save_encrypted(db_path, "annual_donations", "philanthropy", chen_philanthropy, family_id=family_id)

    # Seed Hierarchical Parent & Child Scenarios
    chen_custom_events = [
        {
            "id": "evt_chen_westchester_home",
            "name": "Purchase Westchester Estate ($2.5M)",
            "category": "real_estate",
            "re_action": "buy_vacation",
            "event_type": "single_spike",
            "icon": "evt-real-estate",
            "year": 2028,
            "end_year": 2028,
            "purchase_price": 2500000.0,
            "down_payment_pct": 0.25,
            "mortgage_term": "30_fixed",
            "interest_rate": 0.055,
            "funding_source": "taxable_brokerage",
            "annual_ongoing_carrying_cost": 35000.0,
            "description": "Purchase a $2.5M Westchester estate in 2028 with a 25% ($625k) down payment from the taxable brokerage and a $1.875M 30-year fixed mortgage at 5.5%, plus $35k/yr of carrying costs. The Tribeca condo is kept; this event does not sell it.",
        },
    ]
    chen_scenarios = [
        {
            "id": "scen_baseline",
            "name": "Founder Baseline (Pre-IPO)",
            "description":
                "Current baseline with Series A CEO salary ($275k), Tribeca living expenses "
                "($150k/yr), and unexercised stock options valued at the $2.80 409A common price (the "
                "Series A preferred price is $8.50). Take-home pay of about $308k covers living costs "
                "and the $72k mortgage (3.125%, 25 years left, entered in Settings) with about $85k a "
                "year left, which the plan saves; tuition, the $38k of yearly gifts to the parents "
                "and LP capital calls ($107k in 2026) come out of the liquid pool. Both spouses "
                "retire at 55 and withdrawals begin in 2047; on the fixed return path the taxable and "
                "retirement accounts last past age 100. Monte Carlo success (liquid assets only) is "
                "about 65.9%.",
            "color": PLAN_COLORS["slate"],
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 55,
            "spouse_retirement_age": 55,
            "annual_living_spend": 150000.0,
            "annual_savings": 85000.0,
            "equity_growth_preset": "moderate",
        },
        {
            "id": "scen_chen_secondary_tender",
            "name": "Series B Secondary Tender Offer ($500k)",
            "description":
                "Founder de-risks by selling $500k of common shares in an upcoming institutional "
                "secondary round in 2029 (about $540k after inflation), reallocating into taxable "
                "index funds. Monte Carlo success rises from about 65.9% to about 75.8%.",
            "color": PLAN_COLORS["sapphire"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "added_event_ids": ["evt_capital_windfall"],
        },
        {
            "id": "scen_chen_suburban_home",
            "name": "Westchester Estate & Early Advisory (Age 48)",
            "description":
                "Branches from the secondary tender: buys a $2.5M Westchester estate in 2028 (25% "
                "down, 30-year mortgage at 5.5%, $35k/yr carrying costs) while keeping the Tribeca "
                "condo (modeled as a second-property purchase: a primary-home purchase would sell the "
                "condo and pay off its mortgage), and both spouses step back to angel investing and "
                "advising at 48 on $170k/yr of living spend. About $0.71M of cash leaves in 2028; the "
                "taxable account is used up around 2036 (age 44) and the retirement accounts around "
                "2041 (age 49), after which the plan relies on selling Aether stock. This is the "
                "household's stretch plan: Monte Carlo success is about 43.0%.",
            "color": PLAN_COLORS["cerulean"],
            "is_baseline": False,
            "parent_id": "scen_chen_secondary_tender",
            "primary_retirement_age": 48,
            "spouse_retirement_age": 48,
            "annual_living_spend": 170000.0,
            "annual_savings": 65000.0,
            "added_event_ids": ["evt_chen_westchester_home"],
        },
        {
            "id": "scen_chen_delay_exit",
            "name": "Scale to Series C / Delayed Exit (Age 55)",
            "description":
                "David and Emily keep working to age 60 instead of 55, which adds five more years of "
                "salary and delays withdrawals from 2047 to 2052. The $85k/yr savings target is "
                "unchanged. Monte Carlo success is about 90.2%, against about 65.9% for the baseline.",
            "color": PLAN_COLORS["emerald"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 60,
            "spouse_retirement_age": 60,
                    },
    ]
    seed_family_scenarios(db_path, family_id, chen_scenarios, active_scenario_id="scen_baseline", custom_events=chen_custom_events)

    # Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=[
            {"year": 2018, "true_net_worth": 1150000.0, "is_historical": True},
            {"year": 2019, "true_net_worth": 1450000.0, "is_historical": True},
            {"year": 2020, "true_net_worth": 1850000.0, "is_historical": True},
            {"year": 2021, "true_net_worth": 2350000.0, "is_historical": True},
            {"year": 2022, "true_net_worth": 2600000.0, "is_historical": True},
            {"year": 2023, "true_net_worth": 3150000.0, "is_historical": True},
            {"year": 2024, "true_net_worth": 3700000.0, "is_historical": True},
            {"year": 2025, "true_net_worth": 4200000.0, "is_historical": True},
        ],
        historical_cash_flows=[
            {
                "year": 2018, "is_historical": True, "age_primary": 26, "age_spouse": 24, "household_salary": 340000.0,
                "salary_savings": 131000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 340000.0,
                "living_core": 94000.0, "travel_gogo": 25000.0, "gifting": 10000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 201000.0, "net_cash_flow": 139000.0,
            },
            {
                "year": 2019, "is_historical": True, "age_primary": 27, "age_spouse": 25, "household_salary": 380000.0,
                "salary_savings": 157000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 380000.0,
                "living_core": 103000.0, "travel_gogo": 30000.0, "gifting": 10000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 215000.0, "net_cash_flow": 165000.0,
            },
            {
                "year": 2020, "is_historical": True, "age_primary": 28, "age_spouse": 26, "household_salary": 410000.0,
                "salary_savings": 183000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 410000.0,
                "living_core": 97000.0, "travel_gogo": 15000.0, "gifting": 10000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 194000.0, "net_cash_flow": 216000.0,
            },
            {
                "year": 2021, "is_historical": True, "age_primary": 29, "age_spouse": 27, "household_salary": 460000.0,
                "salary_savings": 209000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 460000.0,
                "living_core": 112000.0, "travel_gogo": 25000.0, "gifting": 15000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 224000.0, "net_cash_flow": 236000.0,
            },
            {
                "year": 2022, "is_historical": True, "age_primary": 30, "age_spouse": 28, "household_salary": 510000.0,
                "salary_savings": 235500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 510000.0,
                "living_core": 123500.0, "travel_gogo": 30000.0, "gifting": 15000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 240500.0, "net_cash_flow": 269500.0,
            },
            {
                "year": 2023, "is_historical": True, "age_primary": 31, "age_spouse": 29, "household_salary": 570000.0,
                "salary_savings": 261500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 570000.0,
                "living_core": 132500.0, "travel_gogo": 35000.0, "gifting": 15000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 254500.0, "net_cash_flow": 315500.0,
            },
            {
                "year": 2024, "is_historical": True, "age_primary": 32, "age_spouse": 30, "household_salary": 370000.0,
                "salary_savings": 26000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 370000.0,
                "living_core": 141000.0, "travel_gogo": 40000.0, "gifting": 15000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 268000.0, "net_cash_flow": 102000.0,
            },
            {
                "year": 2025, "is_historical": True, "age_primary": 33, "age_spouse": 31, "household_salary": 435000.0,
                "salary_savings": 85000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 435000.0,
                "living_core": 150000.0, "travel_gogo": 45000.0, "gifting": 15000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 72000.0, "total_outflow": 282000.0, "net_cash_flow": 153000.0,
            },
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] The Chen Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_ramirez_family(db_path: Path, family_id: int = 4, verbose: bool = True) -> None:
    """
    Populates 'The Ramirez Family' (Austin, TX):
    - Middle-Class Working Household: Carlos Ramirez (Master Electrician) & Sofia Ramirez (High School Teacher)
    - 2 Children in Public School: Mateo (13, 8th grade) & Camila (9, 4th grade)
    - Combined W-2 income: ~$156k. Modest home ($395k) with 3.375% mortgage.
    - Sofia's 403(b) alongside her TRS pension, Traditional and Roth IRAs, Ally Emergency Fund ($24k).
    - Texas 529 College Savings for in-state public universities (UT Austin / Texas A&M).
    - No tech stock options.
    """
    db_path, global_db = _prepare_seed_target(db_path, family_id)
    if verbose:
        print(f"[SEED] Populating The Ramirez Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # Persona: High school teacher (TRS pension) + master electrician, $156k HHI, home & auto loan, Texas 529s
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, 'The Ramirez Family', ?, ?, 1, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status, is_demo = 1, support_access_enabled = 1
        """, (family_id, "TX", "MFJ"))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'TX', 'MFJ', 94000.0, 14000.0, 65, 0.028, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            # Sofia's teaching service is not Social Security covered, so a salary-based estimate would be far too high:
            # only her earlier private-sector years count (Carlos is estimated from his salary).
            **_social_security_section(spouse_monthly=600.0),
            "pension": {"spouse": {"annual_amount": 48000.0, "start_age": 62, "cola": 0.01, "survivor_pct": 0.5}},
            "mortgage": {"remaining_term_years": 24, "annual_rate": 0.03375},
            "notes":
                "Austin single-family home, Texas 0% state tax, Texas TRS pension (Sofia, entered in "
                "Settings) + 403(b), Roth IRAs",
            "investment_policy": {
                "anchor_preset": "boglehead_80_20",
                "drift_tolerance": 0.05,
                "deviations_rationale": "100% passive index adherence across the 403(b), Traditional IRA, and Roth IRAs with total stock and total bond market funds. Zero speculative or private investments."
            },
            "estate_planning": {
                "apply_tcja_sunset": False,
                "charitable_pct": 0.02,
                "trust_preferences": ["will_trust"],
                "verified_audit_ids": ["probate_acc_ramirez_home"]
            }
        })))

        conn.commit()
    _clear_family_users(db_path, family_id)

    carlos_id = security.add_family_member(db_path, family_id, "Carlos Ramirez", "carlos.ramirez.demo@example.com", "1985-04-12", "primary", "admin")
    sofia_id = security.add_family_member(db_path, family_id, "Sofia Ramirez", "sofia.ramirez.demo@example.com", "1987-09-22", "spouse", "admin")
    mateo_id = security.add_family_member(db_path, family_id, "Mateo Ramirez", "mateo.ramirez.demo@example.com", "2013-08-15", "child", "viewer")
    camila_id = security.add_family_member(db_path, family_id, "Camila Ramirez", "camila.ramirez.demo@example.com", "2016-11-04", "child", "viewer")

    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        comp_records = [
            (family_id, carlos_id, 2022, "Ramirez Electric LLC", 72000.0, 4000.0, 0.0, "Master Electrician"),
            (family_id, carlos_id, 2023, "Ramirez Electric LLC", 78000.0, 5000.0, 0.0, "Master Electrician"),
            (family_id, carlos_id, 2024, "Ramirez Electric LLC", 82000.0, 5000.0, 0.0, "Master Electrician"),
            (family_id, carlos_id, 2025, "Ramirez Electric LLC", 85000.0, 6000.0, 0.0, "Master Electrician"),
            (family_id, carlos_id, 2026, "Ramirez Electric LLC", 88000.0, 6000.0, 0.0, "Current W-2 salary"),
            (family_id, sofia_id, 2022, "Capital City Independent School District", 55000.0, 0.0, 0.0, "Biology Teacher"),
            (family_id, sofia_id, 2023, "Capital City Independent School District", 57000.0, 0.0, 0.0, "Biology Teacher"),
            (family_id, sofia_id, 2024, "Capital City Independent School District", 59000.0, 0.0, 0.0, "Science Dept Chair"),
            (family_id, sofia_id, 2025, "Capital City Independent School District", 60500.0, 0.0, 0.0, "Science Dept Chair"),
            (family_id, sofia_id, 2026, "Capital City Independent School District", 62000.0, 0.0, 0.0, "Current step salary"),
        ]
        conn.executemany("INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", comp_records)

        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))

        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        cur = conn.execute("INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes) VALUES (?, 'Rosa Ramirez (Carlos''s Mother)', 1, 'parents', 'Annual living support for mother')", (family_id,))
        rosa_id = cur.lastrowid
        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        conn.executemany("INSERT INTO gifts (family_id, recipient_id, year, amount, notes) VALUES (?, ?, ?, ?, ?)", [
            (family_id, rosa_id, 2025, 3000.0, "Monthly living stipend support ($250/mo)"),
            (family_id, rosa_id, 2026, 3000.0, "Current year budgeted living stipend"),
        ])

        # Tuition & College Records (Texas Public University)
        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        hh_key = _household_key(db_path, family_id)
        ramirez_tuition = [
            # Mateo College (UT Austin / Texas A&M)
            (
                family_id, mateo_id, "2031-2032", "Texas Public University (Freshman)",
                security.encrypt_field(16500.0, key=hh_key), 1, "UT Austin / Texas A&M tuition & fees (Texas 529)",
            ),
            (
                family_id, mateo_id, "2032-2033", "Texas Public University (Sophomore)",
                security.encrypt_field(17200.0, key=hh_key), 1, "Texas in-state tuition & room (Texas 529)",
            ),
            (
                family_id, mateo_id, "2033-2034", "Texas Public University (Junior)",
                security.encrypt_field(18000.0, key=hh_key), 1, "Texas in-state public tuition (Texas 529)",
            ),
            (
                family_id, mateo_id, "2034-2035", "Texas Public University (Senior)",
                security.encrypt_field(18800.0, key=hh_key), 1, "Senior year undergraduate (Texas 529)",
            ),
            # Camila College
            (
                family_id, camila_id, "2035-2036", "Texas Public University (Freshman)",
                security.encrypt_field(18500.0, key=hh_key), 1, "Texas in-state public university (Texas 529)",
            ),
            (
                family_id, camila_id, "2036-2037", "Texas Public University (Sophomore)",
                security.encrypt_field(19300.0, key=hh_key), 1, "Texas in-state tuition & room (Texas 529)",
            ),
            (
                family_id, camila_id, "2037-2038", "Texas Public University (Junior)",
                security.encrypt_field(20100.0, key=hh_key), 1, "Texas in-state public tuition (Texas 529)",
            ),
            (
                family_id, camila_id, "2038-2039", "Texas Public University (Senior)",
                security.encrypt_field(21000.0, key=hh_key), 1, "Senior year undergraduate (Texas 529)",
            ),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ramirez_tuition)
        conn.commit()

    ramirez_accounts = [
        {"id": "acc_ramirez_chk", "name": "Chase Total Checking", "type": "depository", "subtype": "checking", "current_balance": 5800.0, "mask": "3140", "role": "cash_reserve"},
        {"id": "acc_ramirez_hysa", "name": "Ally High Yield Savings (Emergency Fund)", "type": "depository", "subtype": "savings", "current_balance": 24000.0, "mask": "8102", "role": "cash_reserve"},
        {"id": "acc_ramirez_403b", "name": "Sofia Capital City ISD 403(b) (Vanguard 2055)", "type": "investment", "subtype": "403b", "current_balance": 52000.0, "mask": "6641", "role": "retirement_tax_deferred"},
        {"id": "acc_ramirez_ira", "name": "Carlos Schwab Traditional IRA", "type": "investment", "subtype": "ira", "current_balance": 30000.0, "mask": "7712", "role": "retirement_tax_deferred"},
        {"id": "acc_ramirez_roth", "name": "Carlos Schwab Roth IRA", "type": "investment", "subtype": "roth_ira", "current_balance": 16000.0, "mask": "8890", "role": "retirement_roth"},
        {"id": "acc_ramirez_529_mat", "name": "Texas College Savings Plan - Mateo", "type": "investment", "subtype": "529", "current_balance": 14500.0, "mask": "9011", "role": "education_529"},
        {"id": "acc_ramirez_529_cam", "name": "Texas College Savings Plan - Camila", "type": "investment", "subtype": "529", "current_balance": 9800.0, "mask": "9012", "role": "education_529"},
        {"id": "acc_ramirez_home", "name": "Round Rock Single-Family Home", "type": "real_estate", "subtype": "home", "current_balance": 395000.0, "mask": "TX01", "role": "real_estate"},
        {"id": "acc_ramirez_mort", "name": "Wells Fargo 30-Yr Fixed (3.375%)", "type": "loan", "subtype": "mortgage", "current_balance": -242000.0, "mask": "1140", "role": "mortgage_liability"},
        {"id": "acc_ramirez_auto", "name": "Toyota Financial Auto Loan (2021 RAV4)", "type": "loan", "subtype": "auto_loan", "current_balance": -11500.0, "mask": "5520", "role": "auto_loan"},
    ]
    normalize_and_save_accounts(db_path, ramirez_accounts, family_id=family_id, spouse_beneficiaries={"Sofia": carlos_id, "Carlos": sofia_id})

    ramirez_holdings = [
        {"account_id": "acc_ramirez_403b", "ticker": "VTSAX", "name": "Vanguard Total Stock Market Index", "quantity": 250.0, "totalValue": 33000.0, "asset_class": "us_equity"},
        {"account_id": "acc_ramirez_403b", "ticker": "VTIAX", "name": "Vanguard Total International Stock Index", "quantity": 330.0, "totalValue": 11000.0, "asset_class": "intl_equity"},
        {"account_id": "acc_ramirez_403b", "ticker": "VBTLX", "name": "Vanguard Total Bond Market Index", "quantity": 85.0, "totalValue": 8000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_ramirez_ira", "ticker": "SWTSX", "name": "Schwab Total Stock Market Index Fund", "quantity": 240.0, "totalValue": 21000.0, "asset_class": "us_equity"},
        {"account_id": "acc_ramirez_ira", "ticker": "SWAGX", "name": "Schwab U.S. Aggregate Bond Index Fund", "quantity": 950.0, "totalValue": 9000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_ramirez_roth", "ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "quantity": 62.0, "totalValue": 16000.0, "asset_class": "us_equity"},
    ]
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", ramirez_holdings, family_id=family_id)
    security.db_save_encrypted(db_path, "lp_commitments", "private_markets", [], family_id=family_id)

    ramirez_edu = [
        {"user_id": mateo_id, "name": "Mateo Ramirez", "first_name": "Mateo", "birthdate": "2013-08-15", "birth_year": 2013, "college_start": 2031, "current_529_balance": 14500.0, "accounts": [{"name": "Texas College Savings Plan - Mateo", "balance": 14500.0}]},
        {"user_id": camila_id, "name": "Camila Ramirez", "first_name": "Camila", "birthdate": "2016-11-04", "birth_year": 2016, "college_start": 2035, "current_529_balance": 9800.0, "accounts": [{"name": "Texas College Savings Plan - Camila", "balance": 9800.0}]},
    ]
    security.db_save_encrypted(db_path, "children_education_reserves", "education", ramirez_edu, family_id=family_id)

    ramirez_transcripts = {
        "adults": ["Combined Household", "Carlos Ramirez", "Sofia Ramirez"],
        "safe_harbor_2026_target": 17400.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 141000.0, "federal_tax_withheld": 16200.0, "safe_harbor_required": 16000.0},
            "2025": {"combined_w2_income": 145500.0, "federal_tax_withheld": 17400.0, "safe_harbor_required": 16200.0}
        }
    }
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", ramirez_transcripts, family_id=family_id)

    ramirez_philanthropy = {
        "total_lifetime_charity": 2400.0,
        "lifetime_history": [
            {"year": 2025, "total": 1200.0, "budget": 1200.0},
            {"year": 2026, "total": 1200.0, "budget": 1200.0}
        ],
        "annual_budgets": {"2025": 1200.0, "2026": 1200.0},
        "donations_by_year": {
            "2025": {
                "total": 1200.0,
                "budget": 1200.0,
                "donations": [
                    {"organization": "Central Texas Food Bank", "amount": 600.0, "date": "2025-11-20", "description": "Holiday meal support"},
                    {"organization": "Austin Animal Center", "amount": 600.0, "date": "2025-12-15", "description": "Local shelter support"}
                ]
            },
            "2026": {
                "total": 1200.0,
                "budget": 1200.0,
                "donations": [
                    {"organization": "Central Texas Food Bank", "amount": 600.0, "date": "2026-11-20", "description": "Holiday meal support"},
                    {"organization": "Austin Animal Center", "amount": 600.0, "date": "2026-12-15", "description": "Local shelter support"}
                ]
            }
        }
    }
    security.db_save_encrypted(db_path, "annual_donations", "philanthropy", ramirez_philanthropy, family_id=family_id)

    # Seed Hierarchical Parent & Child Scenarios
    ramirez_custom_events = [
        {
            "id": "evt_k12_mateo",
            "name": "Mateo's K-12 Public School",
            "category": "education",
            "event_type": "duration",
            "icon": "",
            "year": 2099,
            "end_year": 2099,
            "annual_amount": 0.0,
            "funding_source": "cash_flow",
            "description": "Round Rock ISD public school (zero private school tuition).",
        },
        {
            "id": "evt_k12_camila",
            "name": "Camila's K-12 Public School",
            "category": "education",
            "event_type": "duration",
            "icon": "",
            "year": 2099,
            "end_year": 2099,
            "annual_amount": 0.0,
            "funding_source": "cash_flow",
            "description": "Round Rock ISD public school (zero private school tuition).",
        },
        {
            "id": "evt_college_mateo",
            "name": "Mateo's College (Texas In-State Public / 529)",
            "category": "college",
            "event_type": "duration",
            "icon": "",
            "child_user_id": mateo_id,
            "child_name": "Mateo Ramirez",
            "year": 2031,
            "end_year": 2034,
            "annual_amount": 16000.0,
            "use_529_reserves": True,
            "funding_source": "529_education_reserve",
            "description": "4-year Texas public university tuition (~$16k/yr), funded by Mateo's Texas 529 plan ($14.5k starting) and monthly family contributions.",
        },
        {
            "id": "evt_college_camila",
            "name": "Camila's College (Texas In-State Public / 529)",
            "category": "college",
            "event_type": "duration",
            "icon": "",
            "child_user_id": camila_id,
            "child_name": "Camila Ramirez",
            "year": 2035,
            "end_year": 2038,
            "annual_amount": 16000.0,
            "use_529_reserves": True,
            "funding_source": "529_education_reserve",
            "description": "4-year Texas public university tuition (~$16k/yr), funded by Camila's Texas 529 plan ($9.8k starting) and monthly family contributions.",
        },
        {
            "id": "evt_family_gifting",
            "name": "Monthly Support for Mother Rosa ($3k/yr)",
            "category": "gifting",
            "event_type": "duration",
            "icon": "",
            "year": 2026,
            "end_year": 2045,
            "annual_amount": 3000.0,
            "funding_source": "cash_flow",
            "description": "Monthly living stipend support for Carlos's elderly mother Rosa ($250/mo).",
        },
        {
            "id": "evt_mortgage_payoff",
            "name": "Pay Off Round Rock Mortgage (2041)",
            "category": "debt_payoff",
            "event_type": "single_spike",
            "year": 2041,
            "end_year": 2041,
            "amount": 114000.0,
            "funding_source": "cash_flow",
            "annual_cashflow_saved": 14700.0,
            "description":
                "Lump-sum payoff of the remaining Round Rock mortgage balance (about $114k at the start "
                "of 2041), eliminating monthly debt service.",
        }
    ]
    ramirez_scenarios = [
        {
            "id": "scen_baseline",
            "name": "Everyday Family Baseline",
            "description":
                "Current trajectory with $156k HHI, Round Rock home, Carlos retiring at 65 and Sofia "
                "at 62. Sofia's Texas TRS pension is entered in Settings: $48k a year in today's "
                "dollars from age 62 (2049), with 1% yearly increases and a 50% survivor share. "
                "Social Security is estimated: about $38.9k a year for Carlos from 2052 (estimated "
                "from his salary) and, for Sofia, her own $600 a month (entered in Settings, since "
                "her teaching years are not Social Security covered) topped up to the spousal "
                "benefit, about $58.3k a year together from 2054. The $242k mortgage at 3.375% (24 "
                "years left, about $14.7k a year) is entered in Settings, and about $14k a year is "
                "saved. Portfolio withdrawals begin in 2049. Monte Carlo success is about 88.5%.",
            "color": PLAN_COLORS["slate"],
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 65,
            "spouse_retirement_age": 62,
            "annual_living_spend": 94000.0,
            "annual_savings": 14000.0,
            "equity_growth_preset": "moderate",
            "event_ids": ["evt_college_mateo", "evt_college_camila", "evt_family_gifting"],
        },
        {
            "id": "scen_ramirez_early_retire_62",
            "name": "Retire at Age 62 (Mortgage-Free)",
            "description":
                "Carlos retires at 62 (2047, three years earlier than the baseline) after paying off "
                "the remaining Round Rock mortgage balance in 2041 (about $114k), which removes the "
                "$14.7k a year of debt service. Sofia's TRS pension still starts in 2049, and Social "
                "Security is claimed at 66 (about $36.3k a year from 2051, $54.2k together from "
                "2053). Without Carlos's last three working years the plan is thin: liquid savings "
                "are used up around 2048 (age 63) and the retirement accounts around 2059 (age 74), "
                "after which spending above Social Security and the pension is unfunded. Monte Carlo "
                "success is about 21.2%.",
            "color": PLAN_COLORS["emerald"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 62,
            "spouse_retirement_age": 62,
            "ss_claim_age": 66,
            "added_event_ids": ["evt_mortgage_payoff"],
        },
        {
            "id": "scen_ramirez_workshop_solar",
            "name": "Solar Efficiency & Reduced Overhead",
            "description":
                "Branches from the Mortgage-Free 62 plan, so it keeps the 2041 mortgage payoff and "
                "Carlos retiring at 62 with Social Security at 66, and cuts living expenses from $94k "
                "to $86k/yr through solar upgrades and lower overhead. The taxable savings last until "
                "about 2049 (age 64) and the retirement accounts past age 100. Monte Carlo success "
                "rises from about 21.2% to about 63.5%.",
            "color": PLAN_COLORS["sapphire"],
            "is_baseline": False,
            "parent_id": "scen_ramirez_early_retire_62",
            "annual_living_spend": 86000.0,
        },
        {
            "id": "scen_ramirez_boost_savings",
            "name": "Higher Savings & Work to Age 67",
            "description":
                "Carlos works to full retirement age 67 (Sofia still retires at 62 with her TRS "
                "pension), claiming Social Security at 67 with no early-claiming reduction (the "
                "benefit keeps growing until age 70), and the savings target rises from $14k to "
                "$18k/yr, about the most that take-home pay leaves after spending and the mortgage "
                "($18.7k a year in 2026). Monte Carlo success is about 100%, against about 88.5% for "
                "the baseline.",
            "color": PLAN_COLORS["cerulean"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 67,
            "ss_claim_age": 67,
            "annual_savings": 18000.0,
        },
    ]
    seed_family_scenarios(db_path, family_id, ramirez_scenarios, active_scenario_id="scen_baseline", custom_events=ramirez_custom_events)

    # Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=[
            {"year": 2018, "true_net_worth": 165000.0, "is_historical": True},
            {"year": 2019, "true_net_worth": 198000.0, "is_historical": True},
            {"year": 2020, "true_net_worth": 235000.0, "is_historical": True},
            {"year": 2021, "true_net_worth": 275000.0, "is_historical": True},
            {"year": 2022, "true_net_worth": 310000.0, "is_historical": True},
            {"year": 2023, "true_net_worth": 345000.0, "is_historical": True},
            {"year": 2024, "true_net_worth": 380000.0, "is_historical": True},
            {"year": 2025, "true_net_worth": 410000.0, "is_historical": True},
        ],
        historical_cash_flows=[
            {
                "year": 2018, "is_historical": True, "age_primary": 33, "age_spouse": 31, "household_salary": 118000.0,
                "salary_savings": 8000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 118000.0,
                "living_core": 75000.0, "travel_gogo": 6000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 97700.0, "net_cash_flow": 20300.0,
            },
            {
                "year": 2019, "is_historical": True, "age_primary": 34, "age_spouse": 32, "household_salary": 124000.0,
                "salary_savings": 9000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 124000.0,
                "living_core": 78500.0, "travel_gogo": 7000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 102200.0, "net_cash_flow": 21800.0,
            },
            {
                "year": 2020, "is_historical": True, "age_primary": 35, "age_spouse": 33, "household_salary": 128000.0,
                "salary_savings": 11000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 128000.0,
                "living_core": 76500.0, "travel_gogo": 4000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 97200.0, "net_cash_flow": 30800.0,
            },
            {
                "year": 2021, "is_historical": True, "age_primary": 36, "age_spouse": 34, "household_salary": 135000.0,
                "salary_savings": 11500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 135000.0,
                "living_core": 82500.0, "travel_gogo": 6000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 105200.0, "net_cash_flow": 29800.0,
            },
            {
                "year": 2022, "is_historical": True, "age_primary": 37, "age_spouse": 35, "household_salary": 140000.0,
                "salary_savings": 12500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 140000.0,
                "living_core": 86500.0, "travel_gogo": 7000.0, "gifting": 3000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 111200.0, "net_cash_flow": 28800.0,
            },
            {
                "year": 2023, "is_historical": True, "age_primary": 38, "age_spouse": 36, "household_salary": 144000.0,
                "salary_savings": 13000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 144000.0,
                "living_core": 89000.0, "travel_gogo": 8000.0, "gifting": 3000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 114700.0, "net_cash_flow": 29300.0,
            },
            {
                "year": 2024, "is_historical": True, "age_primary": 39, "age_spouse": 37, "household_salary": 148000.0,
                "salary_savings": 13500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 148000.0,
                "living_core": 92000.0, "travel_gogo": 8000.0, "gifting": 3000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 117700.0, "net_cash_flow": 30300.0,
            },
            {
                "year": 2025, "is_historical": True, "age_primary": 40, "age_spouse": 38, "household_salary": 152000.0,
                "salary_savings": 14000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 152000.0,
                "living_core": 94000.0, "travel_gogo": 9000.0, "gifting": 3000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 14700.0, "total_outflow": 120700.0, "net_cash_flow": 31300.0,
            },
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] The Ramirez Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_taylor_family(db_path: Path, family_id: int = 5, verbose: bool = True) -> None:
    """
    Populates 'The Taylor Family' (Columbus, OH):
    - Middle-Class Household: Marcus Taylor (Logistics Supervisor) & Danielle Taylor (RN)
    - 1 Child in early elementary school: Jordan (age 6)
    - Combined W-2 income: ~$131k. Modest home ($280k) with mortgage.
    - Federal student loans ($16.5k, $210/mo), building 401(k), 403(b), and Ohio 529.
    """
    db_path, global_db = _prepare_seed_target(db_path, family_id)
    if verbose:
        print(f"[SEED] Populating The Taylor Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # Persona: Registered nurse + warehouse supervisor, $131k HHI, student loans, building emergency fund & 401(k)
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, 'The Taylor Family', ?, ?, 1, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status, is_demo = 1, support_access_enabled = 1
        """, (family_id, "OH", "MFJ"))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'OH', 'MFJ', 68000.0, 11000.0, 65, 0.028, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "mortgage": {"remaining_term_years": 27, "annual_rate": 0.0425},
            "notes": "Columbus single-family home, Ohio state income tax (~2.75%), Buckeye Health 403(b), student loan payoff plan",
            "investment_policy": {
                "anchor_preset": "boglehead_80_20",
                "drift_tolerance": 0.05,
                "deviations_rationale": "Early wealth accumulation phase focused on low-cost broad market total index funds."
            },
            "estate_planning": {
                "apply_tcja_sunset": False,
                "charitable_pct": 0.02,
                "trust_preferences": ["will_trust", "ilit"],
                "verified_audit_ids": ["runway_critical"]
            }
        })))

        conn.commit()
    _clear_family_users(db_path, family_id)

    marcus_id = security.add_family_member(db_path, family_id, "Marcus Taylor", "marcus.taylor.demo@example.com", "1990-06-18", "primary", "admin")
    danielle_id = security.add_family_member(db_path, family_id, "Danielle Taylor", "danielle.taylor.demo@example.com", "1991-10-05", "spouse", "admin")
    jordan_id = security.add_family_member(db_path, family_id, "Jordan Taylor", "jordan.taylor.demo@example.com", "2020-03-24", "child", "viewer")

    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        comp_records = [
            (family_id, marcus_id, 2022, "FreightCorp Logistics", 58000.0, 3000.0, 0.0, "Warehouse Supervisor"),
            (family_id, marcus_id, 2023, "FreightCorp Logistics", 61000.0, 3500.0, 0.0, "Warehouse Supervisor"),
            (family_id, marcus_id, 2024, "FreightCorp Logistics", 64000.0, 4000.0, 0.0, "Operations Supervisor"),
            (family_id, marcus_id, 2025, "FreightCorp Logistics", 66000.0, 4500.0, 0.0, "Operations Supervisor"),
            (family_id, marcus_id, 2026, "FreightCorp Logistics", 68000.0, 5000.0, 0.0, "Current year salary"),
            (family_id, danielle_id, 2022, "Buckeye Health Riverside", 50000.0, 0.0, 0.0, "Staff Nurse (BSN)"),
            (family_id, danielle_id, 2023, "Buckeye Health Riverside", 53000.0, 0.0, 0.0, "Staff Nurse (BSN)"),
            (family_id, danielle_id, 2024, "Buckeye Health Riverside", 55000.0, 0.0, 0.0, "Charge Nurse"),
            (family_id, danielle_id, 2025, "Buckeye Health Riverside", 56500.0, 0.0, 0.0, "Charge Nurse"),
            (family_id, danielle_id, 2026, "Buckeye Health Riverside", 58000.0, 0.0, 0.0, "Current year salary"),
        ]
        conn.executemany("INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", comp_records)

        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))

        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        cur = conn.execute("INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes) VALUES (?, 'Brianna Taylor (Marcus''s Sister)', 1, 'siblings', 'College graduation & birthday gifts')", (family_id,))
        brianna_id = cur.lastrowid
        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        conn.executemany("INSERT INTO gifts (family_id, recipient_id, year, amount, notes) VALUES (?, ?, ?, ?, ?)", [
            (family_id, brianna_id, 2025, 1500.0, "Holiday & birthday gifts"),
            (family_id, brianna_id, 2026, 1500.0, "Current year budgeted gifts"),
        ])

        # Tuition & College Records (Ohio State University)
        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        hh_key = _household_key(db_path, family_id)
        taylor_tuition = [
            (
                family_id, jordan_id, "2038-2039", "Ohio State University (Freshman)",
                security.encrypt_field(19500.0, key=hh_key), 1, "OSU in-state undergraduate tuition & fees (Ohio 529)",
            ),
            (
                family_id, jordan_id, "2039-2040", "Ohio State University (Sophomore)",
                security.encrypt_field(20400.0, key=hh_key), 1, "OSU in-state tuition & campus housing",
            ),
            (
                family_id, jordan_id, "2040-2041", "Ohio State University (Junior)",
                security.encrypt_field(21300.0, key=hh_key), 1, "OSU in-state undergraduate tuition",
            ),
            (
                family_id, jordan_id, "2041-2042", "Ohio State University (Senior)",
                security.encrypt_field(22200.0, key=hh_key), 1, "OSU senior year undergraduate",
            ),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, taylor_tuition)
        conn.commit()

    taylor_accounts = [
        {"id": "acc_taylor_chk", "name": "Huntington Asterisk-Free Checking", "type": "depository", "subtype": "checking", "current_balance": 4200.0, "mask": "4421", "role": "cash_reserve"},
        {"id": "acc_taylor_hysa", "name": "Marcus & Danielle High Yield Savings", "type": "depository", "subtype": "savings", "current_balance": 14500.0, "mask": "7710", "role": "cash_reserve"},
        {"id": "acc_taylor_403b", "name": "Danielle Buckeye Health 403(b) (Fidelity 500)", "type": "investment", "subtype": "403b", "current_balance": 42000.0, "mask": "5120", "role": "retirement_tax_deferred"},
        {"id": "acc_taylor_401k", "name": "Marcus FreightCorp 401(k) (Target 2055)", "type": "investment", "subtype": "401k", "current_balance": 36000.0, "mask": "8341", "role": "retirement_tax_deferred"},
        {"id": "acc_taylor_roth", "name": "Danielle Vanguard Roth IRA (VTI)", "type": "investment", "subtype": "roth_ira", "current_balance": 8500.0, "mask": "9930", "role": "retirement_roth"},
        {"id": "acc_taylor_529", "name": "Ohio CollegeAdvantage 529 - Jordan", "type": "investment", "subtype": "529", "current_balance": 8200.0, "mask": "2210", "role": "education_529"},
        {"id": "acc_taylor_home", "name": "Columbus Suburban 3-Bed Home", "type": "real_estate", "subtype": "home", "current_balance": 280000.0, "mask": "OH01", "role": "real_estate"},
        {"id": "acc_taylor_mort", "name": "Rocket Mortgage 30-Yr Fixed (4.25%)", "type": "loan", "subtype": "mortgage", "current_balance": -192000.0, "mask": "6612", "role": "mortgage_liability"},
        {"id": "acc_taylor_student", "name": "Nelnet Federal Student Loan (Danielle BSN)", "type": "loan", "subtype": "student_loan", "current_balance": -16500.0, "mask": "3340", "role": "student_loan_liability"},
    ]
    normalize_and_save_accounts(db_path, taylor_accounts, family_id=family_id, spouse_beneficiaries={"Danielle": marcus_id, "Marcus": danielle_id})

    taylor_holdings = [
        {"account_id": "acc_taylor_403b", "ticker": "FXAIX", "name": "Fidelity 500 Index Fund", "quantity": 160.0, "totalValue": 30000.0, "asset_class": "us_equity"},
        {"account_id": "acc_taylor_403b", "ticker": "FTIHX", "name": "Fidelity Total International Index Fund", "quantity": 450.0, "totalValue": 6500.0, "asset_class": "intl_equity"},
        {"account_id": "acc_taylor_403b", "ticker": "FXNAX", "name": "Fidelity U.S. Bond Index Fund", "quantity": 530.0, "totalValue": 5500.0, "asset_class": "fixed_income"},
        {"account_id": "acc_taylor_401k", "ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "quantity": 95.0, "totalValue": 24000.0, "asset_class": "us_equity"},
        {"account_id": "acc_taylor_401k", "ticker": "VXUS", "name": "Vanguard Total International Stock ETF", "quantity": 100.0, "totalValue": 6000.0, "asset_class": "intl_equity"},
        {"account_id": "acc_taylor_401k", "ticker": "BND", "name": "Vanguard Total Bond Market ETF", "quantity": 82.0, "totalValue": 6000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_taylor_roth", "ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "quantity": 33.0, "totalValue": 8500.0, "asset_class": "us_equity"},
    ]
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", taylor_holdings, family_id=family_id)
    security.db_save_encrypted(db_path, "lp_commitments", "private_markets", [], family_id=family_id)

    taylor_edu = [
        {"user_id": jordan_id, "name": "Jordan Taylor", "first_name": "Jordan", "birthdate": "2020-03-24", "birth_year": 2020, "college_start": 2038, "current_529_balance": 8200.0, "accounts": [{"name": "Ohio CollegeAdvantage 529 - Jordan", "balance": 8200.0}]},
    ]
    security.db_save_encrypted(db_path, "children_education_reserves", "education", taylor_edu, family_id=family_id)

    taylor_transcripts = {
        "adults": ["Combined Household", "Marcus Taylor", "Danielle Taylor"],
        "safe_harbor_2026_target": 13800.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 119000.0, "federal_tax_withheld": 13200.0, "safe_harbor_required": 13000.0},
            "2025": {"combined_w2_income": 122500.0, "federal_tax_withheld": 13800.0, "safe_harbor_required": 13200.0}
        }
    }
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", taylor_transcripts, family_id=family_id)

    taylor_philanthropy = {
        "total_lifetime_charity": 2000.0,
        "lifetime_history": [
            {"year": 2025, "total": 1000.0, "budget": 1000.0},
            {"year": 2026, "total": 1000.0, "budget": 1000.0}
        ],
        "annual_budgets": {"2025": 1000.0, "2026": 1000.0},
        "donations_by_year": {
            "2025": {
                "total": 1000.0,
                "budget": 1000.0,
                "donations": [
                    {"organization": "Mid-Ohio Food Collective", "amount": 500.0, "date": "2025-11-15", "description": "Community food pantry"},
                    {"organization": "Buckeye Children's Hospital Foundation", "amount": 500.0, "date": "2025-12-10", "description": "Pediatric care gift"}
                ]
            },
            "2026": {
                "total": 1000.0,
                "budget": 1000.0,
                "donations": [
                    {"organization": "Mid-Ohio Food Collective", "amount": 500.0, "date": "2026-11-15", "description": "Community food pantry"},
                    {"organization": "Buckeye Children's Hospital Foundation", "amount": 500.0, "date": "2026-12-10", "description": "Pediatric care gift"}
                ]
            }
        }
    }
    security.db_save_encrypted(db_path, "annual_donations", "philanthropy", taylor_philanthropy, family_id=family_id)

    # Seed Hierarchical Parent & Child Scenarios
    taylor_custom_events = [
        {
            "id": "evt_k12_jordan",
            "name": "Jordan's K-12 Public School",
            "category": "education",
            "event_type": "duration",
            "icon": "",
            "year": 2099,
            "end_year": 2099,
            "annual_amount": 0.0,
            "funding_source": "cash_flow",
            "description": "Columbus public school education (zero private school tuition).",
        },
        {
            "id": "evt_college_jordan",
            "name": "Jordan's College (Ohio In-State Public / 529)",
            "category": "college",
            "event_type": "duration",
            "icon": "",
            "child_user_id": jordan_id,
            "child_name": "Jordan Taylor",
            "year": 2038,
            "end_year": 2041,
            "annual_amount": 18000.0,
            "use_529_reserves": True,
            "funding_source": "529_education_reserve",
            "description": "4-year Ohio public university tuition (~$18k/yr), funded by Jordan's Ohio 529 plan ($8.2k starting) and monthly family savings.",
        },
        {
            "id": "evt_family_gifting",
            "name": "Holiday & Birthday Gifts to Brianna ($1.5k/yr)",
            "category": "gifting",
            "event_type": "duration",
            "icon": "",
            "year": 2026,
            "end_year": 2045,
            "annual_amount": 1500.0,
            "funding_source": "cash_flow",
            "description": "Modest annual holiday and birthday gifts to Marcus's sister Brianna ($1,500/yr).",
        }
    ]
    taylor_scenarios = [
        {
            "id": "scen_baseline",
            "name": "Taylor Family Baseline",
            "description":
                "Current trajectory with $131k HHI, Ohio 529 for Jordan, and target retirement at age "
                "65. Take-home pay of about $106k covers $68k of living spend (childcare included) "
                "and the mortgage ($192k at 4.25%, 27 years left, about $12.0k a year, entered in "
                "Settings), leaving about $26k a year of which the $11k/yr savings target is saved. "
                "Withdrawals begin in 2055 and the accounts last past age 100 on the fixed return "
                "path. Social Security is estimated from earnings: about $32.3k a year from 2057 and "
                "$59.8k together from 2058. Monte Carlo success is about 76.0%.",
            "color": PLAN_COLORS["slate"],
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 65,
            "spouse_retirement_age": 65,
            "annual_living_spend": 68000.0,
            "annual_savings": 11000.0,
            "equity_growth_preset": "moderate",
            "event_ids": ["evt_college_jordan", "evt_family_gifting"],
        },
        {
            "id": "scen_taylor_accelerate_debt",
            "name": "Accelerate Student Debt Elimination",
            "description":
                "Raises the savings target from $11k to $15k/yr, money that would otherwise go to "
                "everyday spending (take-home pay leaves about $26k a year after spending and the "
                "mortgage). Student loan payoff is not modeled; the extra savings stand in for the "
                "faster paydown. Monte Carlo success rises from about 76.0% to about 90.6%.",
            "color": PLAN_COLORS["sapphire"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_savings": 15000.0,
        },
        {
            "id": "scen_taylor_retire_63",
            "name": "Retire at Age 63",
            "description":
                "Branches from the savings-target plan and retires both spouses at 63 instead of 65. "
                "Two fewer working years and two more years of withdrawals (from 2053) leave the plan "
                "with a thin margin: nothing runs out before age 100 on the fixed return path, but "
                "Monte Carlo success is about 69.6%, against about 90.6% for the plan it branches "
                "from.",
            "color": PLAN_COLORS["emerald"],
            "is_baseline": False,
            "parent_id": "scen_taylor_accelerate_debt",
            "primary_retirement_age": 63,
            "spouse_retirement_age": 63,
        },
        {
            "id": "scen_taylor_work_to_67",
            "name": "Full Career to Age 67 (Full Retirement Age)",
            "description":
                "Extends healthcare and logistics careers to full retirement age 67, claiming Social "
                "Security at full retirement age (the benefit keeps growing until age 70). Two more "
                "working years lift Monte Carlo success from about 76.0% to about 94.7%.",
            "color": PLAN_COLORS["amber"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 67,
            "spouse_retirement_age": 67,
            "ss_claim_age": 67,
        },
    ]
    seed_family_scenarios(db_path, family_id, taylor_scenarios, active_scenario_id="scen_baseline", custom_events=taylor_custom_events)

    # Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=[
            {"year": 2018, "true_net_worth": 45000.0, "is_historical": True},
            {"year": 2019, "true_net_worth": 64000.0, "is_historical": True},
            {"year": 2020, "true_net_worth": 88000.0, "is_historical": True},
            {"year": 2021, "true_net_worth": 112000.0, "is_historical": True},
            {"year": 2022, "true_net_worth": 132000.0, "is_historical": True},
            {"year": 2023, "true_net_worth": 154000.0, "is_historical": True},
            {"year": 2024, "true_net_worth": 175000.0, "is_historical": True},
            {"year": 2025, "true_net_worth": 195000.0, "is_historical": True},
        ],
        historical_cash_flows=[
            {
                "year": 2018, "is_historical": True, "age_primary": 28, "age_spouse": 27, "household_salary": 92000.0,
                "salary_savings": 4000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 92000.0,
                "living_core": 53000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 70000.0, "net_cash_flow": 22000.0,
            },
            {
                "year": 2019, "is_historical": True, "age_primary": 29, "age_spouse": 28, "household_salary": 98000.0,
                "salary_savings": 5000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 98000.0,
                "living_core": 55500.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 72500.0, "net_cash_flow": 25500.0,
            },
            {
                "year": 2020, "is_historical": True, "age_primary": 30, "age_spouse": 29, "household_salary": 104000.0,
                "salary_savings": 7000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 104000.0,
                "living_core": 54500.0, "travel_gogo": 2000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 69500.0, "net_cash_flow": 34500.0,
            },
            {
                "year": 2021, "is_historical": True, "age_primary": 31, "age_spouse": 30, "household_salary": 112000.0,
                "salary_savings": 7500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 112000.0,
                "living_core": 58500.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 75500.0, "net_cash_flow": 36500.0,
            },
            {
                "year": 2022, "is_historical": True, "age_primary": 32, "age_spouse": 31, "household_salary": 118000.0,
                "salary_savings": 8500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 118000.0,
                "living_core": 61500.0, "travel_gogo": 5000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 79500.0, "net_cash_flow": 38500.0,
            },
            {
                "year": 2023, "is_historical": True, "age_primary": 33, "age_spouse": 32, "household_salary": 122000.0,
                "salary_savings": 9500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 122000.0,
                "living_core": 64000.0, "travel_gogo": 5000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 82000.0, "net_cash_flow": 40000.0,
            },
            {
                "year": 2024, "is_historical": True, "age_primary": 34, "age_spouse": 33, "household_salary": 125000.0,
                "salary_savings": 10000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 125000.0,
                "living_core": 66500.0, "travel_gogo": 5000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 84500.0, "net_cash_flow": 40500.0,
            },
            {
                "year": 2025, "is_historical": True, "age_primary": 35, "age_spouse": 34, "household_salary": 128000.0,
                "salary_savings": 11000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 128000.0,
                "living_core": 68000.0, "travel_gogo": 6000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 12000.0, "total_outflow": 87000.0, "net_cash_flow": 41000.0,
            },
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] The Taylor Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_foster_family(db_path: Path, family_id: int = 6, verbose: bool = True) -> None:
    """
    Populates 'The Foster Family' (Denver, CO):
    - Single-Parent Household: Jessica Foster (Pediatric Physical Therapist) & Noah Foster (Son, age 12)
    - Zero Spouse (has_spouse = False)
    - W-2 income: ~$115k at Mile High Pediatric Hospital. Head of Household (HOH) tax status.
    - Denver bungalow ($540k) with 3.75% mortgage, 403(b), Roth IRA, Colorado 529, emergency savings.
    """
    db_path, global_db = _prepare_seed_target(db_path, family_id)
    if verbose:
        print(f"[SEED] Populating The Foster Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # Persona: Solo pediatric physical therapist & single mom, $115k W-2, Head of Household, Colorado 529, 403(b) &
        # Roth IRA
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, 'The Foster Family', ?, ?, 1, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status, is_demo = 1, support_access_enabled = 1
        """, (family_id, "CO", "HOH"))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'CO', 'HOH', 50000.0, 11000.0, 62, 0.025, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "mortgage": {"remaining_term_years": 25, "annual_rate": 0.0375},
            "notes": "Denver bungalow, Colorado flat state tax (4.4%), Mile High Pediatric Hospital 403(b), single-parent household",
            "investment_policy": {
                "anchor_preset": "boglehead_80_20",
                "drift_tolerance": 0.05,
                "deviations_rationale": "Core passive index portfolio balancing growth and resilience as a solo earner."
            },
            "estate_planning": {
                "apply_tcja_sunset": False,
                "charitable_pct": 0.05,
                "trust_preferences": ["will_trust", "ilit"],
                "verified_audit_ids": ["probate_acc_foster_home"]
            }
        })))

        conn.commit()
    _clear_family_users(db_path, family_id)

    jessica_id = security.add_family_member(db_path, family_id, "Jessica Foster", "jessica.foster.demo@example.com", "1988-03-22", "primary", "admin")
    noah_id = security.add_family_member(db_path, family_id, "Noah Foster", "noah.foster.demo@example.com", "2014-06-18", "child", "viewer")

    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        comp_records = [
            (family_id, jessica_id, 2022, "Mile High Pediatric Hospital", 98000.0, 2000.0, 0.0, "Pediatric Physical Therapist"),
            (family_id, jessica_id, 2023, "Mile High Pediatric Hospital", 102000.0, 2500.0, 0.0, "Pediatric Physical Therapist"),
            (family_id, jessica_id, 2024, "Mile High Pediatric Hospital", 106000.0, 3000.0, 0.0, "Senior Physical Therapist"),
            (family_id, jessica_id, 2025, "Mile High Pediatric Hospital", 110000.0, 3500.0, 0.0, "Senior Physical Therapist"),
            (family_id, jessica_id, 2026, "Mile High Pediatric Hospital", 115000.0, 4000.0, 0.0, "Current year salary"),
        ]
        conn.executemany("INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", comp_records)

        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))

        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        cur = conn.execute("INSERT INTO gift_recipients (family_id, recipient_group_name, member_count, relationship, notes) VALUES (?, 'Liam Foster (Jessica''s Nephew)', 1, 'nephew', 'Birthday & college fund gifts')", (family_id,))
        liam_id = cur.lastrowid
        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        conn.executemany("INSERT INTO gifts (family_id, recipient_id, year, amount, notes) VALUES (?, ?, ?, ?, ?)", [
            (family_id, liam_id, 2025, 500.0, "Birthday gift & 529 contribution"),
            (family_id, liam_id, 2026, 500.0, "Current year gift budget"),
        ])

        # Tuition & College Records (CU Boulder)
        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        hh_key = _household_key(db_path, family_id)
        foster_tuition = [
            (
                family_id, noah_id, "2032-2033", "CU Boulder (Freshman)",
                security.encrypt_field(18500.0, key=hh_key), 1,
                "Colorado in-state public tuition & fees (DirectPortfolio 529)",
            ),
            (
                family_id, noah_id, "2033-2034", "CU Boulder (Sophomore)",
                security.encrypt_field(19400.0, key=hh_key), 1, "CU Boulder in-state tuition & residence hall",
            ),
            (
                family_id, noah_id, "2034-2035", "CU Boulder (Junior)",
                security.encrypt_field(20300.0, key=hh_key), 1, "CU Boulder in-state undergraduate tuition",
            ),
            (
                family_id, noah_id, "2035-2036", "CU Boulder (Senior)",
                security.encrypt_field(21200.0, key=hh_key), 1, "CU Boulder senior year undergraduate",
            ),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, foster_tuition)
        conn.commit()

    foster_accounts = [
        {"id": "acc_foster_chk", "name": "FirstBank Colorado Checking", "type": "depository", "subtype": "checking", "current_balance": 8450.0, "mask": "2281", "role": "cash_reserve"},
        {"id": "acc_foster_hysa", "name": "Ally Bank High Yield Savings (Emergency)", "type": "depository", "subtype": "savings", "current_balance": 28500.0, "mask": "7134", "role": "cash_reserve"},
        {"id": "acc_foster_403b", "name": "Mile High Pediatric 403(b) (Index 2050)", "type": "investment", "subtype": "403b", "current_balance": 142000.0, "mask": "4810", "role": "retirement_tax_deferred"},
        {"id": "acc_foster_roth", "name": "Jessica Vanguard Roth IRA (VTSAX)", "type": "investment", "subtype": "roth_ira", "current_balance": 48000.0, "mask": "9022", "role": "retirement_roth"},
        {"id": "acc_foster_529", "name": "DirectPortfolio Colorado 529 - Noah", "type": "investment", "subtype": "529", "current_balance": 34200.0, "mask": "1190", "role": "education_529"},
        {"id": "acc_foster_home", "name": "Denver Wash Park Bungalow", "type": "real_estate", "subtype": "home", "current_balance": 540000.0, "mask": "CO01", "role": "real_estate"},
        {"id": "acc_foster_mort", "name": "FirstBank 30-Yr Fixed Mortgage (3.75%)", "type": "loan", "subtype": "mortgage", "current_balance": -315000.0, "mask": "8841", "role": "mortgage_liability"},
        {"id": "acc_foster_auto", "name": "Chase Auto Loan (2022 Subaru Outback)", "type": "loan", "subtype": "auto_loan", "current_balance": -11200.0, "mask": "4390", "role": "auto_loan"},
    ]
    normalize_and_save_accounts(db_path, foster_accounts, family_id=family_id, default_beneficiary_user_id=noah_id)

    foster_holdings = [
        {"account_id": "acc_foster_403b", "ticker": "VTSAX", "name": "Vanguard Total Stock Market Index", "quantity": 660.0, "totalValue": 88000.0, "asset_class": "us_equity"},
        {"account_id": "acc_foster_403b", "ticker": "VTIAX", "name": "Vanguard Total International Stock Index", "quantity": 800.0, "totalValue": 26000.0, "asset_class": "intl_equity"},
        {"account_id": "acc_foster_403b", "ticker": "VBTLX", "name": "Vanguard Total Bond Market Index", "quantity": 295.0, "totalValue": 28000.0, "asset_class": "fixed_income"},
        {"account_id": "acc_foster_roth", "ticker": "VTSAX", "name": "Vanguard Total Stock Market Index", "quantity": 360.0, "totalValue": 48000.0, "asset_class": "us_equity"},
    ]
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", foster_holdings, family_id=family_id)
    security.db_save_encrypted(db_path, "lp_commitments", "private_markets", [], family_id=family_id)

    foster_edu = [
        {"user_id": noah_id, "name": "Noah Foster", "first_name": "Noah", "birthdate": "2014-06-18", "birth_year": 2014, "college_start": 2032, "current_529_balance": 34200.0, "accounts": [{"name": "DirectPortfolio Colorado 529 - Noah", "balance": 34200.0}]},
    ]
    security.db_save_encrypted(db_path, "children_education_reserves", "education", foster_edu, family_id=family_id)

    foster_transcripts = {
        "adults": ["Jessica Foster"],
        "safe_harbor_2026_target": 15000.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 109000.0, "federal_tax_withheld": 14200.0, "safe_harbor_required": 14000.0},
            "2025": {"combined_w2_income": 113500.0, "federal_tax_withheld": 15000.0, "safe_harbor_required": 14200.0}
        }
    }
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", foster_transcripts, family_id=family_id)

    foster_philanthropy = {
        "total_lifetime_charity": 2000.0,
        "lifetime_history": [
            {"year": 2025, "total": 1000.0, "budget": 1000.0},
            {"year": 2026, "total": 1000.0, "budget": 1000.0}
        ],
        "annual_budgets": {"2025": 1000.0, "2026": 1000.0},
        "donations_by_year": {
            "2025": {
                "total": 1000.0,
                "budget": 1000.0,
                "donations": [
                    {"organization": "Mile High Pediatric Hospital Foundation", "amount": 600.0, "date": "2025-11-25", "description": "Pediatric therapy patient assistance fund"},
                    {"organization": "Denver Rescue Mission", "amount": 400.0, "date": "2025-12-18", "description": "Holiday meals and shelter"}
                ]
            },
            "2026": {
                "total": 1000.0,
                "budget": 1000.0,
                "donations": [
                    {"organization": "Mile High Pediatric Hospital Foundation", "amount": 600.0, "date": "2026-11-25", "description": "Pediatric therapy patient assistance fund"},
                    {"organization": "Denver Rescue Mission", "amount": 400.0, "date": "2026-12-18", "description": "Holiday meals and shelter"}
                ]
            }
        }
    }
    security.db_save_encrypted(db_path, "annual_donations", "philanthropy", foster_philanthropy, family_id=family_id)

    # Seed Hierarchical Parent & Child Scenarios
    foster_custom_events = [
        {
            "id": "evt_k12_noah",
            "name": "Noah's K-12 Public School",
            "category": "education",
            "event_type": "duration",
            "icon": "",
            "year": 2099,
            "end_year": 2099,
            "annual_amount": 0.0,
            "funding_source": "cash_flow",
            "description": "Denver public school education (zero private school tuition).",
        },
        {
            "id": "evt_college_noah",
            "name": "Noah's College (Colorado Public / 529)",
            "category": "college",
            "event_type": "duration",
            "icon": "",
            "child_user_id": noah_id,
            "child_name": "Noah Foster",
            "year": 2032,
            "end_year": 2035,
            "annual_amount": 18000.0,
            "use_529_reserves": True,
            "funding_source": "529_education_reserve",
            "description": "4-year Colorado public university tuition (~$18k/yr), funded by Noah's Colorado 529 plan ($34.2k starting) and monthly family savings.",
        },
        {
            "id": "evt_foster_clinic_income",
            "name": "Clinic Owner Distributions (+$20k/yr)",
            "category": "capital_inflow",
            "inflow_source_type": "business_income",
            "event_type": "duration",
            "icon": "evt-rental-income",
            "year": 2029,
            "end_year": 2043,
            "annual_amount": 20000.0,
            "amount": 20000.0,
            "is_outflow": False,
            "funding_source": "cash_flow",
            "description": "After-tax owner distributions from an independent pediatric physical therapy clinic, "
                    "added to Jessica's hospital pay as a stand-in for business income (the engine has no"
                    " business-income input).",
        },
        {
            "id": "evt_family_gifting",
            "name": "Annual Gift to Liam ($500/yr)",
            "category": "gifting",
            "event_type": "duration",
            "icon": "",
            "year": 2026,
            "end_year": 2045,
            "annual_amount": 500.0,
            "funding_source": "cash_flow",
            "description": "Annual birthday and 529 gift to nephew Liam ($500/yr).",
        }
    ]
    foster_scenarios = [
        {
            "id": "scen_baseline",
            "name": "Single-Parent Baseline",
            "description":
                "Solo parent trajectory with a $115k salary plus a $4k bonus, Denver Wash Park home, "
                "Colorado 529 for Noah, and planned retirement at age 62. Take-home pay of about $91k "
                "covers $50k of living spend and the mortgage ($315k at 3.75%, 25 years left, about "
                "$19.4k a year, entered in Settings), leaving about $21k a year of which the $11k/yr "
                "savings target is saved. Withdrawals begin in 2050, and liquid savings are used up "
                "around 2072 (age 84) while the retirement accounts last past age 100. Social "
                "Security is estimated from earnings: about $42.6k a year from 2055. Monte Carlo "
                "success is about 84.8%.",
            "color": PLAN_COLORS["slate"],
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 62,
            "annual_living_spend": 50000.0,
            "annual_savings": 11000.0,
            "equity_growth_preset": "moderate",
            "event_ids": ["evt_college_noah", "evt_family_gifting"],
        },
        {
            "id": "scen_foster_work_to_67",
            "name": "Work to Age 67 (Full Retirement Age)",
            "description":
                "Extends clinical practice to full retirement age 67, claiming solo Social Security "
                "(no spousal fallback) without an early-claiming reduction. Withdrawals start in 2055 "
                "instead of 2050 and no account runs out before age 100. Monte Carlo success is about "
                "99.6%, against about 84.8% for the baseline.",
            "color": PLAN_COLORS["sapphire"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 67,
            "ss_claim_age": 67,
        },
        {
            "id": "scen_foster_independent_clinic",
            "name": "Private Pediatric Clinic Expansion",
            "description":
                "Establishes an independent pediatric physical therapy clinic. The engine has no "
                "business-income input, so the plan adds about $20k a year of after-tax owner "
                "distributions from 2029 to 2043 and raises the savings target to $18k/yr (take-home "
                "pay leaves about $21k after spending and the mortgage). Practice sale proceeds are "
                "not modeled. Monte Carlo success is about 99.5%.",
            "color": PLAN_COLORS["emerald"],
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_savings": 18000.0,
            "added_event_ids": ["evt_foster_clinic_income"],
        },
        {
            "id": "scen_foster_clinic_early_retire",
            "name": "Private Practice Early Exit (Age 55)",
            "description":
                "Branches from Clinic Expansion and retires at 55, claiming Social Security at 62 "
                "(about $29.1k a year from 2050). The owner distributions end in 2043 and the seven "
                "years before Social Security begins are funded from savings: withdrawals begin in "
                "2043 and liquid savings are used up around 2073 (age 85). No practice sale or other "
                "business proceeds are modeled. This is the household's stretch plan: Monte Carlo "
                "success is about 63.1%, against about 99.5% for the clinic plan it branches from.",
            "color": PLAN_COLORS["cerulean"],
            "is_baseline": False,
            "parent_id": "scen_foster_independent_clinic",
            "primary_retirement_age": 55,
            "ss_claim_age": 62,
        },
    ]
    seed_family_scenarios(db_path, family_id, foster_scenarios, active_scenario_id="scen_baseline", custom_events=foster_custom_events)

    # Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=[
            {"year": 2018, "true_net_worth": 150000.0, "is_historical": True},
            {"year": 2019, "true_net_worth": 180000.0, "is_historical": True},
            {"year": 2020, "true_net_worth": 215000.0, "is_historical": True},
            {"year": 2021, "true_net_worth": 255000.0, "is_historical": True},
            {"year": 2022, "true_net_worth": 285000.0, "is_historical": True},
            {"year": 2023, "true_net_worth": 315000.0, "is_historical": True},
            {"year": 2024, "true_net_worth": 350000.0, "is_historical": True},
            {"year": 2025, "true_net_worth": 380000.0, "is_historical": True},
        ],
        historical_cash_flows=[
            {
                "year": 2018, "is_historical": True, "age_primary": 30, "age_spouse": 0, "household_salary": 88000.0,
                "salary_savings": 5500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 88000.0,
                "living_core": 38500.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 62900.0, "net_cash_flow": 25100.0,
            },
            {
                "year": 2019, "is_historical": True, "age_primary": 31, "age_spouse": 0, "household_salary": 93000.0,
                "salary_savings": 6500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 93000.0,
                "living_core": 40500.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 64900.0, "net_cash_flow": 28100.0,
            },
            {
                "year": 2020, "is_historical": True, "age_primary": 32, "age_spouse": 0, "household_salary": 96000.0,
                "salary_savings": 7500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 96000.0,
                "living_core": 39500.0, "travel_gogo": 2000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 61900.0, "net_cash_flow": 34100.0,
            },
            {
                "year": 2021, "is_historical": True, "age_primary": 33, "age_spouse": 0, "household_salary": 102000.0,
                "salary_savings": 8000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 102000.0,
                "living_core": 43000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 67400.0, "net_cash_flow": 34600.0,
            },
            {
                "year": 2022, "is_historical": True, "age_primary": 34, "age_spouse": 0, "household_salary": 106000.0,
                "salary_savings": 9000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 106000.0,
                "living_core": 45000.0, "travel_gogo": 5000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 71400.0, "net_cash_flow": 34600.0,
            },
            {
                "year": 2023, "is_historical": True, "age_primary": 35, "age_spouse": 0, "household_salary": 110000.0,
                "salary_savings": 10000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 110000.0,
                "living_core": 47500.0, "travel_gogo": 5000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 73900.0, "net_cash_flow": 36100.0,
            },
            {
                "year": 2024, "is_historical": True, "age_primary": 36, "age_spouse": 0, "household_salary": 113000.0,
                "salary_savings": 10500.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 113000.0,
                "living_core": 48500.0, "travel_gogo": 5000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 74900.0, "net_cash_flow": 38100.0,
            },
            {
                "year": 2025, "is_historical": True, "age_primary": 37, "age_spouse": 0, "household_salary": 116000.0,
                "salary_savings": 11000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 116000.0,
                "living_core": 50000.0, "travel_gogo": 6000.0, "gifting": 2000.0, "events_outflow": 0.0,
                "mortgage_debt_service": 19400.0, "total_outflow": 77400.0, "net_cash_flow": 38600.0,
            },
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] The Foster Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_empty_family(db_path: Path, family_id: int = 7, verbose: bool = True) -> None:
    """Seeds a fresh, blank tenant (0 members, 0 accounts, 0 grants) for onboarding verification."""
    db_path, global_db = _prepare_seed_target(db_path, family_id)
    if verbose:
        print(f"[SEED] Populating Blank Tenant into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # Persona: Brand New Household (Zero Records Onboarding State)
        conn.execute("""
            INSERT INTO families (family_id, name, primary_state, tax_filing_status, is_demo, support_access_enabled)
            VALUES (?, 'New Household (Blank)', ?, ?, 1, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, primary_state = excluded.primary_state,
                tax_filing_status = excluded.tax_filing_status, is_demo = 1, support_access_enabled = 1
        """, (family_id, "WA", "MFJ"))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'WA', 'MFJ', 120000.0, 50000.0, 60, 0.025, 0.045, '{}')
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings
        """, (family_id,))

        conn.execute("DELETE FROM tuition WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM compensation WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM gift_recipients WHERE family_id = ?", (family_id,))
        conn.execute("DELETE FROM gifts WHERE family_id = ?", (family_id,))
        conn.commit()
    _clear_family_users(db_path, family_id)

    normalize_and_save_accounts(db_path, [], family_id=family_id)
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", [], family_id=family_id)
    security.db_save_encrypted(db_path, "lp_commitments", "private_markets", [], family_id=family_id)
    security.db_save_encrypted(db_path, "tax_document_checklist", "tax_checklist", {}, family_id=family_id)
    security.db_save_encrypted(db_path, "tax_transcripts", "irs_transcripts_sync", {"adults": ["Combined Household"], "historical_summary": {}}, family_id=family_id)
    seed_family_scenarios(db_path, family_id, [
        {
            "id": "scen_baseline",
            "name": "Baseline Plan",
            "description": "Default baseline plan for onboarding.",
            "color": PLAN_COLORS["slate"],
            "equity_growth_preset": "moderate",
            "is_baseline": True,
            "parent_id": None,
        }
    ], active_scenario_id="scen_baseline")
    _sync_seeded_family_to_global(db_path, global_db, family_id)

    if verbose:
        print(f"[SUCCESS] Blank Tenant successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_all_demo_families(db_path: Optional[Path] = None, verbose: bool = True, universe: str = "demo") -> None:
    """Seeds all 7 demo personas into the specified database."""
    if db_path is None:
        db_path = config.get_global_db_path(universe)
    assert_demo_slots_are_safe(db_path, range(1, 8))
    seed_jones_family(db_path, family_id=1, verbose=verbose)
    seed_miller_family(db_path, family_id=2, verbose=verbose)
    seed_chen_family(db_path, family_id=3, verbose=verbose)
    seed_ramirez_family(db_path, family_id=4, verbose=verbose)
    seed_taylor_family(db_path, family_id=5, verbose=verbose)
    seed_foster_family(db_path, family_id=6, verbose=verbose)
    seed_empty_family(db_path, family_id=7, verbose=verbose)
    if Path(db_path).name != "global.db":
        from scripts.migrate_to_family_dbs import migrate_database
        uni = _universe_of_db_path(db_path)
        migrate_database(db_path, universe=uni, verbose=verbose)
    if verbose:
        print(f"[COMPLETE] All 7 Demo Personas successfully seeded into {db_path.name}!")


def main():
    parser = argparse.ArgumentParser(description="Seed demo families for HVL Family Office.")
    parser.add_argument("--universe", default="demo", choices=["demo", "beta", "test"], help="Target database universe (default: demo)")
    parser.add_argument("--family_id", type=int, default=None, help="Specific family ID to seed (1: Jones, 2: Miller, 3: Chen, 4: Ramirez, 5: Taylor, 6: Foster, 7: Blank). Default: All")
    args = parser.parse_args()

    universe = "demo" if args.universe == "beta" else args.universe
    db_path = config.get_global_db_path(universe)
    assert_demo_slots_are_safe(db_path, [args.family_id] if args.family_id in range(1, 8) else range(1, 8))
    if args.family_id == 1:
        seed_jones_family(db_path=db_path, family_id=1, verbose=True)
    elif args.family_id == 2:
        seed_miller_family(db_path=db_path, family_id=2, verbose=True)
    elif args.family_id == 3:
        seed_chen_family(db_path=db_path, family_id=3, verbose=True)
    elif args.family_id == 4:
        seed_ramirez_family(db_path=db_path, family_id=4, verbose=True)
    elif args.family_id == 5:
        seed_taylor_family(db_path=db_path, family_id=5, verbose=True)
    elif args.family_id == 6:
        seed_foster_family(db_path=db_path, family_id=6, verbose=True)
    elif args.family_id == 7:
        seed_empty_family(db_path=db_path, family_id=7, verbose=True)
    else:
        seed_all_demo_families(db_path=db_path, verbose=True)

    from scripts.migrate_to_family_dbs import migrate_database
    migrate_database(db_path, universe=universe, verbose=True)


if __name__ == "__main__":
    main()

