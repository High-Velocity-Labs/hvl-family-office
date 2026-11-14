"""Balance history as one row per account per day instead of one encrypted blob.

`account_balance_history` in `family_encrypted_store` held every account's every dated balance in a single
encrypted JSON value, rewritten whole on each sync. `account_balance_snapshots` keeps one row per
(family, account, day) with the balance encrypted per row, so a sync writes only the days it adds. The blob's
contents move into the table the first time a process opens the database (`db.data_migration`, which needs the
household key), and the blob row is deleted then.

Revision ID: 0007_account_balance_snapshots
Revises: 0006_opaque_notification_keys
Create Date: 2026-11-13 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_account_balance_snapshots"
down_revision: Union[str, None] = "0006_opaque_notification_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS account_balance_snapshots (
        	family_id INTEGER NOT NULL,
        	account_id TEXT NOT NULL,
        	snapshot_date TEXT NOT NULL,
        	balance_enc TEXT NOT NULL,
        	PRIMARY KEY (family_id, account_id, snapshot_date),
        	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS account_balance_snapshots")
