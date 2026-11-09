from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from gmail_agent import public_app


@pytest.mark.parametrize(
    "url",
    [
        "https://script.google.com/macros/s/AKfycbx-example/exec",
        "https://script.google.com/macros/s/deployment_id/exec",
    ],
)
def test_bridge_url_accepts_google_apps_script_web_app_urls(url: str) -> None:
    assert public_app._validate_bridge_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://script.google.com/macros/s/deployment_id/exec",
        "https://evil.example/macros/s/deployment_id/exec",
        "https://script.google.com.evil.example/macros/s/deployment_id/exec",
        "https://script.google.com/macros/s/deployment_id/dev",
        "https://script.google.com/macros/s/deployment_id/exec?secret=leak",
        "https://user:password@script.google.com/macros/s/deployment_id/exec",
        "https://script.google.com/",
    ],
)
def test_bridge_url_rejects_noncanonical_or_unsafe_urls(url: str) -> None:
    with pytest.raises(HTTPException) as error:
        public_app._validate_bridge_url(url)
    assert error.value.status_code == 422


def test_identity_login_requests_no_gmail_scopes() -> None:
    assert public_app.SCOPES == ["openid", "email", "profile"]
    assert not any("gmail" in scope.lower() for scope in public_app.SCOPES)


def test_email_endpoint_uses_apps_script_bridge_not_direct_gmail_api() -> None:
    source = inspect.getsource(public_app.list_emails)
    assert '"list_emails"' in source
    assert "_get_user_bridge(user)" in source
    assert "googleapiclient" not in source
    assert "Credentials(" not in source



def test_per_user_bridge_read_keeps_rls_context_inside_transaction() -> None:
    source = inspect.getsource(public_app._get_user_bridge)
    assert "with pool.connection() as conn, conn.transaction():" in source
    assert source.index("_set_user_context") < source.index("FROM user_apps_script_bridges")


def test_apps_script_backed_email_and_calendar_routes_are_registered() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in public_app.app.routes}
    expected = {
        ("/api/v1/emails/{message_id}", ("GET",)),
        ("/api/v1/emails/{message_id}/archive", ("POST",)),
        ("/api/v1/emails/{message_id}/trash", ("POST",)),
        ("/api/v1/emails/{message_id}/mark-read", ("POST",)),
        ("/api/v1/emails/{message_id}/mark-unread", ("POST",)),
        ("/api/v1/labels", ("GET",)),
        ("/api/v1/calendar/events", ("GET",)),
    }
    assert expected.issubset(routes)


def test_email_list_accepts_search_and_pagination_parameters() -> None:
    signature = inspect.signature(public_app.list_emails)
    assert {"query", "page_token", "offset", "live"}.issubset(signature.parameters)



def test_hosted_core_routes_cover_frontend_persistence_operations() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in public_app.app.routes}
    expected = {
        ("/api/v1/drafts/{draft_id}/send", ("POST",)),
        ("/api/v1/drafts/{draft_id}", ("DELETE",)),
        ("/api/v1/memory", ("GET",)),
        ("/api/v1/memory", ("POST",)),
        ("/api/v1/memory/{memory_id}", ("DELETE",)),
        ("/api/v1/feedback", ("GET",)),
        ("/api/v1/feedback", ("POST",)),
        ("/api/v1/sync", ("POST",)),
        ("/api/v1/briefing/daily", ("GET",)),
        ("/api/v1/chat", ("POST",)),
        ("/api/v1/emails/{message_id}/draft-reply", ("POST",)),
    }
    assert expected.issubset(routes)


def test_ai_summary_is_dispatched_only_to_the_private_worker() -> None:
    source = inspect.getsource(public_app.summarize_email_unavailable)
    assert "_run_local_ai_job" in source
    assert "_require_csrf" in source
    worker_gate = inspect.getsource(public_app._require_online_ai_worker)
    assert "HTTPException(503" in worker_gate
    assert "no AI result was fabricated" in worker_gate


def test_daily_briefing_uses_per_user_gmail_bridge_and_private_worker() -> None:
    source = inspect.getsource(public_app.daily_briefing)
    assert '"list_emails"' in source
    assert "_get_user_bridge(user)" in source
    assert "_get_bridge_email(user" in source
    assert '_run_local_ai_job(user_id, "analyze_email"' in source
    assert '"emails_indexed_in_period"' in source
    assert '"urgent_or_high"' in source
    assert "AI email analysis is not enabled on the hosted backend" not in source


