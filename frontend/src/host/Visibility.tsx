import { useState } from "react";
import * as api from "../api";
import type { Workshop, WorkshopVisibilityResult } from "../types";
import { HIDE_FROM_DISCOVERY_EXPLANATION, VISIBILITY_NOT_ACCESS_CONTROL, visibilityLabel } from "./model";

/** Merchant-owned discovery listing control. Never changes campaign, booking or payment state. */
export function VisibilityControl({ workshop, onChanged, onUnauthorized }: {
  workshop: Pick<Workshop, "workshop_id" | "title" | "hidden_from_discovery_at">;
  onChanged: (result: WorkshopVisibilityResult) => void;
  onUnauthorized: (cause: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hidden = Boolean(workshop.hidden_from_discovery_at);
  const run = async (action: () => Promise<WorkshopVisibilityResult>, failure: string) => {
    if (busy) return;
    setBusy(true); setError(null);
    try { const result = await action(); setConfirming(false); onChanged(result); }
    catch (cause) { if (!onUnauthorized(cause)) setError(`${failure} ${cause instanceof Error ? cause.message : ""}`.trim()); }
    finally { setBusy(false); }
  };
  const titleId = `visibility-${workshop.workshop_id}`;
  return <div className="visibility-control">
    <span className={`host-badge visibility-badge ${hidden ? "hidden-listing" : "listed"}`} role="status">{visibilityLabel(workshop.hidden_from_discovery_at)}</span>
    {hidden
      ? <><button type="button" className="host-text-button restore-visibility" disabled={busy} onClick={() => void run(() => api.restoreVisibility(workshop.workshop_id), "Visibility could not be restored.")}>{busy ? "Restoring…" : "Restore visibility"}</button><p className="host-helper">Shows it in public browsing again. Bookings and payments are unaffected.</p></>
      : !confirming && <button type="button" className="host-text-button hide-from-discovery" disabled={busy} onClick={() => { setConfirming(true); setError(null); }}>Hide from discovery</button>}
    {confirming && !hidden && <div className="host-notice host-warning visibility-confirm" role="alertdialog" aria-labelledby={titleId} aria-describedby={`${titleId}-copy`}>
      <strong id={titleId}>Hide “{workshop.title}” from discovery?</strong>
      <p id={`${titleId}-copy`}>{HIDE_FROM_DISCOVERY_EXPLANATION}</p>
      <p>{VISIBILITY_NOT_ACCESS_CONTROL}</p>
      <div className="visibility-actions"><button type="button" className="host-button secondary confirm-hide" disabled={busy} onClick={() => void run(() => api.hideFromDiscovery(workshop.workshop_id), "The workshop could not be hidden.")}>{busy ? "Hiding…" : "Hide from discovery"}</button><button type="button" className="host-text-button cancel-hide" disabled={busy} onClick={() => setConfirming(false)}>Keep listed</button></div>
    </div>}
    {error && <p className="host-notice host-error" role="alert">{error}</p>}
  </div>;
}
