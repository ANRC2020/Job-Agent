-- Secure pairing for the optional Chromium browser companion.
-- Only hashes are stored; plaintext pairing codes and bearer tokens are shown once.

CREATE TABLE IF NOT EXISTS extension_pairing_code (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extension_pairing_expiry
    ON extension_pairing_code(person_id, expires_at, used_at);

CREATE TABLE IF NOT EXISTS extension_token (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    extension_name TEXT NOT NULL,
    extension_id TEXT,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extension_token_person
    ON extension_token(person_id, revoked_at, last_used_at);
