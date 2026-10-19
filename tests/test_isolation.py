"""Real restricted-login integration; all clearly labelled fixtures are rolled back."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
TABLES = [
    "products",
    "files",
    "own_rulings",
    "checks",
    "reports",
    "check_citations",
    "audit_events",
    "cached_analyses",
    "report_shares",
    "jobs",
]


def test_restricted_runtime_two_org_isolation():
    load_dotenv(ROOT / ".env.local", override=False)
    if os.getenv("RUN_DB_INTEGRATION") != "1":
        pytest.skip("blocked: missing evidence; set RUN_DB_INTEGRATION=1 for live DB")
    dsn = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        pytest.fail(
            "blocked: missing evidence; restricted runtime DB configuration missing"
        )
    checks = []
    marker = uuid4().hex
    email_a, email_b, email_m = (
        f"{marker}-{x}@fixture.invalid" for x in ("a", "b", "m")
    )

    def passed(label):
        checks.append(label)

    try:
        connection = psycopg.connect(dsn, row_factory=dict_row, connect_timeout=15)
    except psycopg.Error:
        pytest.fail(
            "blocked: runtime connection failed (details suppressed)", pytrace=False
        )
    try:
        with connection.transaction(force_rollback=True):
            role = connection.execute(
                "SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert role == {
                "name": "billshield_app",
                "rolsuper": False,
                "rolbypassrls": False,
            }
            owners = connection.execute(
                "SELECT count(*) AS n FROM pg_tables WHERE schemaname='billshield' AND tableowner=current_user"
            ).fetchone()
            assert owners["n"] == 0
            passed(
                "Actual login is billshield_app: nonowner, nonsuperuser, non-BYPASSRLS"
            )

            def identity(email):
                result = connection.execute(
                    "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
                    ("https://fixture.invalid/verified", email, email),
                ).fetchone()["id"]
                connection.execute(
                    "SELECT set_config('app.user_id',%s,true)", (str(result),)
                )
                connection.execute("SELECT set_config('app.org_id','',true)")
                return result

            def scope(user, org):
                connection.execute(
                    "SELECT set_config('app.user_id',%s,true)", (str(user),)
                )
                connection.execute(
                    "SELECT set_config('app.org_id',%s,true)", (str(org),)
                )

            def denied(statement, params=()):
                with pytest.raises(psycopg.Error) as error, connection.transaction():
                    connection.execute(statement, params)
                assert error.value.sqlstate in {"42501", "23503", "23514"}

            denied("SELECT billshield.create_org('TEST FIXTURE: anonymous')")
            denied("SELECT * FROM billshield.users")
            denied("SELECT * FROM billshield.identities")
            user_a = identity(email_a)
            org_a = connection.execute(
                "SELECT billshield.create_org('TEST FIXTURE: isolation A') AS id"
            ).fetchone()["id"]
            user_b = identity(email_b)
            org_b = connection.execute(
                "SELECT billshield.create_org('TEST FIXTURE: isolation B') AS id"
            ).fetchone()["id"]
            passed(
                "Verified identity bootstrap required; identity tables inaccessible directly"
            )
            scope(user_a, org_a)
            token = hashlib.sha256((marker + "invite").encode()).hexdigest()
            connection.execute(
                "SELECT billshield.invite_member(%s,%s)", (email_m, token)
            )
            invite = connection.execute(
                "SELECT * FROM billshield.invitations WHERE token_hash=%s", (token,)
            ).fetchone()
            assert (
                invite["expires_at"] - invite["created_at"]
            ).total_seconds() == 7 * 86400
            scope(user_b, org_b)
            denied("SELECT billshield.accept_invitation(%s)", (token,))
            user_m = identity(email_m)
            assert (
                connection.execute(
                    "SELECT billshield.accept_invitation(%s) AS id", (token,)
                ).fetchone()["id"]
                == org_a
            )
            denied("SELECT billshield.accept_invitation(%s)", (token,))
            scope(user_m, org_a)
            denied("SELECT billshield.invite_member(%s,%s)", (email_b, "b" * 64))
            denied("SELECT billshield.manage_member(%s,'owner')", (user_m,))
            assert (
                connection.execute(
                    "UPDATE billshield.orgs SET name='forbidden' WHERE id=%s", (org_a,)
                ).rowcount
                == 0
            )
            denied(
                "UPDATE billshield.org_members SET role='owner' WHERE user_id=%s",
                (user_m,),
            )
            passed(
                "Invitations are owner-only, verified-email-bound, one-use and expire in seven days"
            )
            scope(user_a, org_a)
            denied("SELECT billshield.manage_member(%s,NULL)", (user_a,))
            denied("SELECT billshield.manage_member(%s,'member')", (user_a,))
            connection.execute("SELECT billshield.manage_member(%s,'owner')", (user_m,))
            connection.execute(
                "SELECT billshield.manage_member(%s,'member')", (user_m,)
            )
            connection.execute("SELECT billshield.manage_member(%s,NULL)", (user_m,))
            scope(user_m, org_a)
            assert (
                connection.execute(
                    "SELECT * FROM billshield.orgs WHERE id=%s", (org_a,)
                ).fetchall()
                == []
            )
            scope(user_a, org_a)
            token2 = hashlib.sha256((marker + "reinvite").encode()).hexdigest()
            connection.execute(
                "SELECT billshield.invite_member(%s,%s)", (email_m, token2)
            )
            scope(user_m, org_a)
            connection.execute("SELECT billshield.accept_invitation(%s)", (token2,))
            passed(
                "Owner manages membership; last owner protected; removal invalidates tenant access"
            )

            source = connection.execute(
                "SELECT source_key FROM billshield.source_documents LIMIT 1"
            ).fetchone()
            snapshot = connection.execute(
                "SELECT id FROM billshield.law_snapshots LIMIT 1"
            ).fetchone()
            assert source and snapshot, (
                "blocked: missing evidence; run deterministic seed first"
            )
            source_key, snapshot_id = source["source_key"], snapshot["id"]
            fixtures = {}

            def insert(table, fields):
                values = {"id": uuid4(), **fields}
                columns = list(values)
                query = sql.SQL(
                    "INSERT INTO billshield.{} ({}) VALUES ({}) RETURNING *"
                ).format(
                    sql.Identifier(table),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                )
                return connection.execute(
                    query,
                    tuple(
                        Jsonb(v) if isinstance(v, dict) else v for v in values.values()
                    ),
                ).fetchone()

            for user, org in ((user_a, org_a), (user_b, org_b)):
                scope(user, org)
                f = fixtures[org] = {}
                common = {"org_id": org}
                f["products"] = insert(
                    "products",
                    {
                        **common,
                        "created_by": user,
                        "name": "TEST FIXTURE: isolated",
                        "client_name": "TEST FIXTURE",
                    },
                )
                f["files"] = insert(
                    "files",
                    {
                        **common,
                        "uploaded_by": user,
                        "object_key": "TEST-FIXTURE/" + uuid4().hex,
                        "declared_size": 100,
                        "declared_type": "application/pdf",
                    },
                )
                f["own_rulings"] = insert(
                    "own_rulings",
                    {
                        **common,
                        "declared_by": user,
                        "file_id": f["files"]["id"],
                        "party_name": "TEST FIXTURE: unverified",
                    },
                )
                f["checks"] = insert(
                    "checks",
                    {
                        **common,
                        "user_id": user,
                        "product_id": f["products"]["id"],
                        "file_id": f["files"]["id"],
                        "own_ruling_id": f["own_rulings"]["id"],
                        "as_of_date": "2026-10-19",
                        "jurisdiction": "IN-GA",
                    },
                )
                f["reports"] = insert(
                    "reports",
                    {
                        **common,
                        "check_id": f["checks"]["id"],
                        "snapshot": {"fixture": True},
                    },
                )
                f["check_citations"] = insert(
                    "check_citations",
                    {
                        **common,
                        "check_id": f["checks"]["id"],
                        "source_key": source_key,
                        "supporting_quote": "TEST FIXTURE: not legal evidence",
                        "claim": "TEST FIXTURE",
                    },
                )
                f["audit_events"] = insert(
                    "audit_events",
                    {
                        **common,
                        "actor_id": user,
                        "check_id": f["checks"]["id"],
                        "event_type": "TEST_FIXTURE",
                        "payload": {"fixture": True},
                    },
                )
                f["cached_analyses"] = insert(
                    "cached_analyses",
                    {
                        **common,
                        "facts_fingerprint": marker,
                        "law_snapshot_id": snapshot_id,
                        "as_of_date": "2026-10-19",
                        "jurisdiction": "IN-GA",
                        "own_ruling_fingerprint": marker,
                        "model_id": "TEST_FIXTURE",
                        "prompt_version": "TEST_FIXTURE",
                        "policy_version": "TEST_FIXTURE",
                        "analysis": {"fixture": True},
                    },
                )
                f["report_shares"] = insert(
                    "report_shares",
                    {
                        **common,
                        "report_id": f["reports"]["id"],
                        "created_by": user,
                        "token_hash": hashlib.sha256(uuid4().bytes).hexdigest(),
                    },
                )
                f["jobs"] = insert(
                    "jobs",
                    {
                        **common,
                        "kind": "TEST_FIXTURE",
                        "payload": {"fixture": True},
                        "idempotency_key": marker,
                    },
                )

            for user, own, other in ((user_a, org_a, org_b), (user_b, org_b, org_a)):
                scope(user, own)
                for table in TABLES:
                    query = sql.SQL("SELECT * FROM billshield.{} WHERE id=%s").format(
                        sql.Identifier(table)
                    )
                    assert connection.execute(
                        query, (fixtures[own][table]["id"],)
                    ).fetchone()
                    assert (
                        connection.execute(
                            query, (fixtures[other][table]["id"],)
                        ).fetchone()
                        is None
                    )
                    clone = dict(fixtures[own][table], org_id=other, id=uuid4())
                    if table == "files":
                        clone["object_key"] = "TEST-FIXTURE/" + uuid4().hex
                    if table == "report_shares":
                        clone["token_hash"] = hashlib.sha256(uuid4().bytes).hexdigest()
                    query = sql.SQL(
                        "INSERT INTO billshield.{} ({}) VALUES ({})"
                    ).format(
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, clone)),
                        sql.SQL(",").join(sql.Placeholder() for _ in clone),
                    )
                    denied(
                        query,
                        tuple(
                            Jsonb(v) if isinstance(v, dict) else v
                            for v in clone.values()
                        ),
                    )
                    # All cross-tenant writes fail or affect zero rows; immutable tables have no UPDATE grant.
                    statement = sql.SQL(
                        "UPDATE billshield.{} SET id=id WHERE id=%s"
                    ).format(sql.Identifier(table))
                    if table in {"reports", "audit_events", "report_shares"}:
                        denied(statement, (fixtures[other][table]["id"],))
                    else:
                        assert (
                            connection.execute(
                                statement, (fixtures[other][table]["id"],)
                            ).rowcount
                            == 0
                        )
                assert (
                    connection.execute(
                        "SELECT * FROM billshield.orgs WHERE id=%s", (other,)
                    ).fetchone()
                    is None
                )
                assert (
                    connection.execute(
                        "SELECT * FROM billshield.org_members WHERE org_id=%s", (other,)
                    ).fetchall()
                    == []
                )
                assert (
                    connection.execute(
                        "SELECT * FROM billshield.invitations WHERE org_id=%s", (other,)
                    ).fetchall()
                    == []
                )
            passed(
                "Both orgs: read/insert/update isolation across every tenant data table plus org/member/invitation reads"
            )

            scope(user_a, org_a)
            for column, table in (
                ("product_id", "products"),
                ("file_id", "files"),
                ("own_ruling_id", "own_rulings"),
            ):
                statement = sql.SQL(
                    "UPDATE billshield.checks SET {}=%s WHERE id=%s"
                ).format(sql.Identifier(column))
                denied(
                    statement,
                    (fixtures[org_b][table]["id"], fixtures[org_a]["checks"]["id"]),
                )
            denied(
                "UPDATE billshield.check_citations SET check_id=%s WHERE id=%s",
                (
                    fixtures[org_b]["checks"]["id"],
                    fixtures[org_a]["check_citations"]["id"],
                ),
            )
            passed(
                "Forged cross-org product/file/own-ruling/check foreign keys rejected"
            )
            scope(user_m, org_a)
            assert connection.execute(
                "SELECT * FROM billshield.files WHERE id=%s",
                (fixtures[org_a]["files"]["id"],),
            ).fetchone()
            assert (
                connection.execute(
                    "UPDATE billshield.files SET status='rejected' WHERE id=%s",
                    (fixtures[org_a]["files"]["id"],),
                ).rowcount
                == 0
            )
            denied(
                "INSERT INTO billshield.files(org_id,uploaded_by,object_key,declared_size,declared_type) VALUES(%s,%s,%s,1,'image/png')",
                (org_a, user_a, "TEST-FIXTURE/" + uuid4().hex),
            )
            passed(
                "Org members may view files; only uploader may create/finalize their upload"
            )
            scope(user_a, org_a)
            for table in ("reports", "audit_events"):
                denied(
                    sql.SQL("UPDATE billshield.{} SET id=id WHERE id=%s").format(
                        sql.Identifier(table)
                    ),
                    (fixtures[org_a][table]["id"],),
                )
                denied(
                    sql.SQL("DELETE FROM billshield.{} WHERE id=%s").format(
                        sql.Identifier(table)
                    ),
                    (fixtures[org_a][table]["id"],),
                )
            connection.execute(
                "UPDATE billshield.checks SET issued_snapshot='{}' WHERE id=%s",
                (fixtures[org_a]["checks"]["id"],),
            )
            denied(
                "UPDATE billshield.checks SET query='changed' WHERE id=%s",
                (fixtures[org_a]["checks"]["id"],),
            )
            passed(
                "Reports and audit append-only; issued rationale check cannot be mutated"
            )
            scope(user_a, org_b)  # Forging scope cannot manufacture membership.
            for table in TABLES:
                assert (
                    connection.execute(
                        sql.SQL("SELECT * FROM billshield.{}").format(
                            sql.Identifier(table)
                        )
                    ).fetchall()
                    == []
                )
            passed("Forged app.org_id without membership exposes no tenant rows")
        with connection.transaction(force_rollback=True):
            values = connection.execute(
                "SELECT current_setting('app.user_id',true) AS u,current_setting('app.org_id',true) AS o"
            ).fetchone()
            assert values["u"] in (None, "") and values["o"] in (None, "")
            # The same identity receives a different UUID: fixture identity and org were rolled back.
            new_user = connection.execute(
                "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
                ("https://fixture.invalid/verified", email_a, email_a),
            ).fetchone()["id"]
            assert new_user != user_a
            passed(
                "Transaction-local identity/org reset; all fixture identity/org/data writes rolled back"
            )
    except psycopg.Error as exc:
        pytest.fail(
            f"Database integration failed ({type(exc).__name__}, SQLSTATE {exc.sqlstate}); details suppressed",
            pytrace=False,
        )
    finally:
        connection.close()
    report = {
        "status": "passed",
        "runtime_role": "billshield_app",
        "fixture_policy": "TEST FIXTURE labels; all writes rolled back",
        "checks": checks,
        "table_count": len(TABLES),
        "engine_or_legal_eval": "not run in M1",
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/isolation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
