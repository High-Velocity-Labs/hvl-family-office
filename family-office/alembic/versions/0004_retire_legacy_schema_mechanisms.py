"""Folds the last schema mechanisms into the revision chain: the legacy `migrations/*.sql` runner and `ensure_init_db_tables`.

- Indexes the `.sql` files created (the tables themselves are in 0001/0003, 0001 now running the `.sql` schema first); every
  statement is `IF NOT EXISTS`.
- `family_domain_versions`, which `db.domain_versions` created on first use.
- `family_encrypted_store` rows with `family_id <= 0` (written by the single-tenant era; `ensure_init_db_tables`
  deleted them on every start) are removed once here.
- A database whose single-tenant `encrypted_store` still has rows keeps them and is logged, as `ensure_init_db_tables`
  did; nothing is assigned to a household.

Revision ID: 0004_retire_legacy_schema_mechanisms
Revises: 0003_operational_tables
Create Date: 2026-10-29 03:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_retire_legacy_schema_mechanisms"
down_revision: Union[str, None] = "0003_operational_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users (family_id, email_hash)",
    "CREATE INDEX IF NOT EXISTS idx_adv_conv_fam ON advisor_conversations(family_id, page_section, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_adv_conv_pinned ON advisor_conversations(family_id, is_pinned DESC, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_adv_msg_conv ON advisor_messages(conversation_id, created_at ASC)",
    "CREATE INDEX IF NOT EXISTS idx_users_family_relationship ON users (family_id, relationship)",
    "CREATE INDEX IF NOT EXISTS idx_equity_companies_family ON equity_companies (family_id, company_id ASC)",
    "CREATE INDEX IF NOT EXISTS idx_equity_grants_family_company ON equity_grants (family_id, company_id, grant_id ASC)",
    "CREATE INDEX IF NOT EXISTS idx_fmv_history_company_date ON fmv_history (company_id, valuation_date ASC)",
    "CREATE INDEX IF NOT EXISTS idx_account_roles_family ON account_roles (family_id, monarch_account_id)",
    "CREATE INDEX IF NOT EXISTS idx_compensation_family_year ON compensation (family_id, tax_year DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tuition_family_child_year ON tuition (family_id, child_user_id, school_year ASC)",
    "CREATE INDEX IF NOT EXISTS idx_gift_recipients_family ON gift_recipients (family_id, recipient_group_name ASC)",
    "CREATE INDEX IF NOT EXISTS idx_gifts_family_year ON gifts (family_id, year DESC, recipient_id)",
    "CREATE INDEX IF NOT EXISTS idx_monarch_accounts_family ON monarch_accounts(family_id)",
    "CREATE INDEX IF NOT EXISTS idx_monarch_holdings_family_acc ON monarch_holdings(family_id, account_id)",
    "CREATE INDEX IF NOT EXISTS idx_tax_transcript_records_family ON tax_transcript_records(family_id, tax_year)",
    "CREATE INDEX IF NOT EXISTS idx_tuition_year_records_family ON tuition_year_records(family_id)",
    "CREATE INDEX IF NOT EXISTS idx_forecast_scenarios_family ON forecast_scenarios(family_id)",
    "CREATE INDEX IF NOT EXISTS idx_forecast_events_family_scen ON forecast_events(family_id, scenario_id)",
    "CREATE INDEX IF NOT EXISTS idx_philanthropy_donations_family_yr ON philanthropy_donations(family_id, tax_year)",
)

_DOMAIN_VERSIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS family_domain_versions ("
    "family_id INTEGER PRIMARY KEY, state_version INTEGER NOT NULL DEFAULT 1, "
    "domains_json TEXT NOT NULL DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)


def _tables(bind) -> set[str]:
    return {row[0] for row in bind.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        bind.exec_driver_sql(_DOMAIN_VERSIONS_DDL)
        existing = _tables(bind)
        for statement in _INDEX_DDL:
            table = statement.split(" ON ", 1)[1].split("(", 1)[0].split()[0]
            if table in existing:
                bind.exec_driver_sql(statement)
        if "family_encrypted_store" in existing:
            bind.exec_driver_sql("DELETE FROM family_encrypted_store WHERE family_id <= 0")
        if "encrypted_store" in existing and bind.exec_driver_sql("SELECT 1 FROM encrypted_store LIMIT 1").fetchone():
            logger.warning(
                "Legacy `encrypted_store` rows have no owning household and were left untouched; "
                "assign them to a household explicitly or remove them manually."
            )
    finally:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    """Indexes and tables hold live data or are harmless; the downgrade intentionally leaves them in place."""
