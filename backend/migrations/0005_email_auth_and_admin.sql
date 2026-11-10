-- Additive account-security foundation for email/password onboarding and platform administration.
-- Existing Google accounts and sessions remain valid. This migration does not change production
-- until the feature branch is deployed and the migration runner is executed.
BEGIN;

-- Email/password users do not have a Google subject. Keep the existing Google subject unique
-- when present, but allow NULL for accounts authenticated by another provider.
ALTER TABLE app_users ALTER COLUMN google_sub DROP NOT NULL;

ALTER TABLE app_users
    ADD COLUMN IF NOT EXISTS password_hash TEXT,
    ADD COLUMN IF NOT EXISTS email_verification_hash BYTEA,
    ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS password_reset_hash BYTEA,
    ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- Do not impose global case-insensitive uniqueness here: legacy Apps Script and Google
-- sign-ins may already represent the same mailbox as separate identities. Account linking
-- must be an explicit verified flow before uniqueness can safely be enforced.
CREATE INDEX IF NOT EXISTS idx_app_users_email_normalized
    ON app_users (lower(email));

CREATE TABLE IF NOT EXISTS auth_email_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('verification_requested','verification_completed','password_reset_requested','password_reset_completed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_ip_hash BYTEA
);
CREATE INDEX IF NOT EXISTS idx_auth_email_events_user_created
    ON auth_email_events(user_id, created_at DESC);

-- Tokens are stored as SHA-256 hashes only. Raw tokens are delivered out-of-band and never
-- persisted. Limit issuance to reduce abuse and prevent token replay.
CREATE TABLE IF NOT EXISTS auth_token_issuance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
    token_hash BYTEA NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auth_token_issuance_user
    ON auth_token_issuance(user_id, purpose, created_at DESC);

COMMIT;
