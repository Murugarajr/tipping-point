import { FormEvent, useEffect, useState } from "react";
import * as api from "./api";
import type { Campaign, DraftPayload, MaterialInput, SessionInfo, ViabilityPreview, Workshop } from "./types";

type View = "overview" | "editor" | "review";
type SessionState = "loading" | "anonymous" | "authenticated" | "expired";

const money = (minor: number, currency = "GBP") =>
  new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(minor / 100);

const displayDate = (value: string | null) => value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Not set";

const toDateTimeLocal = (date: Date) => {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
};

function defaultDraft(): DraftPayload {
  const opens = new Date(Date.now() + 60 * 60 * 1000);
  const closes = new Date(Date.now() + 25 * 60 * 60 * 1000);
  return {
    title: "",
    description: "",
    financials: {
      currency: "GBP",
      ticket_price_minor: 0,
      capacity: 8,
      minimum_operating_attendance: 1,
      fixed_costs_minor: 0,
      materials: [],
      shipping_allowance_minor: 0,
      shipping_allowance_source: "merchant-entered estimate",
      contingency_minor: 0,
      fee_estimate: { percent_basis_points: 249, fixed_minor: 30, label: "merchant-entered-conservative-estimate" },
    },
    schedule: { opens_at: toDateTimeLocal(opens), closes_at: toDateTimeLocal(closes) },
  };
}

function ApiNotice({ error }: { error: string | null }) {
  return error ? <div className="notice error" role="alert">{error}</div> : null;
}

