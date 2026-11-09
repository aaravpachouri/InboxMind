# InboxMind private Windows AI worker

This worker runs Ollama on your own Windows PC and connects outward to InboxMind over HTTPS. It does not expose port 11434, open inbound firewall ports, or send your Gmail bridge secret to the worker.

## Requirements

- Windows 10/11
- Python 3.12 with the Python Launcher (`py`)
- Ollama installed and running locally
- A model installed in Ollama (default: `llama3.2:3b`; change it with `INBOXMIND_OLLAMA_MODEL` if needed)

## One-click Windows launcher

Run `START_INBOXMIND_AGENT.bat` from this folder. It creates the virtual environment if needed, installs the worker dependencies, checks that Ollama is running, and starts the worker. On first run it securely prompts for the one-time worker token and stores it in Windows Credential Manager.

To also register the worker to start automatically at Windows sign-in, run `START_INBOXMIND_AGENT.bat install-autostart`. This creates the scheduled task and then starts the worker in the current window. The first-time setup and API/model requirements below still apply.

## Install manually

1. In InboxMind, open **Settings → Private AI worker** and click **Register this PC**. Copy the one-time worker token. Do not share it.
2. Open this `worker` folder in Command Prompt or PowerShell.
3. Create a virtual environment and install requirements:
   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
4. On first run, start the worker and install its Windows sign-in task:
   ```powershell
   .venv\Scripts\python.exe run_worker.py --install-autostart
   ```
5. Paste the one-time token when prompted. Input is hidden. The worker stores it in Windows Credential Manager for the current Windows account.
6. Keep the worker window open for the current session. At future Windows sign-ins, Task Scheduler starts it automatically. InboxMind Settings should report the worker and model online after its first heartbeat.

The default API URL is `https://inboxmind-aaravpachouri.vercel.app/api/v1`. To override it, set the user environment variable `INBOXMIND_API_BASE` to an HTTPS `/api/v1` endpoint. To select another installed model, set `INBOXMIND_OLLAMA_MODEL` before starting the worker.

## Stop, revoke, or remove

- Close the worker window to stop it.
- Use **Revoke worker** in InboxMind Settings to invalidate its token. A revoked worker cannot claim jobs.
- To register again, revoke the old worker and register a new worker. Windows Credential Manager entry: `InboxMindLocalAIWorker` / `worker-token`.

The worker uses only `http://127.0.0.1:11434` for Ollama. Do not change this to a LAN or public address. AI tasks are limited to analysis, summaries, chat, and drafts. It never sends mail or modifies Gmail.
