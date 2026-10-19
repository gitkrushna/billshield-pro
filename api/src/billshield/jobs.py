from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from billshield.db import TenantSession


class PostgresJobs:
    """Org-scoped at-least-once jobs. Consumers must make side effects idempotent."""

    def enqueue(
        self,
        scope: TenantSession,
        kind: str,
        payload: dict,
        idempotency_key: str | None = None,
    ) -> UUID:
        if not kind or len(kind) > 100:
            raise ValueError("Invalid job kind")
        row = scope.connection.execute(
            "INSERT INTO billshield.jobs (id,org_id,kind,payload,status,run_after,idempotency_key) "
            "VALUES (%s,%s,%s,%s,'queued',now(),%s) "
            "ON CONFLICT (org_id,idempotency_key) DO UPDATE "
            "SET idempotency_key=EXCLUDED.idempotency_key RETURNING id",
            (uuid4(), scope.org_id, kind, Jsonb(payload), idempotency_key),
        ).fetchone()
        return row["id"]

    def claim(self, scope: TenantSession, lease_seconds: int = 60):
        if not 1 <= lease_seconds <= 240:
            raise ValueError("Invalid lease duration")
        lease_token = uuid4()
        return scope.connection.execute(
            "WITH next_job AS (SELECT id FROM billshield.jobs WHERE org_id=%s "
            "AND ((status='queued' AND run_after<=now()) "
            "OR (status='running' AND leased_until<=now())) "
            "ORDER BY run_after,id FOR UPDATE SKIP LOCKED LIMIT 1) "
            "UPDATE billshield.jobs j SET status='running',lease_token=%s,"
            "leased_until=now()+(%s * interval '1 second'),attempts=j.attempts+1 "
            "FROM next_job n WHERE j.id=n.id AND j.org_id=%s RETURNING j.*",
            (scope.org_id, lease_token, lease_seconds, scope.org_id),
        ).fetchone()

    def complete(self, scope: TenantSession, job_id: UUID, lease_token: UUID) -> bool:
        return bool(
            scope.connection.execute(
                "UPDATE billshield.jobs SET status='completed',lease_token=NULL,leased_until=NULL "
                "WHERE id=%s AND org_id=%s AND lease_token=%s AND status='running' "
                "AND leased_until>now() RETURNING id",
                (job_id, scope.org_id, lease_token),
            ).fetchone()
        )

    def fail(self, scope: TenantSession, job_id: UUID, lease_token: UUID, code: str) -> bool:
        # Callers supply a fixed error code, never exception text or private payload data.
        if not code or len(code) > 80 or not all(c.isalnum() or c == "_" for c in code):
            raise ValueError("Error must be a short code")
        return bool(
            scope.connection.execute(
                "UPDATE billshield.jobs SET status='failed',last_error=%s,lease_token=NULL,"
                "leased_until=NULL WHERE id=%s AND org_id=%s AND lease_token=%s "
                "AND status='running' AND leased_until>now() RETURNING id",
                (code, job_id, scope.org_id, lease_token),
            ).fetchone()
        )
