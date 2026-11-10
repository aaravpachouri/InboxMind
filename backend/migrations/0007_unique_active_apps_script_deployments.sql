-- One Apps Script deployment represents one Google mailbox.
-- Prevent the same deployment URL from being attached to multiple InboxMind tenants.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS user_apps_script_bridges_active_url_unique
    ON user_apps_script_bridges (bridge_url)
    WHERE revoked_at IS NULL;

COMMIT;
