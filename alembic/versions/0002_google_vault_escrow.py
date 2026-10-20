"""Add pending_fek_enc and google_vault_synced to users and backfill escrow + email_hash.

Revision ID: 0002_google_vault_escrow
Revises: 0001_baseline
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import security

# revision identifiers, used by Alembic.
revision: str = "0002_google_vault_escrow"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        inspector = sa.inspect(bind)
        if inspector.has_table("users"):
            user_cols = {col["name"] for col in inspector.get_columns("users")}
            if "pending_fek_enc" not in user_cols:
                op.add_column(
                    "users",
                    sa.Column("pending_fek_enc", sa.Text(), nullable=True),
                )
            if "google_vault_synced" not in user_cols:
                op.add_column(
                    "users",
                    sa.Column(
                        "google_vault_synced",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    ),
                )

        if inspector.has_table("families") and inspector.has_table("users"):
            fam_rows = bind.exec_driver_sql(
                "SELECT family_id, encryption_key_enc FROM families WHERE encryption_key_enc IS NOT NULL AND encryption_key_enc != ''"
            ).fetchall()
            root_kek = security.get_or_create_key()
            fernet_kek = security._get_fernet(root_kek)

            for row in fam_rows:
                fid = int(row[0])
                enc_dek = str(row[1])
                bind.exec_driver_sql(
                    "UPDATE users SET pending_fek_enc = ? WHERE family_id = ? AND (pending_fek_enc IS NULL OR pending_fek_enc = '')",
                    (enc_dek, fid),
                )

                user_rows = bind.exec_driver_sql(
                    "SELECT user_id, email FROM users WHERE family_id = ? AND email IS NOT NULL AND email != '' AND (email_hash IS NULL OR email_hash = '')",
                    (fid,),
                ).fetchall()
                if user_rows:
                    try:
                        fam_key = fernet_kek.decrypt(enc_dek.encode("utf-8"))
                    except Exception:
                        fam_key = None
                    for u_row in user_rows:
                        uid = int(u_row[0])
                        raw_em = str(u_row[1] or "")
                        dec_em = (
                            security.decrypt_field(raw_em, default="", key=fam_key)
                            .strip()
                            .lower()
                        )
                        if dec_em:
                            em_hash = security.hash_email(dec_em)
                            bind.exec_driver_sql(
                                "UPDATE users SET email_hash = ? WHERE user_id = ?",
                                (em_hash, uid),
                            )
    finally:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        inspector = sa.inspect(bind)
        if inspector.has_table("users"):
            user_cols = {col["name"] for col in inspector.get_columns("users")}
            if "google_vault_synced" in user_cols:
                op.drop_column("users", "google_vault_synced")
            if "pending_fek_enc" in user_cols:
                op.drop_column("users", "pending_fek_enc")
    finally:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")
