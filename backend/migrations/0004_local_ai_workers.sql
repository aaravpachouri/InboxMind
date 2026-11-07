-- Private, per-account Windows Ollama workers and leased AI jobs.
-- Worker tokens are stored only as SHA-256 hashes. The worker table is intentionally
-- looked up by token hash before tenant context is known; that query returns one row
-- only and grants no access to account data. All job-table access is RLS-scoped.
BEGIN;

CREATE TABLE IF NOT EXISTS user_ai_workers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    token_hash BYTEA NOT NULL UNIQUE,
    device_name TEXT NOT NULL DEFAULT 'Windows PC',
    worker_version TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    installed_models JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_available BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_ai_workers_user_active
    ON user_ai_workers(user_id, last_seen_at DESC) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS user_ai_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL CHECK (job_type IN ('analyze_email','summarize_email','draft_reply','chat')),
    payload BYTEA NOT NULL,
    result BYTEA,
    error TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','leased','completed','failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id UUID REFERENCES user_ai_workers(id) ON DELETE SET NULL,
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_ai_jobs_queue
    ON user_ai_jobs(user_id, status, created_at) WHERE status IN ('queued','leased');
CREATE INDEX IF NOT EXISTS idx_user_ai_jobs_worker
    ON user_ai_jobs(user_id, worker_id, status);

ALTER TABLE user_ai_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_ai_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_ai_jobs_tenant_isolation ON user_ai_jobs;
CREATE POLICY user_ai_jobs_tenant_isolation ON user_ai_jobs
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

COMMIT;
