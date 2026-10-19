# M2 checkpoint — 19 October 2026

Status: **implementation/evaluation stop point; founder acceptance pending.** M1 is approved with conditions, and the founder approved the inline execution choice and authorized this M2 engine/eval work. No M3 API routes, M4 UI or deployment is included.

The legal evaluator attempted the original ten cases, Finish salt, six counterfactuals and the corpus-gap case against the versioned corpus: **0 pass / 0 fail / 18 blocked: missing evidence**. All 18 source-gate safety checks passed. These correct abstentions do not establish code, rate-entry or category correctness. See [evaluation details](../reports/eval.md) and [machine-readable results](../reports/eval.json).

Built:

- Evidence-first Python core with strict ProductFacts separate from BillFields, mandatory GRI/section/chapter/heading/rival/own-ruling retrieval, exact canonical-page quote checks, publication/effective dates, national eight-digit authentication, reviewed rate selectors/conditions/exclusions and independent CGST/Goa SGST Decimal arithmetic. Missing necessary evidence abstains; same-model disagreement alone cannot create Disputable.
- Three concurrent blind proposals, a separate invoice-code defense, bounded retries behind the single DeepSeek adapter, shared 240-second deadline and per-call token/cost/model-version records. Numeric legal rates cannot be proposed by the model. Fact updates revalidate a strict schema; no raw argument enters blind classification.
- Optional separate product/bill text extraction with common-identifier redaction and residual-PII review. Binary uploads remain closed to model use until safely processed. Raw source text and user arguments are absent from issued snapshots.
- Minimal authenticated inline execution with a committed Postgres lease before model work, authenticated idempotent retry, stale-lease fencing, a configurable default 30-check hourly org allowance, bounded lock waits and immutable issuance with one append-only audit event. Recorded pipeline-to-Postgres tests exercise the same path. No new job service, Cron or hosting infrastructure. Actual Vercel hosting configuration remains a later deployment check.
- Versioned canonical source-page ingestion and runtime integrity checks preserve the M1 snapshot and unknown coverage/currentness flags. Source originals remain private under `reference/manual_sources/`; provenance includes URL, retrieval time and SHA-256. No unreviewed numeric rate predicates are activated.

Verification:

| Check | Result |
|---|---|
| Legal evaluation | 0 pass / 0 fail / 18 blocked: missing evidence |
| Actual source-gate safety | 18 pass; no model calls |
| Core validators | 18 synthetic tests passed locally; these are safety/logic evidence, not legal ground truth |
| Python, including recorded pipeline and restricted DB | 120 cases passed in the full suite, plus 3 subsequently added recorded injection fixtures passed; 0 failed / 0 skipped. No production code changed between runs. Fixtures rolled back; no live model calls or S3 writes. See `../reports/m2_tests.json`. |
| Recorded injection boundaries | Label text, bill text and user insistence preserve baseline facts/verdict; raw injected text and invoice fields stay outside blind classification. Live-provider resilience is untested. |
| Lint | Ruff passed for API, scripts and tests |
| Pushed code CI | Commit `35499e6`: secrets, web and adapters jobs all passed. [GitHub Actions run](https://github.com/gitkrushna/billshield-pro/actions/runs/39301411490); `../reports/m2_ci.json` records scope. Private legal accuracy and restricted DB evidence remain separate local gates. |
| Secret checks | Source, tests, scripts and report scans passed; browser secret scan passed on 18 existing assets. Web code unchanged. The complete staged M2 diff also passed gitleaks with zero findings; see `../reports/m2_secrets.json`. |
| Live model quality and completed-check cost | Blocked: provider key absent and required evidence incomplete; zero live calls |

No completed live classification check exists, so **cost per completed check is not measured**. The 18 preflight-only evaluation attempts made no provider calls and incurred zero model-call cost. Successful model usage is priced only when supported by actual token metadata and an explicit price basis; unknown failed-call/retry cost stays unknown. Requested model ID is `deepseek-flash`, documented expected version is `DeepSeek-V4.1-Flash-1017`, and an alias echo is never presented as an attested resolved version. [Official model/pricing reference](https://api-docs.deepseek.com/quick_start/pricing/).

Required source acquisition obtained Goa 9/2025 and 10/2025 rate-notification originals through laptop Chrome: two original PDFs, 76 canonical pages, snapshot `m2-browser-1f4bd452b096b16c06ea`. All 1,018 M1 source records and their manifest/membership hashes remain unchanged. The precise accepted/ingested source list, rejected material, URLs/failures and still-blocked evidence are recorded in [acquisition](../reports/acquisition.md), [ingestion](../reports/m2_ingestion.json) and [runtime corpus](../reports/corpus_runtime.json). National tariff chapters 15/17/19/21/25/30/33/34, full applicable national notes/GRI, CGST 9/2025 and 10/2025 and McNROE remain missing or unreviewed at this checkpoint. No reviewed rules, authenticated national codes or executable rate predicates have been activated; the current source loader therefore permits abstentions only. The old 2023 India Code tariff edition and unrelated official search results were rejected as substitutes, and no acquired PDF failed byte verification. Do not infer eight-digit items or treat a third-party mirror as official evidence.

MVP numeric rate scope begins **22 September 2025**. Exposure is tax difference only: taxable value × (applicable total rate − billed rate) / 100, using Decimal and labelled **“excludes interest and penalty”**. Other-state totals/exposure remain withheld; IGST is outside scope. Every result states **“amendments after 22 Sep 2025 not verified”** and retains actual unknown coverage status. The unset rupee review threshold conservatively leaves `needs_review=true`.

Deferred, not blocked: January 2023 replay; 74A, interest and penalty evidence; the full amendment register; other party-specific rulings. The three labelled M1 storage test objects were already deleted under the narrow authorization; nothing else was deleted. No infrastructure services or general-purpose tooling/runbooks were added. M2 code is limited to the engine, required evidence ingestion/evaluation, existing CI checks and tests.
