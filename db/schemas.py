"""
Typed request and data schemas for Family Office models.
Provides lightweight validation for API payloads, bounding inputs and preventing invalid types.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass(frozen=True)
class CompensationRecordSchema:
    year: int
    company: str
    salary: float = 0.0
    bonus: float = 0.0
    source: str = "Manual Entry"
    user_id: Optional[int] = None
    original_year: Optional[int] = None
    original_company: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CompensationRecordSchema:
        yr = int(data.get("year", 2026))
        sal = float(data.get("salary", 0.0) or 0.0)
        bon = float(data.get("bonus", 0.0) or 0.0)
        company = str(data.get("company", "")).strip()
        source = str(data.get("source", "Manual Entry")).strip()
        uid = None
        if data.get("user_id") is not None:
            try:
                uid = int(data["user_id"])
            except (ValueError, TypeError):
                uid = None
        orig_yr = None
        if data.get("original_year") is not None:
            try:
                orig_yr = int(data["original_year"])
            except (ValueError, TypeError):
                orig_yr = None

        return cls(
            year=yr,
            company=company,
            salary=max(0.0, sal),
            bonus=max(0.0, bon),
            source=source,
            user_id=uid,
            original_year=orig_yr,
            original_company=str(data.get("original_company", "")).strip(),
        )


@dataclass(frozen=True)
class GiftRecordSchema:
    recipient_id: int
    year: int
    amount: float
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GiftRecordSchema:
        rec_id = int(data.get("recipient_id", 0))
        yr = int(data.get("year", 2026))
        amt = float(data.get("amount", 0.0) or 0.0)
        notes = str(data.get("notes", "")).strip()
        return cls(
            recipient_id=rec_id,
            year=yr,
            amount=max(0.0, amt),
            notes=notes,
        )


@dataclass(frozen=True)
class HouseholdProfileSchema:
    state: str = "WA"
    filing_status: str = "MFJ"
    annual_spending: float = 0.0
    annual_savings: float = 0.0
    retirement_age: int = 65
    inflation_rate: float = 0.025

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HouseholdProfileSchema:
        return cls(
            state=str(data.get("state", "WA")).strip().upper()[:2],
            filing_status=str(data.get("filing_status", "MFJ")).strip().upper(),
            annual_spending=max(0.0, float(data.get("annual_spending", 0.0) or 0.0)),
            annual_savings=max(0.0, float(data.get("annual_savings", 0.0) or 0.0)),
            retirement_age=max(30, min(90, int(data.get("retirement_age", 65) or 65))),
            inflation_rate=max(0.0, min(0.20, float(data.get("inflation_rate", 0.025) or 0.025))),
        )


@dataclass(frozen=True)
class OptionExerciseEstimateSchema:
    shares_to_exercise: float
    strike_price: Optional[float] = None
    share_price: Optional[float] = None
    grant_type: str = "nso"
    include_wa_millionaire_tax: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OptionExerciseEstimateSchema:
        shares = float(data.get("shares_to_exercise", 0.0) or 0.0)
        strike = float(data["strike_price"]) if data.get("strike_price") is not None else None
        price = float(data["share_price"]) if data.get("share_price") is not None else None
        gtype = str(data.get("grant_type", "nso")).strip().lower()
        wa_tax = bool(data.get("include_wa_millionaire_tax", False))
        return cls(
            shares_to_exercise=max(0.0, shares),
            strike_price=strike,
            share_price=price,
            grant_type=gtype,
            include_wa_millionaire_tax=wa_tax,
        )


@dataclass(frozen=True)
class ScenarioAssumptionSchema:
    spending_guardrail_mode: str = "off"

    @classmethod
    def sanitize_guardrail_mode(cls, mode: Any) -> str:
        val = str(mode or "off").lower().strip()
        return val if val in ("off", "moderate", "aggressive") else "off"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScenarioAssumptionSchema:
        return cls(
            spending_guardrail_mode=cls.sanitize_guardrail_mode(data.get("spending_guardrail_mode"))
        )


BUG_REPORTS_DDL = """
CREATE TABLE IF NOT EXISTS bug_reports (
    bug_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL DEFAULT 'finances',
    app_version TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    universe TEXT NOT NULL DEFAULT 'public',
    family_id INTEGER NOT NULL DEFAULT 0,
    user_role TEXT NOT NULL DEFAULT 'viewer',
    user_ref TEXT DEFAULT '',
    support_access_enabled INTEGER DEFAULT 0,
    pane TEXT NOT NULL DEFAULT 'overview',
    category TEXT NOT NULL DEFAULT 'math',
    scrubbed_description TEXT NOT NULL DEFAULT '',
    scrubbed_followup TEXT DEFAULT '',
    ai_explanation TEXT DEFAULT '',
    suspected_module TEXT DEFAULT '',
    invariant_summary TEXT DEFAULT '',
    scale_factor REAL DEFAULT 1.0,
    anonymization_mode TEXT DEFAULT 'scaled',
    sanitized_snapshot_json TEXT DEFAULT '{}',
    admin_notes TEXT DEFAULT ''
)
"""

SANDBOX_LEASES_DDL = """
CREATE TABLE IF NOT EXISTS sandbox_leases (
    family_id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    extended_7d INTEGER DEFAULT 0,
    seed_mode TEXT DEFAULT 'blank',
    session_hash TEXT DEFAULT ''
)
"""

DOWNLOAD_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS download_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    app_version TEXT DEFAULT '',
    referrer TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

PORTAL_TELEMETRY_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS portal_telemetry_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    universe TEXT NOT NULL,
    event_type TEXT NOT NULL,
    feature_key TEXT DEFAULT '',
    session_hash TEXT DEFAULT '',
    meta_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    tab TEXT DEFAULT '',
    action TEXT DEFAULT '',
    modal TEXT DEFAULT ''
)
"""
