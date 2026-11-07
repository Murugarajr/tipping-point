import type { Campaign } from "../types";
import { displayDate, money } from "./model";

export default function SettlementPanel({ campaign, refresh }: { campaign: Campaign; refresh: () => void }) {
  const status = campaign.settlement;
  return <section className="host-panel" aria-label="Campaign settlement">
    <h2>Campaign decision &amp; settlement</h2>
    <p>Booking cutoff · London time: {displayDate(campaign.cutoff_at)}</p>
    {!status ? <p className="host-notice">Settlement status is unavailable on this backend/schema. No collection or confirmation is assumed.</p> : <>
      <p className={`host-notice ${status.review_required ? "host-warning" : ""}`}>
        <strong>{status.state === "CONFIRMED" ? "Workshop financially confirmed" : status.state === "CANCELLED" ? "Campaign cancelled after cleanup" : `Campaign ${status.state.toLowerCase()}`}</strong>
        {status.review_required && " · Operator review required; unresolved financial operations remain."}
      </p>
      <dl className="cost-breakdown">
        <div><dt>Currently admitted attendance</dt><dd>{status.admitted_attendance}</dd></div>
        <div><dt>Frozen decision attendance</dt><dd>{status.frozen_attendance ?? "Not frozen yet"}</dd></div>
        <div><dt>Decision</dt><dd>{status.decision_result ?? "Awaiting cutoff"} · {status.decision_reason ?? "No deadline decision yet"}</dd></div>
        <div><dt>Authorized booking amount · not collected</dt><dd>{money(status.authorized_minor)}</dd></div>
        <div><dt>Verified gross collected</dt><dd>{money(status.collected_minor)}</dd></div>
        <div><dt>Verified refunded</dt><dd>{money(status.refunded_minor)}</dd></div>
        <div><dt>Pending capture / release / refund</dt><dd>{status.capture_pending} / {status.release_pending} / {status.refund_pending}</dd></div>
        <div><dt>Collection deadline</dt><dd>{status.settlement_deadline ? displayDate(status.settlement_deadline) : "Not set yet"}</dd></div>
        <div><dt>Frozen estimated fees</dt><dd>{status.estimated_fees_minor === null ? "Not evaluated" : money(status.estimated_fees_minor)}</dd></div>
        <div><dt>Actual returned fees · full cohort</dt><dd>{status.actual_fees_minor === null ? "Not fully available" : money(status.actual_fees_minor)}</dd></div>
        <div><dt>Fee basis used by policy</dt><dd>{status.fee_basis}</dd></div>
        <div><dt>Estimated decision surplus</dt><dd>{status.estimated_surplus_minor === null ? "Not evaluated" : money(status.estimated_surplus_minor)}</dd></div>
        <div><dt>Post-collection policy surplus</dt><dd>{status.post_collection_surplus_minor === null ? "Not evaluated" : money(status.post_collection_surplus_minor)}</dd></div>
      </dl>
      <p className="host-helper">Surplus is a policy calculation, not audited profit. Pending captures are not collected funds. Refunds and authorization releases are different operations; neither is promised instant.</p>
    </>}
    <button className="host-button secondary" onClick={refresh}>Refresh saved campaign status</button>
    <p className="host-helper">Read-only refresh. This does not force a deadline decision, capture, refund or confirmation.</p>
  </section>;
}
