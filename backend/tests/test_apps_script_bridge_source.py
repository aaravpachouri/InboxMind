from __future__ import annotations

from pathlib import Path


BRIDGE = (
    Path(__file__).resolve().parents[2]
    / "apps-script"
    / "InboxMind_Gmail_Bridge_Full_Rewrite.gs"
)


def test_bridge_authenticates_before_dispatch_and_fails_closed() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    do_post = source.split("function doPost(e) {", 1)[1].split("\nfunction jsonOutput_", 1)[0]
    assert do_post.index("getProperty(\"BRIDGE_SECRET\")") < do_post.index("dispatchAction_(")
    assert "if (!savedSecret || !constantTimeEqual_(request.secret, savedSecret))" in do_post
    assert "Invalid parameters" in do_post
    assert "Request failed. Check the action and parameters." in do_post
    assert "String(err && err.message" in do_post  # bounded server-side diagnostic only
    assert "err.stack" not in do_post


def test_bridge_has_a_closed_action_allowlist_and_confirmation_guards() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    dispatch = source.split("function dispatchAction_(action, p) {", 1)[1].split(
        "\nfunction requiredString_", 1
    )[0]
    assert 'default: throw new Error("Unsupported action: " + action);' in dispatch
    for action in (
        "list_emails", "get_email", "get_thread", "send_draft",
        "delete_draft", "send_message", "create_calendar_event",
    ):
        assert f'case "{action}"' in dispatch
    assert 'requireConfirmation_(p, "Sending a draft")' in dispatch
    assert 'requireConfirmation_(p, "Deleting a draft")' in dispatch
    assert 'requireConfirmation_(p, "Sending an email")' in dispatch
    assert 'requireConfirmation_(p, "Creating a calendar event")' in dispatch


def test_bridge_bounds_identifiers_payloads_and_bulk_operations() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "^[A-Za-z0-9_-]{1,256}$" in source
    assert "function boundedText_" in source
    assert "function boundedStringArray_" in source
    assert "ids.length > MAX_MESSAGES" not in source
    assert 'boundedStringArray_(p.message_ids, "message_id", MAX_MESSAGES, 256)' in source
    assert 'boundedText_(p.body_text, "body_text", 500000, false)' in source
    assert "Too many recipients" in source


def test_bridge_does_not_expose_raw_exception_details_to_callers() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    do_post = source.split("function doPost(e) {", 1)[1].split("\nfunction jsonOutput_", 1)[0]
    assert 'error: "Request failed. Check the action and parameters."' in do_post
    assert 'error: String(err && err.message' not in do_post
