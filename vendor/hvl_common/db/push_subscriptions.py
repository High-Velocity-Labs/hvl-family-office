"""
Shared Layer 1 SQLAlchemy 2.0 ORM Mixins, Model Factory, Session Adapter,
and W3C Web Push Subscription Repository (`hvl_common.db.push_subscriptions`).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import ForeignKey, Integer, Text, delete, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from hvl_common.db.types import EncryptedString
from hvl_common.security.sanitize import sanitize_text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_tenant_id(household_id: int = 0, family_id: int = 0) -> int:
    eff = int(household_id or family_id or 0)
    return eff if eff > 0 else 0


class HvlNotificationMixin:
    """Reusable SQLAlchemy 2.0 declarative mixin for `household_notifications`."""

    __tablename__ = "household_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    household_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, default=0, server_default=text("0")
    )
    recipient_email: Mapped[str] = mapped_column(
        Text, nullable=False, default="*", server_default=text("'*'")
    )
    sender_email: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    sender_name: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    category: Mapped[str] = mapped_column(
        Text, nullable=False, default="general", server_default=text("'general'")
    )
    dedupe_key: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    conversation_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    title: Mapped[str] = mapped_column(EncryptedString(default=""), nullable=False, default="")
    body: Mapped[str] = mapped_column(EncryptedString(default=""), nullable=False, default="")
    deep_link: Mapped[str] = mapped_column(
        Text, nullable=False, default="/", server_default=text("'/'")
    )
    channel: Mapped[str] = mapped_column(
        Text, nullable=False, default="in_app", server_default=text("'in_app'")
    )
    is_read: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    @property
    def family_id(self) -> int:
        return int(self.household_id or 0)

    @family_id.setter
    def family_id(self, value: int) -> None:
        self.household_id = int(value or 0)

    def to_dict(self) -> dict[str, Any]:
        hid = int(self.household_id or 0)
        return {
            "id": self.id,
            "household_id": hid,
            "family_id": hid,
            "recipient_email": self.recipient_email or "*",
            "sender_email": self.sender_email or "",
            "sender_name": self.sender_name or "",
            "category": self.category or "general",
            "dedupe_key": self.dedupe_key or "",
            "conversation_id": self.conversation_id or "",
            "title": self.title or "",
            "body": self.body or "",
            "deep_link": self.deep_link or "/",
            "channel": self.channel or "in_app",
            "is_read": int(self.is_read or 0),
            "created_at": self.created_at or "",
        }


class HvlPushSubscriptionMixin:
    """Reusable SQLAlchemy 2.0 declarative mixin for `push_subscriptions`."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    household_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, default=0, server_default=text("0")
    )
    member_email: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    auth: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    device_label: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    @property
    def family_id(self) -> int:
        return int(self.household_id or 0)

    @family_id.setter
    def family_id(self, value: int) -> None:
        self.household_id = int(value or 0)

    def to_dict(self) -> dict[str, Any]:
        hid = int(self.household_id or 0)
        return {
            "id": self.id,
            "household_id": hid,
            "family_id": hid,
            "member_email": self.member_email or "",
            "endpoint": self.endpoint or "",
            "p256dh": self.p256dh or "",
            "auth": self.auth or "",
            "device_label": self.device_label or "",
            "created_at": self.created_at or "",
        }


class NotificationBase(DeclarativeBase):
    """Standalone declarative base when models are not bound to an app-specific Base."""


_MODEL_REGISTRY: dict[tuple[Any, ...], tuple[type, type]] = {}
_ACTIVE_MODELS: dict[str, Any] = {}


def create_notification_models(
    base_cls: type = NotificationBase,
    tenant_fk: str | None = None,
    tenant_col_name: str = "household_id",
) -> tuple[type, type]:
    """Binds `HouseholdNotification` and `PushSubscription` onto `base_cls`."""
    cache_key = (base_cls, tenant_fk, tenant_col_name)
    if cache_key in _MODEL_REGISTRY:
        models = _MODEL_REGISTRY[cache_key]
        _ACTIVE_MODELS["notif"], _ACTIVE_MODELS["push"] = models
        return models

    notif_attrs: dict[str, Any] = {"__tablename__": "household_notifications", "__annotations__": {}}
    push_attrs: dict[str, Any] = {"__tablename__": "push_subscriptions", "__annotations__": {}}
    if tenant_fk:
        fk_col = lambda: mapped_column(  # noqa: E731
            Integer,
            ForeignKey(tenant_fk, ondelete="CASCADE"),
            index=True,
            nullable=False,
            default=0,
            server_default=text("0"),
        )
        notif_attrs["__annotations__"]["household_id"] = Mapped[int]
        notif_attrs["household_id"] = fk_col()
        push_attrs["__annotations__"]["household_id"] = Mapped[int]
        push_attrs["household_id"] = fk_col()

    notif_cls = type("HouseholdNotification", (HvlNotificationMixin, base_cls), notif_attrs)
    push_cls = type("PushSubscription", (HvlPushSubscriptionMixin, base_cls), push_attrs)
    _MODEL_REGISTRY[cache_key] = (notif_cls, push_cls)
    _ACTIVE_MODELS["notif"] = notif_cls
    _ACTIVE_MODELS["push"] = push_cls
    return notif_cls, push_cls


