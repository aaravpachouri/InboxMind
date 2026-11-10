-- Rate-limit password authentication without storing raw email addresses.
BEGIN;

CREATE TABLE IF NOT EXISTS auth_login_attempts (
    id BIGSERIAL PRIMARY KEY,
    email_hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_email_created
    ON auth_login_attempts(email_hash, created_at DESC);

COMMIT;
