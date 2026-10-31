# API guide for the future frontend

Base URL: `http://127.0.0.1:8000/api/v1`

The interactive OpenAPI UI at `http://127.0.0.1:8000/docs` is the source of truth for complete request and response schemas.

## First-run flow

1. `GET /auth/status` — determine whether Gmail is connected.
2. `GET /auth/google/login` — open the returned `authorization_url` in a browser.
3. Google redirects to the configured local callback. Then call `GET /auth/status` again.
4. `POST /sync` with `{"max_results":50,"query":"newer_than:30d","analyze":true}` — index recent messages and run the fast first-pass analysis.
5. Repeat `POST /sync` with the returned `next_page_token` to page through a large mailbox. For a broad index, use query `in:anywhere`; each request is limited to 100 messages. The search query uses Gmail search syntax.
6. Read `GET /insights`, `GET /briefing/daily`, `GET /tasks`, `GET /notifications`, and `GET /emails` to populate the dashboard.

## Main read routes

- `GET /emails?query=...&limit=50&offset=0` — local cached index; optional `unread_only`, `category`, and `priority` filters.
- `GET /emails?live=true&query=...` — query Gmail directly and refresh local cache for returned messages. `page_token` supports pagination.
- `GET /emails/{message_id}` — details, headers, body text, attachments metadata, and current analysis.
- `GET /emails/{message_id}/thread` — entire Gmail thread.
- `POST /emails/{message_id}/analyze` — local AI analysis if Ollama is ready; otherwise heuristic fallback. Body: `{"force":true}`.
- `POST /emails/{message_id}/summarize` — concise summary.
- `POST /chat` — answer a natural-language question using local indexed email evidence. Example: `{"message":"What important messages need a reply today?"}`.
- `GET /follow-ups?minimum_wait_hours=48` — sent threads with no later reply found in the local index. It is a suggestion list, not a guarantee that no reply exists outside the indexed data.
- `GET /briefing/daily?hours=24` — inbox and task briefing for the dashboard.

## Drafting and sending

1. `POST /emails/{message_id}/draft-reply` with `{"instruction":"Reply politely and ask for the deadline","create_in_gmail":true}` to create a reviewed draft.
2. Or use `POST /drafts` to compose a new email. Drafts can be listed, read, and edited.
3. Show the complete recipient, subject, and body to the user for review.
4. Only after explicit user approval, call `POST /drafts/{draft_id}/send` with `{"confirm_send":true}`.

An email body or AI recommendation must never be treated as permission to send. A message should only be sent after the user approves the actual draft.

## Actions

- `POST /emails/{id}/labels` with `add_labels` and `remove_labels`.
- `POST /emails/{id}/archive` and `POST /emails/{id}/trash` require `{"confirm":true}`.
- `POST /emails/{id}/mark-read` and `/mark-unread` update read state.
- `POST /emails/bulk` first defaults to preview with `confirm=false`; review the matched messages, then submit a separate request with `confirm=true`. Actions are capped by server limits. Trash moves messages to Trash; permanent deletion is not implemented.
- `POST /follow-ups/{message_id}/draft` makes a follow-up draft from a sent message; it does not send it.

## Local data and preferences

- `GET/POST /tasks`, `GET/PATCH/DELETE /tasks/{id}` — task list; deletion requires confirmation.
- `GET/POST /memory`, `DELETE /memory/{id}` — inspect and edit user memory. Deletion requires confirmation.
- `POST /feedback` — store explicit feedback locally; recent feedback can be supplied as context to future model analysis/drafting.
- `POST /files/index`, `GET /files/search?query=...` — index/search files under the configured local directory.
- `GET /attachments/{message_id}` — list attachments; download or analyze a supported attachment only after confirmation.
- `GET/POST /calendar/events` — list upcoming events or create an event on the connected account's primary calendar.
- `GET /audit`, `GET /notifications`, `GET/PATCH /settings` — local activity, notifications, and preferences.

## Error handling

- `409`: Gmail is not connected or the action conflicts with the current draft state.
- `400`: explicit confirmation missing or OAuth flow problem.
- `404`: requested cached record not found.
- `413`: attachment exceeds the configured limit.
- `415`: unsupported attachment format.
- `422`: malformed request or no extractable text.
- `502`: Google API or sync operation failed.

The future frontend should display errors from `detail`, should never expose OAuth client secrets or stored token data, and should show the source/provider of AI output (local model versus heuristic fallback).
