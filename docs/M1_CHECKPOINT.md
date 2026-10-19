# M1 checkpoint — 19 October 2026

Status update: **M1 approved with conditions.** M2 is limited to the engine/eval path and awaits approval of the foreground worker proposal below. The manual source-gap answer is in `../reports/acquisition.md`. January 2023 replay is deferred out of MVP. Docker execution remains unverified and is not new M2 scope. The evidence below is the historical M1 checkpoint.

Proposed execution: there is no deployed worker today. Once hosting is permitted, run a check's work inside its authenticated Vercel Python request. Supabase Postgres persists the authorized org-scoped job and result; it does not execute Python. Claim with `SKIP LOCKED` in a short transaction and commit the lease before model calls, then persist completion through a fresh authorized transaction. Keep the total engine deadline at 240 seconds, within the documented 300-second Hobby Fluid Compute request limit; verify the actual hosting configuration at the later deployment gate. No execution after the response is promised. An interrupted attempt is resumed/reclaimed only by an authenticated idempotent retry. No Cron or Supabase-side execution is proposed. M2 evaluation invokes the engine directly on the laptop; business API/job dispatch routes are later work. **Founder approval of this proposal is pending.** Reference: https://vercel.com/docs/functions/limitations .

Created through the founder's laptop Chrome: FREE `billshield-dev` in Mumbai (`ap-south-1`), PRIVATE `billshield-uploads` with a 10 MiB PDF/PNG/JPEG limit, and exactly one S3 access-key pair (`billshield-dev-m1`). The founder personally completed Supabase login and confirmed persistent S3 access creation. Credentials/configuration remain only in ignored `.env.local`; no service-role key was fetched or used. Current auth signing is ECC P-256 and the public JWKS is available. The dashboard's default branch label “PRODUCTION” does not change this project's development-only purpose.

Built:

- Python 3.12/FastAPI/Pydantic 2 foundation; one adapter each for psycopg, JWT/JWKS, S3, SMTP, Postgres jobs and DeepSeek. DeepSeek's public call method always refuses live calls at M1. There is no classification engine or customer workflow.
- Two forward-only dbmate migrations with standard Postgres identity mapping, Owner/Member membership, seven-day email-bound invitations, last-owner protection and membership removal. Products have optional `client_name`; no Consultant or client-company management.
- Tenant-qualified foreign keys and RLS across products/checks/files/reports/citations/cache/own rulings/jobs. Runtime login is separate from migrations, owns no tables and has neither superuser nor BYPASSRLS. Issued reports/checks are immutable and audit records append-only.
- Private quarantine uploads, short signed PUT/GET links, actual type/signature/size inspection, uploader checks and a separate frozen object key so an unexpired PUT cannot replace inspected bytes. Inspection is not a claim of safe extraction/redaction for model use; that remains later work.
- Deterministic research import with source/row hashes, explicit snapshot membership, unreviewed selectors, empty condition predicates and unchanged source rates. FTS and prefix indexes, section mapping and the empty deferred embedding relation are present.
- Next.js 15 strict TypeScript standalone scaffold, API/web Dockerfiles, Compose with Postgres/MinIO/GoTrue/Mailpit, CI including gitleaks, setup and portability runbooks. No deployment.

Observed acceptance evidence:

| Check | Actual result |
|---|---|
| Python tests with live restricted connection enabled | 28 passed, zero skipped. This includes signed JWT rejection checks, real DB adapter membership/scope, real PG jobs and two-org isolation. |
| Two-org data isolation | Passed across 10 tenant tables in both directions, including unauthorized inserts/updates, forged cross-org FKs, uploader ownership, invitation restrictions, owner management, immutability and scope reset. All DB fixtures rolled back. See [isolation evidence](../reports/isolation.json). |
| Seed twice | Both runs succeeded with the same counts and `m1-research-555b61ebe53000172e23`. A read-only restricted-role check reconciled all 1,018 snapshot-member hashes. See [seed evidence](../reports/seed_integration.json). |
| Hosted storage/JWKS | Six live checks passed: asymmetric public JWKS; private bucket/file limits; S3 connection; actual signed upload/finalize/download; unsigned and cross-org denial; frozen bytes and invalid-signature rejection. See [infrastructure evidence](../reports/dev_infrastructure.json). |
| Python lint / API health | Passed. API health returns M1/engine unavailable and a request ID; request logs emit JSON without bodies/paths/secrets. |
| Web lint / strict typing / production standalone build | Passed after clearing generated stale Windows build artifacts. Standalone `server.js` exists. |
| Browser secret scan | Passed across 18 generated assets, including comparison with locally configured secret values without displaying them. |
| Gitleaks 8.30.1 | Passed on the staged implementation/evidence: approximately 465 KB scanned, no findings. Private configuration, reference material and tool downloads are excluded from Git. |
| Compose | `docker compose config --quiet` passed. Docker client exists; Linux daemon is not running. Container startup, local GoTrue email/JWKS and image execution are **unverified**, not passed. |
| CI on GitHub | [Run 2](https://github.com/gitkrushna/billshield-pro/actions/runs/39259279057) passed all three jobs (web, adapters, secrets) for code commit `7ab6676`. The initial Linux import-path failure was corrected with root pytest configuration. CI explicitly reports that hosted/private-corpus integration is separate; the actual local 28-test run supplies that evidence. |

Seed totals: 40 source records; 308 HSN hierarchy rows; 292 rate entries (146 CGST + 146 Goa SGST); 316 scopes; 49 rules; one structured ruling; 12 coverage rows, all `complete=false` and `verified_through=NULL`. No customer/test fixtures or machine condition predicates were seeded.

Source evidence and blockers:

- Every original manifest/source hash matched. Format inspection found 35 valid PDFs, nine non-PDF error bodies and one invalid PDF. Invalid files are logically quarantined in the inspection ledger; originals remain unchanged and are not trusted as PDF evidence.
- The bounded acquisition obtained nine valid official PDFs: six WCO chapter texts, section IV/VI notes and CBIC 12/2022. Original bytes, page text, URLs, retrieval dates and hashes remain private under `reference/acquired/`. They were not silently promoted to reviewed legal seed data. See [acquisition details](../reports/acquisition.md).
- Indian eight-digit tariff lists/notes for 15/17/19/21/30/33 and other recorded current-source gaps remain **blocked: missing evidence**. January 2023 replay and its historical rate acquisition are now **deferred**, outside MVP. No current-law certification or verified-through date is claimed. No M2 legal evaluation ran.
- SMTP adapter exists; actual sender/delivery configuration remains a later founder input. Local SMTP/auth verification awaits Docker.
- Three tiny labelled storage test objects were private in quarantine at M1. Following the founder's narrow cleanup authorization, those exact three objects were deleted and verified absent; all other objects were untouched. See `../reports/storage_cleanup.json`. All related DB fixture writes had rolled back.
- Original research, private configuration and handoff material remain local; source PDFs and the handoff ZIP were not published.

M1 review does not establish legal classification accuracy. The founder will put the model key in `.env.local`; do not request it in chat. Wait for worker-choice approval before starting M2. Then build only the engine/eval path and stop at the M2 checkpoint; no deployment.
