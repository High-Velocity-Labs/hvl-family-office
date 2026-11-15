"""`families.settings` becomes plain columns on `families`, each written on its own.

The settings JSON held login stats, the rekey marker, the onboarding flags, the dashboard layout, primary_state /
tax_filing_status, the demo marker and the Local Desktop passphrase key wrap in one object that every writer read,
changed one key of and rewrote whole, so two concurrent writes lost one. Each key becomes its own column (the
layout lists and the key wraps stay JSON text, saved whole by their one writer); keys nothing reads (`city`,
`persona`) are dropped with the blob.

`local_passphrase_fek_enc` keeps its value: it is wrapped by the owner's passphrase and unwraps the household key,
so it stays outside household-key encryption. `portable_vault_fek` is the passphrase envelope an exported
`.fovault` carries (the `_portable_vault_fek_b64` key before); a live database never holds one.

Revision ID: 0010_family_settings_columns
Revises: 0009_household_assumption_sections
Create Date: 2026-11-15 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_family_settings_columns"
down_revision: Union[str, None] = "0009_household_assumption_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = (
    ("primary_state", "TEXT NOT NULL DEFAULT ''"),
    ("tax_filing_status", "TEXT NOT NULL DEFAULT 'MFJ'"),
    ("is_demo", "INTEGER NOT NULL DEFAULT 0"),
    ("onboarding_completed", "INTEGER NOT NULL DEFAULT 0"),
    ("onboarding_dismissed", "INTEGER NOT NULL DEFAULT 0"),
    ("onboarding_wizard_dismissed", "INTEGER NOT NULL DEFAULT 0"),
    ("overview_widgets", "TEXT"),
    ("scenarios_widgets", "TEXT"),
    ("collapsed_charts", "TEXT"),
    ("last_login_at", "TEXT"),
    ("login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("root_kek_rekeyed", "INTEGER NOT NULL DEFAULT 0"),
    ("local_passphrase_fek_enc", "TEXT"),
    ("portable_vault_fek", "TEXT"),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(families)").fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in existing:
            bind.exec_driver_sql("ALTER TABLE families ADD COLUMN " + name + " " + decl)
    if "settings" not in existing:
        return
    # A flag is set when the key held JSON true or a non-zero number (what `bool(value)` read before).
    bind.exec_driver_sql(
        """
        UPDATE families SET
            primary_state = COALESCE(CAST(json_extract(settings, '$.primary_state') AS TEXT), ''),
            tax_filing_status = COALESCE(
                NULLIF(CAST(json_extract(settings, '$.tax_filing_status') AS TEXT), ''), 'MFJ'
            ),
            is_demo = CASE WHEN json_type(settings, '$.is_demo') = 'true'
                OR (json_type(settings, '$.is_demo') IN ('integer', 'real')
                    AND json_extract(settings, '$.is_demo') != 0)
                THEN 1 ELSE 0 END,
            onboarding_completed = CASE WHEN json_type(settings, '$.onboarding_completed') = 'true'
                OR (json_type(settings, '$.onboarding_completed') IN ('integer', 'real')
                    AND json_extract(settings, '$.onboarding_completed') != 0)
                THEN 1 ELSE 0 END,
            onboarding_dismissed = CASE WHEN json_type(settings, '$.onboarding_dismissed') = 'true'
                OR (json_type(settings, '$.onboarding_dismissed') IN ('integer', 'real')
                    AND json_extract(settings, '$.onboarding_dismissed') != 0)
                THEN 1 ELSE 0 END,
            onboarding_wizard_dismissed = CASE WHEN json_type(settings, '$.onboarding_wizard_dismissed') = 'true'
                OR (json_type(settings, '$.onboarding_wizard_dismissed') IN ('integer', 'real')
                    AND json_extract(settings, '$.onboarding_wizard_dismissed') != 0)
                THEN 1 ELSE 0 END,
            overview_widgets = CASE WHEN json_type(settings, '$.overview_widgets') = 'array'
                THEN json_extract(settings, '$.overview_widgets') END,
            scenarios_widgets = CASE WHEN json_type(settings, '$.scenarios_widgets') = 'array'
                THEN json_extract(settings, '$.scenarios_widgets') END,
            collapsed_charts = CASE WHEN json_type(settings, '$.collapsed_charts') = 'array'
                THEN json_extract(settings, '$.collapsed_charts') END,
            last_login_at = CASE WHEN json_type(settings, '$.last_login_at') = 'text'
                THEN json_extract(settings, '$.last_login_at') END,
            login_count = CASE WHEN json_type(settings, '$.login_count') IN ('integer', 'real')
                THEN CAST(json_extract(settings, '$.login_count') AS INTEGER) ELSE 0 END,
            root_kek_rekeyed = CASE WHEN json_type(settings, '$.root_kek_rekeyed_v1') = 'true' THEN 1 ELSE 0 END,
            local_passphrase_fek_enc = CASE json_type(settings, '$.local_passphrase_fek_enc')
                WHEN 'object' THEN json_extract(settings, '$.local_passphrase_fek_enc')
                WHEN 'text' THEN json_quote(json_extract(settings, '$.local_passphrase_fek_enc')) END,
            portable_vault_fek = CASE json_type(settings, '$._portable_vault_fek_b64')
                WHEN 'object' THEN json_extract(settings, '$._portable_vault_fek_b64')
                WHEN 'text' THEN json_quote(json_extract(settings, '$._portable_vault_fek_b64')) END
        WHERE settings IS NOT NULL AND json_valid(settings) AND json_type(settings) = 'object'
        """
    )
    bind.exec_driver_sql("ALTER TABLE families DROP COLUMN settings")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE families ADD COLUMN settings TEXT"
        " DEFAULT '{\"primary_state\": \"\", \"tax_filing_status\": \"MFJ\"}'"
    )
    bind.exec_driver_sql(
        """
        UPDATE families SET settings = json_patch(
            json_object(
                'primary_state', primary_state,
                'tax_filing_status', tax_filing_status,
                'onboarding_completed', json(CASE WHEN onboarding_completed THEN 'true' ELSE 'false' END),
                'onboarding_dismissed', json(CASE WHEN onboarding_dismissed THEN 'true' ELSE 'false' END),
                'onboarding_wizard_dismissed',
                    json(CASE WHEN onboarding_wizard_dismissed THEN 'true' ELSE 'false' END),
                'login_count', login_count
            ),
            json_object(
                'is_demo', json(CASE WHEN is_demo THEN 'true' END),
                'root_kek_rekeyed_v1', json(CASE WHEN root_kek_rekeyed THEN 'true' END),
                'overview_widgets', json(overview_widgets),
                'scenarios_widgets', json(scenarios_widgets),
                'collapsed_charts', json(collapsed_charts),
                'last_login_at', last_login_at,
                'local_passphrase_fek_enc', json(local_passphrase_fek_enc),
                '_portable_vault_fek_b64', json(portable_vault_fek)
            )
        )
        """
    )
    for name, _decl in reversed(_NEW_COLUMNS):
        bind.exec_driver_sql("ALTER TABLE families DROP COLUMN " + name)