function App() {
  const [sessionState, setSessionState] = useState<SessionState>("loading");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [view, setView] = useState<View>("overview");
  const [workshops, setWorkshops] = useState<Workshop[]>([]);
  const [workshopsLoading, setWorkshopsLoading] = useState(false);
  const [workshopsError, setWorkshopsError] = useState<string | null>(null);
  const [activeWorkshop, setActiveWorkshop] = useState<Workshop | null>(null);
  const [sessionEditableWorkshopIds, setSessionEditableWorkshopIds] = useState<Set<string>>(() => new Set());
  const [draft, setDraft] = useState<DraftPayload>(defaultDraft);
  const [preview, setPreview] = useState<ViabilityPreview | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sessionExpired = (error: unknown): boolean => error instanceof api.ApiError && error.status === 401;
  const handleError = (error: unknown, expiredSession = true) => {
    if (expiredSession && sessionExpired(error)) {
      api.clearCsrfToken();
      setSession(null);
      setSessionState("expired");
      return;
    }
    setActionError(error instanceof Error ? error.message : "The request could not be completed.");
  };

  const loadWorkshops = async () => {
    setWorkshopsLoading(true);
    setWorkshopsError(null);
    try {
      setWorkshops(await api.listWorkshops());
    } catch (error) {
      if (sessionExpired(error)) {
        api.clearCsrfToken(); setSession(null); setSessionState("expired");
      } else {
        setWorkshopsError(error instanceof Error ? error.message : "Could not load workshops.");
      }
    } finally {
      setWorkshopsLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        setSession(await api.restoreSession());
        setSessionState("authenticated");
        await loadWorkshops();
      } catch (error) {
        if (sessionExpired(error)) setSessionState("anonymous");
        else setSessionState("anonymous");
      }
    })();
  }, []);

  const startDraft = () => {
    setActiveWorkshop(null); setDraft(defaultDraft()); setPreview(null); setCampaign(null); setActionError(null); setView("editor");
  };

  const openWorkshop = (workshop: Workshop) => {
    setActiveWorkshop(workshop); setPreview(null); setCampaign(null); setActionError(null);
    if (workshop.is_frozen) { setView("review"); return; }
    setView("editor");
  };

  const onLogin = async (identifier: string, password: string) => {
    setBusy(true); setActionError(null);
    try {
      setSession(await api.login(identifier, password));
      setSessionState("authenticated");
      await loadWorkshops();
    } catch (error) { handleError(error, false); }
    finally { setBusy(false); }
  };

  const onLogout = async () => {
    setBusy(true); setActionError(null);
    try { await api.logout(); setSession(null); setSessionState("anonymous"); setWorkshops([]); setView("overview"); }
    catch (error) { handleError(error); }
    finally { setBusy(false); }
  };

  const saveDraft = async (payload: DraftPayload) => {
    setBusy(true); setActionError(null);
    try {
      const saved = activeWorkshop ? await api.editWorkshop(activeWorkshop.workshop_id, payload) : await api.createWorkshop(payload);
      setActiveWorkshop(saved);
      setDraft(payload);
      setSessionEditableWorkshopIds((current) => new Set(current).add(saved.workshop_id));
      setWorkshops((current) => [saved, ...current.filter((workshop) => workshop.workshop_id !== saved.workshop_id)]);
      setPreview(null);
    } catch (error) { handleError(error); }
    finally { setBusy(false); }
  };

  const requestPreview = async () => {
    if (!activeWorkshop) { setActionError("Save the draft before calculating its server-side economics preview."); return; }
    setBusy(true); setActionError(null);
    try { setPreview(await api.previewWorkshop(activeWorkshop.workshop_id)); }
    catch (error) { handleError(error); }
    finally { setBusy(false); }
  };

  const publish = async () => {
    if (!activeWorkshop || !preview) return;
    setBusy(true); setActionError(null);
    try {
      const published = await api.publishWorkshop(activeWorkshop.workshop_id);
      setCampaign(published);
      const frozen = { ...activeWorkshop, is_frozen: true };
      setActiveWorkshop(frozen);
      setWorkshops((current) => current.map((workshop) => workshop.workshop_id === frozen.workshop_id ? frozen : workshop));
    } catch (error) { handleError(error); }
    finally { setBusy(false); }
  };

  if (sessionState === "loading") return <main className="centered"><p className="eyebrow">Tipping Point merchant</p><h1>Checking your session…</h1><p>Loading your secure merchant workspace.</p></main>;
  if (sessionState === "anonymous" || sessionState === "expired") return <LoginScreen expired={sessionState === "expired"} error={actionError} busy={busy} onLogin={onLogin} />;

  return <main>
    <header className="topbar">
      <div><p className="eyebrow">Tipping Point · Sandbox merchant workspace</p><h1>Run the numbers before you commit.</h1></div>
      <div className="merchant-menu"><span>{session?.merchant.name}</span><button className="secondary" onClick={() => void onLogout()} disabled={busy}>Log out</button></div>
    </header>
    <nav className="nav" aria-label="Merchant navigation"><button className={view === "overview" ? "active" : ""} onClick={() => setView("overview")}>Workshops</button>{activeWorkshop && <button className={view === "editor" ? "active" : ""} onClick={() => setView("editor")}>Draft</button>}{activeWorkshop && <button className={view === "review" ? "active" : ""} onClick={() => setView("review")}>Publish review</button>}</nav>
    <ApiNotice error={actionError} />
    {view === "overview" && <WorkshopOverview workshops={workshops} loading={workshopsLoading} error={workshopsError} onRetry={() => void loadWorkshops()} onNew={startDraft} onOpen={openWorkshop} />}
    {view === "editor" && <DraftEditor draft={draft} setDraft={setDraft} workshop={activeWorkshop} sessionEditable={!activeWorkshop || sessionEditableWorkshopIds.has(activeWorkshop.workshop_id)} preview={preview} busy={busy} onSave={(payload) => void saveDraft(payload)} onPreview={() => void requestPreview()} onReview={() => setView("review")} />}
    {view === "review" && <PublishReview workshop={activeWorkshop} preview={preview} campaign={campaign} busy={busy} onPreview={() => void requestPreview()} onPublish={() => void publish()} onBack={() => setView("editor")} />}
  </main>;
}

