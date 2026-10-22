"""
Declarative SQLAlchemy 2.0 ORM Models for HVL Family Office.

All sensitive PII and financial columns use `EncryptedString`, `EncryptedFloat`, or
`EncryptedJSON` `TypeDecorator` classes from `db.types` so encryption at rest and type
conversion happen automatically at the column definition level.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models_core import (
    AccountRole,
    Base,
    Family,
    FamilyEncryptedStore,
    FamilyStateVersion,
    HouseholdProfile,
    InviteToken,
    MonarchAccount,
    MonarchHolding,
    User,
)
from db.models_planning import (
    AdvisorConversation,
    AdvisorMessage,
    EstateProfile,
    ForecastEvent,
    ForecastScenario,
    ForecastSettings,
    PhilanthropyBudget,
    PhilanthropyDonation,
    TaxTranscriptMeta,
    TaxTranscriptRecord,
)
from db.models_ops import (
    BugReport,
    DownloadEvent,
    PortalTelemetryEvent,
    SandboxLease,
)
from db.types import EncryptedFloat, EncryptedJSON, EncryptedString


class EquityCompany(Base):
    __tablename__ = "equity_companies"

    company_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    company_name: Mapped[str] = mapped_column(
        EncryptedString(default="Company"), nullable=False, default=""
    )
    ticker_or_private: Mapped[str] = mapped_column(Text, nullable=False, default="private")
    current_fmv: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    fmv_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    grants: Mapped[List["EquityGrantRecord"]] = relationship(
        "EquityGrantRecord",
        back_populates="company",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="EquityGrantRecord.grant_id",
    )
    fmv_history: Mapped[List["FmvHistoryRecord"]] = relationship(
        "FmvHistoryRecord",
        back_populates="company",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FmvHistoryRecord.valuation_date",
    )


class EquityGrantRecord(Base):
    __tablename__ = "equity_grants"

    grant_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equity_companies.company_id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    grant_label: Mapped[str] = mapped_column(Text, nullable=False)
    grant_type: Mapped[str] = mapped_column(Text, nullable=False, default="nso")
    strike_price: Mapped[float] = mapped_column(EncryptedFloat(default=0.0), nullable=False, default=0.0)
    shares_granted: Mapped[float] = mapped_column(EncryptedFloat(default=0.0), nullable=False, default=0.0)
    shares_vested: Mapped[float] = mapped_column(EncryptedFloat(default=0.0), nullable=False, default=0.0)
    shares_unvested: Mapped[float] = mapped_column(EncryptedFloat(default=0.0), nullable=False, default=0.0)
    shares_exercised: Mapped[float] = mapped_column(EncryptedFloat(default=0.0), nullable=False, default=0.0)
    cost_basis: Mapped[float] = mapped_column(EncryptedFloat(default=0.0), nullable=False, default=0.0)
    vesting_schedule_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    grant_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fully_vested_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    company: Mapped[Optional["EquityCompany"]] = relationship(
        "EquityCompany", back_populates="grants", lazy="selectin"
    )


class FmvHistoryRecord(Base):
    __tablename__ = "fmv_history"

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equity_companies.company_id", ondelete="CASCADE"), nullable=False
    )
    valuation_date: Mapped[str] = mapped_column(Text, nullable=False)
    share_price: Mapped[float] = mapped_column(Float, nullable=False)
    is_projected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    company: Mapped[Optional["EquityCompany"]] = relationship(
        "EquityCompany", back_populates="fmv_history"
    )


class CompensationRecord(Base):
    __tablename__ = "compensation"

    comp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    employer_name: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    base_salary: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    bonus: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    equity_spread: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    def to_dict(self) -> Dict[str, Any]:
        sal = float(self.base_salary or 0.0)
        bon = float(self.bonus or 0.0)
        return {
            "comp_id": self.comp_id,
            "family_id": self.family_id,
            "user_id": self.user_id,
            "year": self.tax_year,
            "company": self.employer_name or "",
            "salary": sal,
            "bonus": bon,
            "total_compensation": round(sal + bon, 2),
            "source": self.notes or "",
        }


class TuitionRecord(Base):
    __tablename__ = "tuition"

    tuition_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    child_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True
    )
    school_year: Mapped[str] = mapped_column(Text, nullable=False)
    school_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tuition_amount: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    is_projected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    child: Mapped[Optional["User"]] = relationship("User", back_populates="tuition_entries")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tuition_id": self.tuition_id,
            "child_user_id": self.child_user_id,
            "school_year": self.school_year,
            "school_name": self.school_name or "",
            "amount": round(float(self.tuition_amount or 0.0), 2),
            "is_projected": bool(self.is_projected),
            "notes": self.notes or "",
        }


class TuitionYearRecord(Base):
    __tablename__ = "tuition_year_records"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)
    school_name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    total_amount_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    is_projected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    def to_dict(self) -> Dict[str, Any]:
        rec: Dict[str, Any] = (
            dict(self.payload_enc) if isinstance(self.payload_enc, dict) else {}
        )
        rec["school_year"] = str(self.school_year)
        if self.school_name_enc:
            rec["school"] = str(self.school_name_enc)
        rec["total"] = float(self.total_amount_enc or 0.0)
        rec["is_projected"] = bool(self.is_projected)
        if self.notes_enc:
            rec["notes"] = str(self.notes_enc)
        return rec


class GiftRecipient(Base):
    __tablename__ = "gift_recipients"

    recipient_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    recipient_group_name: Mapped[str] = mapped_column(Text, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    relationship_type: Mapped[Optional[str]] = mapped_column(
        "relationship", Text, nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    gifts: Mapped[List["AnnualGift"]] = relationship(
        "AnnualGift",
        back_populates="recipient",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recipient_id": self.recipient_id,
            "recipient_group_name": self.recipient_group_name,
            "member_count": int(self.member_count or 1),
            "relationship": self.relationship_type or "",
            "notes": self.notes or "",
        }


class AnnualGift(Base):
    __tablename__ = "gifts"

    gift_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("gift_recipients.recipient_id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    recipient: Mapped[Optional["GiftRecipient"]] = relationship(
        "GiftRecipient", back_populates="gifts", lazy="selectin"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gift_id": self.gift_id,
            "recipient_id": self.recipient_id,
            "recipient_name": self.recipient.recipient_group_name if self.recipient else "",
            "year": self.year,
            "amount": round(float(self.amount or 0.0), 2),
            "notes": self.notes or "",
        }


__all__ = [
    "Base",
    "Family",
    "User",
    "HouseholdProfile",
    "AccountRole",
    "MonarchAccount",
    "MonarchHolding",
    "FamilyEncryptedStore",
    "FamilyStateVersion",
    "InviteToken",
    "EquityCompany",
    "EquityGrantRecord",
    "FmvHistoryRecord",
    "CompensationRecord",
    "TuitionRecord",
    "TuitionYearRecord",
    "GiftRecipient",
    "AnnualGift",
    "EstateProfile",
    "TaxTranscriptRecord",
    "TaxTranscriptMeta",
    "ForecastSettings",
    "ForecastScenario",
    "ForecastEvent",
    "PhilanthropyBudget",
    "PhilanthropyDonation",
    "AdvisorConversation",
    "AdvisorMessage",
    "BugReport",
    "SandboxLease",
    "DownloadEvent",
    "PortalTelemetryEvent",
]
