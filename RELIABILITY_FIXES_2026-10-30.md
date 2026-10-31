# InboxMind reliability fixes — 30 October 2026

## Implemented in this snapshot

- Background Gmail sync now follows `next_page_token` rather than repeatedly requesting page one.
- The worker stores a continuation cursor in the local state table and resumes it on the next cycle, processing at most 25 pages per cycle. Once a sweep reaches the end, it resets the cursor so the next cycle can discover new mail.
- Message IDs are de-duplicated within a page sweep and the existing SQLite upsert path keeps repeated scans idempotent.
- Repeated page tokens are treated as an error rather than allowing an infinite loop. Failed page requests clear the cursor so the next cycle can restart at the newest page; the failure is recorded in the existing sync error state.
- Deterministic classification adds `posh_training`, `pocso_training`, `corporate_training`, `event_registration`, `customer_support`, and `sales_enquiry`, with the local-model prompt and normalization allowlist updated accordingly.
- Offline reply templates now recognize POSH/POCSO training, corporate training, event registration, and support/booking issues. They ask for missing operational details and avoid inventing prices, availability, or commitments.
- Added regression tests for 200-message pagination, resuming a long sweep, repeated-token safety, business categories, and conservative offline replies.

## Verification performed

- `pytest -q`: **23 passed**.
- `python -m compileall -q gmail_agent tests`: passed.
- Pagination tests use a deterministic fake Gmail provider and local temporary SQLite databases. They do not access or modify a real Gmail account.

## Known limitations

- The worker scans the configured `newer_than:<sync_window_days>d` search window. A large initial backlog is processed in 25-page chunks; it may take multiple background cycles to complete.
- Gmail API quota behavior, actual token-expiration behavior, live Apps Script connectivity, real Ollama reply quality/latency, and analytics against the user's full Gmail sent-mail history were not verified here.
- This archive includes the latest available frontend source overlaid onto the earlier complete frontend scaffold. A full frontend typecheck/build still requires the npm dependencies to be installed; no successful production build is claimed in this report.
- Classification remains deterministic keyword-based when Ollama is unavailable. It should be validated against a larger labeled corpus before being treated as measured business accuracy.


## Automatic inbox classification update

- The background worker now performs its first sync as soon as it starts (provided Gmail is connected and automatic sync is enabled), instead of waiting a full interval before the first run.
- Live Gmail list results are saved and classified with the deterministic local classifier before they are returned to the dashboard. This means newly displayed messages receive a category/priority without requiring the user to click **Analyze**.
- Manual sync now always applies the fast local classifier to messages that do not yet have saved analysis, even when the UI disables the optional model-assisted pass.
- Existing non-empty saved analysis is preserved during routine syncs rather than being overwritten with a lower-detail heuristic result on every poll.
- Added regression coverage for automatic classification across a 200-message paginated sync and preservation of previously saved richer analysis.

## Updated verification

- `pytest -q`: **24 passed**.
- `python -m compileall -q gmail_agent tests`: passed.
- Live Gmail/OAuth and a frontend production build were not run in this environment.
