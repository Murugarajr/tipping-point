import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import type { DraftPayload, MaterialSelection, ViabilityPreview, WorkshopDetail } from "../types";
import { Arrow } from "../public/Artwork";
import { navigate, useLocation } from "../navigation";
import { defaultDraft, displayDate, draftDateLabel, draftFromDetail, firstViableLabel, money, payloadForSave, previewMatchesSaved, publicationSetupIssues, savedTermsKey, sections } from "./model";
import type { Section } from "./model";
import { MoneyField, NumberField } from "./Fields";
import Materials from "./Materials";
import { Notice } from "./HostApp";

export default function Workbench({ id, onUnauthorized }: { id: string; onUnauthorized: (cause: unknown) => boolean }) {
  useLocation();
  const section = sections.includes(window.location.hash.slice(1) as Section) ? window.location.hash.slice(1) as Section : "basics";
  const [detail, setDetail] = useState<WorkshopDetail | null>(null);
  const [draft, setDraft] = useState<DraftPayload>(defaultDraft);
  const [baseline, setBaseline] = useState(() => JSON.stringify(draft));
  const [preview, setPreview] = useState<ViabilityPreview | null>(null);
  const [attendance, setAttendance] = useState<number | null>(null);
  const [loading, setLoading] = useState(id !== "new");
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState("");
  const [approved, setApproved] = useState<string | null>(null);
  const [pendingMaterial, setPendingMaterial] = useState(false);
  const [rawChanged, setRawChanged] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const dirty = pendingMaterial || rawChanged || JSON.stringify(draft) !== baseline;
  const frozen = detail?.is_frozen ?? false;
  const publicationIssues = publicationSetupIssues(detail);
  const reviewReady = Boolean(detail && !dirty && !busy && !publicationIssues.length
    && previewMatchesSaved(detail, preview) && preview?.is_viable_at_capacity);
  const materialPendingChanged = useCallback((pending: boolean) => {
    setPendingMaterial(pending);
    if (pending) { setPreview(null); setApproved(null); }
    else setError(null);
  }, []);
  const changeSection = (next: Section) => navigate(`${window.location.pathname}#${next}`, true);
  const apply = (loaded: WorkshopDetail) => {
    const payload = draftFromDetail(loaded);
    setDetail(loaded); setDraft(payload); setBaseline(JSON.stringify(payload)); setRawChanged(false); setApproved(null); setPreview(null);
  };
  const load = async () => {
    setLoading(true); setLoadError(false); setError(null);
    try { apply(await api.getWorkshop(id)); }
    catch (cause) { setLoadError(true); if (!onUnauthorized(cause)) setError(cause instanceof Error ? cause.message : "The saved workshop could not be loaded."); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (id !== "new") void load(); }, [id]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty && !frozen) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, frozen]);
  const update = (next: DraftPayload) => { setDraft(next); setPreview(null); setApproved(null); setSaveState(""); };
  const refreshAfterSave = async (message: string) => {
    try { apply(await api.getWorkshop(id)); return true; }
    catch (cause) {
      setLoadError(true);
      if (!onUnauthorized(cause)) setError(`${message} Saved details could not be reloaded. Try again before editing or publishing.`);
      return false;
    }
  };
  const financial = <K extends keyof DraftPayload["financials"]>(key: K, value: DraftPayload["financials"][K]) => update({ ...draft, financials: { ...draft.financials, [key]: value } });
  const run = async (action: () => Promise<void>, failureLabel = "") => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await action(); }
    catch (cause) {
      setPreview(null); setApproved(null);
      if (!onUnauthorized(cause)) setError(`${failureLabel ? `${failureLabel}: ` : ""}${cause instanceof Error ? cause.message : "The request could not be completed."}`);
    }
    finally { setBusy(false); }
  };
  const save = () => {
    if (pendingMaterial) {
      setError("An entered material has not been added. Add it to the draft or discard it in Materials before saving.");
      changeSection("materials"); return;
    }
    const invalid = body.current?.querySelector<HTMLInputElement>("form[data-draft-form] input:invalid, form[data-draft-form] textarea:invalid, form[data-draft-form] select:invalid");
    if (invalid) {
      changeSection((invalid.closest("[data-section]")?.getAttribute("data-section") ?? "basics") as Section);
      setError(`${invalid.closest("label")?.textContent?.trim() || "Invalid field"}: ${invalid.validationMessage}`);
      setTimeout(() => { invalid.focus(); invalid.reportValidity(); }, 0); return;
    }
    if (!draft.title.trim()) { setError("Enter a workshop title."); changeSection("basics"); return; }
    if (!draft.schedule.opens_at || !draft.schedule.closes_at || new Date(draft.schedule.closes_at) <= new Date(draft.schedule.opens_at)) { setError("Booking close must be after booking open."); changeSection("basics"); return; }
    if (new Date(draft.schedule.closes_at).getTime() - new Date(draft.schedule.opens_at).getTime() > 48 * 3600000) { setError("Booking campaigns are limited to 48 hours."); changeSection("basics"); return; }
    void run(async () => {
      const saved = id === "new" ? await api.createWorkshop(payloadForSave(draft)) : await api.editWorkshop(id, payloadForSave(draft));
      setSaveState("Saved on the server.");
      if (id === "new") {
        navigate(`/host/workshops/${saved.workshop_id}#${section}`, true);
        return;
      }
      await refreshAfterSave("The draft save succeeded.");
    }, id === "new" ? "Could not create draft" : "Could not save changes");
  };
  const calculate = () => {
    setPreview(null); setApproved(null);
    if (!detail || dirty) { setError(pendingMaterial ? "Add or discard the entered material, then save before running the preview." : "Save this workshop and its changes before running the preview."); return; }
    if (!savedTermsKey(detail)) { setError("Saved-term review metadata is missing. Restart the local backend with the updated code, then reload this workshop."); return; }
    void run(async () => {
      const result = await api.previewWorkshop(id);
      if (!previewMatchesSaved(detail, result)) {
        setError("Saved terms changed since this editor loaded. Reload the saved terms before previewing and reviewing again."); return;
      }
      setPreview(result); setAttendance(null);
    }, "Could not run preview");
  };
  const selectOffer = (selection: MaterialSelection) => run(async () => {
    await api.selectMaterial(id, selection);
    setSaveState("Reviewed material selection saved on the server.");
    if (await refreshAfterSave("The material selection succeeded.")) { setPreview(null); setAttendance(null); }
  });
  const publish = () => void run(async () => {
    if (!detail || dirty || approved !== savedTermsKey(detail) || !previewMatchesSaved(detail, preview) || !preview?.is_viable_at_capacity) return;
    const setupIssues = publicationSetupIssues(detail);
    if (setupIssues.length) { setError(setupIssues.join(" ")); return; }
    const campaign = await api.publishWorkshop(id, {
      expected_terms_version: preview.terms_version,
      expected_terms_snapshot_hash: preview.terms_snapshot_hash,
    });
    setDetail({ ...detail, is_frozen: true, campaign_id: campaign.campaign_id, campaign });
    setSaveState("Published on the server. Terms are frozen."); setApproved(null);
    try { apply(await api.getWorkshop(id)); } catch (cause) {
      if (!onUnauthorized(cause)) setError("Publication succeeded. The saved detail refresh failed; the campaign reference below is the real publish response.");
    }
  });
  const leave = () => { if (!dirty || window.confirm("Leave this workshop and discard unsaved changes?")) navigate("/host"); };
  if (loading) return <section className="host-panel" role="status"><h1>Loading saved workshop…</h1></section>;
  if (loadError) return <section className="host-panel"><h1>Workshop unavailable.</h1><Notice error={error} /><button className="host-button secondary" onClick={() => void load()}>Try again</button><button className="host-text-button" onClick={leave}>Your workshops</button></section>;
  const point = preview?.attendance_curve.find((item) => item.attendance === attendance) ?? preview?.attendance_curve.at(-1);
  const prerequisites = <div className="host-notice workflow-prerequisites" aria-live="polite">
    <strong>{pendingMaterial ? "An entered material is not in the draft yet." : !detail ? "Save this workshop first." : dirty ? "Save your changes first." : !reviewReady ? "Finish the publication checks." : "Ready to review the saved terms."}</strong>
    {pendingMaterial ? <><p>Add the material or explicitly discard it, then save the workshop.</p><button type="button" className="host-text-button" onClick={() => changeSection("materials")}>Finish material entry</button></>
      : !detail || dirty ? <><p>{!detail ? "Create this draft before previewing or acknowledging financial terms." : "Save your changes before running the preview."}</p><button type="button" className="host-button secondary" disabled={busy} onClick={save}>{id === "new" ? "Create draft" : "Save workshop"}</button></>
        : !savedTermsKey(detail) ? <><p>Saved-term review metadata is missing. Restart the local backend with the updated code, then reload this workshop.</p><button type="button" className="host-button secondary" disabled={busy} onClick={() => void load()}>Reload saved terms</button></>
          : publicationIssues.length ? <><ul>{publicationIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul><button type="button" className="host-text-button" onClick={() => changeSection(!detail.title.trim() || !detail.opens_at || !detail.closes_at || detail.financials.ticket_price_minor <= 0 ? "basics" : "economics")}>Complete required inputs</button></>
          : !previewMatchesSaved(detail, preview) ? <><p>Run a successful preview of the current saved terms before acknowledging or publishing.</p><button type="button" className="host-button secondary" disabled={busy} onClick={calculate}>Run server preview</button><button type="button" className="host-text-button" disabled={busy} onClick={() => void load()}>Reload saved terms</button></>
            : !preview?.is_viable_at_capacity ? <><p>Costs are not coverable at capacity. Adjust Economics, save and run another preview.</p><button type="button" className="host-text-button" onClick={() => changeSection("economics")}>Review economics</button></>
              : <p>Preview matches saved terms v{detail.terms_version}. The financial acknowledgement below is separate from Channel3’s development budget.</p>}
  </div>;
  return <section className="workbench" ref={body} onInput={(event) => {
    if ((event.target as HTMLElement).closest("form[data-draft-form]")) {
      setRawChanged(true); setPreview(null); setApproved(null); setSaveState("");
    }
  }}>
    <button className="host-text-button back-link" onClick={leave}>← Your workshops</button>
    <div className="host-page-heading"><div><p className="host-kicker">{id === "new" ? "New workshop" : `Workshop / terms v${detail?.terms_version ?? "—"}`}</p><h1>{draft.title || "Untitled workshop"}</h1><div className="workbench-status"><span className={`host-badge ${frozen ? "frozen" : ""}`}>{frozen ? "Published · immutable" : "Draft"}</span><span role="status">{dirty ? "Unsaved changes" : id === "new" ? "Not saved yet" : saveState || "All changes saved"}</span></div></div><div className="row-actions">{!frozen && <button className="host-button" onClick={save} disabled={busy}>{busy ? "Working…" : id === "new" ? "Create draft" : "Save changes"}<Arrow /></button>}{frozen && detail?.campaign && <a className="host-button secondary" href={`/workshops/${id}`}>View public workshop<Arrow diagonal /></a>}</div></div>
    <Notice error={error} />
    {frozen && <div className="host-notice">Publishing freezes these campaign terms. All inputs below are read-only. OPEN means published, not payment-confirmed.</div>}
    <div className="workbench-grid"><div>
      <nav className="workbench-tabs" aria-label="Workshop setup sections">{sections.map((item, index) => <button key={item} aria-current={section === item ? "step" : undefined} onClick={() => changeSection(item)}><span>0{index + 1}</span>{item === "review" ? "Review & publish" : item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
      <section className="host-panel" data-section="basics" hidden={section !== "basics"} aria-labelledby="basics-title"><h2 id="basics-title">The experience, in your words.</h2><p className="host-helper">Save deliberately. No guest bookings or payments happen in this workbench.</p><form data-draft-form onSubmit={(event) => { event.preventDefault(); save(); }}><fieldset disabled={busy || frozen}><label>Workshop title<input required maxLength={200} value={draft.title} onChange={(event) => update({ ...draft, title: event.target.value })} /></label><label>Description<textarea maxLength={5000} rows={5} value={draft.description} onChange={(event) => update({ ...draft, description: event.target.value })} /></label><div className="host-two-col"><MoneyField label="Ticket price" value={draft.financials.ticket_price_minor} onChange={(value) => financial("ticket_price_minor", value)} /><NumberField label="Capacity · places" min={1} value={draft.financials.capacity} onChange={(value) => financial("capacity", value)} /><NumberField label="Minimum operating attendance" min={1} value={draft.financials.minimum_operating_attendance ?? 1} onChange={(value) => financial("minimum_operating_attendance", value)} /></div><h3>Booking window</h3><p className="host-helper">These are booking dates, not the workshop date. Entered in {Intl.DateTimeFormat().resolvedOptions().timeZone}. Maximum duration: 48 hours.</p><div className="host-two-col"><label>Bookings open<input required type="datetime-local" step="0.001" value={draft.schedule.opens_at} onChange={(event) => update({ ...draft, schedule: { ...draft.schedule, opens_at: event.target.value } })} /></label><label>Booking cutoff<input required type="datetime-local" step="0.001" value={draft.schedule.closes_at} onChange={(event) => update({ ...draft, schedule: { ...draft.schedule, closes_at: event.target.value } })} /></label></div></fieldset></form><div className="host-notice">Workshop delivery date, venue, duration and category are not stored by the current backend. They cannot be entered or published in this slice.</div></section>
      <section className="host-panel" data-section="materials" hidden={section !== "materials"} aria-labelledby="materials-title"><h2 id="materials-title">What will you need?</h2><Materials draft={draft} detail={detail} update={update} disabled={busy || frozen} dirty={dirty} onSelect={selectOffer} onUnauthorized={onUnauthorized} onPendingChange={materialPendingChanged} onSave={save} onSection={changeSection} /></section>
      <section className="host-panel" data-section="economics" hidden={section !== "economics"} aria-labelledby="economics-title"><h2 id="economics-title">Understand the cost of running.</h2><p className="host-helper">Amounts are GBP. Fee inputs are your conservative estimates, not an assumed real PayPal fee schedule.</p><form data-draft-form onSubmit={(event) => { event.preventDefault(); save(); }}><fieldset disabled={busy || frozen}><div className="host-two-col"><MoneyField label="Fixed costs" value={draft.financials.fixed_costs_minor} onChange={(value) => financial("fixed_costs_minor", value)} /><MoneyField label="Shipping allowance" value={draft.financials.shipping_allowance_minor} onChange={(value) => financial("shipping_allowance_minor", value)} /><MoneyField label="Contingency" value={draft.financials.contingency_minor} onChange={(value) => financial("contingency_minor", value)} /></div><label>Shipping allowance source<input required maxLength={120} value={draft.financials.shipping_allowance_source} onChange={(event) => financial("shipping_allowance_source", event.target.value)} /></label>{draft.financials.fee_estimate ? <><div className="host-two-col"><NumberField label="Estimated variable fee · basis points (249 = 2.49%)" value={draft.financials.fee_estimate.percent_basis_points} onChange={(value) => financial("fee_estimate", { ...draft.financials.fee_estimate!, percent_basis_points: value })} /><MoneyField label="Estimated fixed fee · per attendee" value={draft.financials.fee_estimate.fixed_minor} onChange={(value) => financial("fee_estimate", { ...draft.financials.fee_estimate!, fixed_minor: value })} /></div><label>Fee estimate source / label<input required maxLength={100} value={draft.financials.fee_estimate.label} onChange={(event) => financial("fee_estimate", { ...draft.financials.fee_estimate!, label: event.target.value })} /></label></> : <button type="button" className="host-button secondary" onClick={() => financial("fee_estimate", { percent_basis_points: 0, fixed_minor: 0, label: "merchant-entered estimate — review required" })}>Add explicit fee assumptions</button>}</fieldset></form><button className="host-button secondary" disabled={id === "new" || dirty || busy} onClick={calculate}>{busy ? "Calculating…" : "Calculate server preview"}</button>{!frozen && prerequisites}{preview && point && <div className="economics-results"><label>Scenario attendance<select value={point.attendance} onChange={(event) => setAttendance(Number(event.target.value))}>{preview.attendance_curve.map((row) => <option key={row.attendance} value={row.attendance}>{row.attendance} people · {row.is_viable ? "viable" : "not viable"}</option>)}</select></label><div className={`host-notice ${point.is_viable ? "host-positive" : "host-warning"}`}><strong>{point.is_viable ? "This attendance covers the approved cost estimate." : "This attendance does not cover the approved cost estimate."}</strong><p>First viable attendance: {preview.first_viable_attendance ?? "none"}. Pack jumps mean higher attendance may still be non-viable.</p></div><dl className="cost-breakdown">{[
        ["Ticket price", preview.ticket_price_minor], ["Estimated gross revenue", point.gross_minor],
        ["Fixed costs", draft.financials.fixed_costs_minor], ["Materials · whole packs", point.material_cost_minor],
        ["Shipping allowance", draft.financials.shipping_allowance_minor], ["Contingency", draft.financials.contingency_minor],
        ["Estimated payment fees", point.estimated_fees_minor], ["Estimated net revenue", point.estimated_net_minor],
        ["Required budget", point.required_budget_minor], ["Estimated surplus", point.estimated_surplus_minor],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{money(value as number)}</dd></div>)}</dl><div className="attendance-curve" aria-label="Server-calculated viability by attendance">{preview.attendance_curve.map((row) => <button key={row.attendance} className={row.is_viable ? "is-viable" : "not-viable"} aria-pressed={point.attendance === row.attendance} onClick={() => setAttendance(row.attendance)} title={`${row.attendance} attendees: ${row.is_viable ? "viable" : "not viable"}, estimated surplus ${money(row.estimated_surplus_minor)}`}><span>{row.attendance}</span><span>{row.is_viable ? "Viable" : "Not viable"}</span></button>)}</div><p className="host-helper">{preview.materials_note}</p><p className="host-helper">Pure server preview · {preview.algorithm_version}. Not a booking, authorization or confirmation.</p></div>}</section>
      <section className="host-panel" data-section="review" hidden={section !== "review"} aria-labelledby="review-title"><h2 id="review-title">{frozen ? "Your published terms." : "One last look before it goes public."}</h2><p className="host-helper">Publishing freezes these campaign terms. Review them before continuing.</p>{!frozen && prerequisites}{(!detail || dirty) && <p className="host-helper">Values below include unsaved input. Add any entered material and save before running the preview.</p>}<h3>Public metadata</h3><dl className="cost-breakdown"><div><dt>Title</dt><dd>{draft.title || "Not set"}</dd></div><div><dt>Description</dt><dd>{draft.description || "Not set"}</dd></div><div><dt>Ticket / capacity</dt><dd>{money(draft.financials.ticket_price_minor)} / {draft.financials.capacity} places</dd></div><div><dt>Bookings open</dt><dd>{draftDateLabel(draft.schedule.opens_at)}</dd></div><div><dt>Cutoff · London time</dt><dd>{draftDateLabel(draft.schedule.closes_at)}</dd></div></dl><h3>Private approved assumptions</h3><dl className="cost-breakdown"><div><dt>Fixed costs / shipping / contingency</dt><dd>{money(draft.financials.fixed_costs_minor)} / {money(draft.financials.shipping_allowance_minor)} / {money(draft.financials.contingency_minor)}</dd></div><div><dt>Fee estimate</dt><dd>{draft.financials.fee_estimate ? `${draft.financials.fee_estimate.percent_basis_points} basis points + ${money(draft.financials.fee_estimate.fixed_minor)} per attendee · ${draft.financials.fee_estimate.label}` : "Missing"}</dd></div><div><dt>Shipping source</dt><dd>{draft.financials.shipping_allowance_source}</dd></div><div><dt>Minimum operating attendance</dt><dd>{draft.financials.minimum_operating_attendance ?? "Not set"}</dd></div></dl><ul className="review-materials">{draft.financials.materials.map((line) => <li key={line.name}><strong>{line.name}</strong> · {line.pack_size} units/pack at {money(line.pack_price_minor)} · {line.shared_units} shared + {line.per_attendee_units}/attendee · {line.kind}<br /><span>{line.selected_offer_snapshot_id ? `Reviewed provider snapshot: ${line.selected_offer_snapshot_id}` : `Merchant assumption: ${line.source_label}`}</span>{detail?.financials.materials.find((item) => item.name === line.name)?.offer_provenance && <p>Retrieved {displayDate(detail.financials.materials.find((item) => item.name === line.name)!.offer_provenance!.retrieved_at)} · suitability and pack-size review recorded on server</p>}</li>)}</ul><div className="host-notice">PayPal Sandbox prototype. No guest reservation or payment is enabled. OPEN is publication status, not workshop or payment confirmation. Private cost and sourcing details are not exposed in public discovery.</div>{detail?.campaign ? <div className="published-reference"><h3>Persisted campaign</h3><dl><div><dt>Campaign reference</dt><dd>{detail.campaign.campaign_id}</dd></div><div><dt>Status</dt><dd>{detail.campaign.status}</dd></div><div><dt>Frozen snapshot hash</dt><dd>{detail.campaign.terms_snapshot_hash}</dd></div></dl><a className="host-button" href={`/workshops/${id}`}>View public workshop<Arrow diagonal /></a></div> : <><button className="host-button secondary" disabled={id === "new" || dirty || busy} onClick={calculate}>Check saved terms with server preview</button>{preview && <p className={`host-notice ${preview.is_viable_at_capacity ? "host-positive" : "host-warning"}`}>{preview.is_viable_at_capacity ? "Costs are coverable at capacity in the current server preview." : "Publishing is blocked: costs cannot be covered at capacity."}</p>}<label className="host-check"><input type="checkbox" checked={Boolean(approved && approved === savedTermsKey(detail))} disabled={!reviewReady} onChange={(event) => setApproved(event.target.checked ? savedTermsKey(detail) : null)} />I have reviewed these exact saved inputs, material assumptions and Sandbox limitations.</label><button className="host-button" disabled={!reviewReady || approved !== savedTermsKey(detail)} onClick={publish}>{busy ? "Publishing…" : "Publish immutable terms"}</button><p className="host-helper">The server revalidates and locks the current terms. A failed request is not publication success.</p></>}</section>
    </div><aside className="workbench-summary host-panel"><p className="host-kicker">The next decision</p><h2>{frozen ? "Published, not confirmed." : dirty ? "Save your changes." : preview ? "Review the whole curve." : "Make the costs clear."}</h2><dl><div><dt>Ticket price</dt><dd>{money(draft.financials.ticket_price_minor)}</dd></div><div><dt>Capacity</dt><dd>{draft.financials.capacity} places</dd></div><div><dt>First viable attendance</dt><dd>{firstViableLabel(preview)}</dd></div><div><dt>At capacity</dt><dd>{preview ? preview.is_viable_at_capacity ? "Viable estimate" : "Not viable" : "Not calculated"}</dd></div></dl><p>No booking counts or collected funds are available. Estimates are not money collected.</p>{!frozen && <button className="host-button secondary" disabled={busy} onClick={() => pendingMaterial ? changeSection("materials") : dirty || !detail ? save() : changeSection("economics")}>{pendingMaterial ? "Finish material entry" : dirty || !detail ? id === "new" ? "Create draft" : "Save workshop" : "View economics"}<Arrow /></button>}</aside></div>
  </section>;
}
