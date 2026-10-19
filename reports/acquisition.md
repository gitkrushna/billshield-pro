# Source acquisition evidence — 19 October 2026

## M2 current result — supersedes the historical manual-download list below

The founder authorized agent acquisition through laptop Chrome and will not download documents manually. Chrome was verified against the live official CBIC homepage. Originals acquired through Chrome are private in `reference/manual_sources/`; `browser_sources.json` records original URLs, retrieval timestamps and SHA-256. Neither original research nor M1 evidence was overwritten.

**Acquired and ingested: 2 originals, 76 canonical pages.**

| Original | Exact observed official URL | Local file / SHA-256 |
|---|---|---|
| Goa 9/2025–State Tax (Rate), dated 17 September 2025 | https://statetax.goa.gov.in/PDF/state_notif/Rate/09_(09_2025)_2025(rate).pdf | `reference/manual_sources/rates/goa_09_2025_rate.pdf`; `56d104ed800a064248181119ec513f3111b3bce5e30d59852cb04508d91728c5` |
| Goa 10/2025–State Tax (Rate), dated 17 September 2025 | https://statetax.goa.gov.in/PDF/state_notif/Rate/10_(10_2025)_2025(rate).pdf | `reference/manual_sources/rates/goa_10_2025_rate.pdf`; `ada23c9e1219819fff3a0fcd12ae298daab13249d00c01b03764712fcc2aeb33` |

Both were reached through the Goa homepage/navigation and official search result for https://statetax.goa.gov.in/rate_notifications.html . Verification establishes original bytes/page integrity, not a reviewed numeric selector or currentness certification. No numeric rates were activated by ingestion.

**Required and still blocked: missing evidence.** No affected chapter receives an invented eight-digit code; the engine returns `Need more info / source_missing`.

| Required evidence | Actual Chrome navigation / observed document URL | Observed result |
|---|---|---|
| Indian chapters 15/17/19/21/25/30/33/34, applicable national notes and GRI | CBIC homepage → Customs → Tariff: https://www.cbic.gov.in/entities/cbic-content-mst/Njk%3D → June 2025 edition https://www.cbic.gov.in/entities/cbic-content-mst/MTcyNDYy → Import Tariff https://www.cbic.gov.in/entities/cbic-content-mst/MTcyNDY0 | Official index loaded. Individual valid originals were not saved. Unattempted chapter-specific URLs are not invented below. |
| Chapter 15 | https://www.cbic.gov.in/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-15.pdf | June 2025 section III index actually links this June 2024 path. Direct Chrome navigation displayed “Your request cannot be processed / Not Found”. |
| Chapter 30 | https://www.cbic.gov.in/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2025)/CUSTOMS_TARIFF_VOL-I/chap-30.pdf | Observed on section VI index https://www.cbic.gov.in/entities/cbic-content-mst/MTcyNDcz ; Chrome download event timed out; no original saved. |
| Chapter 33 | https://www.cbic.gov.in/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-33.pdf | Observed June 2024 link on June 2025 section VI index; Chrome download event timed out; no original saved. |
| Chapter 34 | https://www.cbic.gov.in/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-34.pdf | Observed June 2024 link on June 2025 section VI index; Chrome download event timed out; no original saved. |
| General Notes / GRI and national section material III/IV/V/VI | https://www.cbic.gov.in/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2025)/CUSTOMS_TARIFF_VOL-I/General-Notes.pdf | Link observed on June 2025 edition page; Chrome download timed out. Complete section material not acquired. A section with no notes must be established from the official edition, not fabricated. |
| Whole national First Schedule, alternate official source for every chapter | https://www.indiacode.nic.in/ → observed migration to https://indiacode.gov.in/ → site search “Customs Tariff Act 1975” → https://indiacode.gov.in/act/087d3280-1ba9-4db1-9316-ccac69e5e81d/sections → https://indiacode.gov.in/pdf-viewer/087d3280-1ba9-4db1-9316-ccac69e5e81d/81945b1f-a032-4a3c-8253-1a37b4543ab7 | Official 764-page original displayed “Last Updated: 08-05-2023”. Rejected as authentication of the required 2025 tariff edition. Print/Download action timed out; no original saved. This is not evidence of current eight-digit codes. |
| CGST 9/2025 and 10/2025–CT(Rate) | https://taxinformation.cbic.gov.in/ ; alternate https://cbic-gst.gov.in/ ; official GST Council index found through Chrome search: https://www.gstcouncil.gov.in/cgst-rate-notification | Tax Information loaded only an empty “Tax Portal” body. CBIC-GST connection reset. GST Council index's newest listed row was 08/2025 (January); required September rows not present. No original saved. The earlier direct paths in the historical inventory were not newly guessed/retried. |
| McNROE order 29/WBAAR/2025-26, 13 February 2026 | WB homepage → GST → Advance Ruling https://comtax.wb.gov.in/GST/GST_Advance_Ruling/gst_advance_ruling.html → observed applicant link https://comtax.wb.gov.in/GST/GST_Advance_Ruling/29WBAAR2025-26_20260216.pdf | Official register identifies applicant/date/question. Chrome download timed out; no original saved. Register summary is not a substitute for the ruling's operative text or proof of universal applicability. |

