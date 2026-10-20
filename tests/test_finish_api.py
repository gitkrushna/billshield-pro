"""Small Finish boundary checks; no live model calls or persistent fixtures."""

import asyncio
import copy
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from billshield.app import MAX_BODY_BYTES, create_app
from billshield.auth import AuthenticationError
from billshield.config import Settings
from billshield.execution import InlineCheckRunner
from billshield.finish import (
    CheckNotFound,
    CheckRequest,
    FinishService,
    IdempotencyConflict,
)
from billshield.jobs import PostgresJobs
from billshield.ports import Identity
from fastapi.testclient import TestClient
from test_execution import inline_scope as inline_scope  # noqa: PLC0414


class FakeAuth:
    def verify(self, token):
        if token not in {"alice", "bob"}:
            raise AuthenticationError("PRIVATE token details")
        return Identity(
            "https://fixture.invalid/auth/v1", token, token + "@fixture.invalid"
        )


class FakeService:
    def __init__(self):
        self.orgs = {}
        self.checks = {}
        self.calls = 0

    def session(self, who):
        return self.orgs.setdefault(who.subject, uuid4())

    def list_checks(self, who, org_id):
        return [
            {
                "id": str(value[1]),
                "description": value[0]["facts"]["name"],
                "result": value[2]["result"],
                "created_at": "2026-10-20T00:00:00Z",
            }
            for (owner, _key), value in self.checks.items()
            if owner == org_id
        ]

    async def create_check(self, who, org_id, key, body):
        request = body.execution_request()
        pair = (org_id, key)
        if pair in self.checks:
            previous, check_id, report = self.checks[pair]
            if previous != request:
                raise IdempotencyConflict()
            return check_id, copy.deepcopy(report)
        self.calls += 1
        check_id = uuid4()
        report = {"result": "Need more info", "evidence": {"facts": request["facts"]}}
        self.checks[pair] = (request, check_id, copy.deepcopy(report))
        return check_id, report

    def get_check(self, who, org_id, check_id):
        for (owner, _key), (_request, existing_id, report) in self.checks.items():
            if owner == org_id and existing_id == check_id:
                return copy.deepcopy(report)
        raise CheckNotFound()


@pytest.fixture
def boundary():
    service = FakeService()
    settings = Settings(
        _env_file=None,
        auth_issuer="https://fixture.invalid/auth/v1",
        auth_publishable_key="sb_publishable_fixture",
    )
    with TestClient(create_app(settings, service=service, auth=FakeAuth())) as client:
        yield client, service


def request_body():
    return {"facts": {"name": "Test salt", "form": "crystals", "use": "food"}}