function LoginScreen({ expired, error, busy, onLogin }: { expired: boolean; error: string | null; busy: boolean; onLogin: (identifier: string, password: string) => Promise<void> }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const submit = (event: FormEvent) => { event.preventDefault(); void onLogin(identifier, password); };
  return <main className="login-shell"><section className="login-card"><p className="eyebrow">Tipping Point · Merchant</p><h1>Plan a workshop that can cover its costs.</h1><p className="muted">Sign in with a merchant account provisioned by your local operator. Payment operations are not available here.</p>{expired && <div className="notice warning">Your merchant session has expired. Sign in again to continue.</div>}<ApiNotice error={error} /><form onSubmit={submit}><label>Login identifier<input required minLength={3} maxLength={100} autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} /></label><label>Password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form></section></main>;
}

function WorkshopOverview({ workshops, loading, error, onRetry, onNew, onOpen }: { workshops: Workshop[]; loading: boolean; error: string | null; onRetry: () => void; onNew: () => void; onOpen: (workshop: Workshop) => void }) {
  return <section className="page"><div className="page-heading"><div><p className="eyebrow">Your workshops</p><h2>Campaign workspace</h2></div><button className="primary" onClick={onNew}>Create draft</button></div>{loading ? <div className="state-card">Loading your owned workshops…</div> : error ? <div className="state-card error"><p>Could not load your workshops: {error}</p><button className="secondary" onClick={onRetry}>Try again</button></div> : workshops.length === 0 ? <div className="state-card"><h3>No workshops yet</h3><p>Create a draft to enter assumptions and run the deterministic server-side economics preview.</p><button className="primary" onClick={onNew}>Create your first draft</button></div> : <div className="workshop-list">{workshops.map((workshop) => <article key={workshop.workshop_id} className="workshop-card"><div><span className={`badge ${workshop.is_frozen ? "published" : "draft"}`}>{workshop.is_frozen ? "Published — immutable" : "Draft"}</span><h3>{workshop.title}</h3><p>{workshop.description || "No description"}</p></div><dl><div><dt>Ticket price</dt><dd>{money(workshop.ticket_price_minor, workshop.currency)}</dd></div><div><dt>Capacity</dt><dd>{workshop.capacity} places</dd></div><div><dt>Booking close</dt><dd>{displayDate(workshop.closes_at)}</dd></div></dl><button className="secondary" onClick={() => onOpen(workshop)}>{workshop.is_frozen ? "View published status" : "Open draft"}</button></article>)}</div>}</section>;
}