An alternate Chrome search restricted to government domains surfaced a Customs Manual, trade notices, an IGST notification and trade-agreement tariff commitments. They were rejected as substitutes for the requested national tariff/CGST instruments; no third-party or paid copy was used. No CAPTCHA was encountered. No WCO Explanatory Notes were acquired.

**Rejected:** zero downloaded files failed byte/PDF verification. The outdated India Code edition, unrelated official search results and retained third-party mirrors were not activated as required current evidence. **Blocked** items above remain explicit; their correct abstention is a safety pass, never a legal-eval pass.

**Deferred, not blocked:** January 2023 replay; 74A/interest/penalty evidence; full amendment register; other party-specific rulings. MVP exposure is tax difference only, labelled “excludes interest and penalty”. Every result states “amendments after 22 Sep 2025 not verified”. No manual download task is assigned to the founder.

## Historical M1 attempts (preserved below; not current instructions)

## Current founder scope: M1 approved with conditions

January 2023 replay is **deferred**, outside MVP. Its 2017–2023 rate chain is not an MVP blocker and is not a manual-download request below. Numeric MVP rate periods begin on 22 September 2025. Older classification authorities are retained as evidence but are not automatically applicable or a source of current numeric rates.

Manual destination: `D:\billshield-pro\reference\manual_sources\` (already created, gitignored through `reference/`). Put only original files there; keep originals in `reference/research/` unchanged. Alongside downloads, `urls.txt` can identify each filename, actual official download URL, retrieval date and edition/as-of date shown by the publisher. If a site supplies HTML, save HTML rather than renaming it PDF. One complete official national First Schedule can satisfy multiple chapter/note requests.

### Required Indian national tariff documents

These are the **exact candidate URLs attempted in M1**, preserved in `reports/acquisition.json`. They were constructed candidate paths, not independently verified download links. Every attempt is recorded only as `blocked_download_failed / URLError`; the log retained neither a concrete HTTP status nor a transport reason. It would be inaccurate to label them 404s or promise these filenames are correct.

| Required full chapter (Indian eight-digit items, chapter notes and applicable edition/amendments) | Exact candidate URL attempted | Recorded failure | Manual destination relative to the folder above |
|---|---|---|---|
| 15 | https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst15-2025.pdf | URLError; no valid file saved | `tariff/chapter-15.pdf` |
| 17 | https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst17-2025.pdf | URLError; no valid file saved | `tariff/chapter-17.pdf` |
| 19 | https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst19-2025.pdf | URLError; no valid file saved | `tariff/chapter-19.pdf` |
| 21 | https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst21-2025.pdf | URLError; no valid file saved | `tariff/chapter-21.pdf` |
| 30 | https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst30-2025.pdf | URLError; no valid file saved | `tariff/chapter-30.pdf` |
| 33 | https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst33-2025.pdf | URLError; no valid file saved | `tariff/chapter-33.pdf` |

Use the official CBIC tariff index to locate the actual edition and working downloads: https://www.cbic.gov.in/entities/cbic-content-mst/Njk%3D . The official India Code tariff entry is https://www.indiacode.nic.in/handle/123456789/8774 . Both index requests timed out in the current web check; that does not prove they fail in laptop Chrome.

Additional national-source gaps:

- **Official Chapter 25 and Chapter 34 copies / edition authentication**: existing Indian eight-digit lists are unverified mirrors, not authenticated official editions. No chapter-specific official URL was attempted for these two chapters, so no direct official download failure is claimed. Obtain them from the same CBIC index, as `tariff/chapter-25.pdf` and `tariff/chapter-34.pdf`, or supply a full official First Schedule containing them. This affects verified code-existence/legacy flags and the salt/soap/handwash fixtures.
- **Indian General Rules for Interpretation 1–6 and section material for III, IV, V and VI**: national preliminaries/First Schedule required, including amendments for the edition used. No verified direct Indian section/GRI PDF URL was located or tried; the index failures above are the available official attempts. Save as `national/gri-and-sections.pdf`, or separate clearly named original files. WCO texts already acquired are six-digit international material, not a substitute for national eight-digit items. A section may have no notes: establish that from the official edition instead of inventing/requesting a nonexistent note. The old WCO VI download returned HTTP 503 text; the later English VI PDF was successfully acquired and does not need downloading again.

### Other documents/evidence needed for the current M2 engine or affected evaluations

| Document/evidence | Exact official URL attempted or located | What actually failed / remains missing | Manual destination |
|---|---|---|---|
| Notification 9/2025–Central Tax (Rate), complete schedules, explanations and operative date | https://taxinformation.cbic.gov.in/view-pdf/1010436/ENG/Notifications | Original bundle has no valid official local file; current web retrieval timed out. The retained ICAI compilation is a mirror and does not establish the full amendment cutoff. | `rates/cgst-09-2025.pdf` |
| Notification 10/2025–Central Tax (Rate), complete exemptions and conditions | https://taxinformation.cbic.gov.in/view-pdf/1010437/ENG/Notifications | Original bundle has no valid official local file; current web retrieval timed out. A mirror exists. | `rates/cgst-10-2025.pdf` |
| Operative amendments/corrigenda affecting the eight supported chapters, from 22 September 2025 to the requested check date, independently for CGST and Goa SGST | Central register: https://taxinformation.cbic.gov.in/ ; existing official Goa baseline URLs below | Central register request timed out. No exhaustive amendment register/cutoff has been verified, so **a finite complete document list and every direct URL cannot honestly be supplied yet**. No invented notification IDs or failed downloads are claimed for unknown documents. Review the official register, save applicable originals and the dated register evidence; otherwise date coverage remains unverified. Known 01/2026 central amendment is already present from an official state host; its 6 May 2026 corrigendum is only in a mirror. 19/2025 is also only mirrored; its relevance must be checked rather than assuming an out-of-scope tobacco amendment blocks these chapters. Matching Goa changes must be independently established. | `rates/` with publisher filenames; dated register evidence may be HTML/PDF |
| McNROE Consumer Products ruling, order 29/WBAAR/2025-26, 13 February 2026 (C1/C2) | https://comtax.wb.gov.in/GST/GST_Advance_Ruling/29WBAAR2025-26_20260216.pdf | Historical fetch manifest records a failed curl command, with the error text truncated (no reliable HTTP status). The command used the same URL plus `?research=20261019`. Current web opening succeeds: 12 pages, identity on page 1 and operative material on pages 11–12. Still no original local PDF in the corpus; founder will download. | `rulings/mcnroe-29-WBAAR-2025-26.pdf` |
| Current CGST section 74A and its commencement/amendment evidence (exposure only) | https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter15/Section74A_v1.00.html | Earlier retrieval timed out; current attempt did not yield usable text. Existing local CGST Act is an August 2021 snapshot and cannot supply 74A. | `exposure/cgst-section-74A.html` (or original official PDF) plus commencement/amendment source |
| Goa GST amendment inserting 74A, with commencement and current applicability (exposure only) | https://statetax.goa.gov.in/PDF/VAT_Othr_Acts/VAT/Acts/Goa%20VAT%20%28Amendment%29%20Act%202025%20dated%2004032025.pdf | Newly located official PDF opens in the web check; not a historical failed URL and not downloaded locally. Despite its misleading VAT filename, page 1 identifies **Goa GST (Amendment) Act 2025, Act 3 of 2025**; 74A appears in the document. Retain the complete PDF and verify currentness, not just a fragment. | `exposure/goa-gst-amendment-act-3-2025.pdf` |
| Current CGST/Goa section 50, applicable interest-rate notification and Rule 88B / corresponding Goa provisions, relevant later amendments (exposure only) | Official central portal attempted: https://taxinformation.cbic.gov.in/ ; official Goa source host: https://statetax.goa.gov.in/ | Current source set was not acquired. No verified direct document URLs or exhaustive amendment list were located; no specific direct-download failure is claimed. Old Act text cannot establish all current interest/refund/penalty applicability. Founder formula/stage assumptions also remain unsigned. | `exposure/`, original publisher filenames, URL provenance |
| A party-specific own ruling, court stay/reversal or later order **only when relied on** (including a party-specific Gopal outcome) | No verified official order URL or complete case identifier has been located for the claimed party-specific relief | This is not a missing universal document for every product. Company filings/ruling summaries cannot establish an applicable court stay or an own-ruling override. Exact order, party, facts, period and current status must be evidenced; otherwise that affected inference/eval remains blocked. | `rulings/`, if supplied/relied on |

Already present; do not needlessly redownload:

- Goa 9/2025 baseline, official: https://statetax.goa.gov.in/PDF/state_notif/Rate/09_(09_2025)_2025(rate).pdf . Local validated file exists.
- Goa 10/2025 baseline, official retry: https://statetax.goa.gov.in/PDF/state_notif/Rate/10_(10_2025)_2025(rate).pdf?download=1 . Initial PDF was truncated; the distinct retry validated and is retained.
- Central 01/2026 amendment, official Karnataka-hosted copy: https://gst.karnataka.gov.in/Documents/NOTIFICATIONS/CTR014426.pdf . Local PDF exists; this does not prove amendment completeness.
- WCO six requested chapters and IV/VI section texts listed in the historical table below; local validated originals exist. WCO GRI text is also retained. National applicability/version still needs review.
- The source-linked Madhan Agro/Ashwani judgments, Incnut/Chehar rulings and Circulars 189/200/247 already have local evidence. They need extraction/applicability/current-status review, not invented replacement sources. Missing fixture facts are not missing legal documents.

Not MVP download requests: the 2017–2023 numeric rate chain and January 2023 replay (deferred); nationwide SGST/IGST/UTGST/cess coverage outside the approved jurisdiction; paid WCO Explanatory Notes; unrelated tariff chapters/analytics. If a check needs an unloaded rival chapter, it must abstain rather than acquire new scope silently.

### M2 behavior until evidence is supplied and validated

For chapters 15/17/19/21/30/33 with required national sources absent: `result="Need more info"`, `reason="source_missing"`, identify the missing documents, withhold unsupported eight-digit code/rate/exposure. Required-source gaps in other supported paths also abstain. No missing source is replaced by an LLM answer, a six-digit international text, or a fake fixture quote. Document arrival is not automatic legal approval or a fabricated `verified_through` date.

Empty reviewed rate predicates, unverified effective intervals/cutoffs, unknown appeal status, missing product facts, and unsigned exposure assumptions are separate review/input gaps. They must be reported honestly; downloading a PDF alone does not resolve them. M2 can build/test the engine after the worker proposal is approved while reporting affected legal evaluations blocked. The source-gap response itself is now supplied; it does not require every manual file to arrive before implementation.

## Historical M1 bounded acquisition

Sixteen official/free source targets were attempted, then retried sequentially after transient network failures. Nine PDFs were acquired and strictly validated. Their original bytes, per-page exact text and retrieval provenance remain private under content-addressed `reference/acquired/`; `reports/acquisition.json` records URLs, publisher, retrieval times, SHA-256, page counts and per-page text hashes. No new document was automatically added to the research seed or marked legally reviewed.

| Official source | Acquired PDF pages | Evidence locator |
|---|---:|---|
| WCO HS2022 chapter 15 | 7 | Notes page 1; full document pages 1–7 |
| WCO HS2022 chapter 17 | 2 | Notes page 1; full document pages 1–2 |
| WCO HS2022 chapter 19 | 2 | Notes page 1; full document pages 1–2 |
| WCO HS2022 chapter 21 | 2 | Notes page 1; full document pages 1–2 |
| WCO HS2022 chapter 30 | 4 | Full document pages 1–4; page text retained individually |
| WCO HS2022 chapter 33 | 2 | Notes page 1; full document pages 1–2 |
| WCO HS2022 Section IV | 1 | Section note page 1 |
| WCO HS2022 Section VI | 1 | Section notes page 1 |
| CBIC notification 12/2022-CT(Rate) | 2 | Amendment candidate pages 1–2; relevance and prior amendment chain need review |

WCO's official index has no standalone section-note link for III or V. This is an index observation only. These international HS documents do not supply India's complete eight-digit tariff lists or prove Indian legal applicability/currentness.

The six candidate Indian tariff endpoints failed. The Notification 1/2017 base target failed to yield a strictly valid local PDF (one response was quarantined; a subsequent retry failed). These are historical attempt records. The founder subsequently **deferred** January 2023 replay and its chapter 19/21 historic central/Goa rate chain out of MVP; do not count that chain as an MVP blocker. Successful web-tool rendering without preserved original bytes was not counted as acquired evidence.

All twelve research coverage flags remain false with no verified-through date. No M2 legal evaluation was run.
