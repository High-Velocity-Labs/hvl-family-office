"""Baseline schema (frozen explicit DDL) and uniform tenant support_access_enabled column.

The DDL below is a snapshot of the schema as of revision 0002; it deliberately does NOT read `db.models`, so a
later model change can never alter what this revision creates. Every statement is `IF NOT EXISTS`, so running it
over a database that already has these tables (legacy `migrations/*.sql`, older Alembic stamps) changes nothing.
The legacy `.sql` schema runs first (see `_PRE_ALEMBIC_SQL`), so a new database has the same defaults and indexes as
every deployed one.
Schema changes after this point are new revisions.

Revision ID: 0001_baseline
Revises: None
Create Date: 2026-10-15 10:00:00.000000

"""
import sqlite3
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema the retired `migrations/*.sql` runner built before Alembic existed (001-004, verbatim). Every deployed
# database was created from it, so a new database starts from the same tables, defaults and indexes; the baseline DDL
# below then adds only what it lacks. Frozen: later schema changes are new revisions.
_PRE_ALEMBIC_SQL = r'''
-- Initial database schema for HVL Family Office
-- Version: 001_initial_schema

CREATE TABLE IF NOT EXISTS families (
    family_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    settings TEXT DEFAULT '{"primary_state": "", "tax_filing_status": "MFJ"}',
    encryption_key_enc TEXT,
    support_access_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT,
    email_hash TEXT,
    birthdate TEXT,
    relationship TEXT NOT NULL DEFAULT 'primary',
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users (family_id, email_hash);

CREATE TABLE IF NOT EXISTS family_encrypted_store (
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    category TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    encrypted_payload TEXT NOT NULL,
    PRIMARY KEY (family_id, key)
);

CREATE TABLE IF NOT EXISTS encrypted_store (
    key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    encrypted_payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS household_profile (
    family_id INTEGER PRIMARY KEY REFERENCES families(family_id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT '',
    filing_status TEXT NOT NULL DEFAULT 'MFJ',
    annual_spending REAL DEFAULT 0.0,
    annual_savings REAL DEFAULT 0.0,
    retirement_age INTEGER DEFAULT 65,
    inflation_rate REAL DEFAULT 0.025,
    real_growth_rate REAL DEFAULT 0.045,
    assumptions_json TEXT DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity_companies (
    company_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    ticker_or_private TEXT NOT NULL DEFAULT 'private',
    current_fmv REAL DEFAULT 0.0,
    fmv_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity_grants (
    grant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES equity_companies(company_id) ON DELETE CASCADE,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    grant_label TEXT NOT NULL,
    grant_type TEXT NOT NULL DEFAULT 'nso',
    strike_price REAL NOT NULL DEFAULT 0.0,
    shares_granted REAL NOT NULL DEFAULT 0.0,
    shares_vested REAL NOT NULL DEFAULT 0.0,
    shares_unvested REAL NOT NULL DEFAULT 0.0,
    shares_exercised REAL NOT NULL DEFAULT 0.0,
    cost_basis REAL NOT NULL DEFAULT 0.0,
    vesting_schedule_json TEXT DEFAULT '{}',
    grant_date TEXT,
    fully_vested_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fmv_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES equity_companies(company_id) ON DELETE CASCADE,
    valuation_date TEXT NOT NULL,
    share_price REAL NOT NULL,
    is_projected INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS account_roles (
    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    monarch_account_id TEXT NOT NULL,
    role TEXT NOT NULL,
    beneficiary_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    is_user_confirmed INTEGER NOT NULL DEFAULT 0,
    is_hidden_from_family_office INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(family_id, monarch_account_id)
);

CREATE TABLE IF NOT EXISTS compensation (
    comp_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    tax_year INTEGER NOT NULL,
    employer_name TEXT NOT NULL,
    base_salary REAL NOT NULL DEFAULT 0.0,
    bonus REAL NOT NULL DEFAULT 0.0,
    equity_spread REAL NOT NULL DEFAULT 0.0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tuition (
    tuition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    child_user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    school_year TEXT NOT NULL,
    school_name TEXT,
    tuition_amount REAL NOT NULL DEFAULT 0.0,
    is_projected INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gift_recipients (
    recipient_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    recipient_group_name TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 1,
    relationship TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gifts (
    gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES gift_recipients(recipient_id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    amount REAL NOT NULL DEFAULT 0.0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS advisor_conversations (
    conversation_id TEXT PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    page_section TEXT NOT NULL DEFAULT 'section-overview',
    title TEXT NOT NULL,
    created_by TEXT,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_adv_conv_fam ON advisor_conversations(family_id, page_section, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_adv_conv_pinned ON advisor_conversations(family_id, is_pinned DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS advisor_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES advisor_conversations(conversation_id) ON DELETE CASCADE,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_adv_msg_conv ON advisor_messages(conversation_id, created_at ASC);

-- Multi-tenant performance indexes for HVL Family Office
-- Version: 002_multi_tenant_indexes

CREATE INDEX IF NOT EXISTS idx_users_family_relationship
    ON users (family_id, relationship);

CREATE INDEX IF NOT EXISTS idx_equity_companies_family
    ON equity_companies (family_id, company_id ASC);

CREATE INDEX IF NOT EXISTS idx_equity_grants_family_company
    ON equity_grants (family_id, company_id, grant_id ASC);

CREATE INDEX IF NOT EXISTS idx_fmv_history_company_date
    ON fmv_history (company_id, valuation_date ASC);

CREATE INDEX IF NOT EXISTS idx_account_roles_family
    ON account_roles (family_id, monarch_account_id);

CREATE INDEX IF NOT EXISTS idx_compensation_family_year
    ON compensation (family_id, tax_year DESC);

CREATE INDEX IF NOT EXISTS idx_tuition_family_child_year
    ON tuition (family_id, child_user_id, school_year ASC);

CREATE INDEX IF NOT EXISTS idx_gift_recipients_family
    ON gift_recipients (family_id, recipient_group_name ASC);

CREATE INDEX IF NOT EXISTS idx_gifts_family_year
    ON gifts (family_id, year DESC, recipient_id);

-- Multi-worker cache consistency: family state versions
-- Version: 003_family_state_versions

CREATE TABLE IF NOT EXISTS family_state_versions (
    family_id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Migration 004: Normalized Relational Domain Tables
-- Replaces monolithic JSON blobs in family_encrypted_store (accounts, holdings,
-- estate_profile, tax_transcripts, private_school_tuition, scenario_system_state,
-- annual_donations) with normalized relational tables keyed by family_id and
-- encrypted at the row/column level via per-family Fernet keys.

CREATE TABLE IF NOT EXISTS monarch_accounts (
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    display_name_enc TEXT NOT NULL DEFAULT '',
    current_balance_enc TEXT NOT NULL DEFAULT '',
    account_type TEXT NOT NULL DEFAULT '',
    subtype TEXT NOT NULL DEFAULT '',
    institution_name_enc TEXT NOT NULL DEFAULT '',
    is_manual INTEGER NOT NULL DEFAULT 0,
    include_in_net_worth INTEGER NOT NULL DEFAULT 1,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    payload_enc TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_monarch_accounts_family ON monarch_accounts(family_id);

CREATE TABLE IF NOT EXISTS monarch_holdings (
    holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    ticker_enc TEXT NOT NULL DEFAULT '',
    security_name_enc TEXT NOT NULL DEFAULT '',
    quantity_enc TEXT NOT NULL DEFAULT '',
    total_value_enc TEXT NOT NULL DEFAULT '',
    basis_enc TEXT NOT NULL DEFAULT '',
    payload_enc TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_monarch_holdings_family_acc ON monarch_holdings(family_id, account_id);

CREATE TABLE IF NOT EXISTS estate_profiles (
    family_id INTEGER PRIMARY KEY REFERENCES families(family_id) ON DELETE CASCADE,
    state_of_residence TEXT NOT NULL DEFAULT '',
    marital_status TEXT NOT NULL DEFAULT 'married_joint',
    prior_lifetime_taxable_gifts_enc TEXT NOT NULL DEFAULT '',
    dsue_ported_enc TEXT NOT NULL DEFAULT '',
    charitable_bequest_pct_enc TEXT NOT NULL DEFAULT '',
    charitable_bequest_fixed_enc TEXT NOT NULL DEFAULT '',
    ilit_death_benefit_enc TEXT NOT NULL DEFAULT '',
    trust_transferred_assets_enc TEXT NOT NULL DEFAULT '',
    estimated_probate_admin_pct_enc TEXT NOT NULL DEFAULT '',
    apply_2026_tcja_sunset INTEGER NOT NULL DEFAULT 0,
    payload_enc TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tax_transcript_records (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    tax_year INTEGER NOT NULL,
    record_type TEXT NOT NULL DEFAULT 'summary',
    taxpayer_name_enc TEXT NOT NULL DEFAULT '',
    w2_wages_enc TEXT NOT NULL DEFAULT '',
    federal_tax_withheld_enc TEXT NOT NULL DEFAULT '',
    social_security_withheld_enc TEXT NOT NULL DEFAULT '',
    medicare_tax_withheld_enc TEXT NOT NULL DEFAULT '',
    mortgage_interest_paid_enc TEXT NOT NULL DEFAULT '',
    qualified_dividends_enc TEXT NOT NULL DEFAULT '',
    realized_capital_gains_enc TEXT NOT NULL DEFAULT '',
    safe_harbor_target_enc TEXT NOT NULL DEFAULT '',
    payload_enc TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tax_transcript_records_family ON tax_transcript_records(family_id, tax_year);

CREATE TABLE IF NOT EXISTS tax_transcript_meta (
    family_id INTEGER PRIMARY KEY REFERENCES families(family_id) ON DELETE CASCADE,
    adults_enc TEXT NOT NULL DEFAULT '',
    available_years_enc TEXT NOT NULL DEFAULT '',
    latest_tax_year INTEGER DEFAULT NULL,
    safe_harbor_2026_target_enc TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tuition_year_records (
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    school_year TEXT NOT NULL,
    school_name_enc TEXT NOT NULL DEFAULT '',
    total_amount_enc TEXT NOT NULL DEFAULT '',
    is_projected INTEGER NOT NULL DEFAULT 0,
    notes_enc TEXT NOT NULL DEFAULT '',
    payload_enc TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, school_year)
);

CREATE INDEX IF NOT EXISTS idx_tuition_year_records_family ON tuition_year_records(family_id);

CREATE TABLE IF NOT EXISTS forecast_settings (
    family_id INTEGER PRIMARY KEY REFERENCES families(family_id) ON DELETE CASCADE,
    active_scenario_id TEXT NOT NULL DEFAULT 'baseline',
    comparison_scenario_id TEXT DEFAULT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS forecast_scenarios (
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL,
    name_enc TEXT NOT NULL,
    description_enc TEXT NOT NULL DEFAULT '',
    is_baseline INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL DEFAULT '#3b82f6',
    overrides_enc TEXT NOT NULL DEFAULT '',
    payload_enc TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, scenario_id)
);

CREATE INDEX IF NOT EXISTS idx_forecast_scenarios_family ON forecast_scenarios(family_id);

CREATE TABLE IF NOT EXISTS forecast_events (
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL DEFAULT 'baseline',
    name_enc TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'expense',
    amount_enc TEXT NOT NULL DEFAULT '',
    start_year INTEGER NOT NULL DEFAULT 2026,
    end_year INTEGER NOT NULL DEFAULT 2026,
    enabled INTEGER NOT NULL DEFAULT 1,
    payload_enc TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_forecast_events_family_scen ON forecast_events(family_id, scenario_id);

CREATE TABLE IF NOT EXISTS philanthropy_budgets (
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    tax_year INTEGER NOT NULL,
    budget_amount_enc TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, tax_year)
);

CREATE TABLE IF NOT EXISTS philanthropy_donations (
    donation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
    tax_year INTEGER NOT NULL,
    donation_date TEXT NOT NULL DEFAULT '',
    organization_enc TEXT NOT NULL,
    amount_enc TEXT NOT NULL,
    description_enc TEXT NOT NULL DEFAULT '',
    payload_enc TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_philanthropy_donations_family_yr ON philanthropy_donations(family_id, tax_year);

'''


