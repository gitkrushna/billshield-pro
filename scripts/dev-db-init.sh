#!/bin/sh
set -eu
# Invoked once by the official Postgres image on a fresh named volume.
# psql's format(%L) quotes credentials; values never appear in logs.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv runtime_password LOCAL_RUNTIME_DB_PASSWORD
\getenv auth_password LOCAL_AUTH_DB_PASSWORD
SELECT format('CREATE ROLE billshield_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :'runtime_password') \gexec
SELECT format('CREATE ROLE billshield_auth LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :'auth_password') \gexec
CREATE DATABASE billshield_auth OWNER billshield_auth;
REVOKE CONNECT ON DATABASE billshield_auth FROM PUBLIC;
GRANT CONNECT ON DATABASE billshield_auth TO billshield_auth;
SQL
