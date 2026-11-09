import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { FormEvent, MouseEvent } from "react";
import * as api from "../api";
import type { HostVisibilityFilter, SessionInfo, Workshop, WorkshopVisibilityResult } from "../types";
import { Arrow, Mark } from "../public/Artwork";
import { navigate, useLocation } from "../navigation";
import { displayDate, intelligenceRoute, money, safeHostReturn, workshopRoute } from "./model";
import Workbench from "./Workbench";
import { VisibilityControl } from "./Visibility";
import "./host.css";

// Read-only AG Grid table view; its chunk (including AG Grid) loads only on /host/console.
const MerchantConsole = lazy(() => import("./MerchantConsole"));
// AG Studio Campaign Intelligence; its chunks load only on /host/workshops/{id}/intelligence.
const CampaignIntelligence = lazy(() => import("./intelligence/CampaignIntelligence"));
export const CONSOLE_PATH = "/host/console";

type SessionState = "loading" | "anonymous" | "authenticated" | "expired" | "unavailable";
export function Notice({ error }: { error: string | null }) {
  return error ? <div className="host-notice host-error" role="alert">{error}</div> : null;
}

export default function HostApp() {
  const location = useLocation();
  const path = window.location.pathname.replace(/\/+$/, "");
  const [state, setState] = useState<SessionState>("loading");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editorId, setEditorId] = useState<string | null>(null);
  const owner = useRef<string | null>(null);
  const retainedReturn = useRef("/host");

  const expire = (cause: unknown) => {
    if (!(cause instanceof api.ApiError && cause.status === 401)) return false;
    api.clearCsrfToken();
    retainedReturn.current = safeHostReturn(window.location.pathname === "/host/login" ? retainedReturn.current : window.location.pathname + window.location.hash);
    setState("expired"); setError(null);
    navigate(`/host/login?returnTo=${encodeURIComponent(retainedReturn.current)}`, true);
    return true;
  };
  useEffect(() => {
    let active = true;
    document.title = "Host workspace | Tipping Point";
    void api.restoreSession().then((info) => {
      if (!active) return;
      owner.current = info.merchant.merchant_id; setSession(info); setState("authenticated");
    }).catch((cause) => {
      if (!active) return;
      setState(cause instanceof api.ApiError && cause.status === 401 ? "anonymous" : "unavailable");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (state === "authenticated") {
      if (path === "/host/login") {
        const target = safeHostReturn(new URLSearchParams(window.location.search).get("returnTo"));
        navigate(target, true);
      } else {
        setEditorId(workshopRoute.exec(path)?.[1] ?? null);
      }
    } else if (state === "anonymous" && path !== "/host/login") {
      navigate(`/host/login?returnTo=${encodeURIComponent(safeHostReturn(path + window.location.hash))}`, true);
    }
  }, [state, path, location]);

  const login = async (identifier: string, password: string) => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const info = await api.login(identifier, password);
      if (owner.current !== info.merchant.merchant_id) setEditorId(null);
      owner.current = info.merchant.merchant_id;
      setSession(info); setState("authenticated");
      const target = safeHostReturn(new URLSearchParams(window.location.search).get("returnTo"));
      navigate(target, true);
    } catch (cause) {
      setError(cause instanceof api.ApiError && cause.status === 401 ? "The login identifier or password is incorrect."
        : cause instanceof api.ApiError && cause.status === 429 ? "Too many sign-in attempts. Please wait before trying again."
          : "Sign-in is unavailable right now. Please try again.");
    } finally { setBusy(false); }
  };
  const logout = async () => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await api.logout();
      setEditorId(null); setSession(null); setState("anonymous");
      navigate("/", true);
    } catch (cause) {
      if (cause instanceof api.ApiError && cause.status === 401) {
        api.clearCsrfToken(); setEditorId(null); setSession(null); setState("anonymous"); navigate("/", true);
      } else setError("Logout failed. Your session may still be active; please try again.");
    }
    finally { setBusy(false); }
  };

  const authenticated = state === "authenticated" && path !== "/host/login";
  const intelligenceId = intelligenceRoute.exec(path)?.[1] ?? null;
  return <>
    {state === "loading" && <main className="host-shell host-loading"><h1>Checking your session…</h1></main>}
    {state === "unavailable" && <main className="merchant-auth login-shell"><section className="login-card"><a href="/">← Public browsing</a><h1>Host workspace unavailable.</h1><p role="alert">Your session could not be checked. This is not an invalid-credentials result.</p><button className="primary" onClick={() => window.location.reload()}>Try again</button></section></main>}
    {(state === "anonymous" || state === "expired") && <LoginScreen expired={state === "expired"} error={error} busy={busy} onLogin={login} />}
    <div hidden={!authenticated} className="host-shell">
      <a className="skip-link" href="#host-content">Skip to workspace</a>
      <header className="host-header"><a className="wordmark" href="/"><Mark /><span>tipping point.</span></a><span className="host-context">Host workspace<span>Sandbox prototype</span></span><a className="text-link public-browse" href="/workshops">Public browsing<Arrow diagonal /></a><div className="merchant-menu"><span>{session?.merchant.name}</span><button className="host-button secondary" onClick={() => void logout()} disabled={busy}>Log out</button></div></header>
      <main id="host-content" className="host-content" tabIndex={-1}>
        <Notice error={error} />
        {/* Kept mounted, but hidden, during same-host reauthentication only. */}
        {editorId && <Workbench key={`${owner.current}:${editorId}`} id={editorId} onUnauthorized={expire} />}
        {authenticated && !editorId && path === "/host" && <WorkshopList onUnauthorized={expire} />}
        {authenticated && !editorId && path === CONSOLE_PATH && <Suspense fallback={<div className="host-panel" role="status">Loading table view…</div>}><MerchantConsole onUnauthorized={expire} /></Suspense>}
        {authenticated && !editorId && intelligenceId && <Suspense fallback={<div className="host-panel" role="status">Loading Campaign Intelligence…</div>}><CampaignIntelligence key={`${owner.current}:${intelligenceId}`} id={intelligenceId} onUnauthorized={expire} /></Suspense>}
        {authenticated && !editorId && path !== "/host" && path !== CONSOLE_PATH && !intelligenceId && <section className="host-panel"><h1>Workspace page not found.</h1><button className="host-button" onClick={() => navigate("/host")}>Your workshops</button></section>}
      </main>
    </div>
  </>;
}

