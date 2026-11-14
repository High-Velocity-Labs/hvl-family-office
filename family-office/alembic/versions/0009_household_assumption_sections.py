"""Planning assumptions as one encrypted row per section; deletion quarantine as plain columns on `families`.

`household_profile.assumptions_json` held every planning section (estate planning, investment policy, pension,
mortgage, ...) in one plain-text JSON object, read and rewritten whole for each section saved.
`household_assumption_sections` keeps one row per (family, section) with the value encrypted under the household key.
The legacy sections move into the table the first time a process opens the database
(`db.household_assumptions.move_legacy_assumptions`, which needs the household key), and the legacy column is cleared
then.

The 30-day deletion quarantine lived as three keys inside `families.settings`; they become the `deletion_*` columns,
and this migration moves the keys out of the settings JSON.

Revision ID: 0009_household_assumption_sections
Revises: 0008_guardrail_mode_and_philanthropy_settings
Create Date: 2026-11-14 01:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_household_assumption_sections"
down_revision: Union[str, None] = "0008_guardrail_mode_and_philanthropy_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS household_assumption_sections (
        	family_id INTEGER NOT NULL,
        	section_key TEXT NOT NULL,
        	value_enc TEXT,
        	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        	PRIMARY KEY (family_id, section_key),
        	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
        )
        """
    )
    existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(families)").fetchall()}
    if "deletion_scheduled_at" not in existing:
        bind.exec_driver_sql("ALTER TABLE families ADD COLUMN deletion_scheduled_at TEXT")
    if "deletion_purge_after" not in existing:
        bind.exec_driver_sql("ALTER TABLE families ADD COLUMN deletion_purge_after TEXT")
    if "deletion_requested_by" not in existing:
        bind.exec_driver_sql("ALTER TABLE families ADD COLUMN deletion_requested_by TEXT")
    bind.exec_driver_sql(
        """
        UPDATE families SET
            deletion_scheduled_at = json_extract(settings, '$.deletion_scheduled_at'),
            deletion_purge_after = json_extract(settings, '$.deletion_purge_after'),
            deletion_requested_by = json_extract(settings, '$.deletion_requested_by'),
            settings = json_remove(
                settings, '$.deletion_scheduled_at', '$.deletion_purge_after', '$.deletion_requested_by'
            )
        WHERE settings IS NOT NULL AND json_valid(settings)
          AND json_type(settings) = 'object'
          AND (json_type(settings, '$.deletion_scheduled_at') IS NOT NULL
               OR json_type(settings, '$.deletion_purge_after') IS NOT NULL
               OR json_type(settings, '$.deletion_requested_by') IS NOT NULL)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        UPDATE families SET settings = json_set(
            CASE WHEN settings IS NOT NULL AND json_valid(settings) THEN settings ELSE '{}' END,
            '$.deletion_scheduled_at', deletion_scheduled_at,
            '$.deletion_purge_after', deletion_purge_after,
            '$.deletion_requested_by', deletion_requested_by
        )
        WHERE deletion_scheduled_at IS NOT NULL
        """
    )
    bind.exec_driver_sql("ALTER TABLE families DROP COLUMN deletion_scheduled_at")
    bind.exec_driver_sql("ALTER TABLE families DROP COLUMN deletion_purge_after")
    bind.exec_driver_sql("ALTER TABLE families DROP COLUMN deletion_requested_by")
    # Sections already moved out of `assumptions_json` stay encrypted rows; this drops them with the table.
    bind.exec_driver_sql("DROP TABLE IF EXISTS household_assumption_sections")
