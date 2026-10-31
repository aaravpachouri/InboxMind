# Google OAuth setup for the local Gmail AI Agent

Google credentials are not included in this project. Create your own OAuth client; do not paste client secrets or access tokens into chat or source code.

## 1. Create a Google Cloud project

1. Open the Google Cloud Console and create/select a project.
2. Enable **Gmail API**. Enable **Google Calendar API** only if you want to use the calendar integration.
3. Configure the OAuth consent screen / Google Auth Platform branding and audience. For a personal local build, keep the audience restricted to your own Google account where the available account type allows it. Add your account as a test user if the app is in Testing.
4. Add only the scopes the app needs:
   - `https://www.googleapis.com/auth/gmail.modify` — read/search/labels/archive/read-state/Trash and manage drafts.
   - `https://www.googleapis.com/auth/gmail.send` — send a draft after explicit confirmation.
   - `https://www.googleapis.com/auth/calendar.events` — optional event reading/creation. Enable/configure this only if you want calendar routes.
5. In Credentials, create an **OAuth client ID** with application type **Web application**.
6. Add this exact authorized redirect URI:

   `http://127.0.0.1:8000/api/v1/auth/google/callback`

   Google requires the configured redirect URI to match the URI used by the application.

## 2. Add credentials locally

1. Copy `.env.example` to `.env`.
2. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the values from your OAuth client.
3. Keep the redirect URI exact. If you change the host or port, change both `.env` and the OAuth client's authorized redirect URI.
4. Do not commit `.env`. The repository `.gitignore` excludes it.

## 3. Connect the account

1. Start the app locally using `scripts/run_windows.bat` on Windows or `./scripts/run_mac.sh` on macOS (or run `uvicorn gmail_agent.main:app --host 127.0.0.1 --port 8000` from an activated virtual environment).
2. Open `http://127.0.0.1:8000/docs`.
3. Call `GET /api/v1/auth/google/login` and copy the `authorization_url` into a browser.
4. Choose your Google account and review requested permissions. If Google shows an unverified-app interstitial during private testing, verify the project/client and only continue if you trust your own configuration.
5. Complete consent. Google returns to the local callback page.
6. Call `GET /api/v1/auth/status` and confirm the returned email address matches your account.
7. Call `POST /api/v1/sync` to index recent emails.

## Troubleshooting

- **`redirect_uri_mismatch`:** exact URI mismatch; check the Cloud Console and `.env`.
- **OAuth client not configured:** fill both Google environment variables.
- **Missing refresh token:** disconnect, then start OAuth again. The code asks Google for offline access and consent; the token store preserves an existing refresh token if Google does not return a new one.
- **Testing mode / token expires:** Google OAuth apps in Testing may have refresh-token lifetime restrictions for external scopes. Reauthorize if Google invalidates the token; publish/verify only if your use case and requirements call for it.
- **Calendar errors:** ensure Google Calendar API is enabled and that the OAuth scopes include `calendar.events`; reconnect after changing scopes.
- **Gmail access denied:** confirm the Gmail API is enabled and that the granted OAuth scopes match `.env`.

Official documentation:

- Gmail scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- OAuth web-server flow: https://developers.google.com/identity/protocols/oauth2/web-server
- Gmail message listing: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
