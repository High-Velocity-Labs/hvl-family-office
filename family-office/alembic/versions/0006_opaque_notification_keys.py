"""Replaces notification dedupe keys that carried a name or an email with an opaque per-row key.

`household_notifications.dedupe_key` is stored in the clear (lookups match it in SQL). Keys used to embed a grant
nickname (`collab:equity:<nickname>`), an adult's name (`job:upload_failed:<name>`, `job:w2:<year>:<name>`,
`job:transcript:<year>:<name>`) or a member's email (`invite:accepted:<email>`). New keys use IDs instead; rows written
before that get `legacy:<notification_id>`, which keeps each notification and its read state but drops the text. The
title and body stay as they are (encrypted columns).

Revision ID: 0006_opaque_notification_keys
Revises: 0005_drop_siri_mcp_tokens
Create Date: 2026-10-30 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_opaque_notification_keys"
down_revision: Union[str, None] = "0005_drop_siri_mcp_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old key prefix, prefix of the ID-based keys that replaced it)
_NAMED_KEY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("collab:equity:", "collab:equity:grant:"),
    ("job:upload_failed:", "job:upload_failed:member:"),
    ("invite:accepted:", "invite:accepted:user:"),
)


def upgrade() -> None:
    bind = op.get_bind()
    has_table = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'household_notifications'"
    ).fetchone()
    if not has_table:
        return
    for old_prefix, new_prefix in _NAMED_KEY_PREFIXES:
        bind.exec_driver_sql(
            "UPDATE household_notifications SET dedupe_key = 'legacy:' || id "
            "WHERE dedupe_key LIKE ? AND dedupe_key NOT LIKE ?",
            (old_prefix + "%", new_prefix + "%"),
        )
    # `job:w2:<year>:<name>` / `job:transcript:<year>:<name>`; the new form is `job:w2:<year>:member:<id>`.
    bind.exec_driver_sql(
        "UPDATE household_notifications SET dedupe_key = 'legacy:' || id "
        "WHERE (dedupe_key LIKE 'job:w2:%' OR dedupe_key LIKE 'job:transcript:%') "
        "AND dedupe_key NOT LIKE '%:member:%'"
    )


def downgrade() -> None:
    """The replaced text is gone by design; there is nothing to restore."""
