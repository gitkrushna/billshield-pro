"""Create the single restricted runtime login, saving credentials only to .env.local."""

import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv, set_key
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.local"
REFERENCE = [
    "source_documents",
    "hsn_codes",
    "rate_entries",
    "rate_scopes",
    "rate_conditions",
    "classification_rules",
    "rule_links",
    "search_synonyms",
    "rulings",
    "ruling_links",
    "data_coverage",
    "law_snapshots",
    "law_snapshot_members",
    "section_chapters",
    "boundary_map",
    "ruling_embeddings",
]
MUTABLE = [
    "products",
    "files",
    "own_rulings",
    "checks",
    "check_citations",
    "cached_analyses",
    "jobs",
]


def provision():
    load_dotenv(ENV, override=False)
    migration_url = os.environ.get("MIGRATION_DATABASE_URL")
    if not migration_url:
        raise SystemExit(
            "Migration configuration missing; runtime provisioning blocked"
        )
    password = secrets.token_urlsafe(48)
    with psycopg.connect(migration_url) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='billshield_app'"
        ).fetchone()
        if exists:
            # Never reset an existing credential silently.
            if not os.environ.get("DATABASE_URL"):
                raise SystemExit(
                    "Runtime role exists but local credential is missing; no reset attempted"
                )
        else:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE billshield_app LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                ).format(sql.Literal(password))
            )
        connection.execute("GRANT USAGE ON SCHEMA billshield TO billshield_app")
        for table in REFERENCE:
            connection.execute(
                sql.SQL("GRANT SELECT ON billshield.{} TO billshield_app").format(
                    sql.Identifier(table)
                )
            )
        for table in MUTABLE:
            connection.execute(
                sql.SQL(
                    "GRANT SELECT,INSERT,UPDATE ON billshield.{} TO billshield_app"
                ).format(sql.Identifier(table))
            )
        connection.execute(
            "GRANT SELECT ON billshield.orgs,billshield.org_members,billshield.invitations TO billshield_app"
        )
        connection.execute(
            "GRANT UPDATE(name,research_opt_in) ON billshield.orgs TO billshield_app"
        )
        connection.execute(
            "GRANT SELECT,INSERT ON billshield.reports,billshield.audit_events,billshield.report_shares TO billshield_app"
        )
        connection.execute(
            "GRANT UPDATE(revoked_at) ON billshield.report_shares TO billshield_app"
        )
        for signature in (
            "current_user_id()",
            "current_org_id()",
            "identity_for_subject(text,text,text)",
            "membership_role(uuid,uuid)",
            "in_org(uuid)",
            "is_owner(uuid)",
            "create_org(text)",
            "invite_member(text,text)",
            "accept_invitation(text)",
            "manage_member(uuid,text)",
        ):
            connection.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION billshield."
                    + signature
                    + " TO billshield_app"
                )
            )
    if not exists:
        parts = urlsplit(migration_url)
        if parts.scheme not in ("postgres", "postgresql"):
            raise SystemExit("Provisioning requires a PostgreSQL URI")
        username = "billshield_app"
        if (
            ".pooler.supabase.com" in (parts.hostname or "")
            and parts.username
            and "." in parts.username
        ):
            username += "." + parts.username.split(".", 1)[1]
        host = parts.hostname or "localhost"
        if ":" in host:
            host = "[" + host + "]"
        netloc = quote(username, safe="") + ":" + quote(password, safe="") + "@" + host
        if parts.port:
            netloc += ":" + str(parts.port)
        runtime_url = urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
        set_key(str(ENV), "DATABASE_URL", runtime_url, quote_mode="always")
    print("Restricted runtime role provisioned; credentials remain in .env.local")


if __name__ == "__main__":
    try:
        provision()
    except (psycopg.Error, ValueError, OSError) as exc:
        raise SystemExit(
            f"Runtime provisioning failed ({type(exc).__name__}); credentials suppressed"
        ) from None
