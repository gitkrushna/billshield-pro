"""Small authenticated Finish workflow, using only the restricted runtime role."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from billshield.config import Settings
from billshield.corpus import load_snapshot
from billshield.db import AuthorizationError, Postgres
from billshield.engine import BillFields, CheckContext, ProductFacts, StrictInput
from billshield.execution import CheckRateLimited, Deadline, InlineCheckRunner
from billshield.jobs import PostgresJobs
from billshield.llm import DeepSeekLLM, TokenPrices
from billshield.pipeline import (
    EnginePipeline,
    IssuedCheck,
    PreparedText,
    prepare_text,
    validate_fact_boundary,
)
from billshield.ports import Identity


class CheckNotFound(LookupError):
    pass


class IdempotencyConflict(ValueError):
    pass


class CheckRequest(StrictInput):
    facts: ProductFacts
    bill: BillFields | None = None
    state: str = Field(default="Goa", min_length=1, max_length=80)
    as_of: date | None = None
    bill_text: str | None = Field(default=None, min_length=1, max_length=40000)
    bill_text_reviewed: bool = False

    @model_validator(mode="after")
    def safe_inputs(self):
        validate_fact_boundary(self.facts)
        if self.bill_text is not None and self.bill_text_reviewed is not True:
            raise ValueError("Bill text requires privacy review")
        if not self.state.strip():
            raise ValueError("A state is required")
        return self

    def execution_request(self) -> dict:
        prepared = prepare_text(self.bill_text, privacy_reviewed=True) if self.bill_text else None
        return {
            "facts": self.facts.model_dump(mode="json"),
            "bill": self.bill.model_dump(mode="json") if self.bill else None,
            "review": self.bill is not None or prepared is not None,
            "bill_text": prepared.text if prepared else None,
            "bill_text_reviewed": prepared is not None,
        }


def verified_prices(now: datetime | None = None) -> TokenPrices:
    """Documented UTC tariff; weekday peak holidays remain an upper-bound estimate."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    peak = now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)
    values = ("0.006", "0.30", "1.20") if peak else ("0.003", "0.15", "0.60")
    band = "peak-window upper bound; Chinese holiday exceptions unverified" if peak else "off-peak"
    return TokenPrices(
        *(Decimal(value) for value in values),
        basis=f"https://api-docs.deepseek.com/quick_start/pricing/; {band}; {now.isoformat()}",
        estimate=peak,
    )


