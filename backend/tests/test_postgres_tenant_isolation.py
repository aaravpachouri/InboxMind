from __future__ import annotations

import os
import uuid

import psycopg
import pytest


DATABASE_URL = os.getenv("INBOXMIND_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="Set INBOXMIND_TEST_DATABASE_URL to run real PostgreSQL tenant-isolation tests.",
)


def _set_tenant(conn: psycopg.Connection, user_id: str) -> None:
    conn.execute("SELECT set_config('app.current_user_id', %s, true)", (user_id,))


def test_postgres_rls_isolates_two_users_and_rejects_cross_tenant_writes():
    # CI connects as a non-owner, non-superuser role. The test runs in one
    # transaction and rolls back, leaving the disposable database clean.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            suffix = uuid.uuid4().hex
            user_a = conn.execute(
                """INSERT INTO app_users(google_sub,email,display_name)
                   VALUES (%s,%s,'Tenant A') RETURNING id""",
                (f"ci-a-{suffix}", f"tenant-a-{suffix}@example.test"),
            ).fetchone()[0]
            user_b = conn.execute(
                """INSERT INTO app_users(google_sub,email,display_name)
                   VALUES (%s,%s,'Tenant B') RETURNING id""",
                (f"ci-b-{suffix}", f"tenant-b-{suffix}@example.test"),
            ).fetchone()[0]

            _set_tenant(conn, str(user_a))
            conn.execute(
                "INSERT INTO user_memories(user_id,category,key,value) VALUES (%s,'test',%s,'A secret')",
                (user_a, suffix),
            )
            conn.execute(
                "INSERT INTO user_settings(user_id,settings) VALUES (%s,'{\"owner\":\"A\"}'::jsonb)",
                (user_a,),
            )
            conn.execute(
                "INSERT INTO user_tasks(user_id,title) VALUES (%s,'A private task')",
                (user_a,),
            )
            conn.execute(
                "INSERT INTO user_drafts(user_id,payload) VALUES (%s,'{\"subject\":\"A\"}'::jsonb)",
                (user_a,),
            )
            conn.execute(
                "INSERT INTO user_feedback(user_id,feedback_text) VALUES (%s,'A private feedback')",
                (user_a,),
            )

            _set_tenant(conn, str(user_b))
            conn.execute(
                "INSERT INTO user_memories(user_id,category,key,value) VALUES (%s,'test',%s,'B secret')",
                (user_b, suffix),
            )
            conn.execute(
                "INSERT INTO user_settings(user_id,settings) VALUES (%s,'{\"owner\":\"B\"}'::jsonb)",
                (user_b,),
            )
            conn.execute(
                "INSERT INTO user_tasks(user_id,title) VALUES (%s,'B private task')",
                (user_b,),
            )
            conn.execute(
                "INSERT INTO user_drafts(user_id,payload) VALUES (%s,'{\"subject\":\"B\"}'::jsonb)",
                (user_b,),
            )
            conn.execute(
                "INSERT INTO user_feedback(user_id,feedback_text) VALUES (%s,'B private feedback')",
                (user_b,),
            )

            _set_tenant(conn, str(user_a))
            assert conn.execute(
                "SELECT value FROM user_memories WHERE key=%s", (suffix,)
            ).fetchall() == [("A secret",)]
            assert conn.execute("SELECT settings->>'owner' FROM user_settings").fetchall() == [("A",)]
            assert conn.execute("SELECT title FROM user_tasks").fetchall() == [("A private task",)]
            assert conn.execute("SELECT payload->>'subject' FROM user_drafts").fetchall() == [("A",)]
            assert conn.execute("SELECT feedback_text FROM user_feedback").fetchall() == [("A private feedback",)]

            # PostgreSQL WITH CHECK policies must reject a forged user_id.
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO user_memories(user_id,category,key,value) VALUES (%s,'test',%s,'forged')",
                        (user_b, f"forged-{suffix}"),
                    )

            # With no tenant context, reads are empty and writes are denied.
            _set_tenant(conn, "")
            assert conn.execute("SELECT id FROM user_memories").fetchall() == []
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO user_feedback(user_id,feedback_text) VALUES (%s,'no context')",
                        (user_a,),
                    )
