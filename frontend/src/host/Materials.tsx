import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import * as api from "../api";
import type { DraftPayload, MaterialInput, MaterialOffer, MaterialSearchResult, MaterialSelection, WorkshopDetail } from "../types";
import { MoneyField, NumberField } from "./Fields";
import { displayDate, materialIsSaved, money } from "./model";
import type { Section } from "./model";

const manualDefaults = (): MaterialInput => ({
  name: "", source_label: "merchant-entered assumption", kind: "consumable",
  shared_units: 0, per_attendee_units: 1, pack_size: 1, pack_price_minor: 0,
});
function safeLink(raw: string | null) {
  try { const url = new URL(raw ?? ""); return url.protocol === "https:" ? url.href : null; }
  catch { return null; }
}
export default function Materials({ draft, detail, update, disabled, dirty, onSelect, onUnauthorized, onPendingChange, onSave, onSection }: {
  draft: DraftPayload; detail: WorkshopDetail | null; update: (value: DraftPayload) => void;
  disabled: boolean; dirty: boolean; onSelect: (value: MaterialSelection) => Promise<void>;
  onUnauthorized: (cause: unknown) => boolean;
  onPendingChange: (pending: boolean) => void;
  onSave: () => void;
  onSection: (section: Section) => void;
}) {
  const [manual, setManual] = useState(manualDefaults);
  const manualForm = useRef<HTMLFormElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [budgetReviewed, setBudgetReviewed] = useState(false);
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState<MaterialSearchResult | null>(null);
  const [selected, setSelected] = useState<MaterialOffer | null>(null);
  const [selection, setSelection] = useState<MaterialSelection>({
    offer_snapshot_id: "", material_name: "", kind: "consumable", pack_size: 1,
    shared_units: 0, per_attendee_units: 1, suitability_reviewed: false,
    pack_size_reviewed: false, review_notes: "", shipping_allowance_minor: 0,
    shipping_allowance_source: "",
  });
  const [editingManual, setEditingManual] = useState<string | null>(null);
  const [manualTouched, setManualTouched] = useState(false);
  const [manualRevision, setManualRevision] = useState(0);
  const manualPending = manualTouched || editingManual !== null || JSON.stringify(manual) !== JSON.stringify(manualDefaults());
  useEffect(() => { onPendingChange(manualPending); }, [manualPending, onPendingChange]);
  const discardManual = () => { setManual(manualDefaults()); setEditingManual(null); setManualTouched(false); setManualRevision((value) => value + 1); setError(null); };
  const providerPrerequisite = !detail ? "Save this workshop before searching for materials."
    : dirty ? "Save your changes before searching for materials. Add or discard any entered material first."
      : searching ? "A Channel3 search is running. Wait for its result."
        : disabled ? "Wait for the current workshop request to finish."
          : !budgetReviewed ? "Acknowledge the existing development request budget before searching."
            : !query.trim() ? "Enter a material search query." : null;
  const addManual = (event: FormEvent) => {
    event.preventDefault(); setError(null);
    if (!manual.name.trim() || (manual.kind === "consumable" && !manual.shared_units && !manual.per_attendee_units)) { setError("Enter a material name and at least one consumable usage quantity."); return; }
    if (draft.financials.materials.some((line) => line.name === manual.name.trim() && line.name !== editingManual)) { setError("Material names must be unique."); return; }
    const lines = draft.financials.materials.filter((line) => line.name !== editingManual);
    update({ ...draft, financials: { ...draft.financials, materials: [...lines, { ...manual, name: manual.name.trim() }] } });
    discardManual();
  };
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!detail || dirty || disabled || searching || !budgetReviewed || !query.trim()) return;
    setSearching(true); setError(null); setSelected(null);
    try { setResult(await api.searchMaterials(detail.workshop_id, query.trim())); }
    catch (cause) {
      if (!onUnauthorized(cause)) setError(cause instanceof Error ? cause.message : "Channel3 search is unavailable.");
    } finally { setSearching(false); }
  };
  const choose = (offer: MaterialOffer) => {
    setSelected(offer);
    setSelection({
      ...selection, offer_snapshot_id: offer.offer_snapshot_id, material_name: offer.product_title,
      suitability_reviewed: false, pack_size_reviewed: false, review_notes: "",
      shipping_allowance_minor: draft.financials.shipping_allowance_minor,
      shipping_allowance_source: draft.financials.shipping_allowance_source,
    });
  };
  const submitSelection = async (event: FormEvent) => {
    event.preventDefault();
    if (!selection.material_name.trim() || (!selection.shared_units && !selection.per_attendee_units && selection.kind === "consumable")) { setError("Review the name and usage quantities."); return; }
    await onSelect({ ...selection, material_name: selection.material_name.trim() });
  };
  return <div className="materials-workbench">
    <p className="host-helper">Provider facts and your assumptions stay separate. Consumables are budgeted in whole packs; reusable equipment is recorded but not budgeted by the current costing policy.</p>
    <div className="host-notice"><strong>Enter → Add material → Save workshop.</strong><p>Typing in the form does not add a line. Add it to the draft, then save the workshop to persist it on the server.</p></div>
    {error && <div className="host-notice host-error" role="alert">{error}</div>}
    <ul className="host-material-list">{draft.financials.materials.map((line) => {
      const provenance = detail?.financials.materials.find((item) => item.name === line.name)?.offer_provenance;
      const stale = provenance && detail && Date.now() - new Date(provenance.retrieved_at).getTime() > detail.offer_stale_after_seconds * 1000;
      return <li key={line.name}><div><strong>{line.name}</strong><span className="material-save-state">{materialIsSaved(line, detail) ? "Saved on server" : "Not saved yet — save workshop"}</span><span className="host-badge">{line.selected_offer_snapshot_id ? "Provider snapshot + reviewed assumptions" : "Merchant-entered assumption"}</span><p>{line.pack_size} units/pack · {money(line.pack_price_minor)} per pack · {line.shared_units} shared units + {line.per_attendee_units} per attendee · {line.kind}</p>{provenance ? <div className="material-provenance"><p>Provider fact: {provenance.product_title} · {provenance.merchant_domain} · {money(provenance.price_minor)}</p><p>Retrieved {displayDate(provenance.retrieved_at)}{stale ? " · STALE — reviewed replacement required before publication" : " · cached server snapshot, not a fresh search"}</p><p>Suitability: {provenance.suitability_reviewed ? "reviewed" : "not reviewed"} · pack size: {provenance.pack_size_reviewed ? "reviewed" : "not reviewed"}</p>{provenance.review_notes && <p>Review notes: {provenance.review_notes}</p>}{safeLink(provenance.product_url) && <a href={safeLink(provenance.product_url)!} target="_blank" rel="noopener noreferrer" className="text-link">View source ↗</a>}<p>To change a selected offer or its assumptions, use explicit search and selection below. Existing facts cannot be overwritten by a draft save.</p></div> : <p>Source: {line.source_label}. Not verified provider pricing.</p>}</div>{!disabled && <div className="material-actions">{!line.selected_offer_snapshot_id && <button className="host-text-button" onClick={() => { setManual({ ...line }); setEditingManual(line.name); }}>Edit assumption</button>}<button className="host-text-button" onClick={() => update({ ...draft, financials: { ...draft.financials, materials: draft.financials.materials.filter((item) => item.name !== line.name) } })}>Remove</button></div>}</li>;
    })}</ul>{dirty && !manualPending && !detail?.is_frozen && <div className="host-notice"><p>Material additions, edits and removals are not persisted until you save the workshop.</p><button type="button" className="host-button secondary" disabled={disabled} onClick={onSave}>{detail ? "Save workshop" : "Create draft"}</button></div>}
    {!draft.financials.materials.length && <p className="host-notice">No material lines yet. Add reviewed manual assumptions, or explicitly search for provider offers after saving the draft.</p>}
    {!detail?.is_frozen && <><h3>{editingManual ? "Edit a manual assumption" : "Add a manual assumption"}</h3><form key={`${manualRevision}:${editingManual ?? "new"}`} ref={manualForm} className="manual-material-form" onInput={() => setManualTouched(true)} onSubmit={addManual}><fieldset disabled={disabled}><label>Material name<input required maxLength={200} value={manual.name} onChange={(event) => setManual({ ...manual, name: event.target.value })} /></label><label>Source / assumption label<input required maxLength={100} value={manual.source_label} onChange={(event) => setManual({ ...manual, source_label: event.target.value })} /></label><div className="host-two-col"><label>Material type<select value={manual.kind} onChange={(event) => setManual({ ...manual, kind: event.target.value as MaterialInput["kind"] })}><option value="consumable">Consumable · budgeted</option><option value="reusable">Reusable · not budgeted</option></select></label><MoneyField label="Assumed pack price" value={manual.pack_price_minor} onChange={(value) => setManual({ ...manual, pack_price_minor: value })} /><NumberField label="Units per pack" min={1} value={manual.pack_size} onChange={(value) => setManual({ ...manual, pack_size: value })} /><NumberField label="Shared units" value={manual.shared_units} onChange={(value) => setManual({ ...manual, shared_units: value })} /><NumberField label="Units per attendee" value={manual.per_attendee_units} onChange={(value) => setManual({ ...manual, per_attendee_units: value })} /></div><button className="host-button secondary" type="submit">{editingManual ? "Update material in draft" : "Add material to draft"}</button>{manualPending && <button type="button" className="host-text-button" onClick={discardManual}>Discard entered material</button>}</fieldset></form>{manualPending && <p className="host-notice host-warning pending-material-notice" role="status">This material has been entered but not added. Add it to the draft or explicitly discard it before saving, previewing or publishing.</p>}
      <div className="channel3-section"><h3>Find material offers with Channel3</h3><p className="host-helper">Explicit search only · GB / English / GBP. No searches run on page load or while typing. Search results are not stock reservations, verified pack quantities or delivered-cost guarantees.</p><p className="host-notice host-warning">The existing live-request allowance has not been reset. Reconcile earlier attempts and confirm remaining budget before searching. Live contract verification remains incomplete.</p><p className="host-helper">This development-budget acknowledgement is only for provider search. Manual materials can be saved, previewed and published without checking it.</p>{providerPrerequisite && <div className="host-notice provider-prerequisites" aria-live="polite"><p>{providerPrerequisite}</p>{manualPending ? <button type="button" className="host-text-button" onClick={() => manualForm.current?.querySelector("input")?.focus()}>Finish Add material above</button> : (!detail || dirty) && <button type="button" className="host-button secondary" disabled={disabled} onClick={onSave}>{detail ? "Save workshop" : "Create draft"}</button>}<button type="button" className="host-text-button" onClick={() => onSection("basics")}>Open Basics</button></div>}<form onSubmit={(event) => void search(event)}><fieldset disabled={disabled || !detail || dirty || searching}><label className="host-check"><input type="checkbox" checked={budgetReviewed} onChange={(event) => setBudgetReviewed(event.target.checked)} />I have reconciled prior attempts and checked the existing provider request budget.</label><label>Material search<input required maxLength={200} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="For example, embroidery needles" /></label><button className="host-button secondary" type="submit" disabled={!budgetReviewed || !query.trim()}>{searching ? "Searching Channel3…" : "Search Channel3"}</button></fieldset></form>{(!detail || dirty) && <p className="host-helper">Save the draft before searching or selecting provider offers.</p>}
      {result && <div className="offer-results"><p className="host-helper">Results retrieved {displayDate(result.retrieved_at)}. A search response is not a guarantee of suitability.</p>{!result.offers.length && <p className="host-notice">No eligible GBP offers were returned. No prices have been invented.</p>}{result.rejected_offers.map((offer, index) => <p className="host-helper" key={index}>Excluded: {offer.product_title} — {offer.ineligible_reason}</p>)}{result.offers.map((offer) => <article className="offer-result" key={offer.offer_snapshot_id}><h4>{offer.product_title}</h4><p>{offer.merchant_domain} · {money(offer.price_minor)} · {offer.currency}</p><p>Retrieved {displayDate(offer.retrieved_at)} · {offer.is_stale ? "STALE" : offer.freshness_label}</p><p className="host-helper">{offer.limitations_note}</p><button className="host-button secondary" disabled={disabled || dirty || offer.is_stale} onClick={() => choose(offer)}>Review this offer</button></article>)}</div>}
      {selected && <form className="offer-review" onSubmit={(event) => void submitSelection(event)}><h3>Review the selected offer</h3><p>Provider fact: {selected.product_title}, {money(selected.price_minor)}. Price is read from the private server snapshot, not this form.</p><fieldset disabled={disabled || dirty || selected.is_stale}><label>Material line name<input required maxLength={200} value={selection.material_name} onChange={(event) => setSelection({ ...selection, material_name: event.target.value })} /></label><p className="host-helper">An existing line with this name will be replaced by this reviewed selection.</p><div className="host-two-col"><label>Material type<select value={selection.kind} onChange={(event) => setSelection({ ...selection, kind: event.target.value as MaterialSelection["kind"] })}><option value="consumable">Consumable</option><option value="reusable">Reusable · not budgeted</option></select></label><NumberField label="Reviewed units per pack" min={1} value={selection.pack_size} onChange={(value) => setSelection({ ...selection, pack_size: value })} /><NumberField label="Shared units" value={selection.shared_units} onChange={(value) => setSelection({ ...selection, shared_units: value })} /><NumberField label="Units per attendee" value={selection.per_attendee_units} onChange={(value) => setSelection({ ...selection, per_attendee_units: value })} /><MoneyField label="Campaign shipping allowance" value={selection.shipping_allowance_minor} onChange={(value) => setSelection({ ...selection, shipping_allowance_minor: value })} /></div><label>Shipping allowance source<input required maxLength={120} value={selection.shipping_allowance_source} onChange={(event) => setSelection({ ...selection, shipping_allowance_source: event.target.value })} /></label><p className="host-helper">Selection replaces the campaign-level shipping allowance; it is counted once, not per material.</p><label>Review notes<textarea maxLength={500} value={selection.review_notes} onChange={(event) => setSelection({ ...selection, review_notes: event.target.value })} /></label><label className="host-check"><input type="checkbox" required checked={selection.suitability_reviewed} onChange={(event) => setSelection({ ...selection, suitability_reviewed: event.target.checked })} />I reviewed this product’s suitability.</label><label className="host-check"><input type="checkbox" required checked={selection.pack_size_reviewed} onChange={(event) => setSelection({ ...selection, pack_size_reviewed: event.target.checked })} />I reviewed the pack size and usage quantities.</label><button className="host-button" type="submit">Save reviewed selection on server</button></fieldset></form>}
      </div></>}
  </div>;
}