function DraftEditor({ draft, setDraft, workshop, sessionEditable, preview, busy, onSave, onPreview, onReview }: { draft: DraftPayload; setDraft: (draft: DraftPayload) => void; workshop: Workshop | null; sessionEditable: boolean; preview: ViabilityPreview | null; busy: boolean; onSave: (payload: DraftPayload) => void; onPreview: () => void; onReview: () => void }) {
  const [material, setMaterial] = useState<MaterialInput>({ name: "", source_label: "merchant-entered assumption", kind: "consumable", shared_units: 0, per_attendee_units: 1, pack_size: 1, pack_price_minor: 0 });
  const [clientError, setClientError] = useState<string | null>(null);
  const disabled = workshop?.is_frozen ?? false;
  const updateFinancial = (key: keyof DraftPayload["financials"], value: number | string) => setDraft({ ...draft, financials: { ...draft.financials, [key]: value } });
  const addMaterial = () => {
    if (!material.name.trim() || material.pack_size < 1 || material.pack_price_minor < 0 || (material.kind === "consumable" && !material.shared_units && !material.per_attendee_units)) { setClientError("Enter a material name, valid pack details, and at least one consumable usage assumption."); return; }
    if (draft.financials.materials.some((line) => line.name === material.name.trim())) { setClientError("Material names must be unique."); return; }
    setDraft({ ...draft, financials: { ...draft.financials, materials: [...draft.financials.materials, { ...material, name: material.name.trim() }] } });
    setMaterial({ name: "", source_label: "merchant-entered assumption", kind: "consumable", shared_units: 0, per_attendee_units: 1, pack_size: 1, pack_price_minor: 0 }); setClientError(null);
  };
  const validateThenSave = () => {
    if (!draft.title.trim()) { setClientError("A workshop title is required."); return; }
    if (draft.financials.minimum_operating_attendance > draft.financials.capacity) { setClientError("Minimum operating attendance cannot exceed capacity."); return; }
    const opens = new Date(draft.schedule.opens_at); const closes = new Date(draft.schedule.closes_at);
    if (Number.isNaN(opens.valueOf()) || Number.isNaN(closes.valueOf()) || closes <= opens) { setClientError("Booking close must be after booking open."); return; }
    if (closes.valueOf() - opens.valueOf() > 48 * 60 * 60 * 1000) { setClientError("Campaign duration cannot exceed 48 hours."); return; }
    const payload = { ...draft, schedule: { opens_at: opens.toISOString(), closes_at: closes.toISOString() } };
    setClientError(null);
    onSave(payload);
  };
  if (workshop && !sessionEditable && !workshop.is_frozen) return <section className="page"><div className="page-heading"><div><p className="eyebrow">Draft terms v{workshop.terms_version}</p><h2>{workshop.title}</h2></div><span className="badge draft">Persisted draft</span></div><div className="state-card contract-gap"><h3>Editing this draft is unavailable after a browser reload</h3><p>The current workshop read API returns its summary, but not the persisted financial inputs, schedule values, material assumptions, or provider-offer provenance needed to reconstruct an editable form safely.</p><p>To avoid overwriting stored terms with invented client values, this frontend does not expose an editor for drafts it did not create or save during this browser session.</p><div className="actions"><button className="secondary" onClick={onPreview} disabled={busy}>{busy ? "Calculating…" : "Calculate current server preview"}</button><button className="primary" onClick={onReview}>Review publication</button></div>{preview && <EconomicsPreview preview={preview} />}</div></section>;
  return <section className="page"><div className="page-heading"><div><p className="eyebrow">{workshop ? `Draft terms v${workshop.terms_version}` : "New workshop"}</p><h2>{workshop ? workshop.title : "Create workshop draft"}</h2></div><span className="badge draft">{workshop ? "Draft" : "Unsaved draft"}</span></div>{workshop && !disabled && <div className="notice info">Editing a saved draft in this browser session. The current read API does not return stored financial inputs, schedules, or material provenance after a reload, so an existing draft cannot be safely rehydrated for editing yet.</div>}{disabled && <div className="notice warning">Published terms are immutable. A material change requires the approved cancellation/new-campaign path.</div>}<ApiNotice error={clientError} /><div className="editor-grid"><div className="form-panel"><fieldset disabled={disabled || busy}><legend>Workshop and campaign</legend><label>Workshop title<input required maxLength={200} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label><label>Description<textarea maxLength={5000} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label><div className="two-col"><NumberField label="Ticket price (pence)" value={draft.financials.ticket_price_minor} onChange={(value) => updateFinancial("ticket_price_minor", value)} /><NumberField label="Capacity" min={1} value={draft.financials.capacity} onChange={(value) => updateFinancial("capacity", value)} /><NumberField label="Minimum operating attendance" min={1} value={draft.financials.minimum_operating_attendance} onChange={(value) => updateFinancial("minimum_operating_attendance", value)} /><NumberField label="Fixed costs (pence)" value={draft.financials.fixed_costs_minor} onChange={(value) => updateFinancial("fixed_costs_minor", value)} /><NumberField label="Shipping allowance (pence)" value={draft.financials.shipping_allowance_minor} onChange={(value) => updateFinancial("shipping_allowance_minor", value)} /><NumberField label="Contingency (pence)" value={draft.financials.contingency_minor} onChange={(value) => updateFinancial("contingency_minor", value)} /><NumberField label="Fee estimate (basis points)" value={draft.financials.fee_estimate.percent_basis_points} onChange={(value) => setDraft({ ...draft, financials: { ...draft.financials, fee_estimate: { ...draft.financials.fee_estimate, percent_basis_points: value } } })} /><NumberField label="Fee estimate fixed amount (pence)" value={draft.financials.fee_estimate.fixed_minor} onChange={(value) => setDraft({ ...draft, financials: { ...draft.financials, fee_estimate: { ...draft.financials.fee_estimate, fixed_minor: value } } })} /></div><label>Shipping allowance source<input maxLength={120} value={draft.financials.shipping_allowance_source} onChange={(event) => updateFinancial("shipping_allowance_source", event.target.value)} /></label><div className="two-col"><label>Booking opens<input type="datetime-local" value={draft.schedule.opens_at} onChange={(event) => setDraft({ ...draft, schedule: { ...draft.schedule, opens_at: event.target.value } })} /></label><label>Booking closes<input type="datetime-local" value={draft.schedule.closes_at} onChange={(event) => setDraft({ ...draft, schedule: { ...draft.schedule, closes_at: event.target.value } })} /></label></div></fieldset><fieldset disabled={disabled || busy}><legend>Material assumptions</legend><p className="helper">These rows are merchant-entered assumptions. They are not verified provider offers and no supplier stock, price, pack quantity, or shipping time is implied.</p>{draft.financials.materials.length > 0 && <ul className="material-list">{draft.financials.materials.map((line) => <li key={line.name}><span><strong>{line.name}</strong> · merchant-entered · {line.kind} · {line.pack_size} units/pack at {money(line.pack_price_minor)}</span><button type="button" className="text-button" onClick={() => setDraft({ ...draft, financials: { ...draft.financials, materials: draft.financials.materials.filter((item) => item.name !== line.name) } })}>Remove</button></li>)}</ul>}<div className="material-form"><label>Material name<input value={material.name} onChange={(event) => setMaterial({ ...material, name: event.target.value })} /></label><label>Type<select value={material.kind} onChange={(event) => setMaterial({ ...material, kind: event.target.value as MaterialInput["kind"] })}><option value="consumable">Consumable</option><option value="reusable">Reusable (not budgeted)</option></select></label><NumberField label="Pack size" min={1} value={material.pack_size} onChange={(value) => setMaterial({ ...material, pack_size: value })} /><NumberField label="Pack price (pence)" value={material.pack_price_minor} onChange={(value) => setMaterial({ ...material, pack_price_minor: value })} /><NumberField label="Shared units" value={material.shared_units} onChange={(value) => setMaterial({ ...material, shared_units: value })} /><NumberField label="Units per attendee" value={material.per_attendee_units} onChange={(value) => setMaterial({ ...material, per_attendee_units: value })} /><button type="button" className="secondary" onClick={addMaterial}>Add material</button></div><div className="provider-note"><strong>Verified provider offers</strong><p>The backend supports an authenticated, server-snapshotted Channel3 search and selection flow. This editor does not call it because the workshop-read contract cannot return selected offer provenance alongside existing draft inputs for safe re-editing. Provider facts and merchant-reviewed assumptions must remain distinct.</p></div></fieldset><div className="actions"><button className="primary" type="button" disabled={disabled || busy} onClick={validateThenSave}>{busy ? "Saving…" : workshop ? "Save draft" : "Create draft"}</button><button className="secondary" type="button" disabled={!workshop || disabled || busy} onClick={onPreview}>Calculate economics preview</button>{preview && <button className="secondary" type="button" onClick={onReview}>Review for publication</button>}</div></div><EconomicsPreview preview={preview} /></div></section>;
}

