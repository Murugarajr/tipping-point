import { useEffect, useState } from "react";
import * as api from "../api";
import type { PublicWorkshop } from "../types";
import { Arrow, Mark } from "./Artwork";
import { displayDate, money } from "../host/model";

const windowLabel = (state: PublicWorkshop["booking_window_status"]) => ({
  not_open_yet: "Booking window not open yet", open: "Booking window open · reservations unavailable",
  closed: "Booking window closed", unavailable: "Booking window unavailable",
})[state];

export function PublishedCollection({ standalone = false }: { standalone?: boolean }) {
  const [items, setItems] = useState<PublicWorkshop[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const load = async () => {
    setState("loading");
    try { setItems(await api.listPublicWorkshops()); setState("ready"); }
    catch { setState("error"); }
  };
  useEffect(() => { void load(); }, []);
  return <section className="section published-collection" aria-labelledby="published-title">
    <div className="section-heading"><div><p className="kicker">Published by independent hosts</p>{standalone ? <h1 id="published-title">What will you<br /><span className="red-text">make next?</span></h1> : <h2 id="published-title">Workshops, with a plan.</h2>}</div>{!standalone && <a className="text-link" href="/workshops">Browse workshops<Arrow /></a>}</div>
    <p className="published-intro">Actual published campaign information. Guest reservations and payments are not enabled yet; an open booking window is not a payment confirmation.</p>
    {state === "loading" ? <div className="public-empty" role="status"><p>Loading published workshops…</p></div>
      : state === "error" ? <div className="public-empty"><h3>Workshops are unavailable right now.</h3><p role="alert">We could not load published information. The examples below are separate illustrations, not replacement inventory.</p><button className="tp-button" onClick={() => void load()}>Try again<Arrow /></button></div>
        : !items.length ? <div className="public-empty published-empty"><Mark /><h3>No workshops published just yet.</h3><p>Good ideas take a little planning. In the meantime, explore the clearly labelled examples below.</p><a className="text-link" href="#example-collection">Explore examples<Arrow /></a></div>
          : <div className="published-grid">{items.map((workshop) => <article className="published-card" key={workshop.workshop_id}><a className="published-art" href={`/workshops/${workshop.workshop_id}`} aria-label={`View ${workshop.title}`}><Mark /><span>Room for<br />something good.</span><Arrow diagonal /></a><span className="outline-pill">Published · {workshop.publication_status}</span><h3><a href={`/workshops/${workshop.workshop_id}`}>{workshop.title}</a></h3><p>{workshop.description || "The host has not added a description."}</p><strong className="published-price">{money(workshop.ticket_price_minor)}<span> per place</span></strong><dl className="card-status"><div><dt>Capacity</dt><dd>{workshop.capacity} places</dd></div><div><dt>Bookings open · London time</dt><dd>{displayDate(workshop.opens_at)}</dd></div><div><dt>Cutoff · London time</dt><dd>{displayDate(workshop.cutoff_at)}</dd></div><div><dt>Booking window</dt><dd>{windowLabel(workshop.booking_window_status)}</dd></div><div><dt>Payment</dt><dd>Unavailable · none collected through this flow</dd></div></dl><a className="text-link" href={`/workshops/${workshop.workshop_id}`}>View workshop<Arrow /></a></article>)}</div>}
  </section>;
}

export function PublishedDetail({ id }: { id: string }) {
  const [workshop, setWorkshop] = useState<PublicWorkshop | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const load = async () => {
    setState("loading");
    try { const found = await api.getPublicWorkshop(id); setWorkshop(found); setState("ready"); document.title = `${found.title} | Tipping Point`; }
    catch (cause) { setState(cause instanceof api.ApiError && cause.status === 404 ? "missing" : "error"); }
  };
  useEffect(() => { void load(); }, [id]);
  if (state !== "ready" || !workshop) return <section className="section public-empty not-found"><h1>{state === "loading" ? "Loading workshop…" : state === "missing" ? "Workshop not found." : "Workshop unavailable."}</h1><p>{state === "missing" ? "That reference is not a published workshop." : state === "error" ? "Published information could not be loaded. No sample details have been substituted." : "Retrieving public campaign information."}</p>{state === "error" && <button className="tp-button" onClick={() => void load()}>Try again<Arrow /></button>}<a className="text-link" href="/workshops">Browse workshops<Arrow /></a></section>;
  return <section className="section real-detail-page"><a className="text-link back-link" href="/workshops">← All workshops</a><div className="real-detail-grid"><div><span className="outline-pill">Published campaign · {workshop.publication_status}</span><h1>{workshop.title}</h1><p className="large-copy">{workshop.description || "The host has not added a description."}</p><div className="published-art detail-published-art" aria-hidden="true"><Mark /><span>A shared table.<br />A considered plan.</span></div><h2>Before you make plans.</h2><p>Workshop delivery date, venue, duration, accessibility information and category are not supported by the current saved metadata. Do not infer these from the booking dates.</p><p>This is a Sandbox prototype. No guest booking or payment can be completed here.</p></div><aside className="public-booking-panel"><div className="detail-price">{money(workshop.ticket_price_minor)}<span>per place · GBP</span></div><dl className="detail-facts"><div><dt>Published capacity</dt><dd>{workshop.capacity} places</dd></div><div><dt>Bookings open · London time</dt><dd>{displayDate(workshop.opens_at)}</dd></div><div><dt>Booking cutoff · London time</dt><dd>{displayDate(workshop.cutoff_at)}</dd></div><div><dt>Publication status</dt><dd>{workshop.publication_status} · not payment-confirmed</dd></div><div><dt>Booking window</dt><dd>{windowLabel(workshop.booking_window_status)}</dd></div><div><dt>Payment capability</dt><dd>Unavailable</dd></div></dl><div className="preview-callout"><strong>Reservations are not enabled.</strong><p>{workshop.availability_note}</p></div><button className="tp-button" disabled>Guest booking unavailable</button><a className="text-link" href="/continue">Explore a separate guest-form preview<Arrow diagonal /></a><p className="small-copy">The preview does not reserve this workshop, save email or authorize a payment.</p></aside></div></section>;
}