class FinishService:
    def __init__(self, settings: Settings):
        if settings.database_url is None:
            raise RuntimeError("Runtime database configuration unavailable")
        self.settings = settings
        self.database = Postgres(settings.database_url.get_secret_value())
        self.jobs = PostgresJobs()
        self.runner = InlineCheckRunner(
            self.database, self.jobs, checks_per_hour=settings.checks_per_hour
        )

    def session(self, identity: Identity) -> UUID:
        # No client-supplied org selector. Self-owner discovery is permitted by
        # the narrow bootstrap RLS policy, before any tenant scope is selected.
        with (
            psycopg.connect(
                self.database.dsn, row_factory=dict_row, connect_timeout=10
            ) as connection,
            connection.transaction(),
        ):
            role = connection.execute(
                "SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles "
                "WHERE rolname=current_user"
            ).fetchone()
            if not role or role != {
                "name": "billshield_app",
                "rolsuper": False,
                "rolbypassrls": False,
            }:
                raise AuthorizationError("Restricted runtime connection required")
            user_id = connection.execute(
                "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
                (identity.issuer, identity.subject, identity.email),
            ).fetchone()["id"]
            connection.execute("SELECT set_config('app.user_id',%s,true)", (str(user_id),))
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("billshield.own-org:" + str(user_id),),
            )
            org = connection.execute(
                "SELECT org_id FROM billshield.org_members WHERE user_id=%s "
                "AND role='owner' AND removed_at IS NULL ORDER BY created_at,org_id LIMIT 1",
                (user_id,),
            ).fetchone()
            if org:
                return org["org_id"]
            return connection.execute(
                "SELECT billshield.create_org(%s) AS id", ("My organisation",)
            ).fetchone()["id"]

    def list_checks(self, identity: Identity, org_id: UUID) -> list[dict]:
        with self.database.tenant(identity, org_id) as scope:
            return scope.connection.execute(
                "SELECT id,product_facts_snapshot->>'name' AS description,result,created_at "
                "FROM billshield.checks WHERE org_id=%s AND user_id=%s "
                "AND issued_snapshot IS NOT NULL ORDER BY created_at DESC,id DESC LIMIT 100",
                (org_id, scope.user_id),
            ).fetchall()

    def get_check(self, identity: Identity, org_id: UUID, check_id: UUID) -> dict:
        with self.database.tenant(identity, org_id) as scope:
            row = scope.connection.execute(
                "SELECT issued_snapshot FROM billshield.checks "
                "WHERE id=%s AND org_id=%s AND user_id=%s AND issued_snapshot IS NOT NULL",
                (check_id, org_id, scope.user_id),
            ).fetchone()
            if row is None:
                raise CheckNotFound()
            return row["issued_snapshot"]

    def _draft(
        self, identity: Identity, org_id: UUID, key: str, body: CheckRequest, request: dict
    ) -> tuple[UUID, CheckContext]:
        with self.database.tenant(identity, org_id) as scope:
            scope.connection.execute("SELECT set_config('lock_timeout','5000',true)")
            scope.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("billshield.check-registration:" + str(org_id),),
            )
            existing = scope.connection.execute(
                "SELECT j.kind,j.payload,c.id,c.as_of_date,c.jurisdiction,c.user_id "
                "FROM billshield.jobs j LEFT JOIN billshield.checks c "
                "ON c.id::text=j.payload->>'check_id' AND c.org_id=j.org_id "
                "WHERE j.org_id=%s AND j.idempotency_key=%s",
                (org_id, key),
            ).fetchone()
            state = (
                "Goa" if body.state.strip().casefold() in {"goa", "in-ga"} else body.state.strip()
            )
            if existing:
                if (
                    existing["kind"] != "check"
                    or existing["user_id"] != scope.user_id
                    or existing["payload"].get("request") != request
                    or existing["jurisdiction"] != state
                    or (body.as_of is not None and existing["as_of_date"] != body.as_of)
                ):
                    raise IdempotencyConflict()
                return existing["id"], CheckContext(existing["as_of_date"], state)
            used = scope.connection.execute(
                "SELECT count(*) AS n FROM billshield.jobs WHERE org_id=%s AND kind='check' "
                "AND created_at>=clock_timestamp()-interval '1 hour'",
                (org_id,),
            ).fetchone()["n"]
            if used >= self.settings.checks_per_hour:
                raise CheckRateLimited()
            product = scope.connection.execute(
                "INSERT INTO billshield.products(org_id,created_by,name,facts) "
                "VALUES(%s,%s,%s,%s) RETURNING id",
                (org_id, scope.user_id, body.facts.name, Jsonb(request["facts"])),
            ).fetchone()["id"]
            as_of = body.as_of or date.today()
            check = scope.connection.execute(
                "INSERT INTO billshield.checks(org_id,user_id,product_id,product_facts_snapshot,"
                "bill_fields,as_of_date,jurisdiction) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    org_id,
                    scope.user_id,
                    product,
                    Jsonb(request["facts"]),
                    Jsonb(request["bill"]),
                    as_of,
                    state,
                ),
            ).fetchone()["id"]
            self.jobs.enqueue(
                scope,
                "check",
                {
                    "check_id": str(check),
                    "user_id": str(scope.user_id),
                    "request": request,
                },
                key,
            )
            return check, CheckContext(as_of, state)

    async def create_check(
        self, identity: Identity, org_id: UUID, key: str, body: CheckRequest
    ) -> tuple[UUID, dict]:
        request = body.execution_request()
        check_id, context = self._draft(identity, org_id, key, body, request)

        async def engine(frozen: dict, deadline: Deadline):
            # Corpus access uses the same authenticated restricted DB boundary.
            # The connection closes before any model call.
            with self.database.tenant(identity, org_id) as scope:
                corpus = load_snapshot(scope.connection, self.settings.law_snapshot_id)
            deadline.remaining()
            model = DeepSeekLLM(
                self.settings.deepseek_api_key.get_secret_value()
                if self.settings.deepseek_api_key
                else "",
                prices=verified_prices(),
            )
            issued = await EnginePipeline(model).run_form(
                ProductFacts.model_validate(frozen["facts"]),
                corpus,
                context,
                bill=BillFields.model_validate(frozen["bill"]) if frozen["bill"] else None,
                bill_text=PreparedText(frozen["bill_text"], privacy_reviewed=True)
                if frozen["bill_text"]
                else None,
                review=frozen["review"],
                deadline_monotonic=deadline.expires_at,
            )
            if isinstance(issued, IssuedCheck):
                ids = list({citation.source_id for citation in issued.result.citations})
                with self.database.tenant(identity, org_id) as scope:
                    rows = scope.connection.execute(
                        "SELECT source_key,title,url FROM billshield.source_documents "
                        "WHERE source_key=ANY(%s)",
                        (ids,),
                    ).fetchall()
                issued = replace(
                    issued,
                    source_links={
                        row["source_key"]: {"title": row["title"], "url": row["url"]}
                        for row in rows
                    },
                )
            return issued

        report = await self.runner.run(identity, org_id, check_id, key, request, engine)
        return check_id, report
