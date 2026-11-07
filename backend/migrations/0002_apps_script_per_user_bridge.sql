-- Per-user Apps Script bridge credentials.
-- Each user must deploy their own copy of the bridge as themselves. Never store one
-- owner's bridge URL as a global bridge for every tenant.
BEGIN;

CREATE TABLE IF NOT EXISTS user_apps_script_bridges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    google_account_email TEXT NOT NULL,
    bridge_url TEXT NOT NULL,
    bridge_secret_ciphertext BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    UNIQUE(user_id, google_account_email),
    UNIQUE(user_id, id),
    CHECK (bridge_url ~ '^https://script[.]google[.]com/macros/s/[^/]+/exec$')
);

CREATE INDEX IF NOT EXISTS idx_user_apps_script_bridges_active
    ON user_apps_script_bridges(user_id, updated_at DESC)
    WHERE revoked_at IS NULL;

ALTER TABLE user_apps_script_bridges ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_apps_script_bridges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_apps_script_bridges_tenant_isolation ON user_apps_script_bridges;
CREATE POLICY user_apps_script_bridges_tenant_isolation ON user_apps_script_bridges
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

COMMIT;
