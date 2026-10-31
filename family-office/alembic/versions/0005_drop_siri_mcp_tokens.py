"""Deletes the `siri:` rows of `mcp_tokens`: Siri now lives only in the assistant app (`/api/siri`).

Family Office minted Shortcut tokens as `mcp_tokens` rows whose `user_email` is `siri:<email>`. With the endpoint gone
nothing can verify them, and they hold a wrapped household FEK, so they are removed rather than left to rot. Only
`global.db` carries the table (created on first use by `hvl_common.mcp.tokens`); databases without it are skipped.

Revision ID: 0005_drop_siri_mcp_tokens
Revises: 0004_retire_legacy_schema_mechanisms
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_drop_siri_mcp_tokens"
down_revision: Union[str, None] = "0004_retire_legacy_schema_mechanisms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    has_table = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mcp_tokens'"
    ).fetchone()
    if has_table:
        bind.exec_driver_sql("DELETE FROM mcp_tokens WHERE LOWER(user_email) LIKE 'siri:%'")


def downgrade() -> None:
    """The deleted tokens were revoked credentials; there is nothing to restore."""
