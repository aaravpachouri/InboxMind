INBOXMIND AUTO-SYNC + SPEED UPDATE

TARGET: the original InboxMind_Unified project root (the folder containing backend and frontend).
Do not apply this to the temporary Reliability_Update project.

INSTALL
1. Stop the original backend and frontend terminals with Ctrl+C.
2. Extract this ZIP directly into:
   C:\Users\Hp\Downloads\InboxMind_Unified\InboxMind_Unified
   The ZIP adds an installer and a uniquely named patch folder; it does not contain .env, database, OAuth tokens, or node_modules.
3. In a VS Code PowerShell terminal opened at that project root, run:
   powershell -NoProfile -ExecutionPolicy Bypass -File ".\Apply-InboxMind-AutoSync-Fast.ps1"
4. Wait for backend tests and frontend production build to finish.
5. Restart the original backend and frontend.
6. Check http://127.0.0.1:8000/api/v1/health and confirm background_sync.enabled is true.

WHAT IT CHANGES
- Enables background sync in both .env and the saved user settings (saved settings override .env).
- Runs sync every 5 minutes, using batches of 10 messages and at most 3 pages per cycle to reduce quota spikes.
- Limits local Ollama model upgrades to 3 messages per cycle.
- Reuses one Gmail API service client for each page rather than rebuilding it per message.
- Avoids loading every email ID into memory on each cycle; checks only IDs in the current batch.
- Preserves approval gates for sending and destructive actions.

SAFETY
- Before applying, the script creates a local backup ZIP in Downloads containing changed source files, the current .env, and an SQLite online backup of the configured database.
- It changes only AUTO_SYNC_ENABLED, SYNC_INTERVAL_SECONDS, and SYNC_BATCH_SIZE in .env; other settings and secrets are preserved.
- It updates only auto_sync_enabled and sync_interval_seconds in saved user settings; all other settings are preserved.
- It runs the backend test suite and frontend production build after applying.

TEST STATUS
- Backend test suite in the build environment: 33 passed.
- Frontend was previously built successfully on the user's Windows setup after the TypeScript annotation fix. This installer runs the frontend build again on that Windows machine.
- Live Gmail sync/quota behavior is not claimed verified by these offline tests.
