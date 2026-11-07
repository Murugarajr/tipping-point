import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import * as api from "../api";
import type { GuestBooking, PublicWorkshop } from "../types";
import { navigate } from "../navigation";
import { displayDate, money } from "../host/model";
import { authorizationExplanation, campaignStatusMessage, guestSettlementPresentation, sandboxApproveUrl } from "./model";
import "./guest.css";

function failure(cause: unknown): string {
  return cause instanceof Error ? cause.message : "The request could not be completed. No successful outcome is assumed.";
}

export function GuestContinue({ id }: { id: string }) {
  const [workshop, setWorkshop] = useState<PublicWorkshop | null>(null);
  const [loadState, setLoadState] = useState("loading");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const submission = useRef<{ key: string; email: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const load = async () => {
    setLoadState("loading");
    try { setWorkshop(await api.getPublicWorkshop(id)); setLoadState("ready"); }
    catch (cause) { setError(failure(cause)); setLoadState("error"); }
  };
  useEffect(() => { void load(); }, [id]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current || !workshop?.reservations_available) return;
    if (!email.trim() || !input.current?.validity.valid) {
      setError("Enter a valid email address, such as you@example.com."); input.current?.focus(); return;
    }
    // A failed request may have succeeded server-side. Retry this immutable submission,
    // never a new reservation key or a changed contact payload.
    if (!submission.current) submission.current = { key: crypto.randomUUID(), email: email.trim() };
    inFlight.current = true; setBusy(true); setError("");
    try {
      await api.createGuestSession();
      const booking = await api.reserveGuestSeat(workshop.campaign_id, submission.current.email, submission.current.key);
      navigate(`/bookings/${booking.booking_id}`);
    } catch (cause) {
      // Framework body validation rejects before the reservation handler runs.
      // Other errors may hide a completed reservation and must keep the same key.
      if (api.isGuestReservationValidationError(cause)) submission.current = null;
      setError(failure(cause));
    }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <section className="section guest-page guest-connected">
    <div className="guest-intro"><p className="kicker">One place. A clear next step.</p><h1>Continue<br />as a guest.</h1><p>{authorizationExplanation}</p><a className="text-link" href={`/workshops/${id}`}>← Workshop details</a></div>
    <div className="guest-form-panel"><span className="outline-pill">PayPal Sandbox · one seat</span>
      {loadState === "loading" ? <p role="status">Loading published workshop…</p> : loadState === "error" ? <><p role="alert">{error}</p><button className="tp-button" onClick={() => void load()}>Try again</button></> : workshop && <>
        <h2>{workshop.title}</h2><p className="detail-price">{money(workshop.ticket_price_minor)}<span>one place · GBP · server-priced</span></p>
        <p>Booking cutoff · London time: {displayDate(workshop.cutoff_at)}</p>
        {!workshop.reservations_available ? <div className="preview-callout"><strong>Reservations unavailable</strong><p>{workshop.availability_note}</p><p className="small-copy">Reason: {workshop.availability_reason}</p></div> : <form noValidate onSubmit={(event) => void submit(event)}>
          <label htmlFor="guest-email">Contact email</label><input ref={input} id="guest-email" type="email" autoComplete="email" maxLength={254} required value={email} readOnly={Boolean(submission.current)} onChange={(event) => setEmail(event.target.value)} aria-invalid={Boolean(error)} aria-describedby="guest-contact-help guest-reserve-error" />
          <p id="guest-contact-help" className="small-copy">Email is contact information, not identity or booking recovery. Your server-issued guest cookie owns the reservation. No email notification is promised. No password is needed.</p>
          {error && <p id="guest-reserve-error" className="form-error" role="alert">{error}</p>}
          {submission.current && error && <p className="small-copy">Retry keeps the same contact and reservation key to avoid a duplicate after an uncertain result.</p>}
          <button className="tp-button" type="submit" disabled={busy}>{busy ? "Reserving your temporary seat…" : submission.current ? "Retry same reservation" : "Continue — reserve one temporary seat"}</button>
        </form>}
      </>}
    </div>
  </section>;
}

export function GuestBookingStatus({ id, suffix }: { id: string; suffix?: "return" | "cancel" }) {
  const [booking, setBooking] = useState<GuestBooking | null>(null);
  const [error, setError] = useState("");
  const [lost, setLost] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const handleError = (cause: unknown) => {
    const code = api.guestErrorCode(cause);
    if (code === "GUEST_SESSION_REQUIRED" || code === "BOOKING_NOT_FOUND" || cause instanceof api.ApiError && [401, 404].includes(cause.status)) {
      setLost(true); setBooking(null); api.clearGuestCsrfToken();
    }
    setError(failure(cause));
  };
  const load = async () => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try { await api.restoreGuestSession(); setBooking(await api.getGuestBooking(id)); setLost(false); }
    catch (cause) { handleError(cause); }
    finally { inFlight.current = false; setBusy(false); }
  };
  useEffect(() => { void load(); }, [id]);
  const mutate = async (operation: (id: string) => Promise<GuestBooking>) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try { setBooking(await operation(id)); }
    catch (cause) { handleError(cause); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const presentation = booking && guestSettlementPresentation(booking);
  const approve = booking && sandboxApproveUrl(booking.approve_url);
  const settlementPayment = booking && ["CAPTURE_PENDING", "PAID", "REFUND_PENDING", "REFUNDED"].includes(booking.state);
  return <section className="section guest-status-page"><p className="kicker">Private guest reservation · Sandbox</p>
    <h1>{lost ? "Reservation access unavailable." : presentation?.[0] ?? "Reservation status"}</h1>
    {suffix && <p className="preview-callout">{suffix === "return" ? "Returned from PayPal. This link is not proof of approval or authorization. The saved backend status below is authoritative. Opening this page does not execute financial operations; deadline processing runs independently." : "Returned from PayPal cancellation. No cancellation or financial cleanup has been performed by opening this page."}</p>}
    {lost ? <div className="preview-callout"><p>This booking is unavailable to the current guest session. The cookie may be lost or expired, or the reservation may belong to another guest. We cannot restore private bookings by email.</p><a className="text-link" href="/workshops">Browse public workshops</a></div> : <>
      {error && <p className="form-error" role="alert">{error}</p>}
      {!booking && !error && <p role="status">Retrieving your saved reservation…</p>}
      {booking && <div className="guest-status-card"><h2>{booking.workshop_title}</h2><p className="large-copy">{money(booking.amount_minor)} · one place · {booking.currency}</p><p>{presentation?.[1]}</p><p>{booking.notice}</p>{!settlementPayment && booking.notice !== authorizationExplanation && <p>{authorizationExplanation}</p>}
        {campaignStatusMessage(booking.campaign_status, booking.sandbox_cleanup_status) && <p className="preview-callout">{campaignStatusMessage(booking.campaign_status, booking.sandbox_cleanup_status)}</p>}
        {settlementPayment && <p>Verified collected: {money(booking.captured_minor ?? 0)} · Verified refunded: {money(booking.refunded_minor ?? 0)}. Pending amounts are not counted as completed.</p>}
        <dl className="detail-facts"><div><dt>Seat currently held</dt><dd>{booking.seat_held ? "Yes, according to saved server status" : "No"}</dd></div><div><dt>Temporary reservation expires · London time</dt><dd>{displayDate(booking.reservation_expires_at)}</dd></div><div><dt>Saved payment state</dt><dd>{booking.payment_state}</dd></div><div><dt>Last saved update · London time</dt><dd>{displayDate(booking.updated_at)}</dd></div></dl>
        <div className="guest-actions">
          {booking.can_create_order && <button className="tp-button" disabled={busy} onClick={() => void mutate(api.createGuestOrder)}>Create PayPal Sandbox order</button>}
          {approve && <a className="tp-button" href={approve} rel="noreferrer">Continue to PayPal Sandbox</a>}
          {booking.approve_url && !approve && <p className="form-error" role="alert">The server approval link could not be validated as PayPal Sandbox. No provider link is offered.</p>}
          {booking.can_authorize && <button className="tp-button" disabled={busy} onClick={() => void mutate(api.authorizeGuestBooking)}>Check approval and authorize</button>}
          {booking.can_cancel && <button className="tp-button tp-button-secondary" disabled={busy} onClick={() => void mutate(api.cancelGuestBooking)}>Request cancellation</button>}
        </div><a className="text-link" href={`/workshops/${booking.workshop_id}`}>Public workshop details</a>
      </div>}
    </>}
    <button className="tp-button tp-button-secondary" disabled={busy} onClick={() => void load()}>{busy ? "Checking saved status…" : "Refresh saved status"}</button>
    <p className="small-copy">Refreshing only reads saved server state; it does not contact PayPal or execute a payment operation. Background settlement is independent of this page. Keep this guest session cookie to retain access. No email has been sent by this page.</p>
  </section>;
}
