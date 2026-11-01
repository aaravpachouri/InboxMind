# InboxMind: per-user Apps Script bridge architecture

## Why this is required

The existing Apps Script bridge uses `USER_ID = "me"` and one `BRIDGE_SECRET` in Script Properties. That is one mailbox per deployment. A shared bridge URL/secret in Render would expose the deployment owner's mailbox to every signed-in user. This must not be used for a public multi-tenant product.

## Required architecture

1. A user signs into InboxMind with a verified identity. Identity sign-in must not request Gmail scopes; Gmail access is handled by Apps Script.
2. Each user deploys their own copy of `InboxMind_Gmail_Bridge_Full_Rewrite.gs` as a web app that executes as the deploying user, authorizes its Gmail scopes, and stores a unique high-entropy `BRIDGE_SECRET` in that script's Script Properties.
3. InboxMind stores that user's bridge URL and secret encrypted at rest in `user_apps_script_bridges`. Access is scoped by the authenticated `user_id` and PostgreSQL RLS. Never use a global bridge credential for all users.
4. On connection, the backend calls `profile` through that user's bridge and verifies the returned mailbox matches the mailbox the user intended to connect before marking it connected.
5. Every Gmail action obtains bridge credentials by authenticated user ID; clients cannot submit a URL or secret per Gmail request. Validate HTTPS and the exact `script.google.com/macros/s/.../exec` URL shape. Keep secrets out of logs and API responses.
6. The current direct-Gmail-OAuth API is not the finished Apps Script integration. Do not deploy this migration alone and do not remove the existing production branch until the endpoints, UI setup flow, encryption, and cross-tenant tests are implemented.

## Deployment gate

- Apply migration only after the bridge management endpoints are implemented and tested.
- Tests must prove a user cannot read, update, revoke, or invoke another user's bridge.
- Tests must prove an unconfigured bridge returns a clear connection-required status and never falls back to direct Gmail API calls.
- Integration tests must use two distinct mock Apps Script deployments/mailboxes and assert all reads/actions remain within each user's bridge.
- Keep Gmail send, draft-send, delete, and trash actions behind explicit confirmation checks.
- No production deployment until all backend tests, frontend build, and two-tenant integration tests pass.

This migration and document are an initial safety foundation, not a claim that multi-user Apps Script support is complete.
