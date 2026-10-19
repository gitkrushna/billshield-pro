"""Inline worker contract and restricted PostgreSQL integration, without API routes."""

import asyncio
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from billshield.db import AuthorizationError, TenantSession
from billshield.execution import (
    CheckInProgress,
    CheckRateLimited,
    Deadline,
    InlineCheckRunner,
    StaleLease,
)
from billshield.jobs import PostgresJobs
from billshield.pipeline import EnginePipeline
from billshield.ports import Identity
from dotenv import load_dotenv
from psycopg.rows import dict_row
from test_engine import evidence as evidence  # noqa: PLC0414
from test_pipeline import RecordedModel


def test_deadline_attempts_share_the_global_budget():
    assert 59 < Deadline.start().attempt_timeout() <= 60
    assert 0 < Deadline(monotonic() + 0.05).attempt_timeout() < 0.051
    with pytest.raises(TimeoutError):
        Deadline(monotonic() - 1).remaining()


def test_hourly_allowance_configuration_is_positive_integer():
    assert InlineCheckRunner(None).checks_per_hour == 30
    for invalid in (0, -1, True, 1.5, "30", None):
        with pytest.raises(ValueError, match="positive integer"):
            InlineCheckRunner(None, checks_per_hour=invalid)


@pytest.fixture
def inline_scope():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.local", override=False)
    if os.getenv("RUN_DB_INTEGRATION") != "1":
        pytest.skip("blocked: restricted DB integration not enabled")
    dsn = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        pytest.fail("blocked: missing restricted database configuration")
    identity = Identity(
        "https://execution-fixture.invalid", str(uuid4()), "m2@fixture.invalid"
    )
    try:
        connection = psycopg.connect(dsn, row_factory=dict_row, connect_timeout=15)
    except psycopg.Error:
        pytest.fail("blocked: restricted DB connection unavailable", pytrace=False)
    with connection, connection.transaction(force_rollback=True):
        role = connection.execute(
            "SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles "
            "WHERE rolname=current_user"
        ).fetchone()
        assert role == {
            "name": "billshield_app",
            "rolsuper": False,
            "rolbypassrls": False,
        }
        user = connection.execute(
            "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
            (identity.issuer, identity.subject, identity.email),
        ).fetchone()["id"]
        connection.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
        org = connection.execute(
            "SELECT billshield.create_org('TEST FIXTURE: M2 execution (rolled back)') AS id"
        ).fetchone()["id"]
        connection.execute("SELECT set_config('app.org_id',%s,true)", (str(org),))
        product = connection.execute(
            "INSERT INTO billshield.products(org_id,created_by,name) VALUES(%s,%s,%s) RETURNING id",
            (org, user, "TEST FIXTURE: execution"),
        ).fetchone()["id"]
        law = connection.execute(
            "SELECT id FROM billshield.law_snapshots ORDER BY id LIMIT 1"
        ).fetchone()
        if not law:
            pytest.fail("blocked: missing seeded law snapshot")

        class Transactions:
            active = False
            exited = 0

            @contextmanager
            def tenant(self, supplied_identity, supplied_org):
                assert supplied_identity == identity and supplied_org == org
                assert not self.active
                self.active = True
                try:
                    # Savepoints permit fixture rollback. Production Postgres.tenant
                    # uses separate connections and commits at these same boundaries.
                    with connection.transaction():
                        yield TenantSession(connection, user, org, "owner")
                finally:
                    self.active = False
                    self.exited += 1

        database = Transactions()

        def draft():
            return connection.execute(
                "INSERT INTO billshield.checks(org_id,user_id,product_id,as_of_date,jurisdiction) "
                "VALUES(%s,%s,%s,'2025-09-22','IN-GA') RETURNING id",
                (org, user, product),
            ).fetchone()["id"]

        snapshot = {
            "result": "Need more info",
            "confidence_band": "Low",
            "law_snapshot_id": law["id"],
            "prompt_version": "fixture-v1",
            "model_id": "deepseek-flash",
            "expected_model_version": "fixture-only",
            "reason": "source_missing",
            "policy_version": "fixture-v1",
        }
        yield database, identity, org, connection, draft, snapshot


