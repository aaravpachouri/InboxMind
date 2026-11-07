-- User-owned memory and feedback records for the hosted multi-tenant app.
BEGIN;

CREATE TABLE IF NOT EXISTS user_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'general',
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, category, key)
);
CREATE INDEX IF NOT EXISTS idx_user_memories_user_updated
    ON user_memories(user_id, updated_at DESC);
ALTER TABLE user_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_memories FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_memories_tenant_isolation ON user_memories;
CREATE POLICY user_memories_tenant_isolation ON user_memories
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'general',
    feedback_text TEXT NOT NULL,
    input_summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_feedback_user_created
    ON user_feedback(user_id, created_at DESC);
ALTER TABLE user_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_feedback_tenant_isolation ON user_feedback;
CREATE POLICY user_feedback_tenant_isolation ON user_feedback
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

COMMIT;
