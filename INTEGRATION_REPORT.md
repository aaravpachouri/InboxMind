# Integration report

## Included
- InboxMind frontend from the AutoClassification update.
- FastAPI backend from the AutoClassification update.
- Recovered Apps Script Gmail bridge client and its tests.
- Bridge-aware backend settings, connection status, and OAuth-route safeguards.
- Windows launcher scripts for the unified root folder.

## Verification performed in this environment
- Backend test suite: **29 passed**.
- Python imports/syntax exercised by pytest.
- Frontend production build: **not verified**; dependency installation did not finish in this environment.
- Live Gmail bridge: **not tested from this package** because real local bridge credentials are intentionally excluded.

## Important local setup
Copy the existing `APPS_SCRIPT_BRIDGE_URL` and `APPS_SCRIPT_BRIDGE_SECRET` from your old backend `.env` into `backend/.env`. Do not upload or share that file. The existing database and credentials are not bundled.
