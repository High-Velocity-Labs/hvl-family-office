"""Baseline schema and uniform tenant support_access_enabled column.

Revision ID: 0001_baseline
Revises: None
Create Date: 2026-10-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from db.models import Base

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        Base.metadata.create_all(bind=bind)

        inspector = sa.inspect(bind)
        if inspector.has_table("families"):
            fam_cols = {col["name"] for col in inspector.get_columns("families")}
            if "support_access_enabled" not in fam_cols:
                op.add_column(
                    "families",
                    sa.Column(
                        "support_access_enabled",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    ),
                )
    finally:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        inspector = sa.inspect(bind)
        if inspector.has_table("families"):
            fam_cols = {col["name"] for col in inspector.get_columns("families")}
            if "support_access_enabled" in fam_cols:
                op.drop_column("families", "support_access_enabled")
    finally:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")
