import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Arrow, CraftArt, Mark, ThresholdArt } from "./Artwork";
import { categories, faqs, filterWorkshops, findWorkshop, formatPrice } from "./content";
import type { CategoryFilter, ExampleWorkshop } from "./content";

function LinkButton({ href, children, secondary = false }: { href: string; children: ReactNode; secondary?: boolean }) {
  return <a className={`tp-button ${secondary ? "tp-button-secondary" : ""}`} href={href}>{children}<Arrow /></a>;
}

function Header({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  return <header className="public-header" onKeyDown={(event) => {
    if (event.key === "Escape" && open) { setOpen(false); menuButton.current?.focus(); }
  }}>
    <a className="wordmark" href="/" aria-label="Tipping Point home"><Mark /><span>tipping point<span className="wordmark-period">.</span></span></a>
    <span className="prototype-label"><span />Sandbox prototype</span>
    <button ref={menuButton} className="menu-toggle" aria-expanded={open} aria-controls="public-navigation" onClick={() => setOpen(!open)}>{open ? "Close" : "Menu"}</button>
    <nav id="public-navigation" className={open ? "public-navigation is-open" : "public-navigation"} aria-label="Main navigation">
      <a href="/workshops" aria-current={path === "/workshops" ? "page" : undefined}>Workshops</a>
      <a href="/#how-it-works" onClick={() => setOpen(false)}>How it works</a>
      <a href="/#for-hosts" onClick={() => setOpen(false)}>For hosts</a>
      <a className="host-link" href="/host/login">Host sign in<Arrow diagonal /></a>
    </nav>
    <a className="header-cta" href="/workshops">Explore workshops<Arrow /></a>
  </header>;
}

function Footer() {
  return <footer className="public-footer">
    <div className="footer-top"><a className="wordmark" href="/"><Mark /><span>tipping point.</span></a><p>A good idea.<br />A few good people.<br />Something worth making.</p>
      <nav aria-label="Footer navigation"><a href="/workshops">Workshops</a><a href="/#how-it-works">How it works</a><a href="/host/login">Host sign in</a><a href="/example-plan">Example host plan</a></nav>
    </div>
    <div className="footer-bottom"><p>Sandbox prototype. No real payments. Example workshops are not bookable.</p><details><summary>Privacy &amp; your data</summary><p>Public browsing needs no account. The guest preview keeps your email only in this page’s memory; it does not save or send it. Host sign-in uses server-issued session and CSRF cookies. Do not enter real payment information. No analytics or marketing signup is added by this frontend.</p></details><span>Made for making.</span></div>
  </footer>;
}

function Hero() {
  return <section className="hero" aria-labelledby="hero-title">
    <div className="hero-copy">
      <p className="kicker"><svg className="little-star" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M12 1v22M1 12h22M4 4l16 16M4 20 20 4" /></svg> Small groups. Real possibilities.</p>
      <h1 id="hero-title">Good workshops.<br />Enough people.<br /><span>Let’s make<br className="desktop-break" /> it happen.</span></h1>
      <p className="hero-intro">Discover hands-on experiences and help independent hosts turn a good idea into a workshop that can actually run.</p>
      <div className="hero-actions"><LinkButton href="/workshops">Explore workshops</LinkButton><a className="text-link" href="#how-it-works">See how it works<Arrow diagonal /></a></div>
      <p className="hero-footnote">See the booking goal. Understand the deadline.<br />Know what happens next.</p>
    </div>
    <div className="hero-bento">
      <div className="tile threshold-tile"><div className="tile-heading"><span>A few people.<br />A shared possibility.</span><span className="tile-index">01 /</span></div><ThresholdArt /><div className="tile-bottom"><strong>Better, together.</strong><span>Illustrative journey<br />Not live bookings</span></div></div>
      <div className="tile pottery-tile"><CraftArt craft="clay" /><span className="art-caption">Less scrolling.<br />More making.</span><span className="round-arrow" aria-hidden="true"><Arrow diagonal /></span></div>
      <div className="tile definition-tile"><span className="tile-index">The idea is simple.</span><h2>Every workshop<br />has a tipping<br />point<span>.</span></h2><p>Enough people to cover approved costs. Then a real check of the group and its payments.</p></div>
      <a className="tile blue-tile" href="/workshops"><span className="open-circle" aria-hidden="true"><Arrow diagonal /></span><strong>Curiosity first.<br />No account needed<br />to explore.</strong></a>
      <div className="tile journey-tile"><span className="tiny-dot" aria-hidden="true" /><div><strong>From “I’m in” to “it’s on”.</strong><p>Reserve → check → confirm or unwind</p><span>Intended booking flow · not enabled yet</span></div></div>
    </div>
  </section>;
}

const steps = [
  ["Find your workshop.", "Browse creative sessions and see what you’ll make, learn and take away."],
  ["Reserve your place.", "The intended guest flow uses a Sandbox payment authorization, not an immediate completed charge. Booking is not enabled yet."],
  ["Reach the booking decision.", "At the cutoff, check the actual booked group, approved costs and payment outcomes. Headcount alone is not confirmation."],
  ["Know where you stand.", "Confirm only after successful checks, or release authorizations and refund any collected payments through the appropriate process."],
] as const;

function HowItWorks() {
  return <section className="section how-section" id="how-it-works" aria-labelledby="how-title">
    <div className="section-heading"><div><p className="kicker">From a good idea to a full table</p><h2 id="how-title">A little clarity.<br />At every step.</h2></div><p>Less guesswork for hosts.<br />A clearer plan for everyone.</p></div>
    <ol className="steps">{steps.map(([title, text], index) => <li key={title}><span className="step-number">0{index + 1}<span aria-hidden="true">↗</span></span><h3>{title}</h3><p>{text}</p></li>)}</ol>
    <details className="payment-details"><summary>One important distinction: authorized is not collected.<span aria-hidden="true">+</span></summary><div><p>A payment authorization may place a temporary hold. Approval alone is not authorization, and authorization is not payment collection. This prototype’s public pages do not perform any of these operations.</p><p>In the intended flow, all required captures must complete and the approved costs must still be covered before confirmation. Partial collection requires compensation. Release and refund timing depends on the provider; unresolved outcomes need review.</p></div></details>
  </section>;
}

function WorkshopCard({ workshop }: { workshop: ExampleWorkshop }) {
  return <article className="example-card">
    <a className="workshop-art-link" href={`/workshops/${workshop.id}`} aria-label={`View example: ${workshop.title}`}><CraftArt craft={workshop.craft} /><span className="example-pill">Example workshop</span><span className="round-arrow"><Arrow diagonal /></span></a>
    <div className="card-meta"><span>{workshop.category} / Beginner-friendly</span><span>{workshop.duration}</span></div>
    <h3><a href={`/workshops/${workshop.id}`}>{workshop.title}</a></h3>
    <p className="card-location">{workshop.location}</p>
    <p className="card-includes">{workshop.includes}</p>
    <div className="card-price"><strong>{formatPrice(workshop.priceMinor)}<span> / person · illustrative</span></strong></div>
    <dl className="card-status"><div><dt>Session date</dt><dd>Not scheduled</dd></div><div><dt>Booking deadline</dt><dd>Not set</dd></div><div><dt>Booking</dt><dd>Preview only</dd></div><div><dt>Payment</dt><dd>Not available</dd></div></dl>
    <a className="text-link" href={`/workshops/${workshop.id}`}>View workshop<Arrow /></a>
  </article>;
}

function Discovery({ standalone = false }: { standalone?: boolean }) {
  const [category, setCategory] = useState<CategoryFilter>("All workshops");
  const workshops = filterWorkshops(category);
  return <section className={`section discovery ${standalone ? "standalone-discovery" : ""}`} aria-labelledby="discovery-title">
    <div className="section-heading"><div><p className="kicker">Make room for something hands-on</p>{standalone ? <h1 id="discovery-title">What will you<br /><span className="red-text">make next?</span></h1> : <h2 id="discovery-title">A good place to start.</h2>}</div>{!standalone && <a className="text-link" href="/workshops">Explore all examples<Arrow diagonal /></a>}</div>
    <div className="example-notice"><span className="outline-pill">Example collection</span><p>A taste of what’s possible, not live inventory. Prices, locations and inclusions are illustrative. No public listing API or guest booking is connected.</p></div>
    <div className="filter-row" role="group" aria-label="Filter example workshops by category">{categories.map((item) => <button key={item} aria-pressed={category === item} className={category === item ? "selected" : ""} onClick={() => setCategory(item)}>{item}</button>)}</div>
    <p className="results-count" role="status">{workshops.length} example {workshops.length === 1 ? "workshop" : "workshops"}{category !== "All workshops" ? ` · ${category}` : ""}</p>
    {workshops.length ? <div className="example-grid">{workshops.map((workshop) => <WorkshopCard key={workshop.id} workshop={workshop} />)}</div> : <div className="public-empty"><h3>No {category.toLowerCase()} examples just yet.</h3><p>Try another category to find something worth making.</p><button className="tp-button" onClick={() => setCategory("All workshops")}>Reset filters<Arrow /></button></div>}
  </section>;
}

function Difference() {
  return <section className="section" aria-labelledby="difference-title">
    <div className="section-heading"><div><p className="kicker">The thoughtful bit</p><h2 id="difference-title">Built around the<br />decision to run.</h2></div><p>A booking goal is a starting point.<br />The full picture matters.</p></div>
    <div className="difference-grid">
      <article className="difference-main"><span className="kicker">01 / Costs first</span><h3>Good plans start<br />with the small things.</h3><p>Materials, packs, space and preparation. Approved assumptions inform the attendance plan—not the other way around.</p><div className="cost-graphic" aria-hidden="true"><span>materials</span><span>space</span><span>time</span><span>the plan <Arrow /></span></div><p className="small-copy">Pack boundaries mean more bookings do not automatically guarantee viability.</p></article>
      <article className="difference-goal"><span className="kicker">02 / A visible goal</span><h3>Not a mystery.<br />A shared milestone.</h3><p>See the goal and cutoff. The actual cohort still needs cost and payment checks.</p><div className="goal-line" aria-hidden="true"><i /><i /><i /><i /><i /></div></article>
      <article className="difference-states"><span className="kicker">03 / Clear payment states</span><h3>Say what’s happened.<br />Not what’s hoped for.</h3><div className="state-chips"><span>Authorized</span><Arrow /><span>Collecting</span><Arrow /><span>Completed</span></div><p>Illustrative states, not current payments. Release requested, refund processing and review required stay visible too.</p></article>
      <article className="difference-small"><span>04 / Open doors</span><h3>Explore without<br />an account.</h3><p>Curiosity should not need a password.</p></article>
      <article className="difference-small"><span>05 / Readiness matters</span><h3>Beyond the<br />booking count.</h3><p>Preparation belongs alongside financial progress in the planned host experience.</p></article>
      <article className="difference-small"><span>06 / Traceable inputs</span><h3>Facts, not<br />wishful thinking.</h3><p>Keep sourced offers and reviewed assumptions distinct. Scenarios are not applied changes.</p></article>
    </div>
  </section>;
}

function HostSection() {
  return <section className="section host-section" id="for-hosts" aria-labelledby="host-title">
    <div className="host-copy"><p className="kicker">For the people who bring people together</p><h2 id="host-title">You bring the idea.<br /><span>See what it takes<br />to run.</span></h2><p>A great workshop is more than a full room. It’s the right materials, a considered budget, and a plan you can explain.</p><div className="hero-actions"><LinkButton href="/host/login">Host sign in</LinkButton><a className="text-link" href="/example-plan">Explore an example plan<Arrow diagonal /></a></div><p className="small-copy">Existing provisioned hosts only. No public registration.</p></div>
    <div className="host-plan-preview"><span className="outline-pill">The intended host journey</span><ol>{["Draft the experience", "Review materials & pack quantities", "Preview attendance & cost scenarios", "Publish clear, immutable terms", "Track readiness & payment outcomes"].map((text, index) => <li key={text}><span>0{index + 1}</span>{text}<Arrow diagonal /></li>)}</ol><p>Drafts, server previews and publication exist today. Readiness and guest payment tracking are still planned.</p></div>
  </section>;
}

const integrations = [
  ["PayPal Sandbox", "Backend adapter", "Authorization-intent orders, authorization and void operations in server code. Offline tests exist; no live verification claimed here. Guest checkout is not connected."],
  ["Channel3", "Backend adapter", "Material-offer search and selection code exists. Live contract verification remains incomplete; examples on this page are not Channel3 results."],
  ["AG Studio / AG Grid", "Planned", "Host analytics, a Tipping Meter and bounded scenario analysis. No Studio component is installed in this frontend."],
  ["Bryntum", "Planned", "An operational dependency timeline for workshop readiness. The example plan is editorial content, not a Bryntum integration."],
  ["APIMatic", "Not verified", "Intended development-time PayPal API context. Plugin use is not established by this frontend implementation."],
  ["Render", "Planned", "Same-origin hosting and background workflow execution. No hosted deployment or workflow run is claimed."],
] as const;

function BuiltWith() {
  return <section className="section built-with" aria-labelledby="built-title"><div className="section-heading"><div><p className="kicker">Behind the scenes</p><h2 id="built-title">Useful technology.<br />Honest about the stage.</h2></div><p>A prototype in progress.<br />Integration is not endorsement.</p></div><div className="integration-list">{integrations.map(([name, status, text]) => <details key={name}><summary><strong>{name}</strong><span className="integration-status">{status}</span><span aria-hidden="true">+</span></summary><p>{text}</p></details>)}</div></section>;
}

function FAQ() {
  return <section className="section faq-section" id="questions" aria-labelledby="faq-title"><div><p className="kicker">A few good questions</p><h2 id="faq-title">Before you<br />pull up a chair.</h2><p>Still exploring? That’s the point.</p></div><div className="faq-list">{faqs.map(([question, answer]) => <details key={question}><summary>{question}<span aria-hidden="true">+</span></summary><p>{answer}</p></details>)}</div></section>;
}

function Closing() {
  return <section className="closing"><span className="closing-symbol" aria-hidden="true">↗</span><p className="kicker">A little time. A new skill. A shared table.</p><h2>Good things happen<br />when we make room.</h2><LinkButton href="/workshops">Find your next workshop</LinkButton><p className="small-copy">Explore the examples. Imagine the possibilities.</p></section>;
}

function Home() {
  return <><Hero /><section className="editorial-intro section"><div><p className="kicker">More than a seat at a table</p><h2>Not another<br />ticket page<span className="red-text">.</span></h2></div><div><p className="large-copy">Small workshops have real costs before the first guest arrives.</p><p>Materials, space, preparation and time. Tipping Point connects those costs to a clear booking decision, so hosts and guests can see the plan.</p><a className="text-link" href="#how-it-works">Here’s how we think about it<Arrow diagonal /></a></div></section><HowItWorks /><Discovery /><Difference /><HostSection /><BuiltWith /><FAQ /><Closing /></>;
}

function Detail({ workshop }: { workshop: ExampleWorkshop }) {
  return <div className="section detail-page"><a className="text-link back-link" href="/workshops">← All example workshops</a><div className="detail-layout">
      <div className="detail-art"><CraftArt craft={workshop.craft} /><span className="example-pill">Original illustration · example workshop</span></div>
      <div className="detail-copy"><span className="outline-pill">Example · {workshop.category}</span><h1>{workshop.title}</h1><p>{workshop.intro}</p><div className="detail-price">{formatPrice(workshop.priceMinor)}<span>per person · illustrative price</span></div><dl className="detail-facts"><div><dt>Where</dt><dd>{workshop.location}</dd></div><div><dt>Duration</dt><dd>{workshop.duration}</dd></div><div><dt>Session date</dt><dd>Not scheduled</dd></div><div><dt>Booking cutoff / goal</dt><dd>Not published</dd></div><div><dt>Booking status</dt><dd>Example only · unavailable</dd></div><div><dt>Payment status</dt><dd>No authorization or collection</dd></div></dl><div className="preview-callout"><strong>This one is an example.</strong><p>No place can be reserved and no payment can be made. Explore the guest form to see the intended first step.</p></div><LinkButton href={`/continue?workshop=${workshop.id}`}>Continue as guest — preview</LinkButton><p className="small-copy">No account creation. No real payments.</p><details className="payment-details"><summary>How payment would work<span aria-hidden="true">+</span></summary><p>Authorize a place in the intended Sandbox flow. Collection happens only after the cutoff checks. A reached headcount alone never confirms a workshop; incomplete collection may require releases and refunds.</p></details></div>
      <section className="detail-about"><p className="kicker">Something made by you</p><h2>A little space to learn.</h2><p>{workshop.intro}</p><h3>What’s included</h3><p>{workshop.includes}.</p><h3>What you’ll explore</h3><p>{workshop.takeaway}</p><h3>Who it’s for</h3><p>A beginner-friendly example. Accessibility, age suitability and any venue requirements would need confirmation in a real published listing.</p></section>
    </div></div>;
}

function GuestPreview() {
  const selectedId = new URLSearchParams(window.location.search).get("workshop");
  const workshop = findWorkshop(selectedId);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const result = useRef<HTMLDivElement>(null);
  useEffect(() => { if (submitted) result.current?.focus(); }, [submitted]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!input.current?.validity.valid || !email.trim()) { setError("Enter a valid email address, such as you@example.com."); input.current?.focus(); return; }
    setError(""); setEmail(""); setSubmitted(true);
  };
  return <section className="section guest-page"><div className="guest-intro"><p className="kicker">Curiosity, without the commitment</p><h1>Your place<br />starts here<span className="red-text">.</span></h1><p>One small step towards making something good.</p><div className="guest-art"><CraftArt craft={workshop?.craft ?? "thread"} /></div></div><div className="guest-form-panel"><span className="outline-pill">Guest-flow preview</span>{workshop ? <h2>{workshop.title}</h2> : <h2>Explore the first step.</h2>}<p>Booking is not enabled yet. This form demonstrates the email step only. It cannot reserve a place, look up bookings or grant account access.</p>{selectedId && !workshop && <p className="preview-callout">That example was not found. You can still explore this standalone form, or <a href="/workshops">choose an example</a>.</p>}
      {submitted ? <div className="guest-result" role="status" tabIndex={-1} ref={result}><span className="kicker">Preview complete</span><h3>That’s where the preview ends.</h3><p>Your email was not saved or sent. No reservation was made, no email was sent, and no payment was authorized. The input has been cleared.</p><p>A genuine booking requires server-issued guest sessions and a connected booking service.</p><a className="text-link" href="/workshops">Back to exploring<Arrow /></a><button className="text-button" onClick={() => { setSubmitted(false); }}>Try the form again</button></div> :
        <form noValidate onSubmit={submit}><label htmlFor="guest-email">Email address</label><input id="guest-email" ref={input} type="email" autoComplete="email" inputMode="email" maxLength={254} required value={email} onChange={(event) => { setEmail(event.target.value); if (error) setError(""); }} aria-invalid={Boolean(error)} aria-describedby={`email-help email-use${error ? " email-error" : ""}`} placeholder="you@example.com" /><p id="email-help" className="small-copy">No password or account creation required.</p><p id="email-use" className="small-copy">In a supported booking flow, your email would be contact information—not proof of identity. In this preview it stays only in page memory and is cleared on submission or navigation.</p>{error && <p id="email-error" className="form-error" role="alert">{error}</p>}<button className="tp-button" type="submit">Explore the next step<Arrow /></button></form>}
      <div className="guest-host-link"><span>Here to host?</span><a className="text-link" href="/host/login">Host sign in<Arrow diagonal /></a></div></div></section>;
}

