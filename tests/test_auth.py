import os
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
from billshield.auth import AuthenticationError, JWTAuth
from billshield.db import AuthorizationError, Postgres
from billshield.ports import Identity
from cryptography.hazmat.primitives.asymmetric import ec
from psycopg.rows import dict_row

ISSUER = "https://fixture.invalid/auth/v1"


@pytest.fixture
def signer():
    private = ec.generate_private_key(ec.SECP256R1())
    keys = SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key())
    )

    def token(**overrides):
        claims = {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": "fixture-subject",
            "email": "fixture@example.invalid",
            "email_verified": True,
            "exp": int(time.time()) + 120,
        }
        claims.update(overrides)
        return jwt.encode(
            claims, private, algorithm="ES256", headers={"kid": "fixture-key"}
        )

    return keys, token


def test_signed_identity_and_tamper_rejection(signer):
    keys, token = signer
    verifier = JWTAuth(ISSUER, "authenticated", keys)
    assert verifier.verify(token()).subject == "fixture-subject"
    pieces = token().split(".")
    pieces[1] = pieces[1][:-3] + "AAAA"
    with pytest.raises(AuthenticationError):
        verifier.verify(".".join(pieces))


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.invalid"},
        {"aud": "another-app"},
        {"exp": int(time.time()) - 10},
        {"email_verified": False},
        {"email_verified": None, "user_metadata": {"email_verified": True}},
        {"email": "not-an-email"},
        {"sub": ""},
    ],
)
def test_wrong_scope_expiry_and_metadata_are_rejected(signer, claims):
    keys, token = signer
    with pytest.raises(AuthenticationError):
        JWTAuth(ISSUER, "authenticated", keys).verify(token(**claims))


def test_symmetric_algorithm_is_rejected_before_jwks():
    verifier = JWTAuth(
        ISSUER,
        "authenticated",
        SimpleNamespace(
            get_signing_key_from_jwt=lambda _: pytest.fail(
                "Must reject HS256 before looking up keys"
            )
        ),
    )
    token = jwt.encode(
        {"sub": "fixture"},
        "fixture-key-of-at-least-32-bytes-123",
        algorithm="HS256",
        headers={"kid": "fixture-key"},
    )
    with pytest.raises(AuthenticationError):
        verifier.verify(token)


@pytest.mark.parametrize(
    "provider,accepted",
    [
        (
            {
                "id": "fixture-subject",
                "email": "fixture@example.invalid",
                "email_confirmed_at": "2026-10-19T00:00:00Z",
            },
            True,
        ),
        (
            {
                "id": "another-subject",
                "email": "fixture@example.invalid",
                "email_confirmed_at": "2026-10-19T00:00:00Z",
            },
            False,
        ),
        (
            {
                "id": "fixture-subject",
                "email": "fixture@example.invalid",
                "user_metadata": {"email_verified": True},
            },
            False,
        ),
    ],
)
def test_provider_email_confirmation_is_bound_to_verified_subject(
    signer, provider, accepted
):
    keys, token = signer
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=provider))
    )
    verifier = JWTAuth(
        ISSUER, "authenticated", keys, userinfo_url=f"{ISSUER}/user", http_client=http
    )
    if accepted:
        assert (
            verifier.verify(token(email_verified=None)).email
            == "fixture@example.invalid"
        )
    else:
        with pytest.raises(AuthenticationError):
            verifier.verify(token(email_verified=None))


def test_database_adapter_resolves_actual_membership_and_scopes_transaction(
    monkeypatch,
):
    """Actual restricted PG queries; only connection lifetime is wrapped to roll fixtures back."""
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("blocked: restricted TEST_DATABASE_URL is missing")
    with (
        psycopg.connect(dsn, row_factory=dict_row) as conn,
        conn.transaction(force_rollback=True),
    ):
        identities = []
        orgs = []
        for label in ("A", "B"):
            identity = Identity(
                "https://adapter-fixture.invalid",
                str(uuid4()),
                f"fixture-{label}@example.invalid",
            )
            user = conn.execute(
                "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
                (identity.issuer, identity.subject, identity.email),
            ).fetchone()["id"]
            conn.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
            orgs.append(
                conn.execute(
                    "SELECT billshield.create_org(%s) AS id",
                    (f"TEST FIXTURE: adapter {label}",),
                ).fetchone()["id"]
            )
            identities.append((identity, user))
        conn.execute("SELECT set_config('app.user_id','',true)")
        conn.execute("SELECT set_config('app.org_id','',true)")

        class RollbackRequestConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def execute(self, *args, **kwargs):
                return conn.execute(*args, **kwargs)

            def transaction(self):
                return conn.transaction(force_rollback=True)

        monkeypatch.setattr(
            psycopg, "connect", lambda *_, **__: RollbackRequestConnection()
        )
        db = Postgres(dsn)
        identity, user_id = identities[0]
        with db.tenant(identity, orgs[0]) as scope:
            assert scope.user_id == user_id and scope.role == "owner"
            context = scope.connection.execute(
                "SELECT current_setting('app.org_id') AS org,current_setting('app.user_id') AS usr"
            ).fetchone()
            assert context == {"org": str(orgs[0]), "usr": str(user_id)}
        assert (
            conn.execute("SELECT current_setting('app.org_id') AS org").fetchone()[
                "org"
            ]
            == ""
        )
        with pytest.raises(AuthorizationError), db.tenant(identity, orgs[1]):
            pytest.fail("Cross-org scope must never be yielded")
        assert (
            conn.execute("SELECT current_setting('app.org_id') AS org").fetchone()[
                "org"
            ]
            == ""
        )
