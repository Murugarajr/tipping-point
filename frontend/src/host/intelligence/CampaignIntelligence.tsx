import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { AgStudioMode } from "ag-studio";
import * as api from "../../api";
import { navigate } from "../../navigation";
import { Notice } from "../HostApp";
import { displayDate } from "../model";
import { buildIntelligence } from "./intelligenceModel";
import { applyVisualizations } from "./analystModel";
import type { AnalystVisualization } from "./analystModel";
import AnalystPanel from "./AnalystPanel";
import type { IntelligenceStudioApi } from "./StudioDashboard";
import type { IntelligenceData } from "./intelligenceModel";
import "./intelligence.css";

// AG Studio (and AG Grid/Charts Enterprise inside it) loads only after the data is ready.
const StudioDashboard = lazy(() => import("./StudioDashboard"));

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; data: IntelligenceData; loadedAt: Date }
  | { kind: "empty"; reason: string }
  | { kind: "unavailable"; reason: string }
  | { kind: "error"; reason: string };

/**
 * Campaign Intelligence: read-only. Requests: GET workshop detail, and POST preview, which the
 * backend documents as a pure calculation (nothing persisted). Never edits, publishes or pays.
 */
export default function CampaignIntelligence({ id, onUnauthorized }: { id: string; onUnauthorized: (cause: unknown) => boolean }) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [mode, setMode] = useState<AgStudioMode>("view");
  const latest = useRef(0);
  const studioApi = useRef<IntelligenceStudioApi | null>(null);
  // Applies server-validated presets through Studio's public getState/setState; null if Studio is not ready.
  const applyAnalystVisualizations = (visualizations: AnalystVisualization[]) => {
    const studio = studioApi.current;
    if (!studio) return null;
    const { state, applied } = applyVisualizations(studio.getState(), visualizations);
    studio.setState(state);
    return applied;
  };

  const load = async () => {
    const request = ++latest.current;
    setState({ kind: "loading" });
    try {
      const detail = await api.getWorkshop(id);
      const preview = await api.previewWorkshop(id);
      if (request !== latest.current) return;
      if (!preview.attendance_curve.length) {
        setState({ kind: "empty", reason: "The backend calculator returned no attendance points for the saved terms. Check capacity and minimum operating attendance in the workbench." });
        return;
      }
      setState({ kind: "ready", data: buildIntelligence(detail, preview), loadedAt: new Date() });
    } catch (cause) {
      if (request !== latest.current || onUnauthorized(cause)) return;
      if (cause instanceof api.ApiError && cause.status === 404) setState({ kind: "unavailable", reason: "This workshop was not found in your workspace." });
      else if (cause instanceof api.ApiError && (cause.status === 409 || cause.status === 422)) setState({ kind: "unavailable", reason: `The backend calculator cannot evaluate the saved terms: ${cause.message}` });
      else if (cause instanceof api.ApiContractError) setState({ kind: "unavailable", reason: cause.message });
      else setState({ kind: "error", reason: "Campaign data could not be loaded. Nothing was changed. Try again." });
    }
  };
  useEffect(() => { document.title = "Campaign Intelligence | Host workspace | Tipping Point"; void load(); }, [id]);

  const back = (event: MouseEvent<HTMLAnchorElement>) => { event.preventDefault(); navigate(`/host/workshops/${encodeURIComponent(id)}`); };

  return <section className="campaign-intelligence" aria-labelledby="ci-heading">
    <p className="back-link"><a className="text-link" href={`/host/workshops/${encodeURIComponent(id)}`} onClick={back}>← Back to workbench</a></p>
    <div className="host-page-heading"><div>
      <p className="host-kicker">Campaign Intelligence · AG Studio</p>
      <h1 id="ci-heading">{state.kind === "ready" ? state.data.health.workshop : "Campaign Intelligence"}</h1>
      <p>Read-only. Figures come from your saved terms and the backend calculator.</p>
    </div>
    {state.kind === "ready" && <div className="host-filter ci-mode" role="group" aria-label="Dashboard mode">
      <button type="button" aria-pressed={mode === "view"} onClick={() => setMode("view")}>View</button>
      <button type="button" aria-pressed={mode === "edit"} onClick={() => setMode("edit")}>Edit layout</button>
    </div>}</div>

    {state.kind === "loading" && <div className="host-panel" role="status" aria-live="polite">Loading campaign data…</div>}
    {state.kind === "error" && <div className="host-panel ci-error"><Notice error={state.reason} /><button className="host-button secondary" onClick={() => void load()}>Try again</button></div>}
    {state.kind === "unavailable" && <div className="host-panel ci-unavailable" role="status"><h2>Campaign Intelligence is unavailable for this workshop.</h2><p className="host-helper">{state.reason}</p><button className="host-button secondary" onClick={() => void load()}>Try again</button></div>}
    {state.kind === "empty" && <div className="host-panel host-empty ci-empty" role="status"><h2>No attendance curve to show.</h2><p>{state.reason}</p></div>}
    {state.kind === "ready" && <>
      <p className="host-helper ci-meta">Saved terms v{state.data.health.terms_version} · {state.data.health.publication} · calculated {displayDate(state.loadedAt.toISOString())}. Authorised amounts are not collected money; estimates are not profit.</p>
      {state.data.warnings.map((warning) => <p key={warning} className="host-notice host-warning" role="status">{warning}</p>)}
      <div className="ci-studio">
        <Suspense fallback={<div className="host-panel" role="status">Loading AG Studio…</div>}>
          <StudioDashboard data={state.data} mode={mode} onApi={(value) => { studioApi.current = value; }} />
        </Suspense>
      </div>
      <AnalystPanel workshopId={id} onUnauthorized={onUnauthorized} applyVisualizations={applyAnalystVisualizations} />
      <section className="host-panel ci-capabilities" aria-labelledby="ci-unavailable-heading">
        <h2 id="ci-unavailable-heading">Not shown or not available</h2>
        <ul>{state.data.unavailable.map((note) => <li key={note}>{note}</li>)}</ul>
      </section>
    </>}
  </section>;
}