def test_targeted_claim_commit_boundary_and_idempotent_report(inline_scope):
    database, identity, org, conn, draft, snapshot = inline_scope
    runner = InlineCheckRunner(database)
    check = draft()
    calls = []
    with database.tenant(identity, org) as scope:
        unrelated = PostgresJobs().enqueue(scope, "other_fixture", {})

    async def engine(request, deadline):
        assert not database.active and database.exited >= 2
        assert 0 < deadline.remaining() <= 240
        calls.append(request)
        running = conn.execute(
            "SELECT status,attempts FROM billshield.jobs WHERE kind='check' AND org_id=%s",
            (org,),
        ).fetchone()
        assert running == {"status": "running", "attempts": 1}
        request["fact"] = "engine may mutate only its own copy"
        return snapshot

    request = {"fact": "fixture"}
    issued = asyncio.run(runner.run(identity, org, check, "same", request, engine))
    assert request == {"fact": "fixture"}
    assert (
        conn.execute(
            "SELECT needs_review FROM billshield.checks WHERE id=%s", (check,)
        ).fetchone()["needs_review"]
        is True
    )
    issued["reason"] = "caller mutation"
    again = asyncio.run(runner.run(identity, org, check, "same", request, engine))
    assert again == snapshot and len(calls) == 1
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM billshield.reports WHERE check_id=%s", (check,)
        ).fetchone()["n"]
        == 1
    )
    events = conn.execute(
        "SELECT event_type,payload FROM billshield.audit_events WHERE check_id=%s",
        (check,),
    ).fetchall()
    assert len(events) == 1 and events[0]["event_type"] == "check_issued"
    assert set(events[0]["payload"]) == {
        "law_snapshot_id",
        "prompt_version",
        "policy_version",
        "model_id",
        "expected_model_version",
        "resolved_model_version",
    }
    assert (
        conn.execute(
            "SELECT status FROM billshield.jobs WHERE id=%s", (unrelated,)
        ).fetchone()["status"]
        == "queued"
    )
    with pytest.raises(ValueError, match="different request"):
        asyncio.run(
            runner.run(identity, org, check, "same", {"fact": "different"}, engine)
        )
    with pytest.raises(ValueError, match="already has an execution"):
        asyncio.run(runner.run(identity, org, check, "different-key", request, engine))
    assert len(calls) == 1


def test_stale_worker_cannot_issue_and_authenticated_retry_recovers(inline_scope):
    database, identity, org, conn, draft, snapshot = inline_scope
    runner = InlineCheckRunner(database)
    check = draft()

    async def late_engine(request, deadline):
        conn.execute(
            "UPDATE billshield.jobs SET leased_until=clock_timestamp()-interval '1 second' "
            "WHERE org_id=%s AND kind='check'",
            (org,),
        )
        return snapshot

    with pytest.raises(StaleLease):
        asyncio.run(runner.run(identity, org, check, "late", {}, late_engine))
    assert (
        conn.execute(
            "SELECT issued_snapshot FROM billshield.checks WHERE id=%s", (check,)
        ).fetchone()["issued_snapshot"]
        is None
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM billshield.reports WHERE check_id=%s", (check,)
        ).fetchone()["n"]
        == 0
    )

    async def fresh_engine(request, deadline):
        return snapshot

    assert (
        asyncio.run(runner.run(identity, org, check, "late", {}, fresh_engine))
        == snapshot
    )
    assert (
        conn.execute(
            "SELECT attempts FROM billshield.jobs WHERE org_id=%s AND kind='check'",
            (org,),
        ).fetchone()["attempts"]
        == 2
    )


def test_active_lease_blocks_duplicate_calls_and_errors_are_private(inline_scope):
    database, identity, org, conn, draft, _snapshot = inline_scope
    runner = InlineCheckRunner(database)
    check = draft()

    async def failed_engine(request, deadline):
        raise RuntimeError("PRIVATE fixture recipe must not enter job errors")

    with pytest.raises(RuntimeError, match="PRIVATE"):
        asyncio.run(runner.run(identity, org, check, "retry", {}, failed_engine))
    job = conn.execute(
        "SELECT * FROM billshield.jobs WHERE org_id=%s AND kind='check'", (org,)
    ).fetchone()
    assert job["status"] == "failed" and job["last_error"] == "engine_failed"
    with database.tenant(identity, org) as scope:
        assert PostgresJobs().claim(scope, 240, job_id=job["id"])

    async def forbidden_engine(request, deadline):
        pytest.fail("A concurrent retry must not execute model calls")

    with pytest.raises(CheckInProgress):
        asyncio.run(runner.run(identity, org, check, "retry", {}, forbidden_engine))
    with pytest.raises(AuthorizationError):
        asyncio.run(runner.run(identity, org, uuid4(), "unknown", {}, forbidden_engine))


