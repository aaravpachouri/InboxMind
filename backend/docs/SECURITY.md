# Security notes

- Keep the server loopback-only. Do not deploy this configuration unchanged to a public host.
- `.env`, the encrypted token file, and its key must remain private. Never commit them.
- The token is encrypted at rest; the app's local SQLite database currently stores email content and indexed document content as plaintext. Enable FileVault and protect backups.
- Run the application under your own macOS account, not as an administrator/root user.
- Treat attachments and email content as untrusted. Open downloaded attachments only if you trust the sender and file type.
- Email-driven task extraction can produce false positives. Review task dates/actions before relying on them.
- Sending requires the user to create/review a draft and explicitly confirm the send endpoint. AI does not autonomously invoke actions.
- Trash is reversible through Gmail; permanent message deletion is intentionally not exposed.
- The background worker never sends, trashes, archives, or changes read state.
- Disconnect removes the local OAuth token and attempts Google's token revocation; it retains the local email index/tasks. Delete the `data/` folder manually if you want to erase cached data too, after stopping the app.
