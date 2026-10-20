import type { ReactNode, RefObject } from "react";

export type Draft = { description: string; composition: string; form: string; use: string; code: string; rate: string; value: string; state: string; date: string; billText: string; reviewed: boolean };
type Citation = { source_id: string; page: number | string; quote: string };
type Facts = { name?: string; composition?: { name: string; proportion_pct?: number | string | null }[]; form?: string; use?: string };
type Bill = { claimed_code?: string | null; billed_rate_pct?: number | string | null; taxable_value?: number | string | null };
type Result = { reason?: string; code?: string | null; rate_pct?: string | number | null; citations?: Citation[]; missing_facts?: string[]; missing_sources?: string[]; banners?: string[] };
type SourceLink = { title: string; url: string };
type Report = { result: string; confidence_band: string; next_step?: string; needs_review?: boolean; reason?: string; exposure_json?: { tax_difference?: string | number | null; label?: string }; law_snapshot_id?: string; evidence?: { result?: Result; facts?: Facts | null; bill?: Bill | null; jurisdiction?: string; as_of?: string; issued_at?: string; source_links?: Record<string, SourceLink> } };
export type Check = { id: string; report: Report };
export const blank = (): Draft => { const d = new Date(); return { description: "", composition: "", form: "", use: "", code: "", rate: "", value: "", state: "Goa", date: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`, billText: "", reviewed: false }; };
export const states = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"];
const humanize = (value: string) => value.replace(/_/g, " ").replace(/^./, (s) => s.toUpperCase());
export const formatDate = (value?: string) => { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); };
const money = (value: string | number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(value));

function CitationTitle({ citation, source }: { citation: Citation; source?: SourceLink }) {
  let href: string | undefined;
  if (source?.url) {
    try {
      const url = new URL(source.url);
      if (["https:", "http:"].includes(url.protocol)) {
        if (url.pathname.toLowerCase().endsWith(".pdf") && !url.hash) url.hash = `page=${encodeURIComponent(citation.page)}`;
        href = url.href;
      }
    } catch { /* Older reports can retain citations without a resolvable source URL. */ }
  }
  return <><span className="citation-title">{href ? <a className="source-link" href={href} target="_blank" rel="noopener noreferrer">{source?.title || citation.source_id}<span aria-hidden="true"> ↗</span></a> : citation.source_id}</span><span className="citation-page">Page {citation.page} · View quote</span></>;
}

export function Icon({ name, size = 20 }: { name: "shield" | "plus" | "list" | "arrow" | "check" | "document" | "download" | "logout" | "info"; size?: number }) {
  const paths: Record<string, ReactNode> = {
    shield: <><path d="M12 3 4.5 6v5c0 4.4 3.1 8.4 7.5 10 4.4-1.6 7.5-5.6 7.5-10V6L12 3Z" /><path d="m8.5 12 2.3 2.3 4.7-5" /></>,
    plus: <path d="M12 5v14M5 12h14" />, list: <><path d="M8 6h12M8 12h12M8 18h12" /><path d="M3 6h.01M3 12h.01M3 18h.01" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />, check: <path d="m5 12 4 4L19 6" />,
    document: <><path d="M14 3H6v18h12V7l-4-4Z" /><path d="M14 3v5h4M9 12h6M9 16h6" /></>,
    download: <><path d="M12 3v12m-4-4 4 4 4-4M5 16v5h14v-5" /></>,
    logout: <><path d="M9 4H4v16h5M10 12h11m-4-4 4 4-4 4" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7h.01" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function ErrorNotice({ children }: { children: ReactNode }) { return <div className="notice error" role="alert"><Icon name="info" /><span>{children}</span></div>; }

export function CheckReport({ check, heading, onEdit, onNew }: { check: Check; heading: RefObject<HTMLHeadingElement | null>; onEdit: () => void; onNew: () => void }) {
  const { report } = check;
  const evidence = report.evidence, result = evidence?.result || {}, facts = evidence?.facts, bill = evidence?.bill;
  const isSupported = report.result === "Supported", isMissing = report.result === "Need more info";
  const qualifications = [...new Set(result.banners || [])];
  const difference = report.exposure_json?.tax_difference;
  const hasDifference = difference != null && Number.isFinite(Number(difference));
  return <article className="report">
    <div className="page-heading report-heading"><div><p className="eyebrow">CHECK REPORT <span className="report-id">/ {check.id.slice(0, 8)}</span></p><h1 ref={heading} tabIndex={-1}>{facts?.name || "Product classification check"}</h1><p className="muted">Issued {formatDate(evidence?.issued_at)}<span className="meta-separator">·</span>{evidence?.jurisdiction || "Jurisdiction not recorded"}<span className="meta-separator">·</span>As of {formatDate(evidence?.as_of)}</p></div><div className="action-group no-print"><button className="button secondary" onClick={() => window.print()}><Icon name="download" size={17} />Download PDF</button><button className="button primary" onClick={onNew}><Icon name="plus" size={17} />New check</button></div></div>
    <section className={`verdict-card ${isSupported ? "is-supported" : "is-review"}`} aria-label="Check outcome"><div className="verdict-main"><span className="verdict-icon"><Icon name={isSupported ? "check" : "info"} size={28} /></span><div><p className="eyebrow">OUTCOME</p><h2>{report.result}</h2><p>{isSupported ? "Supported within the classification level and evidence limits below." : isMissing ? "More facts or verified evidence are needed before relying on a conclusion." : "Review the classification, bill details, and cited evidence before acting."}</p></div></div><div className="verdict-meta"><span>Confidence <strong>{report.confidence_band || "Not recorded"}</strong></span><span>Review flag <strong>{report.needs_review === true ? "On" : report.needs_review === false ? "Off" : "Not recorded"}</strong></span></div></section>
    <div className="report-grid"><div className="report-main"><section className="card report-section"><div className="report-section-heading"><h2>What the evidence says</h2><span className="subtle-label">Classification assessment</span></div><div className="assessment-grid"><div><span>Assessed code</span><strong>{result.code || "Not established"}</strong><small>{result.code ? `${String(result.code).length}-digit classification level` : "Verified evidence is needed"}</small></div><div><span>Assessed GST rate</span><strong>{result.rate_pct != null ? `${result.rate_pct}%` : "Not established"}</strong><small>Subject to jurisdiction coverage</small></div></div><div className="reason-block"><h3>Reason</h3><p>{humanize(result.reason || report.reason || "No reason recorded")}</p></div>{Boolean(result.missing_facts?.length) && <div className="missing-block"><h3>Missing product facts</h3><ul>{result.missing_facts!.map((item, index) => <li key={`${index}-${item}`}>{humanize(item)}</li>)}</ul></div>}{Boolean(result.missing_sources?.length) && <div className="missing-block"><h3>Missing evidence</h3><ul>{result.missing_sources!.map((item, index) => <li key={`${index}-${item}`}>{humanize(item)}</li>)}</ul></div>}</section>
      <section className="card report-section"><div className="report-section-heading"><h2>Supporting citations</h2><span className="count-badge">{result.citations?.length || 0}</span></div>{result.citations?.length ? <div className="citation-list">{result.citations.map((citation, index) => <div className="citation" key={`${citation.source_id}-${citation.page}-${index}`}><span className="citation-number">{String(index + 1).padStart(2, "0")}</span><details className="citation-details"><summary><CitationTitle citation={citation} source={evidence?.source_links?.[citation.source_id]} /></summary><blockquote>{citation.quote}</blockquote></details></div>)}</div> : <div className="no-citations"><Icon name="document" /><p>No verified citations were issued with this check. A classification or rate is not established without supporting evidence.</p></div>}</section>
      <section className="card report-section"><h2>Details checked</h2><dl className="facts-list"><div><dt>Product</dt><dd>{facts?.name || "Not recorded"}</dd></div><div><dt>Composition</dt><dd>{facts?.composition?.length ? facts.composition.map((i) => `${i.name}${i.proportion_pct != null ? ` (${i.proportion_pct}%)` : ""}`).join(", ") : "Not provided"}</dd></div><div><dt>Form</dt><dd>{facts?.form || "Not provided"}</dd></div><div><dt>Use</dt><dd>{facts?.use || "Not provided"}</dd></div><div><dt>HSN on bill</dt><dd>{bill?.claimed_code || "Not provided"}</dd></div><div><dt>GST rate on bill</dt><dd>{bill?.billed_rate_pct != null ? `${bill.billed_rate_pct}%` : "Not provided"}</dd></div><div><dt>Taxable value</dt><dd>{bill?.taxable_value != null ? money(bill.taxable_value) : "Not provided"}</dd></div></dl></section>
    </div><aside className="report-aside"><section className="next-step-card"><span className="eyebrow">YOUR NEXT STEP</span><h2>{isMissing ? "Resolve the gaps." : "Make an informed decision."}</h2><p>{report.next_step || "Review the facts and cited evidence with your GST adviser before acting."}</p><button className="button secondary no-print" onClick={onEdit}>{isMissing ? "Edit facts & run a new check" : "Use details for a new check"}<Icon name="arrow" size={16} /></button></section><section className="card exposure-card"><p className="eyebrow">TAX DIFFERENCE</p><strong className="exposure-amount">{hasDifference ? money(difference!) : "Not established"}</strong><p>{report.exposure_json?.label || "Estimated difference in tax only"}</p><p className="field-help">Excludes interest and penalty.</p></section><section className="limits-card"><div className="limits-title"><Icon name="info" size={18} /><h2>Read with these limits</h2></div><ul>{qualifications.map((banner) => <li key={banner}>{banner}</li>)}</ul></section></aside></div>
    <section className="disclaimer report-disclaimer"><strong>Placeholder disclaimer — wording pending.</strong></section><p className="report-reference">Check ID: {check.id}{report.law_snapshot_id && <> <span>·</span> Evidence snapshot: {report.law_snapshot_id}</>}</p><p className="print-help no-print">“Download PDF” opens your browser’s print dialog. Choose “Save as PDF” to save this report.</p>
  </article>;
}
