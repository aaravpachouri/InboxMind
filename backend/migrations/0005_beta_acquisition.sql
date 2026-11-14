-- InboxMind early-access intake and product feedback.
-- Public writes are mediated only by the backend API; no browser database credentials are exposed.
BEGIN;

CREATE TABLE IF NOT EXISTS beta_signups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    email_normalized TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL CHECK (audience IN ('student','freelancer','indie_hacker','consultant')),
    role_context TEXT NOT NULL DEFAULT '',
    workflow TEXT NOT NULL,
    feedback_commitment BOOLEAN NOT NULL CHECK (feedback_commitment = TRUE),
    contact_consent BOOLEAN NOT NULL CHECK (contact_consent = TRUE),
    consent_version TEXT NOT NULL,
    feedback_token_hash BYTEA NOT NULL,
    source TEXT NOT NULL DEFAULT 'beta_landing_page',
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new','invited','active','waitlisted','declined','deleted')),
    marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_beta_signups_created ON beta_signups(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_beta_signups_audience_status ON beta_signups(audience, status);

CREATE TABLE IF NOT EXISTS beta_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signup_id UUID NOT NULL REFERENCES beta_signups(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (category IN ('onboarding','inbox','priorities','tasks','ai','privacy','bug','other')),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    details TEXT NOT NULL,
    permission_to_quote BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_beta_feedback_signup ON beta_feedback(signup_id, created_at DESC);

COMMENT ON TABLE beta_signups IS 'Early-access requests. Contact consent is limited to beta access and product feedback; marketing_opt_in stays false.';
COMMENT ON TABLE beta_feedback IS 'Product feedback only. Applicants are instructed not to submit mailbox contents or sensitive personal data.';

COMMIT;
