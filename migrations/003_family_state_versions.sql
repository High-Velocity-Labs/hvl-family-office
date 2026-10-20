-- Multi-worker cache consistency: family state versions
-- Version: 003_family_state_versions

CREATE TABLE IF NOT EXISTS family_state_versions (
    family_id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
