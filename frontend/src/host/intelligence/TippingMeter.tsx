import { useEffect, useRef, useState } from "react";
import type { AgWidgetDataFormat, AgWidgetField, AgWidgetFieldReference, AgWidgetParams } from "ag-studio";

/**
 * Tipping Meter: a registered AG Studio custom widget (AG Studio 3.0.0 `AgWidgetDefinition`).
 * It reads only the fields mapped to it, through `widgetApi.getData`, so it shows exactly what the
 * report's data sources contain. Null values are shown as "Not available", never as zero.
 * There is no custom `format`: AG Studio 3.0.0 exposes no public shape builder for a custom
 * widget's `formatShape`, so the meter is configured only through its data mapping.
 */
export interface TippingMeterState {
  type: "tipping-meter";
  dataMapping: {
    capacity: AgWidgetFieldReference[];
    threshold: AgWidgetFieldReference[];
    admitted?: AgWidgetFieldReference[];
    authorized?: AgWidgetFieldReference[];
    collected?: AgWidgetFieldReference[];
    state?: AgWidgetFieldReference[];
  };
  format?: AgWidgetDataFormat<Record<string, never>>;
}

type Slot = keyof TippingMeterState["dataMapping"];
const SLOTS: Slot[] = ["capacity", "threshold", "admitted", "authorized", "collected", "state"];

interface Reading {
  capacity: number | null;
  threshold: number | null;
  admitted: number | null;
  authorized: string | null;
  collected: string | null;
  state: string | null;
}

const asNumber = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : null;

export default function TippingMeter(params: AgWidgetParams<TippingMeterState>) {
  const { widgetApi, dataMapping } = params;
  const [reading, setReading] = useState<Reading | null>(null);
  const latest = useRef(0);
  const shown = useRef<string | null>(null);

  // Runs on every update, as AG Studio documents for the imperative display-state API: each
  // Studio refresh re-renders the widget and expects a fresh getData call. Only the latest
  // response is applied, and state changes only when the reading changes, so this cannot loop.
  useEffect(() => {
    const request = ++latest.current;
    const fields = new Map<Slot, AgWidgetField>();
    for (const slot of SLOTS) {
      const field = (dataMapping[slot] as AgWidgetField[] | undefined)?.[0];
      if (field) fields.set(slot, field);
    }
    if (!fields.has("capacity") || !fields.has("threshold")) {
      widgetApi.setDisplayState("incompleteDataMapping");
      return;
    }
    if (shown.current === null) widgetApi.setDisplayState("loading");
    void widgetApi.getData({ fields: [...fields.values()] }).then((response) => {
      if (request !== latest.current) return;
      const row = response.results.rows[0];
      if (!row) { shown.current = null; setReading(null); widgetApi.setDisplayState("noData"); return; }
      const raw = (slot: Slot) => { const field = fields.get(slot); return field ? row[field.key] : undefined; };
      const formatted = (slot: Slot) => {
        const field = fields.get(slot);
        if (!field) return null;
        const value = row[field.key];
        return value === null || value === undefined ? null : widgetApi.formatFieldValue(field, value);
      };
      const next: Reading = {
        capacity: asNumber(raw("capacity")),
        threshold: asNumber(raw("threshold")),
        admitted: asNumber(raw("admitted")),
        authorized: formatted("authorized"),
        collected: formatted("collected"),
        state: typeof raw("state") === "string" ? raw("state") as string : null,
      };
      const key = JSON.stringify(next);
      if (key !== shown.current) { shown.current = key; setReading(next); }
      widgetApi.setDisplayState("displayed");
    }).catch(() => {
      if (request === latest.current) widgetApi.setDisplayState("noData");
    });
  });

  // Always render a root element: ag-studio-react 3.0.0 treats a function component as mounted only
  // once its container has DOM children, and stops waiting after 1 s, so returning null until data
  // arrives can leave the widget unattached. Studio's own overlay covers this placeholder.
  if (!reading) return <div className="tp-meter" data-testid="tipping-meter" aria-busy="true"><p className="tp-meter-state">Loading…</p></div>;
  const { capacity, threshold, admitted } = reading;
  const scale = capacity && capacity > 0 ? capacity : null;
  const pct = (value: number | null) => value === null || scale === null ? 0 : Math.max(0, Math.min(100, (value / scale) * 100));
  const remaining = admitted !== null && threshold !== null ? Math.max(0, threshold - admitted) : null;
  const label = admitted === null
    ? `Bookings not available. Next viable attendance ${threshold ?? "none"} of ${capacity ?? "unknown"} places.`
    : `${admitted} admitted of ${capacity ?? "unknown"} places; next viable attendance ${threshold ?? "none"}.`;

  return <div className="tp-meter" data-testid="tipping-meter">
    <p className="tp-meter-state">{reading.state ?? "State not mapped"}</p>
    <div className="tp-meter-figures">
      <span className="tp-meter-big">{admitted ?? "—"}</span>
      <span className="tp-meter-of">admitted {admitted === null ? "· not available" : `of ${capacity ?? "?"}`}</span>
    </div>
    <div className="tp-meter-track" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={capacity ?? 0} aria-valuenow={admitted ?? 0}
      aria-valuetext={label}>
      <div className="tp-meter-fill" style={{ width: `${pct(admitted)}%` }} />
      {threshold !== null && <div className="tp-meter-threshold" style={{ left: `${pct(threshold)}%` }} title={`Next viable attendance: ${threshold}`} />}
    </div>
    <dl className="tp-meter-facts">
      <div><dt>Next viable attendance</dt><dd>{threshold ?? "None in curve"}</dd></div>
      <div><dt>Places still required</dt><dd>{remaining ?? "Not available"}</dd></div>
      <div className="tp-meter-authorized"><dt>Authorised · not collected</dt><dd>{reading.authorized ?? "Not available"}</dd></div>
      <div className="tp-meter-collected"><dt>Collected</dt><dd>{reading.collected ?? "Not available"}</dd></div>
    </dl>
  </div>;
}
