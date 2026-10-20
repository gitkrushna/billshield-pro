"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { accessToken, apiRequest, loadAuthConfig, signIn, signOut, signUp } from "../lib/auth";
import { CheckReport, ErrorNotice, Icon, type Check, type Draft, blank, states, formatDate } from "./ui";

type CheckSummary = { id: string; description: string; result: string; created_at: string };
type Identity = { org_id: string; email: string };
type View = "new" | "checks" | "report";

export default function Home() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [starting, setStarting] = useState(true);
  const [authBusy, setAuthBusy] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [authError, setAuthError] = useState("");
  const [view, setView] = useState<View>("new");
  const [draft, setDraft] = useState<Draft>(blank);
  const [check, setCheck] = useState<Check | null>(null);
  const [checks, setChecks] = useState<CheckSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadingCheck, setLoadingCheck] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [editing, setEditing] = useState(false);
  const requestKey = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const loadSequence = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);

  async function openCheck(id: string) {
    const sequence = ++loadSequence.current;
    setView("report"); setError(""); setCheck(null); setLoadingCheck(true);
    try { const response = await apiRequest<Check>(`/api/checks/${encodeURIComponent(id)}`); if (sequence === loadSequence.current) setCheck(response); }
    catch (e) { if (sequence === loadSequence.current) setError(e instanceof Error ? e.message : "Unable to load this check."); }
    finally { if (sequence === loadSequence.current) setLoadingCheck(false); }
  }

  async function connect() {
    setIdentity(await apiRequest<Identity>("/api/session", { method: "POST" }));
    const id = new URLSearchParams(window.location.search).get("check");
    if (id) await openCheck(id);
  }

  useEffect(() => {
    let active = true;
    (async () => {
      try { await loadAuthConfig(); if (active && await accessToken()) await connect(); }
      catch (e) { if (active) setAuthError(e instanceof Error ? e.message : "Unable to connect. Please try again."); }
      finally { if (active) setStarting(false); }
    })();
    const navigate = () => { const id = new URLSearchParams(window.location.search).get("check"); if (id) void openCheck(id); else { setView("new"); setError(""); } };
    window.addEventListener("popstate", navigate);
    return () => { active = false; window.removeEventListener("popstate", navigate); abort.current?.abort(); };
    // Session restoration runs once; requests always read the current token.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => { if (!starting && identity) heading.current?.focus(); }, [view, starting, identity]);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setAuthBusy(true); setAuthError(""); setAuthMessage("");
    try {
      if (authMode === "signup") {
        if (!await signUp(email.trim(), password)) { setAuthMessage("Check your email to confirm your account, then return here to sign in."); setAuthMode("login"); setPassword(""); return; }
      } else await signIn(email.trim(), password);
      await connect(); setPassword("");
    } catch (e) { setAuthError(e instanceof Error ? e.message : "Unable to sign in. Please try again."); }
    finally { setAuthBusy(false); }
  }

  function update<K extends keyof Draft>(key: K, value: Draft[K]) { setDraft((current) => ({ ...current, [key]: value })); requestKey.current = null; setError(""); }

  function newCheck(prefill?: Draft) {
    if (busy) return;
    loadSequence.current++;
    window.history.pushState({}, "", window.location.pathname);
    setDraft(prefill || blank()); setEditing(Boolean(prefill)); setView("new"); setError(""); requestKey.current = null;
    if (view === "new") heading.current?.focus();
  }

  function navigateCheck(id: string) {
    window.history.pushState({}, "", `?check=${encodeURIComponent(id)}`);
    void openCheck(id);
  }

  async function listChecks() {
    if (busy) return;
    loadSequence.current++;
    setView("checks"); setError(""); setListError(""); setLoadingList(true);
    window.history.pushState({}, "", window.location.pathname);
    try { setChecks((await apiRequest<{ checks: CheckSummary[] }>("/api/checks")).checks); }
    catch (e) { setListError(e instanceof Error ? e.message : "Unable to load your checks."); }
    finally { setLoadingList(false); }
  }

  async function submitCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return;
    if (!draft.description.trim() || !draft.form.trim() || !draft.use.trim()) { setError("Add the product description, form, and intended use before running a check."); return; }
    setError(""); setBusy(true); setElapsed(0);
    const controller = new AbortController(); abort.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 245000);
    requestKey.current ||= crypto.randomUUID();
    const bill: Record<string, string | number> = {};
    if (draft.code.trim()) bill.claimed_code = draft.code.trim();
    if (draft.rate !== "") bill.billed_rate_pct = Number(draft.rate);
    if (draft.value !== "") bill.taxable_value = Number(draft.value);
    const body = {
      facts: { name: draft.description.trim(), composition: draft.composition.trim() ? [{ name: draft.composition.trim(), proportion_pct: null }] : [], form: draft.form.trim(), use: draft.use.trim() },
      bill, state: draft.state, as_of: draft.date,
      ...(draft.billText.trim() ? { bill_text: draft.billText.trim(), bill_text_reviewed: draft.reviewed } : {}),
    };
    try {
      const result = await apiRequest<Check>("/api/checks", { method: "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": requestKey.current }, signal: controller.signal });
      setCheck(result); setView("report"); requestKey.current = null;
      window.history.pushState({}, "", `?check=${encodeURIComponent(result.id)}`);
    } catch (e) {
      setError(e instanceof Error && e.name === "AbortError" ? "This check is taking longer than expected. Retry with the same details to recover its result safely." : e instanceof Error ? e.message : "Unable to run this check. Please retry.");
    } finally { clearTimeout(timer); setBusy(false); abort.current = null; }
  }

  function editReport() {
    const evidence = check?.report.evidence, facts = evidence?.facts, bill = evidence?.bill;
    newCheck({ ...blank(), description: facts?.name || "", composition: facts?.composition?.map((i) => `${i.name}${i.proportion_pct != null ? ` (${i.proportion_pct}%)` : ""}`).join(", ") || "", form: facts?.form || "", use: facts?.use || "", code: bill?.claimed_code || "", rate: bill?.billed_rate_pct == null ? "" : String(bill.billed_rate_pct), value: bill?.taxable_value == null ? "" : String(bill.taxable_value), state: evidence?.jurisdiction && states.includes(evidence.jurisdiction) ? evidence.jurisdiction : "Goa", date: evidence?.as_of || blank().date });
  }

  async function logout() {
    loadSequence.current++;
    await signOut(); setIdentity(null); setCheck(null); setChecks([]); setDraft(blank()); setView("new"); setAuthError(""); setAuthMessage("");
    window.history.replaceState({}, "", window.location.pathname);
  }

  if (starting) return <div className="startup" role="status"><span className="brand-icon"><Icon name="shield" size={28} /></span><strong>BillShield<span>Pro</span></strong><span className="spinner" /><p>Connecting to your workspace…</p></div>;

  if (!identity) return <main className="auth-layout">
    <section className="auth-story">
      <Link className="brand" href="/" aria-label="BillShield Pro home"><span className="brand-icon"><Icon name="shield" size={27} /></span><span>BillShield<span className="brand-pro">Pro</span></span></Link>
      <div className="auth-pitch"><p className="eyebrow light">A clearer view of your GST bill</p><h1>Know what supports<br />your classification.</h1><p>Bring your product facts and bill details. Get a careful check with cited evidence, clear limits, and a practical next step.</p><div className="auth-promises"><div><Icon name="document" /><span>Evidence you can inspect</span></div><div><Icon name="shield" /><span>Uncertainty made visible</span></div></div></div>
      <p className="auth-note">Built for informed review. Final tax decisions deserve professional judgment.</p>
    </section>
    <section className="auth-panel"><div className="auth-card"><p className="eyebrow">Your workspace</p><h2>{authMode === "login" ? "Welcome back." : "Start with clarity."}</h2><p className="muted">{authMode === "login" ? "Sign in to run a check and revisit your reports." : "Create your account. Your personal workspace is set up automatically."}</p>
      {authError && <ErrorNotice>{authError}</ErrorNotice>}{authMessage && <div className="notice success" role="status"><Icon name="check" /><span>{authMessage}</span></div>}
      <form onSubmit={authenticate} className="auth-form"><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={authBusy} /><label htmlFor="password">Password</label><input id="password" type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} placeholder={authMode === "signup" ? "At least 8 characters" : "Your password"} minLength={authMode === "signup" ? 8 : undefined} value={password} onChange={(e) => setPassword(e.target.value)} required disabled={authBusy} /><button className="button primary auth-submit" disabled={authBusy}>{authBusy ? <><span className="spinner" /> Connecting…</> : <>{authMode === "login" ? "Sign in" : "Create account"}<Icon name="arrow" size={18} /></>}</button></form>
      <p className="auth-switch">{authMode === "login" ? "New to BillShield?" : "Already have an account?"} <button type="button" className="text-button" disabled={authBusy} onClick={() => { setAuthMode(authMode === "login" ? "signup" : "login"); setAuthError(""); setAuthMessage(""); }}>{authMode === "login" ? "Create an account" : "Sign in"}</button></p>
      <p className="auth-fine">Placeholder disclaimer — wording pending.</p>
    </div><span className="quiet-wordmark">BILLSHIELD PRO</span></section>
  </main>;

  return <div className="app-shell">
    <aside className="sidebar no-print"><Link className="brand" href="/" onClick={(e) => { e.preventDefault(); newCheck(); }}><span className="brand-icon"><Icon name="shield" size={24} /></span><span>BillShield<span className="brand-pro">Pro</span></span></Link><div className="workspace-label">YOUR WORKSPACE</div><nav aria-label="Main navigation"><button className={`nav-item ${view === "new" ? "active" : ""}`} onClick={() => newCheck()} disabled={busy}><Icon name="plus" />New check</button><button className={`nav-item ${view === "checks" ? "active" : ""}`} onClick={() => void listChecks()} disabled={busy}><Icon name="list" />My checks</button></nav><div className="sidebar-bottom"><div className="coverage-mini"><span className="status-dot" /><span>Evidence-led checks</span></div><p>Every result includes its limits.</p><div className="account"><span className="avatar">{identity.email.slice(0, 1).toUpperCase()}</span><div><strong>Personal workspace</strong><span title={identity.email}>{identity.email}</span></div><button className="icon-button" onClick={() => void logout()} title="Sign out" aria-label="Sign out" disabled={busy}><Icon name="logout" size={18} /></button></div></div></aside>
    <div className="main-wrap"><header className="topbar no-print"><span>Workspace <span className="breadcrumb">/</span> {view === "new" ? "New check" : view === "checks" ? "My checks" : "Check report"}</span><span className="private-label"><Icon name="shield" size={14} />Private to your account</span></header>
    <main className="content" id="main-content">
      {view === "new" && <>
        <div className="page-heading"><div><p className="eyebrow">PRODUCT CLASSIFICATION & GST</p><h1 ref={heading} tabIndex={-1}>{editing ? "Add clarity. Check again." : "A little detail. A clearer decision."}</h1><p className="muted">{editing ? "Update the facts below to create a new check. Your previous report stays as issued." : "Tell us what the product is and what appears on the bill."}</p></div><span className="page-badge"><Icon name="document" size={16} />New check</span></div>
        <form className="check-layout" onSubmit={submitCheck}>
          <div className="form-column"><fieldset className="card form-card" disabled={busy}><legend className="sr-only">Product and bill details</legend><div className="section-heading"><span className="step-number">01</span><div><h2>The product</h2><p>Specific facts help us assess the right classification.</p></div></div>
          <div className="field"><label htmlFor="description">Product description <span className="required">*</span></label><textarea id="description" rows={3} maxLength={200} placeholder="e.g. Roasted, salted cashew nuts in a sealed retail pack" value={draft.description} onChange={(e) => update("description", e.target.value)} required /><p className="field-help">Use the product name and details from its label. Avoid names or contact details.</p></div>
          <div className="field"><label htmlFor="composition">Composition / ingredients <span className="optional">Optional</span></label><textarea id="composition" rows={2} maxLength={200} placeholder="e.g. Cashew nuts, vegetable oil, salt; include proportions if known" value={draft.composition} onChange={(e) => update("composition", e.target.value)} /></div>
          <div className="field-grid"><div className="field"><label htmlFor="form">Product form <span className="required">*</span></label><input id="form" required maxLength={200} placeholder="e.g. Roasted, ready to eat" value={draft.form} onChange={(e) => update("form", e.target.value)} /></div><div className="field"><label htmlFor="use">Intended use <span className="required">*</span></label><input id="use" required maxLength={300} placeholder="e.g. Packaged snack" value={draft.use} onChange={(e) => update("use", e.target.value)} /></div></div>
          <div className="form-divider" /><div className="section-heading"><span className="step-number">02</span><div><h2>The bill</h2><p>Enter the printed values. Leave unknown fields empty.</p></div></div>
          <div className="field-grid bill-grid"><div className="field"><label htmlFor="code">HSN on bill <span className="optional">Optional</span></label><input id="code" inputMode="numeric" pattern="[0-9]{4}|[0-9]{6}|[0-9]{8}" title="Enter a 4, 6, or 8 digit HSN code" maxLength={8} placeholder="e.g. 20081920" value={draft.code} onChange={(e) => update("code", e.target.value)} /></div><div className="field"><label htmlFor="rate">GST rate <span className="optional">Optional</span></label><div className="input-affix"><input id="rate" type="number" min="0" max="100" step="0.01" placeholder="e.g. 12" value={draft.rate} onChange={(e) => update("rate", e.target.value)} /><span>%</span></div></div><div className="field"><label htmlFor="value">Taxable value <span className="optional">Optional</span></label><div className="input-affix prefix"><span>₹</span><input id="value" type="number" min="0" max="1000000000000" step="0.01" placeholder="e.g. 10,000" value={draft.value} onChange={(e) => update("value", e.target.value)} /></div></div></div>
          <div className="field-grid"><div className="field"><label htmlFor="state">State / union territory <span className="required">*</span></label><select id="state" value={draft.state} onChange={(e) => update("state", e.target.value)}>{states.map((state) => <option key={state}>{state}</option>)}</select><p className="field-help">Evidence coverage varies by jurisdiction.</p></div><div className="field"><label htmlFor="date">Check as of <span className="required">*</span></label><input id="date" type="date" value={draft.date} onChange={(e) => update("date", e.target.value)} required /><p className="field-help">The date used to assess the cited evidence.</p></div></div>
          <details className="bill-details"><summary>Have bill text? <span>Paste it here · optional</span></summary><div className="field"><label htmlFor="bill-text">Bill text</label><p className="field-help" id="privacy-help">Remove names, phone numbers, addresses, GSTINs, and other personal details before pasting.</p><textarea id="bill-text" rows={5} maxLength={20000} placeholder="Paste the relevant product and tax lines only…" aria-describedby="privacy-help" value={draft.billText} onChange={(e) => { update("billText", e.target.value); setDraft((current) => ({ ...current, reviewed: false })); }} /></div>{draft.billText.trim() && <label className="checkbox-label"><input type="checkbox" checked={draft.reviewed} onChange={(e) => update("reviewed", e.target.checked)} required /> <span>I have removed personal details from this bill text.</span></label>}</details>
          </fieldset>
          {error && <ErrorNotice>{error}</ErrorNotice>}
          <div className="submit-row"><p><Icon name="shield" size={15} />Saved privately in your workspace</p><button className="button primary" type="submit" disabled={busy || Boolean(draft.billText.trim() && !draft.reviewed)}>{busy ? <><span className="spinner" />Checking…</> : <>{requestKey.current ? "Retry check" : "Run check"}<Icon name="arrow" size={18} /></>}</button></div>
          {busy && <div className="processing" role="status" aria-live="polite"><span className="spinner" /><div><strong>{elapsed < 30 ? "Checking your product and bill details" : elapsed < 120 ? "Assessing classification and supporting evidence" : "The evidence check is still running"}</strong><p>Checks can take up to 240 seconds. Keep this page open. {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")} elapsed.</p></div></div>}
          </div>
          <aside className="form-aside"><div className="guide-card"><span className="guide-icon"><Icon name="shield" size={25} /></span><h2>Clarity, with context.</h2><p>A check brings together your product facts, the bill, and the available legal evidence.</p><div className="guide-step"><span>1</span><div><strong>Describe the product</strong><p>Its composition, form, and use matter.</p></div></div><div className="guide-step"><span>2</span><div><strong>Compare the bill</strong><p>Check the HSN and rate shown.</p></div></div><div className="guide-step"><span>3</span><div><strong>Review the evidence</strong><p>Read the reasons, citations, and next step.</p></div></div></div><div className="coverage-note"><Icon name="info" size={18} /><div><strong>Evidence has limits</strong><p>Amendments after 22 Sep 2025 are not verified. Missing facts or sources may lead to “Need more info.”</p></div></div><p className="disclaimer small">Placeholder disclaimer — wording pending.</p></aside>
        </form>
      </>}
      {view === "checks" && <><div className="page-heading"><div><p className="eyebrow">YOUR RECORDS</p><h1 ref={heading} tabIndex={-1}>My checks</h1><p className="muted">Return to the facts and evidence behind each result.</p></div><button className="button primary" onClick={() => newCheck()}><Icon name="plus" size={18} />New check</button></div><section className="card checks-card" aria-label="Saved checks">{loadingList ? <div className="empty-state" role="status"><span className="spinner" /><h2>Loading your checks…</h2></div> : listError ? <div className="empty-state"><ErrorNotice>{listError}</ErrorNotice><button className="button secondary" onClick={() => void listChecks()}>Try again</button></div> : checks.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="document" size={30} /></span><h2>Your first check starts here.</h2><p>Run a check to build a record of your product classifications.</p><button className="button primary" onClick={() => newCheck()}><Icon name="plus" size={18} />Create your first check</button></div> : <><div className="checks-table-head"><span>Product</span><span>Result</span><span>Created</span><span /></div>{checks.map((item) => <a className="check-row" href={`/?check=${encodeURIComponent(item.id)}`} key={item.id} onClick={(e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) { e.preventDefault(); navigateCheck(item.id); } }}><span className="check-description"><Icon name="document" /><span>{item.description || "Product check"}<small>Check {item.id.slice(0, 8)}</small></span></span><span><span className={`result-pill ${item.result === "Supported" ? "supported" : "review"}`}>{item.result}</span></span><span className="check-date">{formatDate(item.created_at)}</span><Icon name="arrow" size={18} /></a>)}</>}</section></>}
      {view === "report" && <>{loadingCheck ? <div className="card empty-state" role="status"><span className="spinner" /><h1 ref={heading} tabIndex={-1}>Loading your report…</h1></div> : error ? <div className="card empty-state"><h1 ref={heading} tabIndex={-1}>Report unavailable</h1><ErrorNotice>{error}</ErrorNotice><div className="action-group"><button className="button secondary" onClick={() => { const id = new URLSearchParams(window.location.search).get("check"); if (id) void openCheck(id); }}>Try again</button><button className="button primary" onClick={() => void listChecks()}>My checks</button></div></div> : check ? <CheckReport check={check} heading={heading} onEdit={editReport} onNew={() => newCheck()} /> : null}</>}
      <footer className="page-footer"><span>BillShield Pro</span><span>Facts first. Evidence always.</span></footer>
    </main></div>
  </div>;
}
