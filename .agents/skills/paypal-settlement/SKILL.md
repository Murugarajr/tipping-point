---
name: paypal-settlement
description: Use when implementing or reviewing Tipping Point PayPal Sandbox checkout, authorization, capture, void, refund, webhooks, settlement, idempotency, reconciliation, or payment concurrency.
---

# PayPal Settlement Workflow

## Read first
1. Read root `AGENTS.md` and the payment/state-machine sections of the implementation plan.
2. Inspect current adapter, domain services, migrations, transaction boundaries, and relevant tests.
3. Verify actual provider contracts using current official PayPal references; use the configured APIMatic context plugin when available.
4. State which transition or failure case the task changes. Preserve the existing interface unless a change is approved.

## Implement safely
- Use authorization-intent checkout. Browser approval alone must not admit a paid or authorized booking.
- Verify order ownership, payee context, amount, currency, authorization state, capacity, and timing server-side.
- Keep campaigns within the approved short-duration policy. Do not assume a long authorization validity window guarantees available funds.
- Persist late/rejected authorizations and release them; do not lose their provider references.
- Freeze one immutable decision cohort before group collection.
- Apply the approved strict policy: all admitted cohort payments must complete before confirmation.
- Persist one logical payment operation and immutable request before an external mutation.
- Claim in a short transaction, commit, call the provider, then persist with a version/ownership check.
- Reuse the logical operation's key on retry wherever the endpoint supports provider idempotency.
- Treat stale-worker fencing and provider idempotency as complementary, not interchangeable.
- On timeout or connection loss, mark the outcome unknown and reconcile. Never blindly replace the operation.
- On partial settlement failure, stop new captures, reconcile in-flight operations, refund completed captures, and void remaining authorizations.
- Refund or capture pending states must remain pending until definitive provider evidence arrives.
- Confirm only after completed collections and the approved economic checks pass.

## Webhooks
- Verify the event against the configured sandbox webhook ID before applying it.
- Durably deduplicate provider event IDs and process idempotently.
- Check resource association, amount/currency where applicable, and current state before transitions.
- Reconcile conflicting/out-of-order events using authoritative provider resources.
- Do not regress terminal application states based solely on late event delivery.
- Acknowledge verified events after durable acceptance; verification outages must not create trusted events.

## Required focused tests
- Approval without authorization; mismatched amount/currency; wrong guest/order ownership.
- Last-seat race; authorization admission versus cutoff freeze; rejected late authorization release.
- Duplicate operation/workflow delivery; webhook versus synchronous response.
- Provider succeeds but persistence fails; worker restarts; stale lease; unknown capture.
- Partial capture failure; late capture during abort; pending refund; interrupted compensation.
- No database lock spans a provider request.

## Evidence and stop condition
Report modified transitions, provider contracts consulted, executed tests, unresolved cases, and actual sandbox evidence separately.
Do not initiate actual sandbox captures/refunds on existing records unless the test scope is approved.
Do not introduce invoices, multi-merchant payouts, live payments, or reauthorization as an incidental fix.

Official entry point: https://developer.paypal.com/api/payments/v2/schema.json
