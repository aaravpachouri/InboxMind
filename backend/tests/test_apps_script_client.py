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


def test_two_tenant_bridge_clients_never_share_deployment_or_secret():
    settings_a = Settings(
        apps_script_bridge_url="https://script.google.com/macros/s/deploymentA/exec",
        apps_script_bridge_secret="a" * 43,
        apps_script_bridge_timeout_seconds=12,
    )
    settings_b = Settings(
        apps_script_bridge_url="https://script.google.com/macros/s/deploymentB/exec",
        apps_script_bridge_secret="b" * 43,
        apps_script_bridge_timeout_seconds=12,
    )
    client_a = AppsScriptGmailClient(settings_a)
    client_b = AppsScriptGmailClient(settings_b)
    calls = []

    def request_a(payload):
        calls.append(("tenant-a", client_a.url, payload["secret"], payload["action"]))
        return {"ok": True, "result": {"email": "tenant-a@example.test"}}

    def request_b(payload):
        calls.append(("tenant-b", client_b.url, payload["secret"], payload["action"]))
        return {"ok": True, "result": {"email": "tenant-b@example.test"}}

    client_a._request = request_a
    client_b._request = request_b

    assert client_a.profile()["email"] == "tenant-a@example.test"
    assert client_b.profile()["email"] == "tenant-b@example.test"
    assert calls == [
        ("tenant-a", settings_a.apps_script_bridge_url, "a" * 43, "profile"),
        ("tenant-b", settings_b.apps_script_bridge_url, "b" * 43, "profile"),
    ]
    assert client_a.url != client_b.url
    assert client_a.secret != client_b.secret


def test_gmail_list_page_size_matches_apps_script_limit():
    client = make_client()
    seen = {}

    def fake_request(payload):
        seen.update(payload)
        return {"ok": True, "result": {"items": [], "total_estimate": 0}}

    client._request = fake_request
    client.list_emails(max_results=50)
    assert seen["params"]["max_results"] == 10
