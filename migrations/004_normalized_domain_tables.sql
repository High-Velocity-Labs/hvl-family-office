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
    state_of_residence TEXT NOT NULL DEFAULT 'WA',
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