function NumberField({ label, value, onChange, min = 0 }: { label: string; value: number; onChange: (value: number) => void; min?: number }) { return <label>{label}<input type="number" min={min} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>; }

function EconomicsPreview({ preview }: { preview: ViabilityPreview | null }) {
  if (!preview) return <aside className="preview-panel empty-preview"><p className="eyebrow">Economics preview</p><h3>Not calculated yet</h3><p>Save the draft, then calculate with the backend’s deterministic calculator. No client-side financial result is treated as authoritative.</p></aside>;
  const capacity = preview.attendance_curve.at(-1);
  return <aside className="preview-panel"><p className="eyebrow">Server-calculated economics preview</p><h3>{preview.is_viable_at_capacity ? "Coverable at capacity" : "Not coverable at capacity"}</h3><div className="metrics"><div><span>First viable attendance</span><strong>{preview.first_viable_attendance ?? "None"}</strong></div><div><span>Capacity estimate</span><strong>{capacity ? money(capacity.estimated_surplus_minor, preview.currency) : "—"}</strong></div></div><p className="helper">“Capacity estimate” is an <strong>estimated surplus</strong> after estimated fees and approved draft costs. It is not collected funds, audited profit, a booking total, or a payment confirmation.</p><p className="helper">{preview.materials_note}</p><details><summary>Attendance curve · {preview.algorithm_version}</summary><div className="curve-table"><div className="curve-head"><span>Attendance</span><span>Budget</span><span>Net estimate</span><span>Estimated surplus</span></div>{preview.attendance_curve.map((point) => <div key={point.attendance} className={point.is_viable ? "viable" : ""}><span>{point.attendance}</span><span>{money(point.required_budget_minor, preview.currency)}</span><span>{money(point.estimated_net_minor, preview.currency)}</span><span>{money(point.estimated_surplus_minor, preview.currency)}</span></div>)}</div></details></aside>;
}

