-- PostgreSQL schema foundation for InboxMind's multi-tenant migration.
-- This migration is intentionally additive and is NOT wired into the legacy SQLite repository yet.
-- Do not deploy the legacy API publicly until every repository is migrated and tenant-scoped.

BEGIN;

CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    display_name TEXT NOT NULL DEFAULT '',
    picture_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    session_token_hash BYTEA NOT NULL UNIQUE,
    csrf_token_hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_active
    ON user_sessions(user_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS oauth_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES user_sessions(id) ON DELETE CASCADE,
    state_hash BYTEA NOT NULL UNIQUE,
    nonce_hash BYTEA,
    purpose TEXT NOT NULL CHECK (purpose IN ('login', 'gmail_connect')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_oauth_transactions_expiry ON oauth_transactions(expires_at);

CREATE TABLE IF NOT EXISTS gmail_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    google_account_sub TEXT NOT NULL,
    email TEXT NOT NULL,
    granted_scopes TEXT[] NOT NULL DEFAULT '{}',
    refresh_token_ciphertext BYTEA NOT NULL,
    access_token_ciphertext BYTEA,
    access_token_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    UNIQUE(user_id, google_account_sub),
    UNIQUE(user_id, email)
);
CREATE INDEX IF NOT EXISTS idx_gmail_accounts_user ON gmail_accounts(user_id);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id UUID PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_emails (
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    gmail_account_id UUID NOT NULL REFERENCES gmail_accounts(id) ON DELETE CASCADE,
    gmail_message_id TEXT NOT NULL,
    thread_id TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL,
    internal_date TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, gmail_account_id, gmail_message_id),
    FOREIGN KEY (user_id, gmail_account_id)
        REFERENCES gmail_accounts(user_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_emails_date ON user_emails(user_id, internal_date DESC);

CREATE TABLE IF NOT EXISTS user_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    gmail_account_id UUID,
    source_message_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    due_at TIMESTAMPTZ,
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'done', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (user_id, gmail_account_id)
        REFERENCES gmail_accounts(user_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_tasks_due ON user_tasks(user_id, status, due_at);

CREATE TABLE IF NOT EXISTS user_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    gmail_account_id UUID,
    gmail_draft_id TEXT,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (user_id, gmail_account_id)
        REFERENCES gmail_accounts(user_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_sync_state (
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    gmail_account_id UUID NOT NULL REFERENCES gmail_accounts(id) ON DELETE CASCADE,
    history_id TEXT,
    last_success_at TIMESTAMPTZ,
    last_error_code TEXT,
    backlog_estimate INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, gmail_account_id),
    FOREIGN KEY (user_id, gmail_account_id)
        REFERENCES gmail_accounts(user_id, id) ON DELETE CASCADE
);

-- Force row-level ownership in PostgreSQL as defense in depth. Application code must still
-- bind the authenticated user ID in every query and set app.current_user_id per transaction.
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sync_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_settings_tenant_isolation ON user_settings;
CREATE POLICY user_settings_tenant_isolation ON user_settings
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

DROP POLICY IF EXISTS user_emails_tenant_isolation ON user_emails;
CREATE POLICY user_emails_tenant_isolation ON user_emails
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

DROP POLICY IF EXISTS user_tasks_tenant_isolation ON user_tasks;
CREATE POLICY user_tasks_tenant_isolation ON user_tasks
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

DROP POLICY IF EXISTS user_drafts_tenant_isolation ON user_drafts;
CREATE POLICY user_drafts_tenant_isolation ON user_drafts
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

DROP POLICY IF EXISTS user_sync_state_tenant_isolation ON user_sync_state;
CREATE POLICY user_sync_state_tenant_isolation ON user_sync_state
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

COMMIT;