function ExamplePlan() {
  return <section className="section example-plan-page"><div className="section-heading"><div><p className="kicker">Public / read-only / illustrative</p><h1>From first idea<br />to ready to make.</h1></div><span className="outline-pill">Example plan · not merchant data</span></div><p className="large-copy">A little clay, a little calm.</p><p className="plan-intro">An editorial walkthrough of the intended workflow. This is not a saved campaign, financial calculation or live operational timeline. No dates, attendance goal or cost assumptions have been approved.</p><ol className="example-plan-steps">{[
    ["Draft the experience", "Describe the activity, venue, duration and what guests should expect.", "Supported in host workspace"],
    ["Review the materials", "Review sourced offers, pack quantities and shipping assumptions. Offers do not reserve supplier stock.", "Backend selection exists · live verification incomplete"],
    ["Preview the decision", "Use the backend cost curve for the actual attendance. This example does not calculate or publish a threshold.", "Server calculator exists"],
    ["Publish clear terms", "Freeze the reviewed terms and a short booking window before accepting reservations.", "Host publication exists · guest booking unavailable"],
    ["Check, then prepare", "At cutoff, check the booked cohort and payment results. Confirm only after collection and financial checks; otherwise unwind safely.", "Settlement & readiness journey planned"],
  ].map(([title, description, status], index) => <li key={title}><span className="plan-number">0{index + 1}</span><div><h2>{title}</h2><p>{description}</p><span className="plan-status">{status}</span></div></li>)}</ol><LinkButton href="/host/login">Go to host sign in</LinkButton></section>;
}

