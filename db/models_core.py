"""
Core Declarative SQLAlchemy 2.0 ORM Models for HVL Family Office.
Defines Base and core household, user, account, and directory models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from db.types import EncryptedFloat, EncryptedJSON, EncryptedString


class Base(DeclarativeBase):
    pass


class Family(Base):
    __tablename__ = "families"

    family_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(EncryptedString(default="Family Office"), nullable=False, default="")
    settings: Mapped[Optional[str]] = mapped_column(
        Text, default='{"primary_state": "WA", "tax_filing_status": "MFJ"}'
    )
    encryption_key_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    support_access_enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="family",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    household_profile: Mapped[Optional["HouseholdProfile"]] = relationship(
        "HouseholdProfile",
        back_populates="family",
        lazy="selectin",
        uselist=False,
        cascade="all, delete-orphan",
    )


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(EncryptedString(default=""), nullable=False, default="")
    email: Mapped[Optional[str]] = mapped_column(EncryptedString(default=""), nullable=True, default="")
    email_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    birthdate: Mapped[Optional[str]] = mapped_column(EncryptedString(default=""), nullable=True, default="")
    relationship_type: Mapped[str] = mapped_column(
        "relationship", Text, nullable=False, default="primary"
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, default="viewer")
    pending_fek_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_vault_synced: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    family: Mapped[Optional["Family"]] = relationship("Family", back_populates="users")
    tuition_entries: Mapped[List["TuitionRecord"]] = relationship(
        "TuitionRecord",
        back_populates="child",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "family_id": self.family_id,
            "name": self.name or "",
            "email": self.email or "",
            "email_hash": self.email_hash or "",
            "birthdate": self.birthdate or "",
            "relationship": self.relationship_type or "child",
            "role": self.role or "viewer",
            "google_vault_synced": bool(self.google_vault_synced),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class HouseholdProfile(Base):
    __tablename__ = "household_profile"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="WA")
    filing_status: Mapped[str] = mapped_column(Text, nullable=False, default="MFJ")
    annual_spending: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    annual_savings: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    retirement_age: Mapped[Optional[int]] = mapped_column(Integer, default=65)
    inflation_rate: Mapped[Optional[float]] = mapped_column(Float, default=0.025)
    real_growth_rate: Mapped[Optional[float]] = mapped_column(Float, default=0.045)
    assumptions_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    family: Mapped[Optional["Family"]] = relationship(
        "Family", back_populates="household_profile"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "filing_status": self.filing_status,
            "annual_spending": self.annual_spending,
            "annual_savings": self.annual_savings,
            "retirement_age": self.retirement_age,
            "inflation_rate": self.inflation_rate,
            "assumptions_json": self.assumptions_json,
        }


class AccountRole(Base):
    __tablename__ = "account_roles"
    __table_args__ = (UniqueConstraint("family_id", "monarch_account_id"),)

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    monarch_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    beneficiary_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    is_user_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_hidden_from_family_office: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role_id": self.role_id,
            "monarch_account_id": self.monarch_account_id,
            "role": self.role,
            "beneficiary_user_id": self.beneficiary_user_id,
            "is_user_confirmed": self.is_user_confirmed,
            "is_hidden_from_family_office": self.is_hidden_from_family_office,
        }


class MonarchAccount(Base):
    __tablename__ = "monarch_accounts"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    current_balance_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    account_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subtype: Mapped[str] = mapped_column(Text, nullable=False, default="")
    institution_name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    is_manual: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    include_in_net_worth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_hidden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    def to_dict(self) -> Dict[str, Any]:
        acc: Dict[str, Any] = (
            dict(self.payload_enc) if isinstance(self.payload_enc, dict) else {}
        )
        acc_id_str = str(self.account_id)
        acc["id"] = acc_id_str
        if self.display_name_enc:
            acc["displayName"] = self.display_name_enc
        acc["currentBalance"] = float(self.current_balance_enc or 0.0)
        include_flag = bool(self.include_in_net_worth)
        acc["includeInNetWorth"] = include_flag
        acc["includeBalanceInNetWorth"] = include_flag
        acc["isHidden"] = bool(self.is_hidden)
        acc["isManual"] = bool(self.is_manual)
        if "type" not in acc or not isinstance(acc.get("type"), dict):
            acc["type"] = {"name": self.account_type or ""}
        if "subtype" not in acc or not isinstance(acc.get("subtype"), dict):
            acc["subtype"] = {"name": self.subtype or ""}
        if self.institution_name_enc:
            if "institution" not in acc or not isinstance(acc.get("institution"), dict):
                acc["institution"] = {"name": self.institution_name_enc}
            if "credential" not in acc or not isinstance(acc.get("credential"), dict):
                acc["credential"] = {"displayName": self.institution_name_enc}
        raw_prov = str(acc.get("provider") or "").lower()
        if acc_id_str.startswith("manual_") or raw_prov == "manual":
            prov, source_label = "manual", "Manual"
        elif acc_id_str.startswith("sfin_") or raw_prov == "simplefin":
            prov, source_label = "simplefin", "SimpleFIN"
        else:
            prov, source_label = "monarch", "Monarch Money"
        acc["provider"] = prov
        acc["source_label"] = source_label
        return acc


class MonarchHolding(Base):
    __tablename__ = "monarch_holdings"

    holding_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    ticker_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    security_name_enc: Mapped[str] = mapped_column(
        EncryptedString(default=""), nullable=False, default=""
    )
    quantity_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    total_value_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    basis_enc: Mapped[float] = mapped_column(
        EncryptedFloat(default=0.0), nullable=False, default=0.0
    )
    payload_enc: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON(default_type="dict"), nullable=False, default=dict
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class FamilyEncryptedStore(Base):
    __tablename__ = "family_encrypted_store"

    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)


class FamilyStateVersion(Base):
    __tablename__ = "family_state_versions"

    family_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


class InviteToken(Base):
    __tablename__ = "invite_tokens"

    invite_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_by_family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("families.family_id", ondelete="CASCADE"), nullable=False
    )
    created_by_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    invite_type: Mapped[str] = mapped_column(Text, nullable=False, default="new_household")
    target_role: Mapped[str] = mapped_column(Text, nullable=False, default="editor")
    label: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invite_id": self.invite_id,
            "code": self.code,
            "created_by_family_id": self.created_by_family_id,
            "created_by_email": self.created_by_email or "",
            "invite_type": self.invite_type or "new_household",
            "target_role": self.target_role or "editor",
            "label": self.label or "",
            "max_uses": int(self.max_uses or 1),
            "uses_count": int(self.uses_count or 0),
            "expires_at": self.expires_at or "",
            "revoked": bool(self.revoked),
            "created_at": self.created_at or "",
        }