def _pre_alembic_statements() -> list[str]:
    """Splits `_PRE_ALEMBIC_SQL` into complete statements."""
    statements, current = [], ""
    for line in _PRE_ALEMBIC_SQL.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            statements.append(current.strip())
            current = ""
    return [stmt for stmt in statements if stmt]


_BASELINE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS bug_reports (
    	bug_id INTEGER NOT NULL,
    	project TEXT DEFAULT 'finances' NOT NULL,
    	app_version TEXT DEFAULT '' NOT NULL,
    	created_at INTEGER NOT NULL,
    	updated_at INTEGER NOT NULL,
    	status TEXT DEFAULT 'open' NOT NULL,
    	universe TEXT DEFAULT 'public' NOT NULL,
    	family_id INTEGER DEFAULT 0 NOT NULL,
    	user_role TEXT DEFAULT 'viewer' NOT NULL,
    	user_ref TEXT DEFAULT '',
    	support_access_enabled INTEGER DEFAULT 0,
    	pane TEXT DEFAULT 'overview' NOT NULL,
    	category TEXT DEFAULT 'math' NOT NULL,
    	scrubbed_description TEXT DEFAULT '' NOT NULL,
    	scrubbed_followup TEXT DEFAULT '',
    	ai_explanation TEXT DEFAULT '',
    	suspected_module TEXT DEFAULT '',
    	invariant_summary TEXT DEFAULT '',
    	scale_factor FLOAT DEFAULT (1.0),
    	anonymization_mode TEXT DEFAULT 'scaled',
    	sanitized_snapshot_json TEXT DEFAULT '{}',
    	admin_notes TEXT DEFAULT '',
    	PRIMARY KEY (bug_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bug_reports_created ON bug_reports (created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bug_reports_project ON bug_reports (project)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bug_reports_status ON bug_reports (status)
    """,
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
    CREATE TABLE IF NOT EXISTS families (
    	family_id INTEGER NOT NULL,
    	name TEXT NOT NULL,
    	settings TEXT,
    	encryption_key_enc TEXT,
    	support_access_enabled INTEGER DEFAULT 0 NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS family_id_allocator (
    	family_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    	allocated_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS family_state_versions (
    	family_id INTEGER NOT NULL,
    	version INTEGER NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id)
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
    CREATE TABLE IF NOT EXISTS portal_telemetry_events (
    	event_id INTEGER NOT NULL,
    	universe TEXT NOT NULL,
    	event_type TEXT NOT NULL,
    	feature_key TEXT DEFAULT '',
    	session_hash TEXT DEFAULT '',
    	meta_json TEXT DEFAULT '{}',
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	tab TEXT DEFAULT '',
    	action TEXT DEFAULT '',
    	modal TEXT DEFAULT '',
    	PRIMARY KEY (event_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_portal_telemetry_created ON portal_telemetry_events (created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_portal_telemetry_tab ON portal_telemetry_events (universe, tab)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_portal_telemetry_uni_evt ON portal_telemetry_events (universe, event_type)
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
    CREATE TABLE IF NOT EXISTS sandbox_leases (
    	family_id INTEGER NOT NULL,
    	created_at INTEGER NOT NULL,
    	expires_at INTEGER NOT NULL,
    	extended_7d INTEGER DEFAULT 0,
    	seed_mode TEXT DEFAULT 'blank',
    	session_hash TEXT DEFAULT '',
    	PRIMARY KEY (family_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sandbox_leases_exp ON sandbox_leases (expires_at)
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
    CREATE TABLE IF NOT EXISTS equity_companies (
    	company_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	company_name TEXT NOT NULL,
    	ticker_or_private TEXT NOT NULL,
    	current_fmv FLOAT,
    	fmv_date TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (company_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS estate_profiles (
    	family_id INTEGER NOT NULL,
    	state_of_residence TEXT NOT NULL,
    	marital_status TEXT NOT NULL,
    	prior_lifetime_taxable_gifts_enc TEXT NOT NULL,
    	dsue_ported_enc TEXT NOT NULL,
    	charitable_bequest_pct_enc TEXT NOT NULL,
    	charitable_bequest_fixed_enc TEXT NOT NULL,
    	ilit_death_benefit_enc TEXT NOT NULL,
    	trust_transferred_assets_enc TEXT NOT NULL,
    	estimated_probate_admin_pct_enc TEXT NOT NULL,
    	apply_2026_tcja_sunset INTEGER NOT NULL,
    	payload_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS family_encrypted_store (
    	family_id INTEGER NOT NULL,
    	"key" TEXT NOT NULL,
    	category TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	encrypted_payload TEXT NOT NULL,
    	PRIMARY KEY (family_id, "key"),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_events (
    	family_id INTEGER NOT NULL,
    	event_id TEXT NOT NULL,
    	scenario_id TEXT NOT NULL,
    	name_enc TEXT NOT NULL,
    	event_type TEXT NOT NULL,
    	amount_enc TEXT NOT NULL,
    	start_year INTEGER NOT NULL,
    	end_year INTEGER NOT NULL,
    	enabled INTEGER NOT NULL,
    	payload_enc TEXT NOT NULL,
    	sort_order INTEGER NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id, event_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_scenarios (
    	family_id INTEGER NOT NULL,
    	scenario_id TEXT NOT NULL,
    	name_enc TEXT NOT NULL,
    	description_enc TEXT NOT NULL,
    	is_baseline INTEGER NOT NULL,
    	color TEXT NOT NULL,
    	overrides_enc TEXT NOT NULL,
    	payload_enc TEXT NOT NULL,
    	sort_order INTEGER NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id, scenario_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_settings (
    	family_id INTEGER NOT NULL,
    	active_scenario_id TEXT NOT NULL,
    	comparison_scenario_id TEXT,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gift_recipients (
    	recipient_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	recipient_group_name TEXT NOT NULL,
    	member_count INTEGER NOT NULL,
    	relationship TEXT,
    	notes TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (recipient_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS household_profile (
    	family_id INTEGER NOT NULL,
    	state TEXT NOT NULL,
    	filing_status TEXT NOT NULL,
    	annual_spending FLOAT,
    	annual_savings FLOAT,
    	retirement_age INTEGER,
    	inflation_rate FLOAT,
    	real_growth_rate FLOAT,
    	assumptions_json TEXT,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id),
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
    CREATE TABLE IF NOT EXISTS monarch_accounts (
    	family_id INTEGER NOT NULL,
    	account_id TEXT NOT NULL,
    	display_name_enc TEXT NOT NULL,
    	current_balance_enc TEXT NOT NULL,
    	account_type TEXT NOT NULL,
    	subtype TEXT NOT NULL,
    	institution_name_enc TEXT NOT NULL,
    	is_manual INTEGER NOT NULL,
    	include_in_net_worth INTEGER NOT NULL,
    	is_hidden INTEGER NOT NULL,
    	payload_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id, account_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monarch_holdings (
    	holding_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	account_id TEXT NOT NULL,
    	ticker_enc TEXT NOT NULL,
    	security_name_enc TEXT NOT NULL,
    	quantity_enc TEXT NOT NULL,
    	total_value_enc TEXT NOT NULL,
    	basis_enc TEXT NOT NULL,
    	payload_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (holding_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS philanthropy_budgets (
    	family_id INTEGER NOT NULL,
    	tax_year INTEGER NOT NULL,
    	budget_amount_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id, tax_year),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS philanthropy_donations (
    	donation_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	tax_year INTEGER NOT NULL,
    	donation_date TEXT NOT NULL,
    	organization_enc TEXT NOT NULL,
    	amount_enc TEXT NOT NULL,
    	description_enc TEXT NOT NULL,
    	payload_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (donation_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tax_transcript_meta (
    	family_id INTEGER NOT NULL,
    	adults_enc TEXT NOT NULL,
    	available_years_enc TEXT NOT NULL,
    	latest_tax_year INTEGER,
    	safe_harbor_2026_target_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tax_transcript_records (
    	record_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	tax_year INTEGER NOT NULL,
    	record_type TEXT NOT NULL,
    	taxpayer_name_enc TEXT NOT NULL,
    	w2_wages_enc TEXT NOT NULL,
    	federal_tax_withheld_enc TEXT NOT NULL,
    	social_security_withheld_enc TEXT NOT NULL,
    	medicare_tax_withheld_enc TEXT NOT NULL,
    	mortgage_interest_paid_enc TEXT NOT NULL,
    	qualified_dividends_enc TEXT NOT NULL,
    	realized_capital_gains_enc TEXT NOT NULL,
    	safe_harbor_target_enc TEXT NOT NULL,
    	payload_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (record_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tuition_year_records (
    	family_id INTEGER NOT NULL,
    	school_year TEXT NOT NULL,
    	school_name_enc TEXT NOT NULL,
    	total_amount_enc TEXT NOT NULL,
    	is_projected INTEGER NOT NULL,
    	notes_enc TEXT NOT NULL,
    	payload_enc TEXT NOT NULL,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (family_id, school_year),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
    	user_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	name TEXT NOT NULL,
    	email TEXT,
    	email_hash TEXT,
    	birthdate TEXT,
    	relationship TEXT NOT NULL,
    	role TEXT NOT NULL,
    	pending_fek_enc TEXT,
    	google_vault_synced INTEGER DEFAULT 0 NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (user_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_roles (
    	role_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	monarch_account_id TEXT NOT NULL,
    	role TEXT NOT NULL,
    	beneficiary_user_id INTEGER,
    	is_user_confirmed INTEGER NOT NULL,
    	is_hidden_from_family_office INTEGER NOT NULL,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (role_id),
    	UNIQUE (family_id, monarch_account_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE,
    	FOREIGN KEY(beneficiary_user_id) REFERENCES users (user_id) ON DELETE SET NULL
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
    """
    CREATE TABLE IF NOT EXISTS compensation (
    	comp_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	user_id INTEGER,
    	tax_year INTEGER NOT NULL,
    	employer_name TEXT NOT NULL,
    	base_salary TEXT NOT NULL,
    	bonus TEXT NOT NULL,
    	equity_spread TEXT NOT NULL,
    	notes TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (comp_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE,
    	FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS equity_grants (
    	grant_id INTEGER NOT NULL,
    	company_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	grant_label TEXT NOT NULL,
    	grant_type TEXT NOT NULL,
    	strike_price TEXT NOT NULL,
    	shares_granted TEXT NOT NULL,
    	shares_vested TEXT NOT NULL,
    	shares_unvested TEXT NOT NULL,
    	shares_exercised TEXT NOT NULL,
    	cost_basis TEXT NOT NULL,
    	vesting_schedule_json TEXT,
    	grant_date TEXT,
    	fully_vested_date TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (grant_id),
    	FOREIGN KEY(company_id) REFERENCES equity_companies (company_id) ON DELETE CASCADE,
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fmv_history (
    	history_id INTEGER NOT NULL,
    	company_id INTEGER NOT NULL,
    	valuation_date TEXT NOT NULL,
    	share_price FLOAT NOT NULL,
    	is_projected INTEGER NOT NULL,
    	notes TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (history_id),
    	FOREIGN KEY(company_id) REFERENCES equity_companies (company_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gifts (
    	gift_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	recipient_id INTEGER NOT NULL,
    	year INTEGER NOT NULL,
    	amount TEXT NOT NULL,
    	notes TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (gift_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE,
    	FOREIGN KEY(recipient_id) REFERENCES gift_recipients (recipient_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tuition (
    	tuition_id INTEGER NOT NULL,
    	family_id INTEGER NOT NULL,
    	child_user_id INTEGER,
    	school_year TEXT NOT NULL,
    	school_name TEXT,
    	tuition_amount TEXT NOT NULL,
    	is_projected INTEGER NOT NULL,
    	notes TEXT,
    	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    	PRIMARY KEY (tuition_id),
    	FOREIGN KEY(family_id) REFERENCES families (family_id) ON DELETE CASCADE,
    	FOREIGN KEY(child_user_id) REFERENCES users (user_id) ON DELETE CASCADE
    )
    """,
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        for statement in _pre_alembic_statements():
            bind.exec_driver_sql(statement)
        for statement in _BASELINE_DDL:
            bind.exec_driver_sql(statement)

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
