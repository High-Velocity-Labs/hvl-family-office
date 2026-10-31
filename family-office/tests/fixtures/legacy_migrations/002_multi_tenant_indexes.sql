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