const FILTERS: { value: HostVisibilityFilter; label: string }[] = [
  { value: "listed", label: "Listed" }, { value: "hidden", label: "Hidden from discovery" }, { value: "all", label: "All" },
];

function WorkshopList({ onUnauthorized }: { onUnauthorized: (cause: unknown) => boolean }) {
  const [workshops, setWorkshops] = useState<Workshop[]>([]);
  const [filter, setFilter] = useState<HostVisibilityFilter>("listed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = async (view: HostVisibilityFilter = filter) => {
    setLoading(true); setError(null);
    try { setWorkshops(await api.listWorkshops(view)); }
    catch (cause) { if (!onUnauthorized(cause)) setError("Your workshops could not be loaded. Try again."); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(filter); }, [filter]);
  const changed = (title: string) => (result: WorkshopVisibilityResult) => {
    setNotice(result.hidden_from_discovery_at
      ? `“${title}” is hidden from discovery. Its link, bookings and payments are unchanged. Find it under “Hidden from discovery”.`
      : `“${title}” is listed in public browsing again.`);
    void load(filter);
  };
  return <section><div className="host-page-heading"><div><p className="host-kicker">Your workshops</p><h1>A clearer plan starts here.</h1><p>Draft the experience. Review the costs. Publish the terms.</p></div><button className="host-button" onClick={() => navigate("/host/workshops/new")}>Create draft<Arrow /></button></div>
    <div className="host-filter" role="group" aria-label="Filter workshops by discovery visibility">{FILTERS.map((item) => <button key={item.value} type="button" aria-pressed={filter === item.value} onClick={() => { setNotice(null); setFilter(item.value); }}>{item.label}</button>)}</div>
    <p className="host-console-link"><a className="text-link" href={CONSOLE_PATH} onClick={(event: MouseEvent<HTMLAnchorElement>) => { event.preventDefault(); navigate(CONSOLE_PATH); }}>Table view<Arrow /></a></p>
    {notice && <p className="host-notice host-positive" role="status">{notice}</p>}
    {loading ? <div className="host-panel" role="status">Loading your owned workshops…</div>
      : error ? <div className="host-panel"><Notice error={error} /><button className="host-button secondary" onClick={() => void load()}>Try again</button></div>
        : !workshops.length ? filter === "hidden"
          ? <div className="host-panel host-empty visibility-empty"><p>No workshops are hidden from discovery.</p></div>
          : <div className="host-panel host-empty"><Mark /><h2>Your first workshop starts with an idea.</h2><p>{filter === "listed" ? "There are no listed workshops. Any workshop you hid from discovery is under “Hidden from discovery”." : "There are no owned workshops yet."} No example inventory is added to this workspace.</p><button className="host-button" onClick={() => navigate("/host/workshops/new")}>Create your first draft</button></div>
          : <div className="host-workshop-list">{workshops.map((workshop) => {
            const gaps = [workshop.ticket_price_minor <= 0 ? "Price not set" : null, !workshop.opens_at || !workshop.closes_at ? "Booking dates missing" : null].filter(Boolean);
            return <article className="host-workshop-row" key={workshop.workshop_id}><div><span className={`host-badge ${workshop.is_frozen ? "frozen" : ""}`}>{workshop.is_frozen ? "Published · immutable" : "Draft"}</span><h2>{workshop.title}</h2><p>{workshop.description || "No description yet."}</p>{gaps.length > 0 && <p className="setup-gaps">{gaps.join(" · ")}</p>}</div><dl><div><dt>Ticket price</dt><dd>{workshop.ticket_price_minor > 0 ? money(workshop.ticket_price_minor) : "Price not set"}</dd></div><div><dt>Capacity</dt><dd>{workshop.capacity} places</dd></div><div><dt>Booking cutoff · London time</dt><dd>{displayDate(workshop.closes_at)}</dd></div></dl><div className="row-actions"><button className="host-button secondary" onClick={() => navigate(`/host/workshops/${workshop.workshop_id}`)}>{workshop.is_frozen ? "Open workshop" : "Continue setup"}<Arrow /></button>{workshop.is_frozen && workshop.campaign_id && <a href={`/workshops/${workshop.workshop_id}`} className="text-link">View public page<Arrow diagonal /></a>}<VisibilityControl workshop={workshop} onChanged={changed(workshop.title)} onUnauthorized={onUnauthorized} /></div></article>;
          })}</div>}
  </section>;
}