def test_daily_briefing_rejects_invalid_worker_json_without_fabricating() -> None:
    source = inspect.getsource(public_app.daily_briefing)
    assert "Private AI worker returned invalid JSON" in source
    assert "No result was fabricated" in source


def test_reply_body_formatter_preserves_and_adds_readable_paragraphs() -> None:
    body = (
        "I hope you are having a good week. I am following up regarding the recent sign-in "
        "notification for my Vercel account. Could you share the details available about this "
        "event? Specifically, I would like to know the sign-in time, associated IP address, "
        "whether the activity was authorized, and whether any account settings were modified."
    )
    formatted = public_app._format_reply_body(body)
    assert "\\n\\n" in formatted
    assert "sign-in notification" in formatted
    assert "account settings were modified" in formatted


def test_reply_body_formatter_preserves_existing_paragraphs_and_removes_model_labels() -> None:
    formatted = public_app._format_reply_body(
        "Suggested reply: Hello, thanks for the update.\\n\\nI will review this and get back to you."
    )
    assert formatted == "Hello, thanks for the update.\\n\\nI will review this and get back to you."


def test_reply_generation_prompt_requires_contextual_professional_paragraphs() -> None:
    source = inspect.getsource(public_app.draft_reply_unavailable)
    assert "context-aware business email reply" in source
    assert "Avoid repeating the sender's entire message" in source
    assert "2-4 short paragraphs" in source
    assert "_format_reply_body" in source


def test_task_candidate_requires_verbatim_source_evidence_and_recipient_confidence() -> None:
    email = {"body_text": "Please send the signed proposal by Friday so we can proceed."}
    valid = {
        "title": "Send the signed proposal",
        "description": "Send the signed proposal to the sender.",
        "due_date": None,
        "priority": "high",
        "confidence": 0.91,
        "evidence_quote": "Please send the signed proposal by Friday",
        "owner": "recipient",
    }
    accepted = public_app._verified_task_candidate(valid, email, {"id": "m1", "subject": "Proposal"})
    assert accepted is not None
    assert accepted["source_email_id"] == "m1"
    assert accepted["evidence_quote"] == valid["evidence_quote"]

    invented_quote = {**valid, "evidence_quote": "Please approve the payment immediately"}
    assert public_app._verified_task_candidate(invented_quote, email) is None
    low_confidence = {**valid, "confidence": 0.4}
    assert public_app._verified_task_candidate(low_confidence, email) is None
    short_quote = {**valid, "evidence_quote": "send it"}
    assert public_app._verified_task_candidate(short_quote, email) is None


def test_task_candidate_rejects_invalid_due_date_without_rejecting_grounded_task() -> None:
    email = {"body_text": "Please send the signed proposal by Friday so we can proceed."}
    candidate = {
        "title": "Send signed proposal",
        "confidence": 0.9,
        "evidence_quote": "Please send the signed proposal by Friday",
        "due_date": "next Friday",
        "priority": "medium",
    }
    accepted = public_app._verified_task_candidate(candidate, email)
    assert accepted is not None
    assert accepted["due_date"] is None


def test_daily_briefing_summary_is_structured_and_action_oriented() -> None:
    summary = public_app._build_briefing_summary(
        [
            {"subject": "Security alert", "priority": "urgent", "ai_summary": "Review sign-in.", "action_needed": True, "is_unread": True},
            {"subject": "Meeting notes", "priority": "normal", "reason": "Confirm attendance.", "action_needed": True, "is_unread": False},
        ],
        [{"title": "Submit proposal"}],
        24,
    )
    assert "Priority attention:" in summary
    assert "Unread items needing attention:" in summary
    assert "Other requested actions:" in summary
    assert "Existing open commitments:" in summary


def test_task_interpreter_requires_owner_evidence_and_explicit_deadlines() -> None:
    source = inspect.getsource(public_app.analyze_email_unavailable)
    assert "exact verbatim quote" in source
    assert "Identify who must act" in source
    assert "_verified_task_candidate" in source
    assert "tasks_created\": 0" in source


def test_daily_briefing_exposes_coverage_and_separate_action_sections() -> None:
    source = inspect.getsource(public_app.daily_briefing)
    assert '"priority_attention"' in source
    assert '"unread_needing_action"' in source
    assert '"emails_analyzed"' in source
    assert '"truncated"' in source