def test_routes_require_auth_and_errors_do_not_echo_private_input(boundary):
    client, service = boundary
    for method, path in (
        ("post", "/api/session"),
        ("get", "/api/checks"),
        ("post", "/api/checks"),
        ("get", f"/api/checks/{uuid4()}"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 401
        assert (
            response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
        )
    assert (
        client.get(
            "/api/checks", headers={"Authorization": "Bearer private"}
        ).status_code
        == 401
    )
    invalid = {"facts": {"name": "PRIVATE recipe", "form": "", "use": "food"}}
    response = client.post(
        "/api/checks", json=invalid, headers={"Authorization": "Bearer alice"}
    )
    assert response.status_code == 422 and "PRIVATE" not in response.text
    assert service.calls == 0
    response = client.post("/api/checks", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert client.get("/api/config").json() == {
        "auth_url": "https://fixture.invalid",
        "auth_publishable_key": "sb_publishable_fixture",
    }
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/api/config",
        "/api/session",
        "/api/checks",
        "/api/checks/{check_id}",
    }
    assert "security" in schema["paths"]["/api/checks"]["post"]


def test_own_session_replay_and_immutable_report_isolation(boundary):
    client, service = boundary
    alice = {"Authorization": "Bearer alice", "Idempotency-Key": "fixture-same"}
    bob = {"Authorization": "Bearer bob"}
    session = client.post("/api/session", headers=alice).json()
    assert client.post("/api/session", headers=alice).json() == session
    body = request_body()
    issued = client.post("/api/checks", headers=alice, json=body)
    assert issued.status_code == 200
    original = issued.json()
    issued.json()["report"]["evidence"]["facts"]["name"] = "caller mutation"
    assert client.post("/api/checks", headers=alice, json=body).json() == original
    path = "/api/checks/" + original["id"]
    assert client.get(path, headers=alice).json() == original
    assert client.get(path, headers=bob).status_code == 404
    assert client.get("/api/checks", headers=bob).json() == {"checks": []}
    assert len(client.get("/api/checks", headers=alice).json()["checks"]) == 1
    body["facts"]["name"] = "changed facts"
    assert client.post("/api/checks", headers=alice, json=body).status_code == 409
    assert service.calls == 1


def test_invoice_review_and_key_are_required_before_execution(boundary):
    client, service = boundary
    headers = {"Authorization": "Bearer alice", "Idempotency-Key": "invoice"}
    body = {**request_body(), "bill_text": "PRIVATE recipe and invoice"}
    response = client.post("/api/checks", headers=headers, json=body)
    assert response.status_code == 422 and "PRIVATE" not in response.text
    assert (
        client.post(
            "/api/checks",
            json=request_body(),
            headers={"Authorization": "Bearer alice"},
        ).status_code
        == 422
    )
    assert service.calls == 0
    body.update(
        bill_text="Email me at fixture@example.invalid", bill_text_reviewed=True
    )
    assert client.post("/api/checks", headers=headers, json=body).status_code == 200
    assert next(iter(service.checks.values()))[0]["bill_text"] == "Email me at [EMAIL]"


def test_restricted_database_registration_and_replay(inline_scope, monkeypatch):
    database, identity, org, connection, _draft, snapshot = inline_scope
    service = FinishService.__new__(FinishService)
    service.database = database
    service.settings = SimpleNamespace(
        checks_per_hour=30,
        law_snapshot_id=snapshot["law_snapshot_id"],
        deepseek_api_key=None,
    )
    service.jobs = PostgresJobs()
    service.runner = InlineCheckRunner(database, service.jobs)
    calls = []

    class RecordedPipeline:
        def __init__(self, model):
            pass

        async def run_form(self, facts, corpus, context, **kwargs):
            assert not database.active
            calls.append(facts)
            return copy.deepcopy(snapshot)

    monkeypatch.setattr("billshield.finish.load_snapshot", lambda *_: object())
    monkeypatch.setattr("billshield.finish.EnginePipeline", RecordedPipeline)
    body = CheckRequest.model_validate(request_body())
    first = asyncio.run(service.create_check(identity, org, "finish-api-replay", body))
    assert (
        asyncio.run(service.create_check(identity, org, "finish-api-replay", body))
        == first
    )
    assert len(calls) == 1
    first[1]["reason"] = "caller mutation"
    stored = service.get_check(identity, org, first[0])
    assert (
        stored == snapshot and service.list_checks(identity, org)[0]["id"] == first[0]
    )
    with pytest.raises(IdempotencyConflict):
        asyncio.run(
            service.create_check(
                identity,
                org,
                "finish-api-replay",
                CheckRequest.model_validate({**request_body(), "state": "Maharashtra"}),
            )
        )

    # Exercise actual identity/bootstrap SQL without persisting a test account.
    @contextmanager
    def rollback_connection(*_args, **_kwargs):
        yield connection

    new_identity = Identity(
        "https://finish-bootstrap.invalid", str(uuid4()), "test@fixture.invalid"
    )
    service.database.dsn = "not used: rollback fixture"
    monkeypatch.setattr("billshield.finish.psycopg.connect", rollback_connection)
    connection.execute("SELECT set_config('app.org_id','',true)")
    own_org = service.session(new_identity)
    assert service.session(new_identity) == own_org
    assert own_org != org
