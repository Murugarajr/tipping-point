Implement the next Tipping Point slice: guest reservations connected to
the existing PayPal Sandbox authorization adapter.

The host workflow now successfully publishes campaigns and displays them
publicly. The public page correctly says reservations are not enabled.
Do not redesign working pages or repeat completed checkpoints.

Goal:
Public workshop → continue as guest → contact email → temporary seat
reservation → PayPal buyer approval → server-verified authorization →
persisted guest reservation status.

Read applicable AGENTS.md instructions, docs/tip-implementation-plan.md,
paypal-settlement, verification-release, and the existing code first.

1. INSPECT AND REUSE

Inspect:
- Public campaign listing/detail APIs and availability logic.
- Existing guest-form UI.
- Merchant authentication and CSRF patterns.
- Campaign/frozen-terms models.
- PayPal adapter and operator runner.
- Current migration head and test-isolation fixtures.

Reuse working code. Do not create a second payment adapter.

Report briefly whether the standalone real Sandbox authorization/void
test has actually completed. If not, keep live verification pending,
but proceed with offline implementation and tests.

Do not claim live verification from mocked tests.

2. IMPLEMENT SERVER-ISSUED GUEST SESSIONS

Use opaque, cryptographically random session tokens.
Persist only token hashes, with expiry and revocation.
Use HttpOnly cookies, Secure in hosted environments, and explicit
SameSite/Path settings.

Keep guest identity separate from merchant identity.
Entering an email provides contact information, not proof of ownership
of existing reservations.

Do not:
- Look up and disclose bookings by email alone.
- Trust caller-provided guest IDs or merchant IDs.
- Store session tokens in browser localStorage.
- Introduce JWTs, magic links, or email delivery in this slice.

Reuse appropriate existing CSRF/origin protection, including protection
for cookie-authenticated guest mutations.

3. IMPLEMENT ONE-SEAT RESERVATIONS

Support one seat per booking and GBP only.

Create a booking linked to:
- Campaign
- Exact published/frozen terms reference
- Server-resolved guest session
- Contact email
- Server-derived ticket price and currency
- Reservation expiry
- Explicit booking/payment state

Check server-side:
- Campaign is published and eligible for reservations.
- Booking window is currently open.
- Campaign is not deciding, cancelled, or otherwise closed.
- Capacity remains available.
- Published terms are valid for this booking.

Use a short database transaction and campaign-row locking or equivalent
to prevent overselling.

Count active reservations and admitted authorizations consistently.
Expired holds must stop consuming capacity without requiring an
unreliable browser timer.

Make repeated reservation submissions idempotent.
Do not trust client prices, capacity, status, or expiry timestamps.

4. ADD DURABLE PAYMENT OPERATIONS

Add the minimum persistence required for:
- Booking
- PayPal order and authorization references
- Provider state
- Operation kind and application state
- Stable operation-scoped request ID
- Immutable request payload/hash
- Unknown outcomes and reconciliation
- Sanitized audit/correlation information

Create and commit the operation record before external mutation.
Never hold database locks/transactions across PayPal requests.

Concurrent requests must not create two logical orders or authorization
operations for the same booking.

Reusing an operation must preserve its request ID and payload.
A timeout must not trigger a replacement order automatically.

5. CONNECT THE EXISTING PAYPAL ADAPTER

Support:
- Create order with intent AUTHORIZE.
- Present the actual validated Sandbox approval link.
- Buyer approves manually in PayPal.
- Backend retrieves and validates the approved order.
- Backend authorizes it.
- Persist and retrieve/validate the authorization.

Validate:
- Stored order ID and booking association.
- Expected merchant/payee from server configuration.
- Exact server-derived amount and GBP currency.
- Purchase-unit/reference linkage.
- Provider status.

Do not accept browser redirect/query parameters as proof of approval.

If using return/cancel routes, generate them from approved server
configuration. No arbitrary client-provided redirect URLs.

The browser must never receive the PayPal client secret or access token.

