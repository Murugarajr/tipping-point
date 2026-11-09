import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { HostVisibilityFilter } from "../types";
import { Arrow, Mark } from "../public/Artwork";
import { navigate } from "../navigation";
import { CONSOLE_FILTERS, DEFAULT_CONSOLE_FILTER, SEATS_NOTE, SETTLEMENT_NOTE, loadConsoleRows } from "./consoleModel";
import type { ConsoleLoad } from "./consoleModel";
import WorkshopGrid from "./WorkshopGrid";
import { Notice } from "./HostApp";

/** Read-only table view. Issues GET requests only; it has no hide, restore, edit, publish or payment controls. */
export default function MerchantConsole({ onUnauthorized }: { onUnauthorized: (cause: unknown) => boolean }) {
  const [filter, setFilter] = useState<HostVisibilityFilter>(DEFAULT_CONSOLE_FILTER);
  const [result, setResult] = useState<ConsoleLoad | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  const load = async (view: HostVisibilityFilter) => {
    const request = ++latest.current;
    setLoading(true); setError(null);
    try {
      const loaded = await loadConsoleRows(view);
      if (request === latest.current) setResult(loaded);
    } catch (cause) {
      if (request !== latest.current) return;
      if (!onUnauthorized(cause)) { setResult(null); setError("Your workshops could not be loaded. Try again."); }
    } finally {
      if (request === latest.current) setLoading(false);
    }
  };
  useEffect(() => { document.title = "Table view | Host workspace | Tipping Point"; }, []);
  useEffect(() => { void load(filter); }, [filter]);

  const back = (event: MouseEvent<HTMLAnchorElement>) => { event.preventDefault(); navigate("/host"); };
  const rows = result?.rows ?? [];

  return <section className="merchant-console" aria-labelledby="console-heading">
    <p className="back-link"><a className="text-link" href="/host" onClick={back}>← Your workshops</a></p>
    <div className="host-page-heading"><div>
      <p className="host-kicker">Your workshops · Table view</p>
      <h1 id="console-heading">Every workshop at a glance.</h1>
      <p>Read-only. Open a workshop to make changes in its workbench.</p>
    </div></div>
    <div className="host-filter" role="group" aria-label="Filter workshops by discovery visibility">
      {CONSOLE_FILTERS.map((item) => <button key={item.value} type="button" aria-pressed={filter === item.value} disabled={loading && filter === item.value}
        onClick={() => setFilter(item.value)}>{item.label}</button>)}
    </div>
    {loading ? <div className="host-panel" role="status" aria-live="polite">Loading your workshops…</div>
      : error ? <div className="host-panel console-error"><Notice error={error} /><button className="host-button secondary" onClick={() => void load(filter)}>Try again</button></div>
        : !rows.length ? <div className="host-panel host-empty console-empty"><Mark />
          <h2>{filter === "hidden" ? "No workshops are hidden from discovery." : filter === "listed" ? "There are no listed workshops." : "There are no owned workshops yet."}</h2>
          <p>{filter === "listed" ? "Any workshop you hid from discovery is under “Hidden from discovery”." : "No example inventory is added to this workspace."}</p>
          <button className="host-button secondary" onClick={() => navigate("/host")}>Your workshops<Arrow /></button></div>
          : <>
            {result!.failedDetails > 0 && <div className="host-notice host-warning console-partial" role="status">
              Details for {result!.failedDetails} published workshop{result!.failedDetails === 1 ? "" : "s"} could not be loaded.
              Affected cells show “Unavailable”; no values were guessed.{" "}
              <button type="button" className="host-text-button" onClick={() => void load(filter)}>Try again</button>
            </div>}
            <WorkshopGrid rows={rows} />
            <dl className="console-notes">
              <div><dt>* Seats available</dt><dd>{SEATS_NOTE}</dd></div>
              <div><dt>† Settlement</dt><dd>{SETTLEMENT_NOTE}</dd></div>
            </dl>
          </>}
  </section>;
}
