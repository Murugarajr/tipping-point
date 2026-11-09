import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import * as api from "../../api";
import {
  MAX_MESSAGE_CHARS, SUGGESTED_QUESTIONS, analystErrorText, answerParagraphs, boundedHistory, connectionLabel, statusText,
} from "./analystModel";
import type { AnalystActivity, AnalystStatus, AnalystVisualization, ChatMessage } from "./analystModel";

interface Turn {
  question: string;
  answer?: string;
  status?: "answered" | "limit_reached";
  activity?: AnalystActivity[];
  applied?: string[];
  error?: string;
  cancelled?: boolean;
}

/**
 * Read-only Rescue Analyst. The model/tool loop runs on the server; this panel only sends bounded
 * conversation text and applies server-validated visualization presets to Studio.
 * Answers are rendered as plain React text: no HTML, scripts or links.
 */
export default function AnalystPanel({ workshopId, onUnauthorized, applyVisualizations }: {
  workshopId: string;
  onUnauthorized: (cause: unknown) => boolean;
  applyVisualizations: (visualizations: AnalystVisualization[]) => string[] | null;
}) {
  const [status, setStatus] = useState<AnalystStatus | null>(null);
  const [statusError, setStatusError] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);

  useEffect(() => {
    let active = true;
    void api.getAnalystStatus(workshopId).then((value) => { if (active) setStatus(value); })
      .catch((cause) => { if (active && !onUnauthorized(cause)) setStatusError(true); });
    return () => { active = false; controller.current?.abort(); };
  }, [workshopId]);

  const ask = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy.current || !status?.available) return;
    busy.current = true; setPending(true);
    const history: ChatMessage[] = turns.filter((t) => t.answer).flatMap((t) => [{ role: "user" as const, content: t.question }, { role: "assistant" as const, content: t.answer! }]);
    const index = turns.length;
    setTurns((all) => [...all, { question: trimmed }]);
    setQuestion("");
    const abort = new AbortController();
    controller.current = abort;
    const update = (patch: Partial<Turn>) => setTurns((all) => all.map((turn, i) => i === index ? { ...turn, ...patch } : turn));
    try {
      const result = await api.askAnalyst(workshopId, boundedHistory(history, trimmed), abort.signal);
      const applied = result.visualizations.length ? applyVisualizations(result.visualizations) : [];
      update({ answer: result.answer, status: result.status, activity: result.activity,
        applied: applied ?? [], error: applied === null ? "The dashboard was not ready, so the requested chart was not added." : undefined });
    } catch (cause) {
      if (abort.signal.aborted) update({ cancelled: true });
      else if (!onUnauthorized(cause)) update({ error: cause instanceof api.ApiError ? analystErrorText(cause.status, cause.detail) : analystErrorText(null, null) });
    } finally {
      busy.current = false; setPending(false); controller.current = null;
    }
  };
  const submit = (event: FormEvent) => { event.preventDefault(); void ask(question); };

  return <section className="host-panel ci-analyst" aria-labelledby="ci-analyst-heading">
    <div className="ci-analyst-head">
      <h2 id="ci-analyst-heading">Rescue Analyst</h2>
      <span className="host-badge ci-analyst-connection">{status ? connectionLabel(status) : statusError ? "Status unavailable" : "Checking…"}</span>
    </div>
    <p className="host-helper">Read-only. Answers use your saved terms and the backend calculator. Estimates and attendance scenarios are not bookings or collected money. It cannot publish, edit terms or take payments.</p>
    {statusError && <p className="host-notice host-warning" role="status">The analyst status could not be checked. The dashboard above is unaffected.</p>}
    {status && !status.available && <p className="host-notice ci-analyst-off" role="status"><strong>Analyst not configured.</strong> {statusText(status)} The dashboard above is unaffected.</p>}
    {status?.available && <>
      <div className="ci-analyst-suggestions" role="group" aria-label="Suggested questions">
        {SUGGESTED_QUESTIONS.map((q) => <button key={q} type="button" className="host-text-button" disabled={pending} onClick={() => void ask(q)}>{q}</button>)}
      </div>
      <ol className="ci-analyst-turns" aria-live="polite">
        {turns.map((turn, i) => <li key={i} className="ci-analyst-turn">
          <p className="ci-analyst-question"><span className="host-kicker">You asked</span>{turn.question}</p>
          {!turn.answer && !turn.error && !turn.cancelled && <p role="status" className="ci-analyst-pending">Working… the server is calling {connectionLabel(status)} and the backend calculator.</p>}
          {turn.cancelled && <p role="status" className="host-notice">Stopped waiting. The server may still finish the model call it had started; it is read-only, so nothing changes either way.</p>}
          {turn.error && <p role="alert" className="host-notice host-error">{turn.error}</p>}
          {turn.activity && turn.activity.length > 0 && <details className="ci-analyst-activity"><summary>Tool activity ({turn.activity.length})</summary>
            <ul>{turn.activity.map((a, j) => <li key={j} data-status={a.status}>{a.status === "ok" ? "✓" : a.status === "limit" ? "⏹" : "✕"} {a.summary}</li>)}</ul></details>}
          {turn.answer && <div className="ci-analyst-answer"><span className="host-kicker">Analyst</span>{answerParagraphs(turn.answer).map((p, j) => <p key={j}>{p}</p>)}</div>}
          {turn.status === "limit_reached" && <p className="host-notice host-warning" role="status">The run limit was reached before a complete answer.</p>}
          {turn.applied && turn.applied.length > 0 && <p className="host-notice host-positive" role="status">Added or updated on the dashboard: {turn.applied.join("; ")}.</p>}
        </li>)}
      </ol>
      <form onSubmit={submit} className="ci-analyst-form" aria-busy={pending}>
        <label htmlFor="ci-analyst-question">Ask about this workshop</label>
        <textarea id="ci-analyst-question" rows={2} maxLength={MAX_MESSAGE_CHARS} value={question} disabled={pending}
          onChange={(event) => setQuestion(event.target.value)} />
        <div className="ci-analyst-actions">
          <button className="host-button" disabled={pending || !question.trim()}>{pending ? "Working…" : "Ask"}</button>
          {pending && <button type="button" className="host-button secondary ci-analyst-cancel" onClick={() => controller.current?.abort()}>Stop waiting</button>}
        </div>
      </form>
    </>}
  </section>;
}