def test_global_timeout_does_not_issue_report(inline_scope, monkeypatch):
    database, identity, org, conn, draft, snapshot = inline_scope
    runner = InlineCheckRunner(database)
    check = draft()
    monkeypatch.setattr(
        Deadline, "start", classmethod(lambda cls: cls(monotonic() + 0.1))
    )

    async def sleeping_engine(request, deadline):
        await asyncio.sleep(1)
        return snapshot

    with pytest.raises(TimeoutError):
        asyncio.run(runner.run(identity, org, check, "timeout", {}, sleeping_engine))
    assert (
        conn.execute(
            "SELECT issued_snapshot FROM billshield.checks WHERE id=%s", (check,)
        ).fetchone()["issued_snapshot"]
        is None
    )


def test_recorded_pipeline_to_inline_immutable_issuance(inline_scope, evidence):
    database, identity, org, conn, draft, fixture_snapshot = inline_scope
    facts, corpus, proposals, context = evidence
    # Synthetic legal evidence exercises the whole contract, not legal accuracy.
    corpus = replace(corpus, snapshot_id=fixture_snapshot["law_snapshot_id"])
    context = replace(context, as_of=date(2025, 9, 22))
    recorded = RecordedModel(facts, proposals[0])
    pipeline = EnginePipeline(recorded)
    runner = InlineCheckRunner(database)
    check = draft()
    request = {
        "facts": facts.model_dump(mode="json"),
        "bill": {
            "claimed_code": "33071010",
            "billed_rate_pct": "18",
            "taxable_value": "1000",
        },
    }

    async def execute(frozen_request, deadline):
        # Postgres.tenant commits on exit in production; this fixture uses real
        # restricted-role SQL with savepoints so no issued fixture persists.
        assert not database.active and database.exited >= 1
        job = conn.execute(
            "SELECT status,lease_token FROM billshield.jobs WHERE org_id=%s AND kind='check'",
            (org,),
        ).fetchone()
        assert job["status"] == "running" and job["lease_token"] is not None
        return await pipeline.run_request(
            frozen_request,
            corpus,
            context,
            candidate_chapters=("33",),
            deadline_monotonic=deadline.expires_at,
        )

    issued = asyncio.run(runner.run(identity, org, check, "pipeline", request, execute))
    assert issued["result"] == "Wrong"
    assert issued["evidence"]["result"]["rate_pct"] == "5.0"
    assert issued["evidence"]["facts"] == request["facts"]
    assert len(issued["evidence"]["calls"]) == 3
    assert issued["model_id"] == "deepseek-flash"
    assert issued["resolved_model_version"] is None
    assert issued["needs_review"] is True
    row = conn.execute(
        "SELECT issued_snapshot,product_facts_snapshot,bill_fields,needs_review "
        "FROM billshield.checks WHERE id=%s",
        (check,),
    ).fetchone()
    assert row["issued_snapshot"] == issued and row["needs_review"] is True
    assert row["product_facts_snapshot"] == request["facts"]
    assert row["bill_fields"] == issued["evidence"]["bill"]
    issued["evidence"]["facts"]["name"] = "caller changed this"
    again = asyncio.run(runner.run(identity, org, check, "pipeline", request, execute))
    assert again == row["issued_snapshot"] and len(recorded.messages) == 3
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM billshield.reports WHERE check_id=%s", (check,)
        ).fetchone()["n"]
        == 1
    )


def test_hourly_org_allowance_excludes_idempotent_retry(inline_scope):
    database, identity, org, conn, draft, snapshot = inline_scope
    runner = InlineCheckRunner(database, checks_per_hour=1)
    first, second = draft(), draft()
    calls = []

    async def engine(request, deadline):
        calls.append(request)
        return snapshot

    issued = asyncio.run(runner.run(identity, org, first, "hourly-first", {}, engine))
    assert (
        asyncio.run(runner.run(identity, org, first, "hourly-first", {}, engine))
        == issued
    )
    with pytest.raises(CheckRateLimited, match="Hourly check allowance"):
        asyncio.run(runner.run(identity, org, second, "hourly-second", {}, engine))
    assert len(calls) == 1
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM billshield.jobs WHERE org_id=%s AND kind='check'",
            (org,),
        ).fetchone()["n"]
        == 1
    )
    assert (
        conn.execute(
            "SELECT issued_snapshot FROM billshield.checks WHERE id=%s",
            (second,),
        ).fetchone()["issued_snapshot"]
        is None
    )
