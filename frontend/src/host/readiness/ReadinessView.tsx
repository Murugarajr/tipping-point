import "./bryntumLicense"; // must run before the Bryntum modules load
import { useEffect, useMemo, useRef, useState } from "react";
import { BryntumGantt } from "@bryntum/gantt-react-business";
import "@bryntum/core-business/fontawesome/css/fontawesome.css";
import "@bryntum/core-business/fontawesome/css/solid.css";
import "@bryntum/gantt-business/gantt.css";
import "@bryntum/gantt-business/svalbard.css";
import "./readiness.css";
import * as api from "../../api";
import { navigate } from "../../navigation";
import { displayDate } from "../model";
import { intelligencePath } from "../intelligence/intelligenceModel";
import { NO_SAVED_DATE, READINESS_TIME_ZONE, buildReadiness, ganttProject, shortDateText, timelineWindow } from "./readinessModel";
import type { Readiness, ReadinessRow } from "./readinessModel";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; readiness: Readiness; loadedAt: Date }
  | { kind: "unavailable"; reason: string }
  | { kind: "error"; reason: string };

const KIND_LABEL: Record<ReadinessRow["kind"], string> = { saved: "Saved", proposed: "Proposed", unavailable: "Unavailable" };

function dateText(row: ReadinessRow): string | null {
  if (!row.start) return null;
  return row.end ? `${displayDate(row.start)} → ${displayDate(row.end)}` : displayDate(row.start);
}

/**
 * Read-only Bryntum Gantt of one owned workshop's saved booking, decision and settlement dates.
 * Nothing on this page writes: the Gantt is read-only with every editing feature disabled, and the
 * only request is the existing owned-workshop GET.
 */
export default function ReadinessView({ id, onUnauthorized }: { id: string; onUnauthorized: (cause: unknown) => boolean }) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const latest = useRef(0);

  const load = async () => {
    const request = ++latest.current;
    setState({ kind: "loading" });
    try {
      const detail = await api.getWorkshop(id);
      if (request !== latest.current) return;
      setState({ kind: "ready", readiness: buildReadiness(detail), loadedAt: new Date() });
    } catch (cause) {
      if (request !== latest.current || onUnauthorized(cause)) return;
      if (cause instanceof api.ApiError && cause.status === 404) setState({ kind: "unavailable", reason: "This workshop was not found in your workspace." });
      else if (cause instanceof api.ApiContractError) setState({ kind: "unavailable", reason: cause.message });
      else setState({ kind: "error", reason: "Readiness data could not be loaded. Nothing was changed. Try again." });
    }
  };
  useEffect(() => { document.title = "Readiness | Host workspace | Tipping Point"; void load(); }, [id]);

  const ready = state.kind === "ready" ? state.readiness : null;
  const rowById = useMemo(() => new Map(ready ? [ready.workshop, ...ready.rows].map((r) => [r.id, r]) : []), [ready]);
  const project = useMemo(() => ready ? ganttProject(ready) : undefined, [ready]);
  const timeline = useMemo(() => ready ? timelineWindow(ready.range) : null, [ready]);

  const columns = useMemo(() => [
    { type: "name", field: "name", text: "Milestone", width: 250, sortable: false, editor: false, draggable: false, resizable: false, groupable: false },
    {
      id: "status", text: "Status", width: 150, sortable: false, editor: false, draggable: false, resizable: false, groupable: false,
      renderer: ({ record }: { record: { id: string | number } }) => {
        const row = rowById.get(String(record.id));
        return row ? { tag: "span", className: `tp-pill tp-pill-${row.tone}`, text: row.status } : "";
      },
    },
    {
      id: "detail", text: "Date / detail", flex: 1, sortable: false, editor: false, draggable: false, resizable: false, groupable: false,
      renderer: ({ record }: { record: { id: string | number } }) => {
        const row = rowById.get(String(record.id));
        if (!row) return "";
        const when = shortDateText(row);
        return { tag: "div", className: "tp-detail", children: [
          when ? { tag: "span", className: "tp-date", text: when } : { tag: "span", className: "tp-no-date", text: NO_SAVED_DATE },
          { tag: "span", className: "tp-detail-note", text: `${KIND_LABEL[row.kind]} · ${row.detail}` },
        ] };
      },
    },
  ], [rowById]);

  return <section className="tp-readiness-page" aria-labelledby="readiness-heading">
    <div className="host-page-heading">
      <div>
        <p className="host-kicker">Workshop readiness · read-only</p>
        <h1 id="readiness-heading">{ready ? ready.workshop.name : "Readiness timeline"}</h1>
        <p>Saved booking, decision and settlement dates from the backend. Proposed operational tasks have no saved date.</p>
      </div>
      <div className="tp-readiness-links">
        <a className="text-link" href={`/host/workshops/${id}`} onClick={(event) => { event.preventDefault(); navigate(`/host/workshops/${id}`); }}>Back to workbench</a>
        <a className="text-link" href={intelligencePath(id)} onClick={(event) => { event.preventDefault(); navigate(intelligencePath(id)); }}>Campaign Intelligence</a>
      </div>
    </div>

    {state.kind === "loading" && <div className="host-panel" role="status">Loading saved dates…</div>}
    {(state.kind === "unavailable" || state.kind === "error") && <div className="host-panel" role="alert"><p>{state.reason}</p>
      {state.kind === "error" && <button className="host-button secondary" onClick={() => void load()}>Try again</button>}</div>}

    {ready && project && timeline && <>
      <div className="tp-readiness host-panel" data-testid="readiness-gantt">
        <BryntumGantt
          project={project}
          timeZone={READINESS_TIME_ZONE}
          columns={columns}
          startDate={timeline.startDate}
          endDate={timeline.endDate}
          viewPreset={timeline.viewPreset}
          rowHeight={36}
          barMargin={9}
          subGridConfigs={{ locked: { width: 600 } }}
          readOnly
          taskDragFeature={false}
          taskResizeFeature={false}
          taskDragCreateFeature={false}
          taskEditFeature={false}
          taskMenuFeature={false}
          taskCopyPasteFeature={false}
          cellEditFeature={false}
          cellMenuFeature={false}
          cellCopyPasteFeature={false}
          rowCopyPasteFeature={false}
          headerMenuFeature={false}
          scheduleMenuFeature={false}
          timeAxisHeaderMenuFeature={false}
          dependenciesFeature={false}
          dependencyEditFeature={false}
          percentBarFeature={false}
          projectLinesFeature={false}
          rowReorderFeature={false}
          columnReorderFeature={false}
          columnResizeFeature={false}
          sortFeature={false}
          filterFeature={false}
        />
      </div>
      <p className="host-helper">All times, in the list and on the timeline, are UK time (Europe/London). No dependency lines are drawn because the backend stores no dependencies between these steps. Loaded {displayDate(state.kind === "ready" ? state.loadedAt.toISOString() : null)}.</p>
      <details className="host-panel tp-readiness-summary">
        <summary>Text summary</summary>
        <ul>{[ready.workshop, ...ready.rows].map((row) => <li key={row.id} data-row={row.id} data-tone={row.tone} data-kind={row.kind}>
          <strong>{row.name}</strong> — {row.status} · {dateText(row) ?? NO_SAVED_DATE} · {KIND_LABEL[row.kind]}: {row.detail}
        </li>)}</ul>
      </details>
    </>}
  </section>;
}
