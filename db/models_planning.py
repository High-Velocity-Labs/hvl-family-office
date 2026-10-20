"""
Planning, tax, forecasting, estate, and AI advisor SQLAlchemy models.
Extracted from db/models.py for modularity.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models_core import Base
from db.types import EncryptedFloat, EncryptedJSON, EncryptedString


class EstateProfile(Base):
    __tablename__ = "estate_profiles"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    state_of_residence: Mapped[str] = mapped_column(Text, nullable=False, default="WA")
    marital_status: Mapped[str] = mapped_column(Text, nullable=False, default="married_joint")
    prior_lifetime_taxable_gifts_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    dsue_ported_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    charitable_bequest_pct_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    charitable_bequest_fixed_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    ilit_death_benefit_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    trust_transferred_assets_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    estimated_probate_admin_pct_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.015), nullable=False, default=0.015
    )
    apply_2026_tcja_sunset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = (
            dict(self.payload_enc) if isinstance(self.payload_enc, dict) else {}
        )
        out["state_of_residence"] = str(
            self.state_of_residence or out.get("state_of_residence") or "WA"
        )
        out["marital_status"] = str(
            self.marital_status or out.get("marital_status") or "married_joint"
        )
        out["apply_2026_tcja_sunset"] = bool(self.apply_2026_tcja_sunset)
        out["charitable_bequest_pct"] = float(self.charitable_bequest_pct_enc or 0.0)
        return out


class TaxTranscriptRecord(Base):
    __tablename__ = "tax_transcript_records"

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    record_type: Mapped[str] = mapped_column(Text, nullable=False, default="summary")
    taxpayer_name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    w2_wages_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    federal_tax_withheld_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    social_security_withheld_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    medicare_tax_withheld_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    mortgage_interest_paid_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    qualified_dividends_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    realized_capital_gains_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    safe_harbor_target_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class TaxTranscriptMeta(Base):
    __tablename__ = "tax_transcript_meta"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    adults_enc: Mapped[Any] = mapped_column(
        EncryptedJSON(default_type="none"), nullable=False, default=""
    )
    available_years_enc: Mapped[Any] = mapped_column(
        EncryptedJSON(default_type="none"), nullable=False, default=""
    )
    latest_tax_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    safe_harbor_2026_target_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class ForecastSettings(Base):
    __tablename__ = "forecast_settings"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    active_scenario_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="baseline"
    )
    comparison_scenario_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class ForecastScenario(Base):
    __tablename__ = "forecast_scenarios"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    scenario_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    description_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    is_baseline: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str] = mapped_column(Text, nullable=False, default="#3b82f6")
    overrides_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    @property
    def spending_guardrail_mode(self) -> str:
        if isinstance(self.payload_enc, dict):
            return str(self.payload_enc.get("spending_guardrail_mode") or "off")
        return "off"


class ForecastEvent(Base):
    __tablename__ = "forecast_events"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(Text, nullable=False, default="baseline")
    name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False, default="expense")
    amount_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    start_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    end_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class PhilanthropyBudget(Base):
    __tablename__ = "philanthropy_budgets"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    tax_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_amount_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class PhilanthropyDonation(Base):
    __tablename__ = "philanthropy_donations"

    donation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    donation_date: Mapped[str] = mapped_column(Text, nullable=False, default="")
    organization_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    amount_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    description_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class AdvisorConversation(Base):
    __tablename__ = "advisor_conversations"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    page_section: Mapped[str] = mapped_column(
        Text, nullable=False, default="section-overview"
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_pinned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    messages: Mapped[List["AdvisorMessage"]] = relationship(
        "AdvisorMessage",
        back_populates="conversation",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AdvisorMessage.message_id",
    )


class AdvisorMessage(Base):
    __tablename__ = "advisor_messages"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("advisor_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    conversation: Mapped[Optional["AdvisorConversation"]] = relationship(
        "AdvisorConversation", back_populates="messages"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content or "",
            "created_at": self.created_at,
        }