HouseholdNotification, PushSubscription = create_notification_models(NotificationBase)


@contextmanager
def _open_session(
    session_scope_fn: Any,
    db_path: Any,
    eff_id: int,
    *,
    member_email: str = "",
    commit: bool = False,
    invalidate_cache: bool = True,
) -> Iterator[Session]:
    """Adapts a SQLAlchemy `Session` or a session context-manager callable across HVL apps."""
    if isinstance(session_scope_fn, Session):
        yield session_scope_fn
        if commit:
            session_scope_fn.flush()
        return

    sig = inspect.signature(session_scope_fn)
    params = sig.parameters
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    kwargs: dict[str, Any] = {}
    if "household_id" in params or has_var_kw:
        kwargs["household_id"] = eff_id
    elif "family_id" in params:
        kwargs["family_id"] = eff_id
    if ("member_email" in params or has_var_kw) and member_email:
        kwargs["member_email"] = member_email
    if "commit" in params or has_var_kw:
        kwargs["commit"] = commit
    if "invalidate_cache" in params or has_var_kw:
        kwargs["invalidate_cache"] = invalidate_cache

    pos_params = [
        p for p in params.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if pos_params and pos_params[0].name in ("db_path", "path"):
        ctx = session_scope_fn(db_path, **kwargs)
    else:
        if "db_path" in params:
            kwargs["db_path"] = db_path
        ctx = session_scope_fn(**kwargs)

    with ctx as session:
        yield session


def save_push_subscription(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    member_email: str = "",
    endpoint: str = "",
    p256dh: str = "",
    auth: str = "",
    device_label: str = "",
    db_path: Path | str | None = None,
    push_model: Any = None,
) -> dict[str, Any]:
    """Saves or updates a W3C Web Push subscription endpoint for a household member."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    if eff_id <= 0:
        return {}
    clean_endpoint = sanitize_text(endpoint, max_length=2048, default="")
    if not clean_endpoint:
        raise ValueError("Subscription endpoint must not be empty.")
    clean_email = sanitize_text(member_email, max_length=254, default="").lower()
    clean_p256dh = sanitize_text(p256dh, max_length=512, default="")
    clean_auth = sanitize_text(auth, max_length=512, default="")
    clean_label = sanitize_text(device_label, max_length=120, default="")
    model = push_model or _ACTIVE_MODELS.get("push") or PushSubscription
    now_iso = _utc_now_iso()

    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, commit=True
    ) as session:
        existing = session.scalars(select(model).where(model.endpoint == clean_endpoint)).first()
        if existing is not None:
            existing.household_id = eff_id
            existing.member_email = clean_email
            existing.p256dh = clean_p256dh
            existing.auth = clean_auth
            existing.device_label = clean_label
            existing.created_at = now_iso
            sub = existing
        else:
            sub = model(
                household_id=eff_id,
                member_email=clean_email,
                endpoint=clean_endpoint,
                p256dh=clean_p256dh,
                auth=clean_auth,
                device_label=clean_label,
                created_at=now_iso,
            )
            session.add(sub)
        session.flush()
        session.refresh(sub)
        return sub.to_dict()


def delete_push_subscription(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    member_email: str = "",
    endpoint: str = "",
    db_path: Path | str | None = None,
    push_model: Any = None,
) -> bool:
    """Removes a push subscription endpoint for a member."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    clean_email = sanitize_text(member_email, max_length=254, default="").lower()
    clean_endpoint = sanitize_text(endpoint, max_length=2048, default="")
    if eff_id <= 0 or not clean_endpoint:
        return False
    model = push_model or _ACTIVE_MODELS.get("push") or PushSubscription

    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, commit=True
    ) as session:
        stmt = delete(model).where(model.endpoint == clean_endpoint)
        if clean_email:
            stmt = stmt.where(func.lower(model.member_email) == clean_email)
        res = session.execute(stmt)
        return int(res.rowcount or 0) > 0


def get_member_push_subscriptions(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    member_email: str = "",
    db_path: Path | str | None = None,
    push_model: Any = None,
) -> list[dict[str, Any]]:
    """Returns all push subscriptions for a household member."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    clean_email = sanitize_text(member_email, max_length=254, default="").lower()
    if eff_id <= 0 or not clean_email:
        return []
    model = push_model or _ACTIVE_MODELS.get("push") or PushSubscription

    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, invalidate_cache=False
    ) as session:
        rows = session.scalars(
            select(model)
            .where(
                model.household_id == eff_id,
                func.lower(model.member_email) == clean_email,
            )
            .order_by(model.id.desc())
        ).all()
        return [r.to_dict() for r in rows]
