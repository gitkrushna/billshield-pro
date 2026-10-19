# M1 portability note

The application uses standard interfaces: psycopg/Postgres, JWT/JWKS, S3, SMTP and HTTP. There is no Supabase browser data SDK, `auth.uid()` dependency or service-role key. Identity is `(issuer, subject)` mapped to an internal user; changing issuers requires an explicit identity migration rather than assuming identical subjects.

| Change | Configuration / implementation boundary |
| --- | --- |
| Database host | New standard Postgres, session connection on port 5432, migration credentials separated from `billshield_app` runtime login. Apply forward-only `db/migrations` with dbmate. Preserve role grants, RLS, membership checks and tenant-qualified foreign keys. Runtime must remain a nonowner with no BYPASSRLS. Rerun actual restricted-role isolation before use. |
| Auth issuer | `AUTH_ISSUER`, `AUTH_JWKS_URL`, `AUTH_AUDIENCE`, optional trusted `AUTH_USERINFO_URL` and public key. Use asymmetric signing and confirm verified email. API validates tokens; a browser claim alone establishes nothing. A vendor-specific sign-in module can be added at M4. |
| Object storage | `S3_ENDPOINT_URL`, region, bucket and server-only credentials. Preserve private quarantine, ownership checks, short signed URLs and actual file validation. A public signing hostname must resolve for the browser; an internal Compose hostname does not. |
| Email | SMTP host/port/from and credentials; STARTTLS enabled for real delivery. Mailpit captures local development mail only. |
| LLM | The single DeepSeek HTTP adapter is behind a port. Requested alias `deepseek-flash`, expected serving version `DeepSeek-V4.1-Flash-1017`; record resolved version only if attested. No live calls at M1 and no fallback provider. |
| Jobs | Postgres queue using `FOR UPDATE SKIP LOCKED`; no host-specific scheduler. |

The first portable target is local Docker Compose. A second target is an ordinary Linux container host with the same API image and Next.js standalone image behind HTTPS, with external standard Postgres, private S3-compatible storage, a JWT/JWKS issuer and SMTP configured through server-side secrets. No deployment has been performed. Keep migrations a separate one-off job, API runtime restricted and public web free of secrets. This is a documented target, not a second-host acceptance result.

Local Compose includes only Postgres, MinIO, API/web and the GoTrue + Mailpit services required for email-verified auth. GoTrue identity tables live in a separate database; the application schema never depends on them. Mail confirmation remains enabled. No hardcoded development access token or disabled-auth mode exists. The Compose runtime, sign-in delivery and second host are **unverified until actually exercised**.
