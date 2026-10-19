"""Authenticated inline execution; no background worker or hosting dependency.

The caller supplies a verified Identity and a previously created draft check.
``engine(request, deadline)`` is async and must use the remaining deadline for
each model transport (at most 60 seconds per attempt). It returns a JSON object
with result, confidence_band, law_snapshot_id, prompt_version, model_id and
expected_model_version, or an IssuedCheck. Extra evidence, policy and cost fields remain in the
immutable issued snapshot. No database transaction spans engine/model work.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from psycopg.types.json import Jsonb

from billshield.db import AuthorizationError, Postgres, TenantSession
from billshield.jobs import PostgresJobs
from billshield.pipeline import ExecutionInput, IssuedCheck, validate_fact_boundary
from billshield.ports import Identity


class CheckInProgress(RuntimeError):
    """The same authenticated request already has a live lease; retry later."""


class CheckRateLimited(RuntimeError):
    """The organization has used its configured hourly check allowance."""


class StaleLease(RuntimeError):
    """A late worker may not issue a result after expiry or replacement."""


@dataclass(frozen=True)
class Deadline:
    expires_at: float

    @classmethod
    def start(cls) -> Deadline:
        return cls(monotonic() + 240)

    def remaining(self) -> float:
        seconds = self.expires_at - monotonic()
        if seconds <= 0:
            raise TimeoutError("Engine deadline exceeded")
        return seconds

    def attempt_timeout(self) -> float:
        return min(60.0, self.remaining())


Engine = Callable[[dict, Deadline], Awaitable[dict | IssuedCheck]]
RESULTS = {"Supported", "Rate right, HSN wrong", "Wrong", "Disputable", "Need more info"}


class InlineCheckRunner:
    def __init__(
        self, database: Postgres, jobs: PostgresJobs | None = None, *, checks_per_hour: int = 30
    ):
        if type(checks_per_hour) is not int or checks_per_hour < 1:
            raise ValueError("Hourly check allowance must be a positive integer")
        self.database = database
        self.jobs = jobs or PostgresJobs()
        self.checks_per_hour = checks_per_hour

    async def run(
        self,
        identity: Identity,
        org_id: UUID,
        check_id: UUID,
        idempotency_key: str,
        request: dict,
        engine: Engine,
    ) -> dict:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("A bounded idempotency key is required")
        # Copy before awaiting: caller mutation cannot change the leased request.
        frozen_request = json.loads(json.dumps(request, allow_nan=False))
        if "facts" in frozen_request:
            parsed = ExecutionInput.model_validate(frozen_request)
            validate_fact_boundary(parsed.facts)
        deadline = Deadline.start()
        with self.database.tenant(identity, org_id) as scope:
            wait_ms = str(max(1, min(5000, int(deadline.remaining() * 1000))))
            scope.connection.execute(
                "SELECT set_config('lock_timeout',%s,true), "
                "set_config('statement_timeout',%s,true)",
                (wait_ms, wait_ms),
            )
            # All registration paths lock the organization before a check row.
            # The transaction lock protects the count + insert against parallel
            # requests without holding any lock across engine/model execution.
            scope.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("billshield.check-registration:" + str(org_id),),
            )
            check = self._check(scope, check_id)
            # Serialize registration for one check even when callers use different
            # keys. The check row lock ends before the first model call.
            other = scope.connection.execute(
                "SELECT idempotency_key FROM billshield.jobs WHERE org_id=%s "
                "AND kind='check' AND payload->>'check_id'=%s LIMIT 1",
                (org_id, str(check_id)),
            ).fetchone()
            if other and other["idempotency_key"] != idempotency_key:
                raise ValueError("This check already has an execution request")
            existing = scope.connection.execute(
                "SELECT id FROM billshield.jobs WHERE org_id=%s AND idempotency_key=%s",
                (org_id, idempotency_key),
            ).fetchone()
            if existing is None:
                used = scope.connection.execute(
                    "SELECT count(*) AS n FROM billshield.jobs WHERE org_id=%s AND kind='check' "
                    "AND created_at>=clock_timestamp()-interval '1 hour'",
                    (org_id,),
                ).fetchone()["n"]
                if used >= self.checks_per_hour:
                    raise CheckRateLimited("Hourly check allowance reached; retry later")
            payload = {
                "check_id": str(check_id),
                "user_id": str(scope.user_id),
                "request": frozen_request,
            }
            job_id = self.jobs.enqueue(scope, "check", payload, idempotency_key)
            job = scope.connection.execute(
                "SELECT status FROM billshield.jobs WHERE id=%s AND org_id=%s",
                (job_id, org_id),
            ).fetchone()
            if job["status"] == "completed":
                if check["issued_snapshot"] is None:
                    raise RuntimeError("Completed job has no issued check")
                return copy.deepcopy(check["issued_snapshot"])
            if check["issued_snapshot"] is not None:
                raise ValueError("This check has already been issued")
            lease = self.jobs.claim(scope, lease_seconds=240, job_id=job_id)
            if lease is None:
                raise CheckInProgress("Check execution is in progress")
        # Exiting tenant commits the lease. There is deliberately no connection
        # or open transaction while the async engine performs external calls.
        try:
            async with asyncio.timeout(deadline.remaining()):
                result = await engine(frozen_request, deadline)
            deadline.remaining()
            snapshot = self._snapshot(result, frozen_request, check)
        except BaseException:
            # Error detail may contain recipe/model data. Persist a fixed code.
            # Cancellation/process death can leave an expiring lease instead.
            try:
                with self.database.tenant(identity, org_id) as scope:
                    self.jobs.fail(scope, job_id, lease["lease_token"], "engine_failed")
            except Exception:
                pass
            raise
        with self.database.tenant(identity, org_id) as scope:
            self._check(scope, check_id)
            if not self.jobs.complete(scope, job_id, lease["lease_token"]):
                raise StaleLease("Check lease expired or was replaced")
            row = scope.connection.execute(
                "UPDATE billshield.checks SET result=%s,confidence_band=%s,next_step=%s,"
                "needs_review=%s,exposure_json=%s,law_snapshot_id=%s,prompt_version=%s,"
                "model_id=%s,expected_model_version=%s,resolved_model_version=%s,"
                "product_facts_snapshot=COALESCE(%s,product_facts_snapshot),"
                "bill_fields=COALESCE(%s,bill_fields),"
                "issued_snapshot=%s WHERE id=%s AND org_id=%s AND user_id=%s "
                "AND issued_snapshot IS NULL RETURNING id",
                (
                    snapshot["result"],
                    snapshot["confidence_band"],
                    snapshot.get("next_step"),
                    snapshot.get("needs_review", True),
                    Jsonb(snapshot.get("exposure_json")),
                    snapshot["law_snapshot_id"],
                    snapshot["prompt_version"],
                    snapshot["model_id"],
                    snapshot["expected_model_version"],
                    snapshot.get("resolved_model_version"),
                    Jsonb(snapshot["evidence"]["facts"]) if "evidence" in snapshot else None,
                    Jsonb(snapshot["evidence"]["bill"]) if "evidence" in snapshot else None,
                    Jsonb(snapshot),
                    check_id,
                    org_id,
                    scope.user_id,
                ),
            ).fetchone()
            if not row:
                # Rolls back job completion as well as report issuance.
                raise StaleLease("Check was already issued")
            scope.connection.execute(
                "INSERT INTO billshield.reports(org_id,check_id,snapshot) VALUES(%s,%s,%s)",
                (org_id, check_id, Jsonb(snapshot)),
            )
            scope.connection.execute(
                "INSERT INTO billshield.audit_events(org_id,actor_id,check_id,event_type,payload) "
                "VALUES(%s,%s,%s,'check_issued',%s)",
                (
                    org_id,
                    scope.user_id,
                    check_id,
                    Jsonb(
                        {
                            key: snapshot.get(key)
                            for key in (
                                "law_snapshot_id",
                                "prompt_version",
                                "policy_version",
                                "model_id",
                                "expected_model_version",
                                "resolved_model_version",
                            )
                        }
                    ),
                ),
            )
        return snapshot

    @staticmethod
    def _check(scope: TenantSession, check_id: UUID) -> dict:
        check = scope.connection.execute(
            "SELECT user_id,issued_snapshot,as_of_date,jurisdiction FROM billshield.checks "
            "WHERE id=%s AND org_id=%s FOR UPDATE",
            (check_id, scope.org_id),
        ).fetchone()
        if not check or check["user_id"] != scope.user_id:
            raise AuthorizationError("Check creator permission required")
        return check

    @staticmethod
    def _snapshot(
        result: dict | IssuedCheck, request: dict | None = None, check: dict | None = None
    ) -> dict:
        if isinstance(result, IssuedCheck):
            if request is not None:
                # The engine may not issue a different product or invoice from
                # the authenticated, idempotently leased structured request.
                parsed = ExecutionInput.model_validate(request)
                if parsed.facts != result.facts or parsed.bill != result.bill:
                    raise ValueError("Issued facts differ from the execution request")
            if check is not None and (
                result.as_of != check["as_of_date"].isoformat()
                or result.jurisdiction
                != {"IN-GA": "Goa"}.get(check["jurisdiction"], check["jurisdiction"])
            ):
                raise ValueError("Issued scope differs from the draft check")
            result = result.execution_snapshot()
        # Strict JSON prevents mutable aliases, NaN, Decimal or arbitrary object
        # encodings from yielding different persisted and returned reports.
        snapshot = json.loads(json.dumps(result, allow_nan=False))
        if not isinstance(snapshot, dict):
            raise ValueError("Engine must return a report object")
        if snapshot.get("result") not in RESULTS:
            raise ValueError("Invalid engine result")
        if snapshot.get("confidence_band") not in {"High", "Medium", "Low"}:
            raise ValueError("Invalid engine confidence")
        if "needs_review" in snapshot and not isinstance(snapshot["needs_review"], bool):
            raise ValueError("Review decision must be a boolean")
        for key in ("law_snapshot_id", "prompt_version", "model_id", "expected_model_version"):
            if not isinstance(snapshot.get(key), str) or not snapshot[key]:
                raise ValueError("Report version metadata is required")
        return snapshot