function PublishReview({ workshop, preview, campaign, busy, onPreview, onPublish, onBack }: { workshop: Workshop | null; preview: ViabilityPreview | null; campaign: Campaign | null; busy: boolean; onPreview: () => void; onPublish: () => void; onBack: () => void }) {
  const canPublish = Boolean(workshop && preview?.is_viable_at_capacity && !workshop.is_frozen);
  if (!workshop) return <section className="page state-card"><h2>No draft selected</h2><p>Create or open a draft before reviewing publication.</p></section>;
  return <section className="page review"><p className="eyebrow">Publish review</p><h2>{workshop.title}</h2>{campaign || workshop.is_frozen ? <><div className="notice success"><strong>Published — immutable terms.</strong> This campaign is OPEN for publication status only. It is not confirmed, no guest booking data is available here, and no funds have been collected through this UI.</div>{campaign && <dl className="review-list"><div><dt>Campaign ID</dt><dd>{campaign.campaign_id}</dd></div><div><dt>Booking cutoff</dt><dd>{displayDate(campaign.cutoff_at)}</dd></div><div><dt>Frozen terms hash</dt><dd className="hash">{campaign.terms_snapshot_hash}</dd></div></dl>}<BookingUnavailable /></> : <><p>Review the current saved draft before freezing it. Publishing uses the backend’s ownership checks, current stored terms, fresh server-side validation, and capacity viability gate.</p>{!preview ? <div className="state-card"><h3>Preview required</h3><p>Calculate the server-side economics preview before publication review.</p><button className="primary" onClick={onPreview} disabled={busy}>{busy ? "Calculating…" : "Calculate preview"}</button></div> : <><EconomicsPreview preview={preview} /><div className="notice warning"><strong>Publishing is a one-way terms freeze.</strong> Published terms cannot be edited. “Open” means published; it does not mean a guest has authorized payment, a place has been reserved, or any payment has been collected.</div><div className="actions"><button className="secondary" onClick={onBack}>Back to draft</button><button className="primary" disabled={!canPublish || busy} onClick={onPublish}>{busy ? "Publishing…" : "Confirm and publish immutable terms"}</button></div>{!preview.is_viable_at_capacity && <p className="validation-copy">Publication is blocked: the current draft cannot cover costs at maximum capacity.</p>}</>}</>}</section>;
}

function BookingUnavailable() { return <section className="booking-unavailable"><p className="eyebrow">Guest booking and payment</p><h3>Unavailable in this slice</h3><p>Booking-domain persistence and server-side payment operations are not implemented for the frontend. No “Reserve with PayPal” control is shown, no PayPal secret is exposed, and this UI cannot invoke the operator runner.</p><p><strong>Collected funds: unavailable.</strong> An estimated surplus is not collected money.</p></section>; }

export default App;