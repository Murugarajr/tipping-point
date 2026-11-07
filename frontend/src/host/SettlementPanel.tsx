import type { Campaign } from "../types";
import { displayDate, money, settlementHeadline } from "./model";

export default function SettlementPanel({ campaign, refresh }: { campaign: Campaign; refresh: () => void }) {
  const status = campaign.settlement;
  return <section className="host-panel" aria-label="Campaign settlement">
    <h2>Campaign decision &amp; settlement</h2>
    <p>Booking cutoff · London time: {displayDate(campaign.cutoff_at)}</p>
    {!status ? <p className="host-notice">Settlement status is unavailable on this backend/schema. No collection or confirmation is assumed.</p> : <>
      <p className={`host-notice ${status.review_required ? "host-warning" : ""}`}>
        <strong>{settlementHeadline(status)}</strong>
        {status.review_required && " · Operator review required; unresolved financial operations remain."}
      </p>
      {status.sandbox_cleanup && <p className="host-notice">
        Sandbox operator-test cleanup{status.sandbox_cleanup.previously_confirmed ? " of a previously financially confirmed campaign" : ""}.
        The completed capture is being refunded, not voided. Historical gross collection stays shown separately from refunded and net amounts.
        {status.sandbox_cleanup.review_reason && ` Review reason: ${status.sandbox_cleanup.review_reason}.`}
      </p>}
      <dl className="cost-breakdown">
        <div><dt>Currently admitted attendance</dt><dd>{status.admitted_attendance}</dd></div>
        <div><dt>Frozen decision attendance</dt><dd>{status.frozen_attendance ?? "Not frozen yet"}</dd></div>
        <div><dt>Decision</dt><dd>{status.decision_result ?? "Awaiting cutoff"} · {status.decision_reason ?? "No deadline decision yet"}</dd></div>
        <div><dt>Authorized booking amount · not collected</dt><dd>{money(status.authorized_minor)}</dd></div>
        <div><dt>Verified gross collected</dt><dd>{money(status.collected_minor)}</dd></div>
        <div><dt>Verified refunded</dt><dd>{money(status.refunded_minor)}</dd></div>
        <div><dt>Net collected after verified refunds</dt><dd>{money(status.net_collected_minor ?? status.collected_minor - status.refunded_minor)}</dd></div>
        {status.sandbox_cleanup && <div><dt>Test cleanup reason · requested</dt><dd>{status.sandbox_cleanup.reason ?? "Not recorded"} · {status.sandbox_cleanup.requested_at ? displayDate(status.sandbox_cleanup.requested_at) : "Not recorded"}</dd></div>}
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
