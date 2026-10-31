# Secure multi-user deployment migration

Status: **not deployable yet**. This repository's current backend is a single-installation application and must not be exposed as a public multi-user API.

## Non-negotiable architecture

- Google sign-in establishes an InboxMind user identity from a verified Google OpenID Connect ID token. Gmail authorization is a separate OAuth grant and must be tied to that identity.
- Store users, server-side sessions, OAuth state/nonces, and encrypted Google credentials in PostgreSQL. Every record containing user data must have a `user_id` ownership key and enforce it in repository queries (not only in frontend filters).
- Never accept a user ID, Gmail account ID, tenant ID, or ownership scope from a request body/query as authority. Derive it only from a verified server-side session.
- Use opaque, cryptographically random server-side session IDs in `HttpOnly; Secure; SameSite=Lax` cookies; rotate after authentication, expire sessions, support logout/revocation, and protect state-changing cookie-authenticated requests against CSRF.
- Bind OAuth state to the initiating authenticated session, use one-time state with short expiry, validate the OIDC issuer/audience/nonce, and use the production callback URL.
- Encrypt refresh tokens at rest with a required deployment-managed encryption key (not a key stored beside the database). Never log tokens, authorization codes, message bodies, or secrets.
- Remove process-global Gmail clients, shared token stores, shared per-user settings, and shared background workers. Each request and background job must be scoped to one authenticated user. Jobs must carry a tenant ID from trusted internal scheduling metadata and re-check ownership.
- Migrate email, task, draft, memory, feedback, notification, file-index, sync-state, and settings records to PostgreSQL with tenant ownership and foreign keys. Every query/update/delete must include tenant scope. Add automated cross-tenant isolation tests for every resource class.
- Public deployments must fail closed if required secrets, production origins, HTTPS OAuth redirect URI, PostgreSQL URL, or encryption key are missing. Do not silently fall back to SQLite, local files, localhost Ollama, or Apps Script bridge in production.
- Configure CORS for the exact Vercel origin, secure cookie settings, trusted proxy handling, request limits, security headers, rate limits on authentication endpoints, and privacy-safe health checks.

## Current blockers found in the existing implementation

- `Services` constructs one shared database, secret store, OAuth service, Gmail client, AI engine, task service, file index, and background worker.
- `GoogleOAuthService` holds OAuth state in a process-local dictionary and saves tokens to one shared `SecretStore`.
- The SQLite schema has no tenant ownership columns on emails, tasks, drafts, memories, feedback, notifications, file index, or application state.
- User preferences are restored from a single global `user_settings` state record.
- The local-only host guard rejects public Render hostnames, while simply removing it would expose a shared, single-user backend.
- The frontend defaults to `http://127.0.0.1:8000/api/v1`; it must use the deployed API URL and a cookie-based authenticated request flow.

## Release gates

Do not create or deploy a public Render backend until all gates pass:

1. PostgreSQL migration and tenant-scoped repositories are implemented.
2. Google identity login, per-user Gmail OAuth grant, server-side sessions, CSRF protections, and token encryption are implemented.
3. All API endpoints and background jobs derive and enforce tenant scope.
4. Automated tests prove user A cannot read, mutate, enumerate, or trigger jobs against user B's data or tokens.
5. Existing tests pass; new auth, CSRF, token isolation, session expiry, OAuth state replay, and cross-tenant tests pass.
6. Frontend sign-in/sign-out and API calls use the production API origin and secure cookies.
7. Render environment variables, database, migration command, and Vercel environment configuration are validated without committing secrets.
8. Smoke tests verify unauthenticated API calls are rejected and each test user sees only their own mailbox and tasks.

A deployment being marked READY is not evidence that these security gates have passed.