6. HANDLE LATE AND UNKNOWN OUTCOMES

A browser cancellation is not proof that no provider operation succeeded.

If authorization completes after the reservation expires, capacity is
lost, or campaign admission closes:
- Persist the authorization reference.
- Do not admit the booking.
- Queue/record release of that same uncaptured authorization.
- Show release pending until the provider outcome is established.

Implement a narrow resumable reconciliation/release service and an
operator invocation for this slice. It must preserve operation keys
and survive restart.

Do not depend on an open browser tab for cleanup.
Do not create another general-purpose operator framework.

For an ambiguous authorization response, retrieve the known order and
associated resources before any new mutation.
Keep unresolved cases visible.

Do not implement capture, refunds, settlement, or reauthorization yet.

7. IMPLEMENT THE ACTUAL GUEST UI

On eligible published workshops, replace the unavailable button with
“Reserve a place”.

Keep booking disabled with a specific reason when:
- Booking has not opened.
- Booking has closed.
- Capacity is exhausted.
- Payment configuration is unavailable.
- Campaign is no longer eligible.

Do not enable booking merely because the campaign status is OPEN.

Guest flow:
- Workshop/price summary
- Email input
- Clear authorization explanation
- Explicit continue action
- PayPal approval handoff
- Reservation status page

Explain:
“This Sandbox prototype authorizes a test payment. An authorization
is not a completed charge. The workshop is not confirmed by this step.”

Status page must distinguish:
- Seat held temporarily
- Awaiting buyer approval
- Checking payment
- Authorized reservation
- Expired
- Release pending
- Authorization voided
- Review required

An authorized reservation is not a confirmed workshop.

Retrieve booking status only for its owning guest session.
For a lost/expired session, explain the limitation; do not recover
private records simply by asking for an email.

Do not display “email sent” or promise email notifications.

8. DATABASE AND MIGRATION APPROVAL

Adding the minimal guest/booking/payment-operation schema is approved.

Use one additive migration after the actual current head.
Do not rewrite existing migrations or reset databases.
Preserve financial references with restrictive deletion rules.

Apply and test only against tipping_point_test in this task.
Do not apply the new migration to tipping_point_dev yet; report its
exact revision and schema changes for approval.

Use existing dependencies. Propose any genuinely necessary new package
before installing it.

9. AUTOMATED VERIFICATION

All provider calls in automated tests must use MockTransport or existing
offline fixtures. No real credentials or live API requests.

Cover:
- Guest session creation, expiry, and ownership.
- Email does not grant access to someone else's booking.
- CSRF/origin rejection.
- Booking-window enforcement.
- Price/currency derived from frozen terms.
- Last-seat contention with separate DB connections and coordination.
- Expired seat release.
- Repeated booking/order/authorization requests.
- Provider approval without authorization is not success.
- Payee/amount/reference mismatch.
- Mutation timeout and restart/reconciliation.
- Authorization arriving after expiry or cutoff.
- Persisted release/void handling.
- No duplicate logical payment operations.
- Frontend success, error, pending, and unavailable states.
- Existing host publication and public discovery regressions.

Preserve sentinel and unrelated records.
Do not perform automatic schema teardown or broad data cleanup.

10. EXECUTION BOUNDARIES AND DELIVERABLE

Use the repository-root .venv for all Python commands.
Use existing frontend tooling.

No live Channel3 or PayPal calls are approved.
No production payments, captures, refunds, deployment, account changes,
credential changes, commits, or pushes.

If tools fail, report NOT RUN instead of claiming verification.

Implement the slice, then stop with:
- Files changed
- Exact additive migration
- Guest/booking/payment state transitions
- Routes and actual frontend connections
- Executed test/build results
- Remaining limitations
- Exact development-migration command proposed for approval
- A separate checklist for one human-approved end-to-end Sandbox test

Success means the complete reservation journey works against mocked
provider responses with durable backend state—not merely that the
“Reserve a place” button is clickable.