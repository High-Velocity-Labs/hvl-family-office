"""Operational tables that used to be created outside Alembic.

Folds `ensure_init_db_tables` (invite_tokens, download_events, family_id_allocator, notifications) and
`db.conversations.ensure_conversation_tables` into the revision chain. Every statement is `IF NOT EXISTS`, so
databases that already have these tables (created by those helpers) are unchanged.

Revision ID: 0003_operational_tables
Revises: 0002_google_vault_escrow
Create Date: 2026-10-29 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_operational_tables"
down_revision: Union[str, None] = "0002_google_vault_escrow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OPERATIONAL_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS download_events (
    	event_id INTEGER NOT NULL,
    	target TEXT NOT NULL,
    	app_version TEXT DEFAULT '',
    	referrer TEXT DEFAULT '',
    	user_agent TEXT DEFAULT '',
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS family_id_allocator (
    	family_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    	allocated_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS household_notifications (
    	id INTEGER NOT NULL,
    	household_id INTEGER DEFAULT 0 NOT NULL,
    	recipient_email TEXT DEFAULT '*' NOT NULL,
    	sender_email TEXT DEFAULT '' NOT NULL,
    	sender_name TEXT DEFAULT '' NOT NULL,
    	category TEXT DEFAULT 'general' NOT NULL,
    	dedupe_key TEXT DEFAULT '' NOT NULL,
    	conversation_id TEXT DEFAULT '' NOT NULL,
    	title TEXT NOT NULL,
    	body TEXT NOT NULL,
    	deep_link TEXT DEFAULT '/' NOT NULL,
    	channel TEXT DEFAULT 'in_app' NOT NULL,
    	is_read INTEGER DEFAULT 0 NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_household_notifications_household_id ON household_notifications (household_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS push_subscriptions (
    	id INTEGER NOT NULL,
    	household_id INTEGER DEFAULT 0 NOT NULL,
    	member_email TEXT DEFAULT '' NOT NULL,
    	endpoint TEXT NOT NULL,
    	p256dh TEXT DEFAULT '' NOT NULL,
    	auth TEXT DEFAULT '' NOT NULL,
    	device_label TEXT DEFAULT '' NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (id),
    	UNIQUE (endpoint)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_push_subscriptions_household_id ON push_subscriptions (household_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS advisor_conversations (
    	conversation_id VARCHAR NOT NULL,
    	family_id INTEGER NOT NULL,
    	page_section TEXT NOT NULL,
    	title TEXT NOT NULL,
    	created_by TEXT,
    	is_pinned INTEGER NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (conversation_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invite_tokens (
    	invite_id INTEGER NOT NULL,
    	code TEXT NOT NULL,
    	created_by_family_id INTEGER NOT NULL,
    	created_by_email TEXT,
    	invite_type TEXT NOT NULL,
    	target_role TEXT NOT NULL,
    	label TEXT,
    	max_uses INTEGER NOT NULL,
    	uses_count INTEGER NOT NULL,
    	expires_at TEXT NOT NULL,
    	revoked INTEGER NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (invite_id),
    	UNIQUE (code),
    	FOREIGN KEY(created_by_family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS advisor_messages (
    	message_id INTEGER NOT NULL,
    	conversation_id VARCHAR NOT NULL,
    	family_id INTEGER NOT NULL,
    	role TEXT NOT NULL,
    	content TEXT NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (message_id),
    	FOREIGN KEY(conversation_id) REFERENCES advisor_conversations (conversation_id) ON DELETE CASCADE,
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        for statement in _OPERATIONAL_DDL:
            bind.exec_driver_sql(statement)
    finally:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    """Operational tables hold live data; the downgrade intentionally leaves them in place."""
