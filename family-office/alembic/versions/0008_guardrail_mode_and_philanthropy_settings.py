"""Forecast guardrail mode as its own column; philanthropy ledger totals in their own table.

`forecast_scenarios.spending_guardrail_mode` was read from inside the encrypted `payload_enc` JSON. It is a state,
so it gets a plain column ("inherit" takes the parent scenario's mode; NULL marks a row not moved yet).
`philanthropy_budgets` held a JSON settings blob (lifetime total, lifetime history, per-year totals) in
`budget_amount_enc` on a fake `tax_year = -1` row; those move to `philanthropy_settings`, one row per household.
Both values are encrypted on disk, so moving existing data needs the household key: `db.column_backfill` does it the
first time a process opens the database.

One-way in practice: once the data has moved, the previous release reads every guardrail mode as "off" and empty
philanthropy totals, and `downgrade()` drops the moved totals. Roll forward, not back.

Revision ID: 0008_guardrail_mode_and_philanthropy_settings
Revises: 0007_account_balance_snapshots
Create Date: 2026-11-14 01:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_guardrail_mode_and_philanthropy_settings"
down_revision: Union[str, None] = "0007_account_balance_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _scenario_columns(bind) -> set[str]:
    return {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(forecast_scenarios)")}


def upgrade() -> None:
    bind = op.get_bind()
    # A global directory DB has no forecast_scenarios table (PRAGMA then lists no columns): nothing to alter there.
    columns = _scenario_columns(bind)
    if columns and "spending_guardrail_mode" not in columns:
        bind.exec_driver_sql("ALTER TABLE forecast_scenarios ADD COLUMN spending_guardrail_mode TEXT")
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS philanthropy_settings (
        	family_id INTEGER NOT NULL,
        	total_lifetime_charity_enc TEXT NOT NULL,
        	lifetime_history_enc TEXT NOT NULL,
        	year_totals_enc TEXT NOT NULL,
        	updated_at TEXT DEFAULT (CURRENT_TIMESTAMP),
        	PRIMARY KEY (family_id),
        	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TABLE IF EXISTS philanthropy_settings")
    if "spending_guardrail_mode" in _scenario_columns(bind):
        bind.exec_driver_sql("ALTER TABLE forecast_scenarios DROP COLUMN spending_guardrail_mode")