function NotFound() {
  return <section className="section public-empty not-found"><p className="kicker">404 / A loose thread</p><h1>Nothing to make<br />of this page.</h1><p>This page or example workshop could not be found.</p><LinkButton href="/workshops">Explore workshops</LinkButton></section>;
}

export default function PublicApp({ path }: { path: string }) {
  let page: ReactNode;
  let title: string;
  if (path === "/") { page = <Home />; title = "Good workshops. Enough people."; }
  else if (path === "/workshops") { page = <Discovery standalone />; title = "Explore example workshops"; }
  else if (path.startsWith("/workshops/")) {
    const workshop = findWorkshop(path.slice("/workshops/".length));
    page = workshop ? <Detail workshop={workshop} /> : <NotFound />;
    title = workshop?.title ?? "Page not found";
  }
  else if (path === "/continue") { page = <GuestPreview />; title = "Guest-flow preview"; }
  else if (path === "/example-plan") { page = <ExamplePlan />; title = "An example host plan"; }
  else { page = <NotFound />; title = "Page not found"; }
  useEffect(() => { document.title = `${title} | Tipping Point`; }, [title]);
  return <div className="public-site"><a className="skip-link" href="#main-content">Skip to content</a><Header path={path} /><main id="main-content" tabIndex={-1}>{page}</main><Footer /></div>;
}