function LoginScreen({ expired, error, busy, onLogin }: { expired: boolean; error: string | null; busy: boolean; onLogin: (identifier: string, password: string) => Promise<void> }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!busy) void onLogin(identifier, password).finally(() => setPassword(""));
  };
  return <main className="merchant-auth login-shell"><a className="skip-link" href="#host-login">Skip to sign in</a><section className="login-card" id="host-login" tabIndex={-1}>
    <a className="wordmark" href="/"><Mark /><span>tipping point.</span></a><p className="eyebrow">Sandbox · Host workspace</p><h1>Your idea.<br />A clearer plan.</h1><p className="muted">Sign in with your provisioned host account. Guest exploration never grants host access.</p>
    {expired && <div className="notice warning" role="status">Your host session has expired. Unsaved input stays in this page’s memory for the same host. Sign in again to continue.</div>}<Notice error={error} />
    <form onSubmit={submit} aria-busy={busy}><label htmlFor="host-identifier">Login identifier</label><input id="host-identifier" required minLength={3} maxLength={100} autoComplete="username" disabled={busy} value={identifier} onChange={(event) => setIdentifier(event.target.value)} /><div className="password-label"><label htmlFor="host-password">Password</label><button type="button" className="password-toggle" aria-controls="host-password" aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)}>{showPassword ? "Hide password" : "Show password"}</button></div><input id="host-password" required type={showPassword ? "text" : "password"} autoComplete="current-password" disabled={busy} value={password} onChange={(event) => setPassword(event.target.value)} /><button className="primary" disabled={busy}>{busy ? "Signing in…" : "Host sign in"}<Arrow /></button><p className="helper">No public registration or password reset. Contact your operator for access.</p></form><a className="text-link" href="/">Back to exploring<Arrow diagonal /></a>
  </section></main>;
}
