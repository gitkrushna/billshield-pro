from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from billshield.ports import Identity


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class TenantSession:
    connection: psycopg.Connection
    user_id: UUID
    org_id: UUID
    role: str

    def require_owner(self) -> None:
        if self.role != "owner":
            raise AuthorizationError("Owner permission required")


class Postgres:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def tenant(self, identity: Identity, org_id: UUID) -> Iterator[TenantSession]:
        """A fresh transaction owns scope; closing it clears all SET LOCAL values."""
        with psycopg.connect(self.dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                role = connection.execute(
                    "SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                ).fetchone()
                if (
                    not role
                    or role["name"] != "billshield_app"
                    or (role["rolsuper"] or role["rolbypassrls"])
                ):
                    raise AuthorizationError("Restricted billshield_app connection required")
                row = connection.execute(
                    "SELECT billshield.identity_for_subject(%s, %s, %s) AS id",
                    (identity.issuer, identity.subject, identity.email),
                ).fetchone()
                if not row or not row["id"]:
                    raise AuthorizationError("Unknown identity")
                user_id = row["id"]
                connection.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                membership = connection.execute(
                    "SELECT billshield.membership_role(%s, %s) AS role", (user_id, org_id)
                ).fetchone()
                if not membership or membership["role"] not in {"owner", "member"}:
                    raise AuthorizationError("Organisation membership required")
                connection.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
                yield TenantSession(connection, user_id, org_id, membership["role"])
