# InboxMind multi-user release readiness

This document describes the tested release candidate on `feat/universal-hosted-multi-tenant`.
It is not a production deployment authorization.

## Zero-cost operating model

- Render web service and PostgreSQL are configured for their free plans.
- AI runs through the owner's already-running private Windows worker and local Ollama model. End users do not install Ollama.
- If the private worker is offline, AI requests must fail clearly; the API must not silently switch to a paid cloud model.
- No paid inference provider, email service, or hosting tier is enabled by this configuration.
- Free-tier quotas, sleeping, and provider limits still apply. "Free plan" does not guarantee uninterrupted availability.

## Required Render environment

Set these values in the Render service environment before switching the service to this branch:

| Variable | Value / source |
| --- | --- |
| `DATABASE_URL` | Existing free `inboxmind-postgres` connection |
| `APPS_SCRIPT_ENCRYPTION_KEY` | Preserve the existing production Fernet key; do not rotate while encrypted bridge secrets exist |
| `GOOGLE_CLIENT_ID` | Google OAuth Web client ID |
| `GOOGLE_CLIENT_SECRET` | Matching Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | `https://inboxmind-rose.vercel.app/api/v1/auth/google/callback` |
| `FRONTEND_URL` | `https://inboxmind-rose.vercel.app` |
| `ALLOWED_ORIGINS` | `https://inboxmind-rose.vercel.app` |
| `RESEND_API_KEY` | Optional account-email delivery provider key; signup/recovery email will fail closed without it |
| `INBOXMIND_AUTH_EMAIL_FROM` | Verified sender address for the configured email provider |
| `PLATFORM_ADMIN_EMAILS` | Comma-separated, explicitly authorized admin email(s) |
| `AI_BACKEND_MODE` | `private_worker` |
| `OLLAMA_MODEL` | `llama3.2:3b` (must match the installed model on the private worker) |
| `AUTO_SYNC_ENABLED` | `false` until per-user sync has been explicitly validated |

Google OAuth setup must include the exact Vercel same-origin callback URI above. The Vercel rewrite proxies `/api/v1/*` to Render; using the Vercel callback keeps the session cookie on the frontend origin. Set `GOOGLE_REDIRECT_URI` in Render to the same URI. Keep the OAuth audience and test-user policy appropriate for the intended users.

## Required Vercel configuration

- Deploy the frontend from `feat/universal-hosted-multi-tenant` only after approving the release.
- Keep the same-origin `/api/v1/*` rewrite to the Render API.
- Do not expose database URLs, OAuth client secrets, bridge secrets, worker tokens, or model-provider keys in Vercel client-side variables.

## First-use smoke test

1. Open the deployed frontend over HTTPS.
2. Create a new test account with an email address controlled by the tester.
3. Confirm the verification email arrives; verify once, then confirm replay is rejected.
4. Sign in, sign out, sign in again, and confirm session cookies are Secure, HttpOnly, and scoped correctly.
5. Connect a dedicated test Gmail account through its own Apps Script bridge. Do not use a personal production mailbox for initial testing.
6. Confirm inbox, drafts, tasks, settings, memory, notifications, and AI jobs remain isolated between two test users.
7. Confirm the private worker can process only its owner's queued jobs and that AI reports unavailable when the worker is stopped.
8. Confirm send and Trash require deliberate user confirmation.
9. Confirm session revocation and admin denial for a normal account. Email/password recovery is disabled for this no-email-provider release.
10. Inspect logs for secrets, raw auth tokens, message bodies, or cross-tenant data. None should be logged.

## Release gate

The GitHub Actions workflow must pass backend tests (including disposable PostgreSQL RLS tests), Python compilation, and frontend production build. Then perform the live smoke test above on a separate test deployment and test database.

Before production deployment, inspect the production database for duplicate active `bridge_url` values because migration 0007 adds a unique partial index and will fail safely if duplicates exist. Do not merge, change the live Render branch, apply migrations to the production database, or publish the frontend until the owner explicitly approves deployment. A green CI run is not a substitute for verifying required provider credentials, OAuth consent, email delivery, and the live worker.
