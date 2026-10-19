# BillShield Pro

M2 engine/evaluation checkpoint: evidence-first Python classification validators, separate facts/bill inputs, bounded DeepSeek orchestration, inline Postgres leases and immutable issuance. The current corpus has no activated reviewed rules, codes or rate predicates: required evidence gaps return `Need more info / source_missing`. The Next.js page remains a development marker; product API/UI and deployment are later milestones.

Current results: [M2 checkpoint](docs/M2_CHECKPOINT.md), [legal evaluation](reports/eval.md), [source acquisition](reports/acquisition.md). Stop for founder review before M3. Historical foundation evidence remains in the [M1 checkpoint](docs/M1_CHECKPOINT.md).

**Verification not established.** Research coverage is incomplete; blank verified-through dates remain blank. Safety tests and a successful build do not establish legal correctness. MVP rates start 22 September 2025; results state “amendments after 22 Sep 2025 not verified”. Exposure is tax difference only, labelled “excludes interest and penalty”. January 2023 replay, the amendment register, 74A/interest/penalty evidence and other party-specific rulings are deferred.

## Requirements and secrets

Use Python 3.12 with uv, Node 24 and pnpm 11.21.0. Dependency resolutions are locked in `api/uv.lock` and `web/pnpm-lock.yaml`. The web uses Next.js 15.5.28, the maintenance release identified in the [14 October 2026 security advisory](https://nextjs.org/blog/nextjs-security-update-october-14-2026). pnpm uses the hoisted linker so Next's standalone tracing can copy real package directories on Windows without enabling developer-mode symlinks.

Keep all real configuration in gitignored `.env.local`; `.env.example` lists names only. Never print a connection URL, password, JWT, S3 credential or private JWK. Never fetch/use a Supabase service-role key. Runtime `DATABASE_URL` uses the restricted `billshield_app` login; `MIGRATION_DATABASE_URL` is a distinct migration identity using the Session pooler on port 5432. API/web must never run with migration credentials. Do not prefix secrets with `NEXT_PUBLIC_`.

The original `reference/research` remains private and gitignored. It is required for the real research import and local corpus reconciliation. It must be provided separately in a clean checkout; CI intentionally does not pretend that absent corpus acceptance passed.

## Host development

From the repository root:

```powershell
uv sync --project api --frozen
pnpm --dir web install --frozen-lockfile
uv run --project api python scripts/migrate.py
uv run --project api python scripts/provision_runtime.py
uv run --project api python scripts/seed.py
uv run --project api python scripts/seed.py
uv run --project api python scripts/verify_seed.py
uv run --project api pytest
$env:RUN_DB_INTEGRATION = "1"
uv run --project api --env-file .env.local pytest tests/test_isolation.py -q
pnpm --dir web lint
pnpm --dir web typecheck
pnpm --dir web build
pnpm --dir web check:client-secrets
```

Install the [official dbmate v2.35.1 release](https://github.com/amacneil/dbmate/releases/tag/v2.35.1) for your platform, on PATH or Windows `.tools/dbmate.exe` (or set `DBMATE_BIN`). The migration wrapper applies forward-only plain SQL without echoing credentials. Provisioning creates a nonowner, non-superuser, non-BYPASSRLS runtime login and preserves existing credentials. Do not rotate an existing role password to resolve a missing local file.

`make seed` runs the deterministic import using `MIGRATION_DATABASE_URL`. Run it twice against the same migrated development DB and compare table counts/snapshot hashes; inspect `reports/` for the resulting manifest and actual M1 evidence. Missing live DB/corpus evidence is blocked. `make isolation` opts into actual restricted-role integration with `RUN_DB_INTEGRATION=1`; a skipped integration test is missing evidence. The isolation tests use labelled ephemeral fixtures and rollback; runtime access must connect as `billshield_app` through `TEST_DATABASE_URL` or `DATABASE_URL`, never as `postgres` with an application-side filter.

`make verify-seed` reconciles all 1,018 snapshot-member hashes and actual table counts through the restricted connection. `uv run --project api python scripts/check_dev.py` checks hosted dev JWKS and the private bucket without uploads; it requires `APPROVED_DEV_PROJECT_REF` to match the configured project and pooler. The explicit `--storage-write-check` option tests real tiny labelled uploads, rolls back DB fixtures and retains three private quarantine objects without deleting them. See `reports/dev_infrastructure.json` for the observed run.

To start the health-only API: `uv run --project api --env-file .env.local uvicorn billshield.app:app --host 127.0.0.1 --port 8000 --no-access-log`. Start web with `pnpm --dir web dev`. API health is `/healthz`, web health `/health`; neither endpoint establishes storage/database readiness. Product routes/sign-in UI are intentionally absent at M1.

## Local Docker Compose

Docker Desktop's Linux engine must be running. On 19 October 2026 the Docker client was present but the daemon was unavailable; **Compose execution and the local email/JWKS path are unverified**, not passed. No containers were run as part of that observation.

```powershell
node scripts/dev-init.mjs
docker compose --env-file .env.local config --quiet
docker compose --env-file .env.local up --build -d
docker compose --env-file .env.local ps
```

The initializer appends only missing `LOCAL_*` values to `.env.local` using cryptographic randomness and an ES256 signing key; it preserves hosted config. Compose explicitly uses only local values and never passes a hosted env file wholesale into containers. Keep `.env.local` private. Docker's full `config` output contains resolved secrets; use `config --quiet` and never paste full inspect/env/log output into a report.

Services: Postgres (`localhost:54322`), private MinIO (`localhost:9000`, console `:9001`), GoTrue (`localhost:9999`), Mailpit (`localhost:8025`), API (`localhost:8000`) and web (`localhost:3000`). All published ports bind only to loopback. GoTrue owns a separate auth database and sends real local confirmation/magic-link email into Mailpit. Autoconfirm and anonymous auth are disabled. ES256/JWKS remains enabled; there is no token bypass. A one-off dbmate job migrates, then a separate provisioning job grants the runtime role before API startup.

To verify local auth once Docker works, request an OTP with `POST http://localhost:9999/otp` and JSON `{"email":"m1-local@example.test","create_user":true}`. Open the email in Mailpit and follow the confirmation link. Tokens arrive in the redirect URL fragment; do not paste/screenshot them. Verify the resulting token with the API auth adapter using issuer `http://localhost:9999`, JWKS `http://localhost:9999/.well-known/jwks.json`, audience `authenticated` and trusted `/user` verification. A bad signature, wrong issuer/audience, expiry or unconfirmed email must fail. This is a runbook; actual confirmation/token verification must be recorded separately.

M1 has no browser uploads. Compose's internal MinIO endpoint supports API-side adapter checks; a future browser signing flow must use a hostname reachable from both browser and API, preserve the signature's exact host, and verify actual bytes and ownership on finalization before model use. Never expose MinIO credentials to web.

`docker compose --env-file .env.local down` stops services and preserves volumes. Do not run volume deletion/reset commands on the founder's data. Init scripts run only on a fresh volume; changes to role/password config require a reviewed migration, not deleting the database.

## Checks and portability

GitHub Actions runs adapter and recorded engine tests, lint, strict web typing, a production build, a fail-closed browser secret scan and gitleaks. The browser scan fails if a build is absent, scans actual JS/assets and checks secret environment values when supplied without printing them. CI's public source cannot include private research, so corpus/legal evaluation remains an explicit local acceptance gate. No live model call has been made at this checkpoint; completed-check cost is unmeasured.

See `docs/VENDOR_SWITCH.md` for changing Postgres/auth/S3/SMTP hosts and the documented second container target. No second host or production deployment is claimed. Stop at the M2 checkpoint before product API/UI work.
