"""
Idempotent Demo Family Seeder for HVL Family Office.
Targets the 'demo' (or 'test') universe database without touching production (Family 1).

Seeds 'The Jones Family' (San Francisco, CA):
- Dual High-Earners: Dr. Sarah Jones, MD (UCSF Surgeon) & Alex Jones (Principal AI Engineer)
- 3 Children across all tiers: Maya (College @ UC Berkeley), Ethan (High School @ Lick-Wilmerding), Chloe (SF Day School)
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
# Ensure parent directory and bundled vendor directory are in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if (BASE_DIR / "vendor").exists() and str(BASE_DIR / "vendor") not in sys.path:
    sys.path.append(str(BASE_DIR / "vendor"))

from hvl_common.db import get_db_connection
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

import config
import security


def _clear_family_users(db_path: Path, family_id: int) -> None:
    """Clears all users for a family across monolithic, dedicated family, and global databases."""
    uni = "demo" if ("demo" in str(db_path) or "beta" in str(db_path)) else ("test" if "test" in str(db_path) else ("sandbox" if "sandbox" in str(db_path) else "public"))
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
) -> None:
    """Seeds hierarchical scenarios (parent and child plans) and events into scenario_system_state."""
    import forecast_engine

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
) -> None:
    """Normalizes account payload ensuring both camelCase and snake_case keys are present for 100% interoperability."""
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
        try:
            ret_ids = [
                str(a.get("id") or "").strip()
                for a in raw_accounts
                if str(a.get("role") or "").strip() in ("retirement_tax_deferred", "retirement_roth")
            ]
            # Leave the last retirement account without a default beneficiary so Survivorship Audit demos an actionable warning
            unconfirmed_ret_id = ret_ids[-1] if len(ret_ids) >= 2 else None
            with get_db_connection(db_path) as conn:
                for acc in raw_accounts:
                    acc_id = str(acc.get("id") or "").strip()
                    role = str(acc.get("role") or "").strip()
                    if not (acc_id and role):
                        continue
                    ben_id = acc.get("beneficiary_user_id")
                    if ben_id is None and default_beneficiary_user_id and role in ("retirement_tax_deferred", "retirement_roth"):
                        if acc_id != unconfirmed_ret_id:
                            ben_id = default_beneficiary_user_id
                    is_conf = 1 if ben_id else 0
                    conn.execute("""
                        INSERT INTO account_roles (family_id, monarch_account_id, role, beneficiary_user_id, is_user_confirmed, is_hidden_from_family_office)
                        VALUES (?, ?, ?, ?, ?, 0)
                        ON CONFLICT(family_id, monarch_account_id) DO UPDATE SET
                            role = excluded.role,
                            beneficiary_user_id = excluded.beneficiary_user_id,
                            is_user_confirmed = excluded.is_user_confirmed,
                            is_hidden_from_family_office = excluded.is_hidden_from_family_office
                    """, (family_id, acc_id, role, ben_id, is_conf))
                conn.commit()
        except Exception:
            pass


def seed_family_tax_checklist_progress(db_path: Path, family_id: int, tax_year: int = 2025) -> None:
    """Seeds realistic mid-tax-season document statuses (Sent to CPA, Received, Waiting) for demo households."""
    try:
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
    except Exception as exc:
        logger.debug("Could not seed tax checklist progress for family %s: %s", family_id, exc)


def _get_demo_advisor_conversations(family_id: int) -> List[Any]:
    """Returns curated, persona-aligned, PII-free demo advisor conversations for each demo household."""
    all_conversations: Dict[int, List[Any]] = {
        # Family 1: The Jones Family (San Francisco, CA - High Earners, Multi-Company Equity, 3 Kids)
        1: [
            ("beta-conv-jones-00", family_id, "section-overview", "Chief of Staff Executive Radar & Action Briefing", "Primary Member", 1, "2026-10-15 08:30:00", "2026-10-15 08:32:00", [
                ("user", "Run our Chief of Staff Executive Radar briefing. What needs our attention across taxes, LP commitments, and estate readiness this quarter?", "2026-10-15 08:30:00"),
                ("model", "### 🧭 Chief of Staff Executive Radar Briefing\n\n1. **Survivorship & Probate Readiness (70/100):**\n   * **Action Required:** Your **Vanguard Joint Taxable Brokerage ($1.85M)** and **SF Primary Residence ($2.45M)** lack revocable trust titling (`SLAT` / `RLT`) or `TOD` designation, exposing them to California statutory probate fees.\n   * **Beneficiary Gap:** Confirm contingent beneficiary designation on **Alex's Roth IRA ($195k)** (Dr. Sarah Jones's 403(b)/457(b)/Roth and Alex's 401(k) are confirmed **✓ Verified**).\n2. **Private Markets LP Commitment Book ($1.60M Committed | 1.30x TVPI):**\n   * **Unfunded Dry Powder:** **$550,000** across 3 funds (3.9x covered by liquid reserves, $218.5k cash).\n   * **Stale Valuation Mark:** **Pinnacle Real Estate Opportunity II** ($190k NAV) is still marked as of `2025-12-31` (>120 days stale) with Schedule K-1 `Expected`.\n3. **Tax Season Checklist & 110% Safe Harbor:**\n   * **Checklist Progress:** **9 of 11** documents received or sent to CPA; awaiting **Vanguard 1099-Consolidated** and **Pinnacle Real Estate Schedule K-1**.\n   * **2026 Safe Harbor Target:** **$412,500** (110% of prior-year tax liability); RSU supplemental withholding gap (`22%` statutory vs. `37%` top bracket) is marked **✓ Verified** via Q3 Form 1040-ES.", "2026-10-15 08:32:00")
            ]),
            ("beta-conv-jones-01", family_id, "section-equity", "Option Exercise & Capital Requirements", "Primary Member", 1, "2026-10-10 14:20:00", "2026-10-10 14:22:00", [
                ("user", "What are my strike capital requirements and estimated tax liability if I exercise my vested NSO options this quarter?", "2026-10-10 14:20:00"),
                ("model", "### 💡 Equity Liquidity & Tax Analysis\n\nBased on your active **Nexus Founding NSO (NX-01)** grant:\n\n1. **Strike Capital Required:** At $1.75 strike price for 50,000 vested options, your total exercise cost is **$87,500.00**.\n2. **Spread Taxation (Ordinary Income):** NSO exercise triggers ordinary income tax on the spread between Fair Market Value (FMV) of $24.00 and your $1.75 strike price ($1,112,500 spread). At California's top marginal tax bracket plus federal ordinary income rates, ensure estimated federal and state withholding reserves are funded prior to exercise.\n3. **Liquidity Options:** Consider modeling a **cashless exercise** or utilizing cash reserves in your high-yield savings to avoid liquidating core index holdings.", "2026-10-10 14:22:00")
            ]),
            ("beta-conv-jones-02", family_id, "section-holdings", "Core & Satellite Portfolio Drift Analysis", "Primary Member", 1, "2026-10-11 09:15:00", "2026-10-11 09:18:00", [
                ("user", "Our portfolio has drifted +3.2% above target in US Equities. Does our Investment Policy Statement require rebalancing now?", "2026-10-11 09:15:00"),
                ("model", "### 📊 IPS Portfolio Drift Assessment\n\nYour portfolio is anchored to **Core & Satellite (50/20/15/5/10)** with a **±5.0% tolerance band**.\n\n* **Current US Equity Allocation:** 53.2% (Target: 50.0%)\n* **Tolerance Status:** Drift (+3.2%) is currently **within the allowable tolerance band**.\n* **Recommendation:** No immediate rebalancing transaction is required. To maintain tax efficiency, direct upcoming dividend distributions and new contributions into underweighted satellite asset classes rather than triggering taxable capital gain sales in your taxable brokerage account.", "2026-10-11 09:18:00")
            ]),
            ("beta-conv-jones-03", family_id, "section-scenarios", "Monte Carlo Longevity Stress Test", "Primary Member", 0, "2026-10-12 16:40:00", "2026-10-12 16:45:00", [
                ("user", "How does our retirement plan hold up if equity valuations drop 30% over the next 3 years?", "2026-10-12 16:40:00"),
                ("model", "### 📉 Longevity Stress Test Replay\n\nRunning a Monte Carlo 1,000-trial sequence of returns simulation with a 30% drawdown in private tech equity:\n\n* **Simulated Plan Success Rate:** **96.4%** across 35-year longevity.\n* **Safe Withdrawal Rate:** Current effective withdrawal rate is 2.8%, well below the 4.0% conservative ceiling.\n* **Cash Buffer:** Maintaining an 18-to-24 month liquid cash reserve in treasury bills/HYSA protects you from forced asset liquidations during severe market drawdowns.", "2026-10-12 16:45:00")
            ]),
            ("beta-conv-jones-04", family_id, "section-arbitrage", "State Tax Arbitrage & Domicile Planning", "Primary Member", 0, "2026-10-13 11:00:00", "2026-10-13 11:04:00", [
                ("user", "What are the primary residency criteria for establishing tax domicile in a 0% personal income tax state?", "2026-10-13 11:00:00"),
                ("model", "### 🏛️ Domicile & Statutory Residency Rules\n\nTo establish primary tax domicile in a 0% state (e.g., WA, TX, NV, FL):\n\n1. **The 183-Day Rule:** You must spend at least 183 days of the tax year in your new state of domicile.\n2. **Primary Abode & Vital Interests:** Primary residential ownership, family school enrollments, and principal banking connections should reflect the new location.\n3. **Audit Trail:** Maintain contemporaneous travel records, flight receipts, and credit card physical transaction logs to substantiate your physical presence against California FTB residency audits.", "2026-10-13 11:04:00")
            ]),
            ("beta-conv-jones-05", family_id, "section-education", "Tiered Education Funding: UC Berkeley vs Private Prep", "Primary Member", 0, "2026-10-14 09:30:00", "2026-10-14 09:33:00", [
                ("user", "With Maya at UC Berkeley and Ethan attending Lick-Wilmerding, how should we prioritize 529 withdrawals versus taxable cash flow?", "2026-10-14 09:30:00"),
                ("model", "### 🎓 Education Funding & 529 Tax Rules\n\n1. **Maya (UC Berkeley - Higher Education):** Fully qualified for ScholarShare 529 distributions covering tuition, mandatory fees, books, and on/off-campus room & board. Distributions are 100% tax-free at both federal and California state levels.\n2. **Ethan (Lick-Wilmerding - High School):** While federal law permits up to $10,000/year per student from a 529 for K-12 tuition, **California does not conform** to this provision. Any California 529 distribution used for K-12 tuition is treated as a non-qualified state distribution, subjecting earnings to CA state income tax plus a 2.5% state penalty.\n3. **Recommendation:** Fund Ethan's private high school tuition directly from taxable cash flow or bonus reserves, preserving 529 compounding for college and graduate education.", "2026-10-14 09:33:00")
            ])
        ],
        # Family 2: The Miller Family (WA State - FIRE Early Retired, $6.5M Liquid, Zero W-2)
        2: [
            ("beta-conv-miller-01", family_id, "section-scenarios", "FIRE Dynamic Safe Withdrawal Rate (SWR) & Guardrails", "Primary Member", 1, "2026-10-11 10:15:00", "2026-10-11 10:18:00", [
                ("user", "With $6.5M in liquid investments and our annual spending at $185k, what does our safe withdrawal rate look like under a dynamic guardrail strategy?", "2026-10-11 10:15:00"),
                ("model", "### 🛡️ FIRE Decumulation & Guardrail Analysis\n\nBased on your $6.5M liquid portfolio and $185,000 baseline living expenses:\n\n* **Initial Withdrawal Rate:** **2.85%**, well below the conservative 3.25% early retirement ceiling.\n* **Glidepath Asset Allocation (60/40):** 60% global equities ($3.90M) paired with 40% intermediate treasuries & fixed income ($2.60M) creates an 8-year defensive buffer against sequence-of-returns risk.\n* **Guyton-Klinger Guardrails:** If market appreciation pulls your withdrawal rate below 2.2%, a 10% prosperity bonus can be distributed; if a severe prolonged bear market pushes it above 3.8%, inflation adjustments are temporarily frozen.\n* **Longevity Solvency:** Monte Carlo modeling indicates a **100% portfolio survival rate** across a 45-year retirement horizon to age 95.", "2026-10-11 10:18:00")
            ]),
            ("beta-conv-miller-02", family_id, "section-tax", "Roth Conversion Ladder & ACA MAGI Optimization", "Primary Member", 1, "2026-10-12 13:20:00", "2026-10-12 13:24:00", [
                ("user", "We want to execute an $80k annual Roth conversion from Robert's Traditional IRA. How does this impact our Affordable Care Act (ACA) health insurance premium tax credits?", "2026-10-12 13:20:00"),
                ("model", "### ⚖️ Roth Conversion vs. ACA Premium Tax Credit Trade-off\n\n* **Zero W-2 Advantage:** With zero earned income in Washington State (0% state income tax), your Modified Adjusted Gross Income (MAGI) consists entirely of taxable dividends, interest, and executed IRA conversions.\n* **Federal Tax Bracket Arbitrage:** Converting $80,000 fills the 10% and 12% federal tax brackets (after the MFJ standard deduction of ~$29,200), allowing you to pay minimal federal income tax before Required Minimum Distributions (RMDs) trigger at age 75.\n* **ACA Subsidy Threshold:** Under current enhanced ACA rules, benchmark Silver plan premiums are capped at 8.5% of household MAGI. Keeping MAGI under $110,000 preserves substantial monthly premium tax credits while converting $80k annually.", "2026-10-12 13:24:00")
            ]),
            ("beta-conv-miller-03", family_id, "section-holdings", "Tax-Efficient Asset Location & Dividend Drag", "Primary Member", 0, "2026-10-13 15:45:00", "2026-10-13 15:48:00", [
                ("user", "Our taxable Vanguard brokerage generates roughly $88k/year in qualified dividends. Should we reallocate fixed income to mitigate tax drag?", "2026-10-13 15:45:00"),
                ("model", "### 📊 Asset Location Strategy (Taxable vs. Tax-Deferred)\n\n* **Current Placement:** Keeping fixed-income and bond funds inside Robert's Traditional IRA shields ordinary interest from annual taxation.\n* **Taxable Brokerage Optimization:** Your taxable brokerage should remain 100% broad-market passive index equities (VTI/VXUS) where qualified dividends receive favorable 15% federal capital gains rates and zero WA state income tax.\n* **Cash Cushion:** Your $250k Treasury-bills reserve produces state-tax-exempt federal interest, serving as a 16-month living expense buffer that prevents forced selling during equity corrections.", "2026-10-13 15:48:00")
            ])
        ],
        # Family 3: The Chen Family (NYC - Series A Tech Founder, High Illiquidity, Toddler)
        3: [
            ("beta-conv-chen-01", family_id, "section-equity", "ISO Exercise & Alternative Minimum Tax (AMT) Modeling", "Primary Member", 1, "2026-10-10 11:10:00", "2026-10-10 11:14:00", [
                ("user", "If I exercise my 120,000 vested ISOs in NovaPulse AI at the current $3.80 409A valuation ($0.35 strike), what is our AMT exposure this year?", "2026-10-10 11:10:00"),
                ("model", "### ⚠️ ISO Exercise & Alternative Minimum Tax (AMT) Analysis\n\nBased on your NovaPulse AI incentive stock options:\n\n1. **Strike Capital Required:** 120,000 shares × $0.35 strike = **$42,000.00** upfront cash.\n2. **AMT Preference Spread:** ($3.80 409A − $0.35 strike) × 120,000 = **$414,000.00** added to Alternative Minimum Taxable Income (AMTI).\n3. **Estimated Federal AMT Liability:** Triggers an estimated **$107,000–$115,000** in AMT liability for tax year 2026 under Form 6251.\n4. **Form 8801 Minimum Tax Credit:** AMT paid on ISO exercise generates a Minimum Tax Credit (MTC) that carries forward indefinitely to offset regular tax in future years when regular tax exceeds tentative AMT.\n5. **Timing Warning:** Exercise early in the calendar year (Q1) to allow monitoring of private secondary valuation trends before the December 31 irrevocable AMT tax lock.", "2026-10-10 11:14:00")
            ]),
            ("beta-conv-chen-02", family_id, "section-scenarios", "Section 1202 QSBS 5-Year Holding Period Strategy", "Primary Member", 1, "2026-10-12 14:00:00", "2026-10-12 14:05:00", [
                ("user", "How do our NovaPulse AI founder shares qualify for Section 1202 QSBS, and what are the rules if the company raises a Series B next year?", "2026-10-12 14:00:00"),
                ("model", "### 📜 Section 1202 QSBS Tax Exemption Framework\n\n* **100% Federal Capital Gain Exclusion:** Up to **$10,000,000** (or 10x adjusted basis) in federal capital gains can be completely excluded from tax upon exit.\n* **Statutory Requirements:** Stock must be acquired at original issuance from an active domestic C-Corporation with gross assets under $50M immediately before and after issuance.\n* **5-Year Holding Clock:** The holding period began on your initial equity grant/83(b) filing date. Secondary tender offers or sales prior to the 5-year anniversary disqualify the sold shares from QSBS treatment (or require a Section 1045 rollover into another qualifying QSB within 60 days).\n* **NYS/NYC Tax Conformance:** Note that while New York State and NYC conform to federal Section 1202 exclusions, high-earner local tax planning is essential.", "2026-10-12 14:05:00")
            ]),
            ("beta-conv-chen-03", family_id, "section-education", "529 Superfunding for Liam & NY State Tax Deduction", "Primary Member", 0, "2026-10-14 08:30:00", "2026-10-14 08:34:00", [
                ("user", "We want to superfund Liam's college savings with a $180,000 contribution. How does the 5-year gift forward election work, and what is our NY state tax deduction?", "2026-10-14 08:30:00"),
                ("model", "### 🎓 529 5-Year Forward Superfunding (Form 709)\n\n* **Annual Gift Exclusion Forwarding:** Couples filing MFJ can contribute up to **$180,000** in a single year ($36,000 annual exclusion × 5 years) without triggering federal gift tax or tapping lifetime unified gift exemptions, by electing 5-year averaging on IRS Form 709.\n* **Compound Growth Horizon:** Superfunding at age 2 gives Liam 16 years of tax-free compounding. At an assumed 6.5% net return, $180k projects to ~$495,000 by college matriculation at age 18.\n* **New York State Tax Deduction Cap:** NY State limits the income tax deduction to **$10,000/year** for married couples ($5,000 for singles). The excess $170,000 does not carry forward for NY state tax deductions, but all future growth and qualified withdrawals remain 100% tax-free at both federal and NY state levels.", "2026-10-14 08:34:00")
            ])
        ],
        # Family 4: The Ramirez Family (Austin, TX - Middle-Class Working Household, TRS Pension, Trade Solo 401k)
        4: [
            ("beta-conv-ramirez-01", family_id, "section-overview", "Texas TRS Pension Integration & Social Security WEP Rules", "Primary Member", 1, "2026-10-11 11:00:00", "2026-10-11 11:05:00", [
                ("user", "How does Sofia's Texas Teacher Retirement System (TRS) pension affect our Social Security benefits under the Windfall Elimination Provision (WEP)?", "2026-10-11 11:00:00"),
                ("model", "### 🏛️ Texas TRS & Social Security WEP / GPO Coordination\n\n* **Sofia's Non-Covered Pension:** Because Sofia contributes to Texas TRS instead of paying Social Security FICA taxes on her teaching salary, her earned Social Security from previous private-sector jobs is subject to the **Windfall Elimination Provision (WEP)**.\n* **WEP Impact:** WEP can reduce Sofia's own Social Security benefit by up to 50% of her TRS pension, capped at a maximum reduction of ~$587/month (2026 ceiling), but it can **never reduce her benefit to zero**.\n* **Carlos's Social Security Is Unaffected:** Carlos's primary Social Security benefit from electrical contracting is 100% protected and based on his full covered earnings history.\n* **Retirement Replacement Rate:** Sofia's TRS pension (projected at 2.3% × years of service × final average salary = ~$48k/yr) combined with Carlos's Social Security provides an exceptional guaranteed baseline, reducing dependence on market withdrawals.", "2026-10-11 11:05:00")
            ]),
            ("beta-conv-ramirez-02", family_id, "section-cashflow", "Solo 401(k) vs. SEP-IRA for Electrical Contracting Income", "Primary Member", 1, "2026-10-13 14:10:00", "2026-10-13 14:15:00", [
                ("user", "Carlos earned $32,000 in net 1099 electrical trade income this year. What is the most tax-advantageous retirement vehicle to shelter this?", "2026-10-13 14:10:00"),
                ("model", "### ⚡ Solo 401(k) vs. SEP-IRA Evaluation\n\n**Recommendation: Solo 401(k)**\n\n1. **Contribution Capacity:** Carlos can contribute up to 20% of net self-employment earnings as an 'employer profit-sharing' contribution (~$6,000), plus up to $23,500 in 'employee elective deferrals' (if not already maxed elsewhere), sheltering over $28,000 of his $32,000 net trade income.\n2. **Backdoor Roth Preservation:** A Solo 401(k) does **not** trigger IRA aggregation rules (pro-rata rule under IRS Section 408(d)(10)), keeping both Carlos and Sofia eligible for clean Backdoor Roth IRA conversions. A SEP-IRA would create taxable pro-rata friction.\n3. **Texas 0% State Tax:** Combined with Texas having no state income tax, pre-tax Solo 401(k) deferrals reduce federal AGI directly at Carlos's 22% marginal bracket.", "2026-10-13 14:15:00")
            ]),
            ("beta-conv-ramirez-03", family_id, "section-education", "Mortgage Prepayment (3.375%) vs. Texas 529 College Savings", "Primary Member", 0, "2026-10-14 10:20:00", "2026-10-14 10:24:00", [
                ("user", "We have an extra $450/month in cash flow. Should we make extra principal payments on our 3.375% mortgage or split it between Mateo and Camila's Texas 529 plans?", "2026-10-14 10:20:00"),
                ("model", "### ⚖️ Debt Prepayment vs. College Investment Trade-off\n\n* **Mortgage Rate Benchmark:** Your fixed 3.375% mortgage interest rate is historically low and well below current Treasury yields (~4.2%) and conservative diversified equity returns (~6.5–7.5%). Prepaying yields an after-tax guaranteed return of only 3.375%.\n* **College Tuition Horizon:** Mateo (age 11) is 7 years from college, and Camila (age 8) is 10 years away. In-state public tuition at UT Austin or Texas A&M currently averages ~$28k/year all-in (tuition, fees, room & board).\n* **Strategic Recommendation:** Direct $225/month each into Mateo and Camila's Texas College Savings 529 portfolios (age-based conservative tracks). Maintaining the 3.375% mortgage schedule preserves liquidity and provides superior compounding for their college horizon.", "2026-10-14 10:24:00")
            ])
        ],
        # Family 5: The Taylor Family (Columbus, OH - Young Accumulators, Pre-K Daycare, Student Debt)
        5: [
            ("beta-conv-taylor-01", family_id, "section-cashflow", "Federal Student Loans vs. 403(b) Employer Match", "Primary Member", 1, "2026-10-12 12:00:00", "2026-10-12 12:04:00", [
                ("user", "We have $16,500 left on federal student loans at 4.65%. Should we accelerate payoff or invest more into Danielle's hospital 403(b)?", "2026-10-12 12:00:00"),
                ("model", "### 🎯 Student Loan Payoff vs. 403(b) Match Optimization\n\n1. **Rule 1: Always Capture 100% of Employer Match:** Danielle's hospital 403(b) provides a 50% match on the first 6% of salary. That is an immediate, risk-free **50% instant return**, vastly exceeding the 4.65% interest cost of the student loans.\n2. **Student Loan Interest Deduction:** At $126k MFJ income, your interest payments on the $16,500 balance are deductible above-the-line on Form 1040 (up to the $2,500 phaseout limit starting at $165k MFJ), lowering effective borrowing cost to ~3.6%.\n3. **Action Plan:** Maintain standard monthly amortization ($210/mo) on the student loans while maximizing Danielle's 403(b) match and contributing to Roth IRAs.", "2026-10-12 12:04:00")
            ]),
            ("beta-conv-taylor-02", family_id, "section-education", "Ohio CollegeAdvantage 529 State Tax Deduction", "Primary Member", 1, "2026-10-13 16:30:00", "2026-10-13 16:34:00", [
                ("user", "How much can we deduct on our Ohio state tax return for contributing to Jordan's 529 college savings plan?", "2026-10-13 16:30:00"),
                ("model", "### 🌰 Ohio CollegeAdvantage (OTTA) 529 Tax Rules\n\n* **State Tax Deduction Limit:** Ohio allows married couples filing jointly to deduct up to **$4,000 per year, per beneficiary** from Ohio adjusted gross income for contributions to Ohio's 529 CollegeAdvantage plan.\n* **Unlimited Carryforward:** Any contribution exceeding $4,000 in a calendar year can be carried forward indefinitely and deducted in future tax years until fully exhausted.\n* **Net Savings:** At Ohio's top marginal bracket (~2.75%), a $4,000 annual contribution yields an immediate $110 in state tax savings, in addition to 100% tax-free growth and tax-free qualified distributions for Jordan's future education.", "2026-10-13 16:34:00")
            ]),
            ("beta-conv-taylor-03", family_id, "section-overview", "Emergency Fund Sizing During Peak Pre-K Daycare Costs", "Primary Member", 0, "2026-10-14 09:10:00", "2026-10-14 09:14:00", [
                ("user", "Jordan's full-time daycare costs $1,250/month ($15,000/yr). Should our emergency fund be 3 months or 6 months?", "2026-10-14 09:10:00"),
                ("model", "### 🛡️ Emergency Reserve Calibration for Young Families\n\n* **Recommended Reserve: 6 Months ($32,000)**\n* **Fixed Cost Inflexibility:** Daycare tuition ($1,250/mo) and mortgage ($1,850/mo) are mandatory fixed expenses that cannot be quickly eliminated if Marcus or Danielle experiences a career transition.\n* **Dual-Earner Advantage:** Because Danielle is a healthcare RN and Marcus works in logistics management, dual-income diversification reduces the odds of simultaneous unemployment. However, keeping 6 months in a 4.5% high-yield savings account (HYSA) provides peace of mind and prevents relying on high-interest credit cards or tapping retirement funds.", "2026-10-14 09:14:00")
            ])
        ],
        # Family 6: The Foster Family (Denver, CO - Single-Parent Household, Sole Breadwinner, Estate Protection)
        6: [
            ("beta-conv-foster-01", family_id, "section-estate", "Sole-Earner Estate Planning & Legal Guardianship for Noah", "Primary Member", 1, "2026-10-11 14:00:00", "2026-10-11 14:05:00", [
                ("user", "As a single parent, what estate planning documents do I need to ensure Noah (age 12) is protected if something happens to me?", "2026-10-11 14:00:00"),
                ("model", "### 👨‍👦 Single-Parent Estate Protection Framework\n\n1. **Revocable Living Trust (RLT):** Critical. Without a trust, your Denver bungalow ($540k) and accounts would pass through Colorado probate court, and a court-appointed conservator would control assets until Noah turns 18. An RLT allows your appointed Successor Trustee to manage funds for Noah's health, education, maintenance, and support (HEMS) well into adulthood (e.g., ages 25/30).\n2. **Testamentary Guardian Nomination:** Explicitly designates who will raise Noah. Must be executed in both your Will and a standalone nomination document.\n3. **Beneficiary Designations:** Ensure your 403(b), Roth IRA, and life insurance name the Revocable Living Trust as the contingent beneficiary (with appropriate look-through trust provisions), never a minor child directly.\n4. **Advance Directives:** Medical Power of Attorney, HIPAA authorization, and Durable Financial Power of Attorney.", "2026-10-11 14:05:00")
            ]),
            ("beta-conv-foster-02", family_id, "section-overview", "Life & Disability Insurance Adequacy for Noah's Future", "Primary Member", 1, "2026-10-13 10:15:00", "2026-10-13 10:20:00", [
                ("user", "I have 2x salary ($230k) in group life insurance through Children's Hospital Colorado. Is this enough to cover Noah?", "2026-10-13 10:15:00"),
                ("model", "### 🛡️ Life & Disability Protection Gap Analysis\n\n* **The 2x Salary Gap:** $230,000 is insufficient for a sole provider. Noah is 12; he has 6 years until college and 10 years until financial independence. Surviving mortgage debt ($340k) alone exceeds your employer group coverage.\n* **Coverage Recommendation:** Purchase a **15-year level term policy of $1,000,000 to $1,250,000**. Term rates for a healthy physical therapist in her late 30s/early 40s are very affordable (~$45–$65/month) and provide full income replacement plus college funding.\n* **Own-Occupation Disability:** As a pediatric physical therapist, physical mobility is essential to your W-2 earnings. Review whether hospital disability is 'any occupation' or 'own occupation', and consider a supplemental individual disability policy.", "2026-10-13 10:20:00")
            ]),
            ("beta-conv-foster-03", family_id, "section-education", "Colorado CollegeInvest 529 State Tax Benefit & Matching", "Primary Member", 0, "2026-10-14 11:30:00", "2026-10-14 11:34:00", [
                ("user", "How does the Colorado CollegeInvest 529 plan work for Head of Household filers, and is there a state tax deduction?", "2026-10-14 11:30:00"),
                ("model", "### 🏔️ Colorado CollegeInvest 529 Tax Rules\n\n* **100% State Tax Deduction:** Colorado offers one of the nation's most generous 529 incentives: contributions to any Colorado CollegeInvest plan are **100% deductible dollar-for-dollar** against Colorado state taxable income, with no dollar cap for Colorado residents.\n* **Head of Household Savings:** At Colorado's 4.4% flat income tax rate, contributing $6,000/year to Noah's Direct Portfolio CollegeInvest account saves an immediate **$264/year** in Colorado state income taxes.\n* **Matching Grants:** Check eligibility for Colorado's *Matching Grant Program*, which provides dollar-for-dollar matches up to $500/year for eligible middle-income Colorado families with children under age 13.", "2026-10-14 11:34:00")
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

    try:
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
                    "INSERT INTO advisor_conversations (conversation_id, family_id, page_section, title, created_by, is_pinned, created_at, updated_at) "
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
    except Exception as e:
        logger.warning("Could not seed advisor conversations for family %s: %s", family_id, e)


def _load_fixture(filename: str) -> Any:
    """Loads a JSON fixture from data/fixtures/."""
    fixture_path = BASE_DIR / "data" / "fixtures" / filename
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_jones_family(db_path: Path, family_id: int = 1, verbose: bool = True) -> None:
    """Populates the specified database with the complete Jones family dataset from JSON fixtures."""
    security.init_db(db_path)

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
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET
                name = excluded.name,
                settings = excluded.settings,
                support_access_enabled = 1
        """, (family_id, fam["name"], json.dumps(fam["settings"])))

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
        default_beneficiary_user_id=member_ids.get("alex"),
    )

    # C. Seed Holdings Breakdown
    security.db_save_encrypted(db_path, "holdings", "monarch_sync", accounts_data["holdings"], family_id=family_id)

    # C2. Seed Private Markets LP Commitment Book ($1.6M across Venture, PE, and Real Estate)
    from services.private_markets_service import DEFAULT_DEMO_LP_COMMITMENTS
    security.db_save_encrypted(db_path, "lp_commitments", "holdings", [dict(d) for d in DEFAULT_DEMO_LP_COMMITMENTS], family_id=family_id)

    # C3. Seed Children 529 Education Reserves
    jones_edu = [
        {"user_id": member_ids.get("maya"), "name": "Maya Jones", "first_name": "Maya", "birthdate": "2007-04-12", "birth_year": 2007, "college_start": 2024, "current_529_balance": 68000.0, "accounts": [{"name": "ScholarShare 529 - Maya (College)", "balance": 68000.0}]},
        {"user_id": member_ids.get("ethan"), "name": "Ethan Jones", "first_name": "Ethan", "birthdate": "2011-09-20", "birth_year": 2011, "college_start": 2028, "current_529_balance": 145000.0, "accounts": [{"name": "ScholarShare 529 - Ethan (High School)", "balance": 145000.0}]},
        {"user_id": member_ids.get("chloe"), "name": "Chloe Jones", "first_name": "Chloe", "birthdate": "2018-02-14", "birth_year": 2018, "college_start": 2036, "current_529_balance": 125000.0, "accounts": [{"name": "ScholarShare 529 - Chloe (Grade School)", "balance": 125000.0}]},
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
    seed_family_scenarios(db_path, family_id, profile_data["scenarios"], active_scenario_id="scen_baseline")

    # G. Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=profile_data["historical_ribbon"],
        historical_cash_flows=profile_data["historical_cash_flows"],
    )

    # H. Seed Demo AI Advisor Conversations
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)

    if verbose:
        print(f"[SUCCESS] The Jones Family successfully seeded into {db_path.name}!")
        print(f"  - Dr. Sarah Jones, MD (Admin) & Alex Jones (Admin)")
        print(f"  - 3 Students: Maya (College), Ethan (High School), Chloe (Grade School)")
        print(f"  - Companies: Nexus AI Inc. ($24 FMV, NSO grants) & CloudFlow Systems")
        print(f"  - Net Worth: ~$5.7M across Real Estate, Taxable Brokerage, 401k/403b, 529s")


