from __future__ import annotations

import pytest

from gmail_agent.apps_script_client import AppsScriptGmailClient
from gmail_agent.config import Settings


URL = "https://script.google.com/macros/s/AKfycbxExample/exec"
SECRET = "s" * 43


def make_client() -> AppsScriptGmailClient:
    settings = Settings(
        apps_script_bridge_url=URL,
        apps_script_bridge_secret=SECRET,
        apps_script_bridge_timeout_seconds=12,
    )
    return AppsScriptGmailClient(settings)


def test_profile_uses_authenticated_bridge_post():
    client = make_client()
    seen = {}

    def fake_request(payload):
        seen.update(payload)
        return {"ok": True, "result": {"email": "person@example.com", "messages_total": 12, "threads_total": 7}}

    client._request = fake_request
    result = client.profile()
    assert result["email"] == "person@example.com"
    assert result["messages_total"] == 12
    assert seen["secret"] == SECRET
    assert seen["action"] == "profile"


def test_bridge_error_is_reported_without_secret():
    client = make_client()
    client._request = lambda payload: {"ok": False, "error": "Unauthorized"}
    with pytest.raises(RuntimeError, match="Unauthorized"):
        client.profile()


def test_untrusted_url_is_rejected():
    settings = Settings(apps_script_bridge_url="https://example.com/not-the-bridge", apps_script_bridge_secret=SECRET)
    with pytest.raises(RuntimeError, match="Google Apps Script Web app URL"):
        AppsScriptGmailClient(settings)


def test_trash_requires_bridge_confirmation_flag():
    client = make_client()
    seen = {}

    def fake_request(payload):
        seen.update(payload)
        return {"ok": True, "result": {"success": True}}

    client._request = fake_request
    client.trash("message-1")
    assert seen["action"] == "trash"
    assert seen["params"]["confirmed"] is True


def test_system_trash_label_cannot_be_applied_via_generic_label_route():
    client = make_client()
    with pytest.raises(RuntimeError, match="explicit confirm-protected Trash action"):
        client.modify_labels("message-1", ["TRASH"], [])
