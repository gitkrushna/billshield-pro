"""Real Postgres adapter tests. Absence of a restricted test DB is explicitly skipped."""

import os
from uuid import uuid4

import psycopg
import pytest
from billshield.db import TenantSession
from billshield.jobs import PostgresJobs
from billshield.llm import DeepSeekLLM, LiveModelCallsDisabled
from psycopg.rows import dict_row


@pytest.fixture
def scope():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip(
            "blocked: TEST_DATABASE_URL for restricted billshield_app role is missing"
        )
    with (
        psycopg.connect(dsn, row_factory=dict_row) as conn,
        conn.transaction(force_rollback=True),
    ):
        role = conn.execute(
            "SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles "
            "WHERE rolname=current_user"
        ).fetchone()
        assert role == {
            "name": "billshield_app",
            "rolsuper": False,
            "rolbypassrls": False,
        }
        user = conn.execute(
            "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
            (
                "https://jobs-fixture.invalid",
                str(uuid4()),
                "jobs-fixture@example.invalid",
            ),
        ).fetchone()["id"]
        conn.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
        org = conn.execute(
            "SELECT billshield.create_org(%s) AS id",
            ("TEST FIXTURE: jobs (rolled back)",),
        ).fetchone()["id"]
        conn.execute("SELECT set_config('app.org_id',%s,true)", (str(org),))
        yield TenantSession(conn, user, org, "owner")


def test_idempotent_job_and_stale_worker_fencing(scope):
    jobs = PostgresJobs()
    first = jobs.enqueue(scope, "fixture", {"fixture": True}, "fixture-idempotency")
    assert (
        jobs.enqueue(scope, "fixture", {"fixture": True}, "fixture-idempotency")
        == first
    )
    lease = jobs.claim(scope)
    assert lease["id"] == first and lease["attempts"] == 1
    assert jobs.claim(scope) is None
    assert not jobs.complete(scope, first, uuid4())
    assert jobs.complete(scope, first, lease["lease_token"])
    assert not jobs.complete(scope, first, lease["lease_token"])


def test_expired_lease_is_reclaimed_with_new_token(scope):
    jobs = PostgresJobs()
    job_id = jobs.enqueue(scope, "fixture", {})
    old = jobs.claim(scope)
    scope.connection.execute(
        "UPDATE billshield.jobs SET leased_until=now()-interval '1 second' WHERE id=%s",
        (job_id,),
    )
    new = jobs.claim(scope)
    assert new["lease_token"] != old["lease_token"] and new["attempts"] == 2
    assert not jobs.complete(scope, job_id, old["lease_token"])
    assert jobs.fail(scope, job_id, new["lease_token"], "fixture_failure")


def test_m1_model_gate_is_unconditional():
    with pytest.raises(LiveModelCallsDisabled):
        DeepSeekLLM().complete([])
