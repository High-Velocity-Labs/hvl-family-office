-- Initial database schema for HVL Family Office
-- Version: 001_initial_schema

CREATE TABLE IF NOT EXISTS families (
    family_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    settings TEXT DEFAULT '{"primary_state": "WA", "tax_filing_status": "MFJ"}',
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
    state TEXT NOT NULL DEFAULT 'WA',
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
