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
                """INSERT INTO user_apps_script_bridges
                   (user_id,google_account_email,bridge_url,bridge_secret_ciphertext)
                   VALUES (%s,%s,%s,%s)""",
                (user_a, f"gmail-a-{suffix}@example.test",
                 f"https://script.google.com/macros/s/deployment-a-{suffix}/exec", b"cipher-a"),
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
                """INSERT INTO user_apps_script_bridges
                   (user_id,google_account_email,bridge_url,bridge_secret_ciphertext)
                   VALUES (%s,%s,%s,%s)""",
                (user_b, f"gmail-b-{suffix}@example.test",
                 f"https://script.google.com/macros/s/deployment-b-{suffix}/exec", b"cipher-b"),
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
            assert conn.execute(
                "SELECT google_account_email,bridge_url FROM user_apps_script_bridges"
            ).fetchall() == [(
                f"gmail-a-{suffix}@example.test",
                f"https://script.google.com/macros/s/deployment-a-{suffix}/exec",
            )]
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

def test_postgres_ai_worker_jobs_are_isolated_and_bound_to_the_leasing_worker():
    # Exercise the exact job ownership guarantees used by claim/complete routes.
    # Worker tokens are not stored in plaintext; this test uses opaque hashes.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            suffix = uuid.uuid4().hex
            user_a = conn.execute(
                """INSERT INTO app_users(google_sub,email,display_name)
                   VALUES (%s,%s,'Worker Tenant A') RETURNING id""",
                (f"worker-a-{suffix}", f"worker-a-{suffix}@example.test"),
            ).fetchone()[0]
            user_b = conn.execute(
                """INSERT INTO app_users(google_sub,email,display_name)
                   VALUES (%s,%s,'Worker Tenant B') RETURNING id""",
                (f"worker-b-{suffix}", f"worker-b-{suffix}@example.test"),
            ).fetchone()[0]

            worker_a = conn.execute(
                """INSERT INTO user_ai_workers(user_id,token_hash,device_name)
                   VALUES (%s,%s,'A PC') RETURNING id""",
                (user_a, b"hash-a-" + suffix.encode()),
            ).fetchone()[0]
            worker_b = conn.execute(
                """INSERT INTO user_ai_workers(user_id,token_hash,device_name)
                   VALUES (%s,%s,'B PC') RETURNING id""",
                (user_b, b"hash-b-" + suffix.encode()),
            ).fetchone()[0]

            _set_tenant(conn, str(user_a))
            job_a = conn.execute(
                """INSERT INTO user_ai_jobs(user_id,job_type,payload,status)
                   VALUES (%s,'chat',%s,'queued') RETURNING id""",
                (user_a, b"encrypted-a"),
            ).fetchone()[0]
            _set_tenant(conn, str(user_b))
            job_b = conn.execute(
                """INSERT INTO user_ai_jobs(user_id,job_type,payload,status)
                   VALUES (%s,'chat',%s,'queued') RETURNING id""",
                (user_b, b"encrypted-b"),
            ).fetchone()[0]

            # Worker A sees and leases only A's job, even when querying broadly.
            _set_tenant(conn, str(user_a))
            visible = conn.execute(
                "SELECT id,user_id FROM user_ai_jobs WHERE status='queued'"
            ).fetchall()
            assert [row[0] for row in visible] == [job_a]
            leased = conn.execute(
                """UPDATE user_ai_jobs SET status='leased',worker_id=%s,
                          lease_until=now()+interval '2 minutes'
                   WHERE id=%s AND user_id=%s AND status='queued'
                   RETURNING id""",
                (worker_a, job_a, user_a),
            ).fetchone()
            assert leased[0] == job_a

            # Cross-tenant claim/update is invisible and cannot mutate B's job.
            forged_claim = conn.execute(
                """UPDATE user_ai_jobs SET status='leased',worker_id=%s
                   WHERE id=%s AND user_id=%s RETURNING id""",
                (worker_a, job_b, user_b),
            ).fetchall()
            assert forged_claim == []
            assert conn.execute(
                "SELECT status FROM user_ai_jobs WHERE id=%s", (job_b,)
            ).fetchall() == []

            # Even within A, a different worker cannot complete the leased job.
            wrong_worker = conn.execute(
                """UPDATE user_ai_jobs SET status='completed',result=%s
                   WHERE id=%s AND user_id=%s AND worker_id=%s AND status='leased'
                   RETURNING id""",
                (b"forged-result", job_a, user_a, worker_b),
            ).fetchall()
            assert wrong_worker == []
            correct_worker = conn.execute(
                """UPDATE user_ai_jobs SET status='completed',result=%s
                   WHERE id=%s AND user_id=%s AND worker_id=%s AND status='leased'
                   RETURNING id""",
                (b"valid-result", job_a, user_a, worker_a),
            ).fetchone()
            assert correct_worker[0] == job_a