def seed_miller_family(db_path: Path, family_id: int = 2, verbose: bool = True) -> None:
    """Seeds The Miller Family (FIRE Early Retired, WA State, $6.5M Liquid, Zero W-2)."""
    security.init_db(db_path)
    if verbose:
        print(f"[SEED] Populating The Miller Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, 'The Miller Family', ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, settings = excluded.settings, support_access_enabled = 1
        """, (family_id, json.dumps({
            "primary_state": "WA",
            "tax_filing_status": "MFJ",
            "city": "Seattle",
            "is_demo": True,
            "persona": "Early Retired FIRE ($6.5M Liquid, 0% WA State Tax, Zero W-2)"
        })))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'WA', 'MFJ', 185000.0, 0.0, 50, 0.024, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "notes": "Fully early-retired FIRE. Annual $80k Roth conversion ladder strategy.",
            "investment_policy": {
                "anchor_preset": "glidepath_60_40",
                "drift_tolerance": 0.05,
                "deviations_rationale": "Strict adherence to 60/40 age-based glidepath for sequence-of-returns defense during early FIRE decumulation. Zero private investments or illiquid alternative assets."
            },
            "estate_planning": {
                "apply_tcja_sunset": True,
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
            (family_id, robert_id, 2022, "Microsoft Corporation", 255000.0, 45000.0, 60000.0, "Final career year prior to early retirement"),
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
    normalize_and_save_accounts(db_path, miller_accounts, family_id=family_id, default_beneficiary_user_id=karen_id)

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
        "safe_harbor_2026_target": 24500.0,
        "historical_summary": {
            "2023": {"combined_w2_income": 0.0, "federal_tax_withheld": 22000.0, "safe_harbor_required": 18000.0, "qualified_dividends": 78000.0, "realized_capital_gains": 42000.0},
            "2024": {"combined_w2_income": 0.0, "federal_tax_withheld": 23500.0, "safe_harbor_required": 21000.0, "qualified_dividends": 84000.0, "realized_capital_gains": 48000.0},
            "2025": {"combined_w2_income": 0.0, "federal_tax_withheld": 25000.0, "safe_harbor_required": 24500.0, "qualified_dividends": 88000.0, "realized_capital_gains": 54000.0}
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
            "name": "Roth Conversion Ladder ($80k/yr Bracket-Fill)",
            "category": "roth_conversion",
            "event_type": "duration",
            "icon": "evt-roth-ladder",
            "year": 2026,
            "end_year": 2036,
            "roth_strategy_preset": "auto_bracket_12",
            "max_annual_conversion": 80000.0,
            "annual_conversion": 80000.0,
            "marginal_tax_rate": 0.12,
            "amount": 80000.0,
            "annual_amount": 80000.0,
            "is_outflow": True,
            "funding_source": "taxable_brokerage",
            "description": "Systematic $80k/yr Traditional-to-Roth conversion filling the 12% federal bracket during zero-W-2 FIRE years while preserving ACA premium tax credits.",
        },
        {
            "id": "evt_aca_bridge_miller",
            "name": "Pre-65 ACA Healthcare Bridge (MAGI-Subsidized)",
            "category": "pre65_healthcare",
            "event_type": "duration",
            "icon": "evt-ltc-shield",
            "year": 2026,
            "end_year": 2038,
            "annual_premium": 24000.0,
            "annual_amount": 24000.0,
            "amount": 24000.0,
            "aca_subsidy_mode": "aca_magi",
            "is_outflow": True,
            "funding_source": "taxable_brokerage",
            "description": "Pre-Medicare ACA Silver plan bridge to age 65 with dynamic MAGI subsidy optimization alongside the $80k Roth conversion ladder.",
        },
    ]
    miller_scenarios = [
        {
            "id": "scen_baseline",
            "name": "FIRE Lifestyle Baseline",
            "description": "Current early-retired trajectory with $185k/yr living spend funded entirely from $6.5M liquid index portfolio and annual Roth conversion ladder.",
            "color": "#64748B",
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 50,
            "spouse_retirement_age": 50,
            "annual_living_spend": 185000.0,
            "annual_savings": 0.0,
            "equity_growth_preset": "moderate",
            "spending_guardrail_mode": "moderate",
            "event_ids": ["evt_family_gifting", "evt_roth_ladder_miller", "evt_aca_bridge_miller"],
        },
        {
            "id": "scen_miller_global_travel",
            "name": "Global Travel & Sabbatical Years",
            "description": "Elevates annual living and experiential travel spending from $185k to $240k/yr during the active early retirement decade (ages 52-65).",
            "color": "#1D4ED8",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_living_spend": 240000.0,
        },
        {
            "id": "scen_miller_islands_cabin",
            "name": "San Juan Islands Cabin & Travel",
            "description": "Branches from Global Travel plan to acquire a Puget Sound waterfront cabin ($2.5M in 2028) while sustaining elevated world travel.",
            "color": "#0284C7",
            "is_baseline": False,
            "parent_id": "scen_miller_global_travel",
            "added_event_ids": ["evt_vacation_home"],
        },
        {
            "id": "scen_miller_conservative_guardrail",
            "name": "Bear Market Spending Guardrail",
            "description": "Defensive FIRE guardrail: scales back annual spending to $145k/yr and models conservative 2.5% real growth to stress-test sequence-of-returns risk.",
            "color": "#059669",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_living_spend": 145000.0,
            "equity_growth_preset": "conservative",
            "spending_guardrail_mode": "aggressive",
            "drawdown_order": "pretax_first",
        },
    ]
    seed_family_scenarios(db_path, family_id, miller_scenarios, active_scenario_id="scen_baseline", custom_events=miller_custom_events)
    seed_family_tax_checklist_progress(db_path, family_id=family_id)

    # Historical Ribbon & Cash Flow series for continuous timeline (2018-2025)
    seed_family_historical_forecast(
        db_path=db_path,
        family_id=family_id,
        historical_ribbon=[
            {"year": 2018, "true_net_worth": 3100000.0, "is_historical": True},
            {"year": 2019, "true_net_worth": 3750000.0, "is_historical": True},
            {"year": 2020, "true_net_worth": 4450000.0, "is_historical": True},
            {"year": 2021, "true_net_worth": 5400000.0, "is_historical": True},
            {"year": 2022, "true_net_worth": 5100000.0, "is_historical": True},
            {"year": 2023, "true_net_worth": 5750000.0, "is_historical": True},
            {"year": 2024, "true_net_worth": 6200000.0, "is_historical": True},
            {"year": 2025, "true_net_worth": 6500000.0, "is_historical": True},
        ],
        historical_cash_flows=[
            {"year": 2018, "is_historical": True, "age_primary": 39, "age_spouse": 37, "household_salary": 440000.0, "salary_savings": 220000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 440000.0, "living_core": 110000.0, "travel_gogo": 30000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 150000.0, "net_cash_flow": 290000.0},
            {"year": 2019, "is_historical": True, "age_primary": 40, "age_spouse": 38, "household_salary": 470000.0, "salary_savings": 240000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 470000.0, "living_core": 115000.0, "travel_gogo": 35000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 160000.0, "net_cash_flow": 310000.0},
            {"year": 2020, "is_historical": True, "age_primary": 41, "age_spouse": 39, "household_salary": 490000.0, "salary_savings": 260000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 490000.0, "living_core": 100000.0, "travel_gogo": 15000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 125000.0, "net_cash_flow": 365000.0},
            {"year": 2021, "is_historical": True, "age_primary": 42, "age_spouse": 40, "household_salary": 520000.0, "salary_savings": 280000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 520000.0, "living_core": 120000.0, "travel_gogo": 25000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 155000.0, "net_cash_flow": 365000.0},
            {"year": 2022, "is_historical": True, "age_primary": 43, "age_spouse": 41, "household_salary": 550000.0, "salary_savings": 300000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 550000.0, "living_core": 125000.0, "travel_gogo": 30000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 165000.0, "net_cash_flow": 385000.0},
            {"year": 2023, "is_historical": True, "age_primary": 44, "age_spouse": 42, "household_salary": 480000.0, "salary_savings": 200000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 480000.0, "living_core": 130000.0, "travel_gogo": 40000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 180000.0, "net_cash_flow": 300000.0},
            {"year": 2024, "is_historical": True, "age_primary": 45, "age_spouse": 43, "household_salary": 0.0, "salary_savings": 0.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 0.0, "living_core": 140000.0, "travel_gogo": 50000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 200000.0, "net_cash_flow": -200000.0},
            {"year": 2025, "is_historical": True, "age_primary": 46, "age_spouse": 44, "household_salary": 0.0, "salary_savings": 0.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 0.0, "living_core": 145000.0, "travel_gogo": 55000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 0.0, "total_outflow": 210000.0, "net_cash_flow": -210000.0},
        ],
    )

    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)

    if verbose:
        print(f"[SUCCESS] The Miller Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_chen_family(db_path: Path, family_id: int = 3, verbose: bool = True) -> None:
    """Seeds The Chen Family (Series A Founder, NYC, ISO / AMT, Toddler 529 Superfunding)."""
    security.init_db(db_path)
    if verbose:
        print(f"[SEED] Populating The Chen Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, 'The Chen Family', ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, settings = excluded.settings, support_access_enabled = 1
        """, (family_id, json.dumps({
            "primary_state": "NY",
            "tax_filing_status": "MFJ",
            "city": "New York",
            "is_demo": True,
            "persona": "Startup Founder, ISO / AMT Planning, Tribeca Condo, Toddler 529"
        })))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'NY', 'MFJ', 310000.0, 140000.0, 50, 0.026, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "notes": "NYC resident (high local tax). Series A Founder with large unexercised ISO block.",
            "investment_policy": {
                "anchor_preset": "all_equity_90_10",
                "drift_tolerance": 0.07,
                "deviations_rationale": "Overweight concentrated company equity (ISO/NSO) and venture holdings from previous founding journey; minimal bond allocation (<5%) due to long time horizon and high risk appetite."
            },
            "estate_planning": {
                "apply_tcja_sunset": True,
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
            (family_id, emily_id, 2024, "Studio Gang Architects", 145000.0, 15000.0, 0.0, "Senior Architect"),
            (family_id, emily_id, 2025, "Studio Gang Architects", 155000.0, 20000.0, 0.0, "Associate Director"),
            (family_id, emily_id, 2026, "Studio Gang Architects", 165000.0, 20000.0, 0.0, "Current year salary"),
        ]
        conn.executemany("INSERT INTO compensation (family_id, user_id, tax_year, employer_name, base_salary, bonus, equity_spread, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", comp_records)

        # Equity: Multi-Company (Aether Robotics Inc. Series A + Veritas AI RSUs)
        conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (family_id,))
        cur = conn.execute("INSERT INTO equity_companies (family_id, company_name, ticker_or_private, current_fmv, fmv_date) VALUES (?, 'Aether Robotics Inc.', 'private', 8.50, '2025-10-01')", (family_id,))
        aether_id = cur.lastrowid

        cur2 = conn.execute("INSERT INTO equity_companies (family_id, company_name, ticker_or_private, current_fmv, fmv_date) VALUES (?, 'Veritas AI', 'private', 12.00, '2025-10-01')", (family_id,))
        veritas_id = cur2.lastrowid

        conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (family_id,))
        grants = [
            (aether_id, family_id, "Founder Common Stock (83b Filed)", "common", 0.001, 1500000.0, 1125000.0, 375000.0, 1500000.0, 0.001,
             json.dumps({"schedule": "4-year monthly, 1-year cliff", "cliff_months": 12}), "2023-01-01", "2027-01-01"),
            (aether_id, family_id, "Series Seed Incentive Stock Option (ISO)", "iso", 0.50, 150000.0, 100000.0, 50000.0, 0.0, 0.50,
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
            (aether_id, "2025-10-01", 8.50, 0, "Series A Round ($8.50)"),
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
        chen_tuition = [
            (family_id, leo_id, "2026-2027", "Tribeca Early Childhood (Nursery)", security.encrypt_field(28000.0), 1, "Tribeca toddler program (2s)"),
            (family_id, leo_id, "2027-2028", "Tribeca Montessori (Pre-K 3)", security.encrypt_field(32000.0), 1, "Pre-K 3 nursery school"),
            (family_id, leo_id, "2028-2029", "Tribeca Montessori (Pre-K 4)", security.encrypt_field(35000.0), 1, "Pre-K 4 program"),
            (family_id, leo_id, "2029-2030", "NYC Independent School (Kindergarten)", security.encrypt_field(54000.0), 1, "Kindergarten tuition"),
            (family_id, leo_id, "2030-2031", "NYC Independent School (1st Grade)", security.encrypt_field(56500.0), 1, "1st Grade elementary"),
            (family_id, leo_id, "2031-2032", "NYC Independent School (2nd Grade)", security.encrypt_field(59000.0), 1, "2nd Grade elementary"),
            (family_id, leo_id, "2042-2043", "Elite Private University (College Freshman)", security.encrypt_field(85000.0), 1, "Projected college freshman year (Superfunded 529)"),
            (family_id, leo_id, "2043-2044", "Elite Private University (College Sophomore)", security.encrypt_field(88000.0), 1, "Projected college sophomore year"),
            (family_id, leo_id, "2044-2045", "Elite Private University (College Junior)", security.encrypt_field(92000.0), 1, "Projected college junior year"),
            (family_id, leo_id, "2045-2046", "Elite Private University (College Senior)", security.encrypt_field(96000.0), 1, "Projected college senior year"),
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
        {"id": "acc_chen_ret_01", "name": "David Founder Solo 401(k)", "type": "investment", "subtype": "401k", "current_balance": 210000.0, "mask": "7710", "role": "retirement_tax_deferred"},
        {"id": "acc_chen_ret_02", "name": "Emily Studio 401(k)", "type": "investment", "subtype": "401k", "current_balance": 185000.0, "mask": "6620", "role": "retirement_tax_deferred"},
        {"id": "acc_chen_529_leo", "name": "NY 529 Direct Plan - Leo (Superfunded)", "type": "investment", "subtype": "529", "current_balance": 185000.0, "mask": "9901", "role": "education_529"},
        {"id": "acc_chen_re_01", "name": "Tribeca NYC Condo Loft", "type": "real_estate", "subtype": "home", "current_balance": 2150000.0, "mask": "NY01", "role": "real_estate"},
        {"id": "acc_chen_mort_01", "name": "Chase Jumbo Fixed Mortgage (3.125%)", "type": "loan", "subtype": "mortgage", "current_balance": -1250000.0, "mask": "4401", "role": "mortgage_liability"}
    ]
    normalize_and_save_accounts(db_path, chen_accounts, family_id=family_id, default_beneficiary_user_id=emily_id)

    chen_edu = [
        {"user_id": leo_id, "name": "Leo Chen", "first_name": "Leo", "birthdate": "2024-05-10", "birth_year": 2024, "college_start": 2042, "current_529_balance": 185000.0, "accounts": [{"name": "NY 529 Direct Plan - Leo (Superfunded)", "balance": 185000.0}]},
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
            "strategy": "venture",
            "vintage_year": 2024,
            "total_commitment": 150000.0,
            "paid_in_capital": 60000.0,
            "distributions": 0.0,
            "current_nav": 74000.0,
            "expected_term_years": 10,
            "notes": "Operator angel syndicate investing in seed-stage AI & robotics startups.",
        },
        {
            "id": "lp_chen_deeptech_seed_iv",
            "fund_name": "DeepTech Seed Fund IV, LP",
            "strategy": "venture",
            "vintage_year": 2025,
            "total_commitment": 100000.0,
            "paid_in_capital": 25000.0,
            "distributions": 0.0,
            "current_nav": 26500.0,
            "expected_term_years": 10,
            "notes": "LP allocation granted as a portfolio founder scout.",
        },
    ]
    security.db_save_encrypted(db_path, "lp_commitments", "private_markets", chen_lp_commitments, family_id=family_id)

    chen_transcripts = {
        "adults": ["Combined Household", "David Chen", "Emily Chen"],
        "safe_harbor_2026_target": 145000.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 370000.0, "federal_tax_withheld": 88000.0, "safe_harbor_required": 85000.0},
            "2025": {"combined_w2_income": 435000.0, "federal_tax_withheld": 115000.0, "safe_harbor_required": 126500.0}
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
    chen_scenarios = [
        {
            "id": "scen_baseline",
            "name": "Founder Baseline (Pre-IPO)",
            "description": "Current baseline with Series A CEO salary ($275k), Tribeca living expenses ($310k/yr), and unexercised stock options.",
            "color": "#64748B",
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 50,
            "spouse_retirement_age": 50,
            "annual_living_spend": 310000.0,
            "annual_savings": 140000.0,
            "equity_growth_preset": "moderate",
        },
        {
            "id": "scen_chen_secondary_tender",
            "name": "Series B Secondary Tender Offer ($500k)",
            "description": "Founder de-risks by selling $500k of common shares in an upcoming institutional secondary round in 2029, reallocating into taxable index funds.",
            "color": "#1D4ED8",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "added_event_ids": ["evt_capital_windfall"],
        },
        {
            "id": "scen_chen_suburban_home",
            "name": "Westchester Estate & Early Advisory (Age 48)",
            "description": "Branches from secondary tender: relocates from NYC to Westchester ($2.5M estate in 2028), shifts to angel investing/advising at age 48.",
            "color": "#0284C7",
            "is_baseline": False,
            "parent_id": "scen_chen_secondary_tender",
            "primary_retirement_age": 48,
            "spouse_retirement_age": 48,
            "annual_living_spend": 260000.0,
            "added_event_ids": ["evt_vacation_home"],
        },
        {
            "id": "scen_chen_delay_exit",
            "name": "Scale to Series C / Delayed Exit (Age 55)",
            "description": "David remains operating CEO through high-growth scale-up to age 55, increasing annual savings to $180k/yr before full liquidity event.",
            "color": "#059669",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 55,
            "spouse_retirement_age": 55,
            "annual_savings": 180000.0,
        },
    ]
    seed_family_scenarios(db_path, family_id, chen_scenarios, active_scenario_id="scen_baseline")

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
            {"year": 2018, "is_historical": True, "age_primary": 31, "age_spouse": 30, "household_salary": 340000.0, "salary_savings": 100000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 340000.0, "living_core": 160000.0, "travel_gogo": 25000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 250000.0, "net_cash_flow": 90000.0},
            {"year": 2019, "is_historical": True, "age_primary": 32, "age_spouse": 31, "household_salary": 380000.0, "salary_savings": 120000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 380000.0, "living_core": 175000.0, "travel_gogo": 30000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 270000.0, "net_cash_flow": 110000.0},
            {"year": 2020, "is_historical": True, "age_primary": 33, "age_spouse": 32, "household_salary": 410000.0, "salary_savings": 140000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 410000.0, "living_core": 165000.0, "travel_gogo": 15000.0, "gifting": 10000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 245000.0, "net_cash_flow": 165000.0},
            {"year": 2021, "is_historical": True, "age_primary": 34, "age_spouse": 33, "household_salary": 460000.0, "salary_savings": 160000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 460000.0, "living_core": 190000.0, "travel_gogo": 25000.0, "gifting": 15000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 285000.0, "net_cash_flow": 175000.0},
            {"year": 2022, "is_historical": True, "age_primary": 35, "age_spouse": 34, "household_salary": 510000.0, "salary_savings": 180000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 510000.0, "living_core": 210000.0, "travel_gogo": 30000.0, "gifting": 15000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 310000.0, "net_cash_flow": 200000.0},
            {"year": 2023, "is_historical": True, "age_primary": 36, "age_spouse": 35, "household_salary": 570000.0, "salary_savings": 200000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 570000.0, "living_core": 225000.0, "travel_gogo": 35000.0, "gifting": 15000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 330000.0, "net_cash_flow": 240000.0},
            {"year": 2024, "is_historical": True, "age_primary": 37, "age_spouse": 36, "household_salary": 620000.0, "salary_savings": 220000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 620000.0, "living_core": 240000.0, "travel_gogo": 40000.0, "gifting": 15000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 350000.0, "net_cash_flow": 270000.0},
            {"year": 2025, "is_historical": True, "age_primary": 38, "age_spouse": 37, "household_salary": 680000.0, "salary_savings": 240000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 680000.0, "living_core": 255000.0, "travel_gogo": 45000.0, "gifting": 15000.0, "events_outflow": 0.0, "mortgage_debt_service": 55000.0, "total_outflow": 370000.0, "net_cash_flow": 310000.0},
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)

    if verbose:
        print(f"[SUCCESS] The Chen Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_ramirez_family(db_path: Path, family_id: int = 4, verbose: bool = True) -> None:
    """
    Populates 'The Ramirez Family' (Austin, TX):
    - Middle-Class Working Household: Carlos Ramirez (Master Electrician) & Sofia Ramirez (High School Teacher)
    - 2 Children in Public School: Mateo (11, 6th grade) & Camila (8, 3rd grade)
    - Combined W-2 income: ~$150k. Modest home ($395k) with 3.375% mortgage.
    - Texas TRS 403(b), Roth IRA, Solo 401(k), Ally Emergency Fund ($24k).
    - Texas 529 College Savings for in-state public universities (UT Austin / Texas A&M).
    - No tech stock options.
    """
    security.init_db(db_path)
    if verbose:
        print(f"[SEED] Populating The Ramirez Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute("""
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, 'The Ramirez Family', ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, settings = excluded.settings, support_access_enabled = 1
        """, (family_id, json.dumps({
            "primary_state": "TX",
            "tax_filing_status": "MFJ",
            "city": "Austin",
            "is_demo": True,
            "persona": "High school teacher + master electrician, $150k HHI, home & auto loan, Texas 529s"
        })))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'TX', 'MFJ', 94000.0, 24000.0, 65, 0.028, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "notes": "Austin single-family home, Texas 0% state tax, Texas TRS pension + 403(b), Roth IRAs",
            "investment_policy": {
                "anchor_preset": "boglehead_80_20",
                "drift_tolerance": 0.05,
                "deviations_rationale": "100% passive index adherence across 403(b), 457(b), and Roth IRAs with total stock and total bond market funds. Zero speculative or private investments."
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
            (family_id, carlos_id, 2026, "Ramirez Electric LLC", 88000.0, 6000.0, 0.0, "Current contractor draw"),
            (family_id, sofia_id, 2022, "Austin Independent School District", 55000.0, 0.0, 0.0, "Biology Teacher"),
            (family_id, sofia_id, 2023, "Austin Independent School District", 57000.0, 0.0, 0.0, "Biology Teacher"),
            (family_id, sofia_id, 2024, "Austin Independent School District", 59000.0, 0.0, 0.0, "Science Dept Chair"),
            (family_id, sofia_id, 2025, "Austin Independent School District", 60500.0, 0.0, 0.0, "Science Dept Chair"),
            (family_id, sofia_id, 2026, "Austin Independent School District", 62000.0, 0.0, 0.0, "Current step salary"),
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
        ramirez_tuition = [
            # Mateo College (UT Austin / Texas A&M)
            (family_id, mateo_id, "2031-2032", "Texas Public University (Freshman)", security.encrypt_field(16500.0), 1, "UT Austin / Texas A&M tuition & fees (Texas 529)"),
            (family_id, mateo_id, "2032-2033", "Texas Public University (Sophomore)", security.encrypt_field(17200.0), 1, "Texas in-state tuition & room (Texas 529)"),
            (family_id, mateo_id, "2033-2034", "Texas Public University (Junior)", security.encrypt_field(18000.0), 1, "Texas in-state public tuition (Texas 529)"),
            (family_id, mateo_id, "2034-2035", "Texas Public University (Senior)", security.encrypt_field(18800.0), 1, "Senior year undergraduate (Texas 529)"),
            # Camila College
            (family_id, camila_id, "2035-2036", "Texas Public University (Freshman)", security.encrypt_field(18500.0), 1, "Texas in-state public university (Texas 529)"),
            (family_id, camila_id, "2036-2037", "Texas Public University (Sophomore)", security.encrypt_field(19300.0), 1, "Texas in-state tuition & room (Texas 529)"),
            (family_id, camila_id, "2037-2038", "Texas Public University (Junior)", security.encrypt_field(20100.0), 1, "Texas in-state public tuition (Texas 529)"),
            (family_id, camila_id, "2038-2039", "Texas Public University (Senior)", security.encrypt_field(21000.0), 1, "Senior year undergraduate (Texas 529)"),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ramirez_tuition)
        conn.commit()

    ramirez_accounts = [
        {"id": "acc_ramirez_chk", "name": "Chase Total Checking", "type": "depository", "subtype": "checking", "current_balance": 5800.0, "mask": "3140", "role": "cash_reserve"},
        {"id": "acc_ramirez_hysa", "name": "Ally High Yield Savings (Emergency Fund)", "type": "depository", "subtype": "savings", "current_balance": 24000.0, "mask": "8102", "role": "cash_reserve"},
        {"id": "acc_ramirez_403b", "name": "Sofia Texas TRS 403(b) (Vanguard 2055)", "type": "investment", "subtype": "403b", "current_balance": 52000.0, "mask": "6641", "role": "retirement_tax_deferred"},
        {"id": "acc_ramirez_ira", "name": "Carlos Schwab Traditional IRA", "type": "investment", "subtype": "ira", "current_balance": 30000.0, "mask": "7712", "role": "retirement_tax_deferred"},
        {"id": "acc_ramirez_roth", "name": "Carlos Schwab Roth IRA", "type": "investment", "subtype": "roth_ira", "current_balance": 16000.0, "mask": "8890", "role": "retirement_roth"},
        {"id": "acc_ramirez_529_mat", "name": "Texas College Savings Plan - Mateo", "type": "investment", "subtype": "529", "current_balance": 14500.0, "mask": "9011", "role": "education_529"},
        {"id": "acc_ramirez_529_cam", "name": "Texas College Savings Plan - Camila", "type": "investment", "subtype": "529", "current_balance": 9800.0, "mask": "9012", "role": "education_529"},
        {"id": "acc_ramirez_home", "name": "Round Rock Single-Family Home", "type": "real_estate", "subtype": "home", "current_balance": 395000.0, "mask": "TX01", "role": "real_estate"},
        {"id": "acc_ramirez_mort", "name": "Wells Fargo 30-Yr Fixed (3.375%)", "type": "loan", "subtype": "mortgage", "current_balance": -242000.0, "mask": "1140", "role": "mortgage_liability"},
        {"id": "acc_ramirez_auto", "name": "Toyota Financial Auto Loan (2021 RAV4)", "type": "loan", "subtype": "auto_loan", "current_balance": -11500.0, "mask": "5520", "role": "auto_loan"},
    ]
    normalize_and_save_accounts(db_path, ramirez_accounts, family_id=family_id, default_beneficiary_user_id=sofia_id)

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
        {"user_id": camila_id, "name": "Camila Ramirez", "first_name": "Camila", "birthdate": "2016-11-04", "birth_year": 2016, "college_start": 2034, "current_529_balance": 9800.0, "accounts": [{"name": "Texas College Savings Plan - Camila", "balance": 9800.0}]},
    ]
    security.db_save_encrypted(db_path, "children_education_reserves", "education", ramirez_edu, family_id=family_id)

    ramirez_transcripts = {
        "adults": ["Combined Household", "Carlos Ramirez", "Sofia Ramirez"],
        "safe_harbor_2026_target": 18500.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 141000.0, "federal_tax_withheld": 16200.0, "safe_harbor_required": 16000.0},
            "2025": {"combined_w2_income": 145500.0, "federal_tax_withheld": 17400.0, "safe_harbor_required": 17820.0}
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
            "year": 2034,
            "end_year": 2037,
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
            "name": "Pay Off Round Rock Mortgage ($242k)",
            "category": "debt_payoff",
            "event_type": "single_spike",
            "year": 2027,
            "end_year": 2027,
            "amount": 242000.0,
            "funding_source": "cash_flow",
            "annual_cashflow_saved": 14500.0,
            "description": "Lump-sum payoff of Round Rock mortgage loan, eliminating monthly debt service.",
        }
    ]
    ramirez_scenarios = [
        {
            "id": "scen_baseline",
            "name": "Everyday Family Baseline",
            "description": "Current trajectory with $150k HHI, Texas TRS pension accumulation, Round Rock home, and retirement at age 65.",
            "color": "#64748B",
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 65,
            "spouse_retirement_age": 65,
            "annual_living_spend": 94000.0,
            "annual_savings": 24000.0,
            "equity_growth_preset": "moderate",
            "event_ids": ["evt_college_mateo", "evt_college_camila", "evt_family_gifting"],
        },
        {
            "id": "scen_ramirez_early_retire_62",
            "name": "Retire at Age 62 (Mortgage-Free)",
            "description": "Pays off the Round Rock mortgage in 2027 ($242k), eliminating monthly debt service and enabling early retirement and Social Security at age 62.",
            "color": "#059669",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 62,
            "spouse_retirement_age": 62,
            "ss_claim_age": 62,
            "added_event_ids": ["evt_mortgage_payoff"],
        },
        {
            "id": "scen_ramirez_workshop_solar",
            "name": "Solar Efficiency & Reduced Overhead",
            "description": "Branches from Mortgage-Free 62 plan: leverages solar upgrades to dial living expenses down to $76k/yr for comfortable debt-free retirement.",
            "color": "#1D4ED8",
            "is_baseline": False,
            "parent_id": "scen_ramirez_early_retire_62",
            "annual_living_spend": 76000.0,
        },
        {
            "id": "scen_ramirez_boost_savings",
            "name": "Aggressive 403(b) & Roth Catch-Up (Age 67)",
            "description": "Max out age 50+ catch-up contributions ($32k/yr annual savings) and work to age 67 to maximize Social Security delayed retirement credits.",
            "color": "#0284C7",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 67,
            "spouse_retirement_age": 67,
            "ss_claim_age": 67,
            "annual_savings": 32000.0,
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
            {"year": 2018, "is_historical": True, "age_primary": 34, "age_spouse": 33, "household_salary": 118000.0, "salary_savings": 18000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 118000.0, "living_core": 78000.0, "travel_gogo": 6000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 104000.0, "net_cash_flow": 14000.0},
            {"year": 2019, "is_historical": True, "age_primary": 35, "age_spouse": 34, "household_salary": 124000.0, "salary_savings": 20000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 124000.0, "living_core": 82000.0, "travel_gogo": 7000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 109000.0, "net_cash_flow": 15000.0},
            {"year": 2020, "is_historical": True, "age_primary": 36, "age_spouse": 35, "household_salary": 128000.0, "salary_savings": 24000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 128000.0, "living_core": 80000.0, "travel_gogo": 4000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 104000.0, "net_cash_flow": 24000.0},
            {"year": 2021, "is_historical": True, "age_primary": 37, "age_spouse": 36, "household_salary": 135000.0, "salary_savings": 26000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 135000.0, "living_core": 86000.0, "travel_gogo": 6000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 112000.0, "net_cash_flow": 23000.0},
            {"year": 2022, "is_historical": True, "age_primary": 38, "age_spouse": 37, "household_salary": 140000.0, "salary_savings": 28000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 140000.0, "living_core": 90000.0, "travel_gogo": 7000.0, "gifting": 3000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 118000.0, "net_cash_flow": 22000.0},
            {"year": 2023, "is_historical": True, "age_primary": 39, "age_spouse": 38, "household_salary": 144000.0, "salary_savings": 30000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 144000.0, "living_core": 93000.0, "travel_gogo": 8000.0, "gifting": 3000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 122000.0, "net_cash_flow": 22000.0},
            {"year": 2024, "is_historical": True, "age_primary": 40, "age_spouse": 39, "household_salary": 148000.0, "salary_savings": 32000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 148000.0, "living_core": 96000.0, "travel_gogo": 8000.0, "gifting": 3000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 125000.0, "net_cash_flow": 23000.0},
            {"year": 2025, "is_historical": True, "age_primary": 41, "age_spouse": 40, "household_salary": 152000.0, "salary_savings": 34000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 152000.0, "living_core": 98000.0, "travel_gogo": 9000.0, "gifting": 3000.0, "events_outflow": 0.0, "mortgage_debt_service": 18000.0, "total_outflow": 128000.0, "net_cash_flow": 24000.0},
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)

    if verbose:
        print(f"[SUCCESS] The Ramirez Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_taylor_family(db_path: Path, family_id: int = 5, verbose: bool = True) -> None:
    """
    Populates 'The Taylor Family' (Columbus, OH):
    - Middle-Class Household: Marcus Taylor (Logistics Supervisor) & Danielle Taylor (RN)
    - 1 Child in Pre-K: Jordan (age 4)
    - Combined W-2 income: ~$126k. Modest home ($280k) with mortgage.
    - Federal student loans ($16.5k, $210/mo), building 401(k), 403(b), and Ohio 529.
    """
    security.init_db(db_path)
    if verbose:
        print(f"[SEED] Populating The Taylor Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute("""
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, 'The Taylor Family', ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, settings = excluded.settings, support_access_enabled = 1
        """, (family_id, json.dumps({
            "primary_state": "OH",
            "tax_filing_status": "MFJ",
            "city": "Columbus",
            "is_demo": True,
            "persona": "Registered nurse + warehouse supervisor, $126k HHI, student loans, building emergency fund & 401(k)"
        })))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'OH', 'MFJ', 88000.0, 15000.0, 65, 0.028, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "notes": "Columbus single-family home, Ohio state income tax (~2.75%), OhioHealth 403(b), student loan payoff plan",
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
            (family_id, danielle_id, 2022, "OhioHealth Riverside Methodist", 50000.0, 0.0, 0.0, "Staff Nurse (BSN)"),
            (family_id, danielle_id, 2023, "OhioHealth Riverside Methodist", 53000.0, 0.0, 0.0, "Staff Nurse (BSN)"),
            (family_id, danielle_id, 2024, "OhioHealth Riverside Methodist", 55000.0, 0.0, 0.0, "Charge Nurse"),
            (family_id, danielle_id, 2025, "OhioHealth Riverside Methodist", 56500.0, 0.0, 0.0, "Charge Nurse"),
            (family_id, danielle_id, 2026, "OhioHealth Riverside Methodist", 58000.0, 0.0, 0.0, "Current year salary"),
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
        taylor_tuition = [
            (family_id, jordan_id, "2038-2039", "Ohio State University (Freshman)", security.encrypt_field(19500.0), 1, "OSU in-state undergraduate tuition & fees (Ohio 529)"),
            (family_id, jordan_id, "2039-2040", "Ohio State University (Sophomore)", security.encrypt_field(20400.0), 1, "OSU in-state tuition & campus housing"),
            (family_id, jordan_id, "2040-2041", "Ohio State University (Junior)", security.encrypt_field(21300.0), 1, "OSU in-state undergraduate tuition"),
            (family_id, jordan_id, "2041-2042", "Ohio State University (Senior)", security.encrypt_field(22200.0), 1, "OSU senior year undergraduate"),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, taylor_tuition)
        conn.commit()

    taylor_accounts = [
        {"id": "acc_taylor_chk", "name": "Huntington Asterisk-Free Checking", "type": "depository", "subtype": "checking", "current_balance": 4200.0, "mask": "4421", "role": "cash_reserve"},
        {"id": "acc_taylor_hysa", "name": "Marcus & Danielle High Yield Savings", "type": "depository", "subtype": "savings", "current_balance": 14500.0, "mask": "7710", "role": "cash_reserve"},
        {"id": "acc_taylor_403b", "name": "Danielle OhioHealth 403(b) (Fidelity 500)", "type": "investment", "subtype": "403b", "current_balance": 42000.0, "mask": "5120", "role": "retirement_tax_deferred"},
        {"id": "acc_taylor_401k", "name": "Marcus FreightCorp 401(k) (Target 2055)", "type": "investment", "subtype": "401k", "current_balance": 36000.0, "mask": "8341", "role": "retirement_tax_deferred"},
        {"id": "acc_taylor_roth", "name": "Danielle Vanguard Roth IRA (VTI)", "type": "investment", "subtype": "roth_ira", "current_balance": 8500.0, "mask": "9930", "role": "retirement_roth"},
        {"id": "acc_taylor_529", "name": "Ohio CollegeAdvantage 529 - Jordan", "type": "investment", "subtype": "529", "current_balance": 8200.0, "mask": "2210", "role": "education_529"},
        {"id": "acc_taylor_home", "name": "Columbus Suburban 3-Bed Home", "type": "real_estate", "subtype": "home", "current_balance": 280000.0, "mask": "OH01", "role": "real_estate"},
        {"id": "acc_taylor_mort", "name": "Rocket Mortgage 30-Yr Fixed (4.25%)", "type": "loan", "subtype": "mortgage", "current_balance": -192000.0, "mask": "6612", "role": "mortgage_liability"},
        {"id": "acc_taylor_student", "name": "Nelnet Federal Student Loan (Danielle BSN)", "type": "loan", "subtype": "student_loan", "current_balance": -16500.0, "mask": "3340", "role": "student_loan_liability"},
    ]
    normalize_and_save_accounts(db_path, taylor_accounts, family_id=family_id, default_beneficiary_user_id=danielle_id)

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
        "safe_harbor_2026_target": 14200.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 119000.0, "federal_tax_withheld": 13200.0, "safe_harbor_required": 13000.0},
            "2025": {"combined_w2_income": 122500.0, "federal_tax_withheld": 13800.0, "safe_harbor_required": 14520.0}
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
                    {"organization": "Nationwide Children's Hospital Foundation", "amount": 500.0, "date": "2025-12-10", "description": "Pediatric care gift"}
                ]
            },
            "2026": {
                "total": 1000.0,
                "budget": 1000.0,
                "donations": [
                    {"organization": "Mid-Ohio Food Collective", "amount": 500.0, "date": "2026-11-15", "description": "Community food pantry"},
                    {"organization": "Nationwide Children's Hospital Foundation", "amount": 500.0, "date": "2026-12-10", "description": "Pediatric care gift"}
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
            "description": "Current trajectory with $126k HHI, student loan repayment ($210/mo), Ohio 529 for Jordan, and target retirement at age 65.",
            "color": "#64748B",
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 65,
            "spouse_retirement_age": 65,
            "annual_living_spend": 88000.0,
            "annual_savings": 15000.0,
            "equity_growth_preset": "moderate",
            "event_ids": ["evt_college_jordan", "evt_family_gifting"],
        },
        {
            "id": "scen_taylor_accelerate_debt",
            "name": "Accelerate Student Debt Elimination",
            "description": "Directs bonus compensation to pay off student loans by 2028, redirecting debt service into boosted 401(k)/403(b) savings ($22k/yr).",
            "color": "#1D4ED8",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_savings": 22000.0,
        },
        {
            "id": "scen_taylor_retire_63",
            "name": "Debt-Free Retirement at Age 63",
            "description": "Branches from Accelerated Debt Elimination: compounding debt-free retirement accounts enables retiring 2 years early at age 63.",
            "color": "#059669",
            "is_baseline": False,
            "parent_id": "scen_taylor_accelerate_debt",
            "primary_retirement_age": 63,
            "spouse_retirement_age": 63,
        },
        {
            "id": "scen_taylor_work_to_67",
            "name": "Full Career to Age 67 (Max Social Security)",
            "description": "Extends healthcare and logistics careers to full retirement age 67, capturing maximum hospital pension/403(b) match and delayed Social Security.",
            "color": "#D97706",
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
            {"year": 2018, "is_historical": True, "age_primary": 27, "age_spouse": 28, "household_salary": 92000.0, "salary_savings": 10000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 92000.0, "living_core": 68000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 87000.0, "net_cash_flow": 5000.0},
            {"year": 2019, "is_historical": True, "age_primary": 28, "age_spouse": 29, "household_salary": 98000.0, "salary_savings": 12000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 98000.0, "living_core": 71000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 90000.0, "net_cash_flow": 8000.0},
            {"year": 2020, "is_historical": True, "age_primary": 29, "age_spouse": 30, "household_salary": 104000.0, "salary_savings": 16000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 104000.0, "living_core": 70000.0, "travel_gogo": 2000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 87000.0, "net_cash_flow": 17000.0},
            {"year": 2021, "is_historical": True, "age_primary": 30, "age_spouse": 31, "household_salary": 112000.0, "salary_savings": 18000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 112000.0, "living_core": 75000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 94000.0, "net_cash_flow": 18000.0},
            {"year": 2022, "is_historical": True, "age_primary": 31, "age_spouse": 32, "household_salary": 118000.0, "salary_savings": 20000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 118000.0, "living_core": 79000.0, "travel_gogo": 5000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 99000.0, "net_cash_flow": 19000.0},
            {"year": 2023, "is_historical": True, "age_primary": 32, "age_spouse": 33, "household_salary": 122000.0, "salary_savings": 22000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 122000.0, "living_core": 82000.0, "travel_gogo": 5000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 102000.0, "net_cash_flow": 20000.0},
            {"year": 2024, "is_historical": True, "age_primary": 33, "age_spouse": 34, "household_salary": 125000.0, "salary_savings": 24000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 125000.0, "living_core": 85000.0, "travel_gogo": 5000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 105000.0, "net_cash_flow": 20000.0},
            {"year": 2025, "is_historical": True, "age_primary": 34, "age_spouse": 35, "household_salary": 128000.0, "salary_savings": 26000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 128000.0, "living_core": 87000.0, "travel_gogo": 6000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 14000.0, "total_outflow": 108000.0, "net_cash_flow": 20000.0},
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)

    if verbose:
        print(f"[SUCCESS] The Taylor Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_foster_family(db_path: Path, family_id: int = 6, verbose: bool = True) -> None:
    """
    Populates 'The Foster Family' (Denver, CO):
    - Single-Parent Household: Jessica Foster (Pediatric Physical Therapist) & Noah Foster (Son, age 12)
    - Zero Spouse (has_spouse = False)
    - W-2 income: ~$115k at Children's Hospital Colorado. Head of Household (HOH) tax status.
    - Denver bungalow ($540k) with 3.75% mortgage, 403(b), Roth IRA, Colorado 529, emergency savings.
    """
    security.init_db(db_path)
    if verbose:
        print(f"[SEED] Populating The Foster Family into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute("""
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, 'The Foster Family', ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, settings = excluded.settings, support_access_enabled = 1
        """, (family_id, json.dumps({
            "primary_state": "CO",
            "tax_filing_status": "HOH",
            "city": "Denver",
            "is_demo": True,
            "persona": "Solo pediatric physical therapist & single mom, $115k W-2, Head of Household, Colorado 529, 403(b) & Roth IRA"
        })))

        conn.execute("""
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate, assumptions_json
            ) VALUES (?, 'CO', 'HOH', 78000.0, 18500.0, 62, 0.025, 0.045, ?)
            ON CONFLICT(family_id) DO UPDATE SET
                state = excluded.state, filing_status = excluded.filing_status,
                annual_spending = excluded.annual_spending, annual_savings = excluded.annual_savings,
                retirement_age = excluded.retirement_age, inflation_rate = excluded.inflation_rate,
                real_growth_rate = excluded.real_growth_rate, assumptions_json = excluded.assumptions_json
        """, (family_id, json.dumps({
            "notes": "Denver bungalow, Colorado flat state tax (4.4%), Children's Hospital Colorado 403(b), single-parent household",
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
            (family_id, jessica_id, 2022, "Children's Hospital Colorado", 98000.0, 2000.0, 0.0, "Pediatric Physical Therapist"),
            (family_id, jessica_id, 2023, "Children's Hospital Colorado", 102000.0, 2500.0, 0.0, "Pediatric Physical Therapist"),
            (family_id, jessica_id, 2024, "Children's Hospital Colorado", 106000.0, 3000.0, 0.0, "Senior Physical Therapist"),
            (family_id, jessica_id, 2025, "Children's Hospital Colorado", 110000.0, 3500.0, 0.0, "Senior Physical Therapist"),
            (family_id, jessica_id, 2026, "Children's Hospital Colorado", 115000.0, 4000.0, 0.0, "Current year salary"),
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
        foster_tuition = [
            (family_id, noah_id, "2032-2033", "CU Boulder (Freshman)", security.encrypt_field(18500.0), 1, "Colorado in-state public tuition & fees (DirectPortfolio 529)"),
            (family_id, noah_id, "2033-2034", "CU Boulder (Sophomore)", security.encrypt_field(19400.0), 1, "CU Boulder in-state tuition & residence hall"),
            (family_id, noah_id, "2034-2035", "CU Boulder (Junior)", security.encrypt_field(20300.0), 1, "CU Boulder in-state undergraduate tuition"),
            (family_id, noah_id, "2035-2036", "CU Boulder (Senior)", security.encrypt_field(21200.0), 1, "CU Boulder senior year undergraduate"),
        ]
        conn.executemany("""
            INSERT INTO tuition (family_id, child_user_id, school_year, school_name, tuition_amount, is_projected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, foster_tuition)
        conn.commit()

    foster_accounts = [
        {"id": "acc_foster_chk", "name": "FirstBank Colorado Checking", "type": "depository", "subtype": "checking", "current_balance": 8450.0, "mask": "2281", "role": "cash_reserve"},
        {"id": "acc_foster_hysa", "name": "Ally Bank High Yield Savings (Emergency)", "type": "depository", "subtype": "savings", "current_balance": 28500.0, "mask": "7134", "role": "cash_reserve"},
        {"id": "acc_foster_403b", "name": "Children's Hospital 403(b) (Index 2050)", "type": "investment", "subtype": "403b", "current_balance": 142000.0, "mask": "4810", "role": "retirement_tax_deferred"},
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
        "safe_harbor_2026_target": 15200.0,
        "historical_summary": {
            "2024": {"combined_w2_income": 109000.0, "federal_tax_withheld": 14200.0, "safe_harbor_required": 14000.0},
            "2025": {"combined_w2_income": 113500.0, "federal_tax_withheld": 15000.0, "safe_harbor_required": 15400.0}
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
                    {"organization": "Children's Hospital Colorado Foundation", "amount": 600.0, "date": "2025-11-25", "description": "Pediatric therapy patient assistance fund"},
                    {"organization": "Denver Rescue Mission", "amount": 400.0, "date": "2025-12-18", "description": "Holiday meals and shelter"}
                ]
            },
            "2026": {
                "total": 1000.0,
                "budget": 1000.0,
                "donations": [
                    {"organization": "Children's Hospital Colorado Foundation", "amount": 600.0, "date": "2026-11-25", "description": "Pediatric therapy patient assistance fund"},
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
            "description": "Solo parent trajectory with $115k W-2, Denver Wash Park home, Colorado 529 for Noah, and planned retirement at age 62.",
            "color": "#64748B",
            "is_baseline": True,
            "parent_id": None,
            "primary_retirement_age": 62,
            "annual_living_spend": 78000.0,
            "annual_savings": 18500.0,
            "equity_growth_preset": "moderate",
            "event_ids": ["evt_college_noah", "evt_family_gifting"],
        },
        {
            "id": "scen_foster_work_to_67",
            "name": "Work to Age 67 (Max Solo Social Security)",
            "description": "Extends clinical practice to age 67 to maximize solo Social Security benefits (no spousal fallback) and compound 403(b) balances.",
            "color": "#1D4ED8",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "primary_retirement_age": 67,
            "ss_claim_age": 67,
        },
        {
            "id": "scen_foster_independent_clinic",
            "name": "Private Pediatric Clinic Expansion",
            "description": "Establishes an independent pediatric physical therapy clinic, growing net income and boosting annual savings to $26k/yr.",
            "color": "#059669",
            "is_baseline": False,
            "parent_id": "scen_baseline",
            "annual_savings": 26000.0,
        },
        {
            "id": "scen_foster_clinic_early_retire",
            "name": "Private Practice Early Exit (Age 60)",
            "description": "Branches from Clinic Expansion: sells practice equity at age 60 to fund early retirement with bridge living spend until age 62 Social Security.",
            "color": "#0284C7",
            "is_baseline": False,
            "parent_id": "scen_foster_independent_clinic",
            "primary_retirement_age": 60,
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
            {"year": 2018, "is_historical": True, "age_primary": 32, "age_spouse": 0, "household_salary": 88000.0, "salary_savings": 12000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 88000.0, "living_core": 56000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 77000.0, "net_cash_flow": 11000.0},
            {"year": 2019, "is_historical": True, "age_primary": 33, "age_spouse": 0, "household_salary": 93000.0, "salary_savings": 14000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 93000.0, "living_core": 59000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 80000.0, "net_cash_flow": 13000.0},
            {"year": 2020, "is_historical": True, "age_primary": 34, "age_spouse": 0, "household_salary": 96000.0, "salary_savings": 16000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 96000.0, "living_core": 58000.0, "travel_gogo": 2000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 77000.0, "net_cash_flow": 19000.0},
            {"year": 2021, "is_historical": True, "age_primary": 35, "age_spouse": 0, "household_salary": 102000.0, "salary_savings": 18000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 102000.0, "living_core": 63000.0, "travel_gogo": 4000.0, "gifting": 1000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 84000.0, "net_cash_flow": 18000.0},
            {"year": 2022, "is_historical": True, "age_primary": 36, "age_spouse": 0, "household_salary": 106000.0, "salary_savings": 20000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 106000.0, "living_core": 66000.0, "travel_gogo": 5000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 89000.0, "net_cash_flow": 17000.0},
            {"year": 2023, "is_historical": True, "age_primary": 37, "age_spouse": 0, "household_salary": 110000.0, "salary_savings": 22000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 110000.0, "living_core": 69000.0, "travel_gogo": 5000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 92000.0, "net_cash_flow": 18000.0},
            {"year": 2024, "is_historical": True, "age_primary": 38, "age_spouse": 0, "household_salary": 113000.0, "salary_savings": 23000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 113000.0, "living_core": 71000.0, "travel_gogo": 5000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 94000.0, "net_cash_flow": 19000.0},
            {"year": 2025, "is_historical": True, "age_primary": 39, "age_spouse": 0, "household_salary": 116000.0, "salary_savings": 24000.0, "social_security": 0.0, "event_inflows": 0.0, "total_inflow": 116000.0, "living_core": 73000.0, "travel_gogo": 6000.0, "gifting": 2000.0, "events_outflow": 0.0, "mortgage_debt_service": 16000.0, "total_outflow": 97000.0, "net_cash_flow": 19000.0},
        ],
    )

    seed_family_tax_checklist_progress(db_path=db_path, family_id=family_id)
    seed_demo_advisor_conversations(db_path=db_path, family_id=family_id)

    if verbose:
        print(f"[SUCCESS] The Foster Family successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_empty_family(db_path: Path, family_id: int = 7, verbose: bool = True) -> None:
    """Seeds a fresh, blank tenant (0 members, 0 accounts, 0 grants) for onboarding verification."""
    security.init_db(db_path)
    if verbose:
        print(f"[SEED] Populating Blank Tenant into {db_path.name} (family_id={family_id})...")

    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            INSERT INTO families (family_id, name, settings, support_access_enabled)
            VALUES (?, 'New Household (Blank)', ?, 1)
            ON CONFLICT(family_id) DO UPDATE SET name = excluded.name, settings = excluded.settings, support_access_enabled = 1
        """, (family_id, json.dumps({
            "primary_state": "WA",
            "tax_filing_status": "MFJ",
            "is_demo": True,
            "persona": "Brand New Household (Zero Records Onboarding State)"
        })))

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
            "color": "#94A3B8",
            "equity_growth_preset": "moderate",
            "is_baseline": True,
            "parent_id": None,
        }
    ], active_scenario_id="scen_baseline")

    if verbose:
        print(f"[SUCCESS] Blank Tenant successfully seeded into {db_path.name} (family_id={family_id})!")


def seed_all_demo_families(db_path: Path, verbose: bool = True) -> None:
    """Seeds all 7 demo personas into the specified database."""
    seed_jones_family(db_path, family_id=1, verbose=verbose)
    seed_miller_family(db_path, family_id=2, verbose=verbose)
    seed_chen_family(db_path, family_id=3, verbose=verbose)
    seed_ramirez_family(db_path, family_id=4, verbose=verbose)
    seed_taylor_family(db_path, family_id=5, verbose=verbose)
    seed_foster_family(db_path, family_id=6, verbose=verbose)
    seed_empty_family(db_path, family_id=7, verbose=verbose)
    try:
        from scripts.migrate_to_family_dbs import migrate_database
        uni = "demo" if ("demo" in str(db_path) or "beta" in str(db_path)) else ("test" if "test" in str(db_path) else ("sandbox" if "sandbox" in str(db_path) else "public"))
        migrate_database(db_path, universe=uni, verbose=verbose)
    except Exception as exc:
        if verbose:
            print(f"[NOTICE] Family database synchronization: {exc}")
    if verbose:
        print(f"[COMPLETE] All 7 Demo Personas successfully seeded into {db_path.name}!")


def main():
    parser = argparse.ArgumentParser(description="Seed demo families for HVL Family Office.")
    parser.add_argument("--universe", default="demo", choices=["demo", "beta", "test"], help="Target database universe (default: demo)")
    parser.add_argument("--family_id", type=int, default=None, help="Specific family ID to seed (1: Jones, 2: Miller, 3: Chen, 4: Ramirez, 5: Taylor, 6: Foster, 7: Blank). Default: All")
    args = parser.parse_args()

    universe = "demo" if args.universe == "beta" else args.universe
    db_path = config.get_db_path_for_universe(universe)
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

    try:
        from scripts.migrate_to_family_dbs import migrate_database
        migrate_database(db_path, universe=universe, verbose=True)
    except Exception as exc:
        print(f"[NOTICE] Family database synchronization: {exc}")


if __name__ == "__main__":
    main()

