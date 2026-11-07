# Tipping Point Implementation Plan

## Product Decision

Build Tipping Point as a focused application for independent workshop hosts.

A host creates a workshop, prices its materials using actual product offers, sets a ticket price, and publishes a short booking campaign. Guests authorize payment when reserving a place. At the booking deadline, the application checks whether the workshop can cover its approved costs.

If the campaign qualifies, the application attempts to collect the authorized payments. If the campaign does not qualify, it releases the authorizations. If collection partially fails, the application stops confirmation and follows a compensating refund-and-release process.

The product promise is:

> “Know whether your workshop can run before committing to its costs.”

The guest-facing payment explanation is:

> “Authorize your place now. Payment is collected only if the workshop passes its booking and payment checks. A temporary authorization may appear on your payment account.”

Do not describe Tipping Point as escrow, a savings account, guaranteed crowdfunding, or an atomic group-payment service.

### Initial Audience

Target one merchant running practical, materials-based workshops.

The initial demonstration should use one non-perfume workshop category, such as beginner embroidery, sketchbook making, or another craft supported by useful Channel3 product results.

Choose the final category only after testing actual product search coverage.

Do not expand into a general event marketplace.

### Success Criteria

A successful implementation lets a judge observe:

1. A host creates and costs a workshop.
2. Channel3 returns actual material offers.
3. The application calculates the required attendance.
4. A guest authorizes payment through PayPal Sandbox.
5. AG Studio explains the campaign’s financial position.
6. Bryntum displays the campaign’s operational dependencies.
7. A Render Workflow executes the deadline decision.
8. The application either confirms successful collection or visibly releases/compensates payments.
9. The integration evidence explains how APIMatic informed the implemented PayPal integration.

Winning is an objective, not an engineering guarantee. Prioritize a coherent, working product over the number of visible sponsor logos.

## Contest Constraints

The official deadline is 12 November 2026 at 12:00 p.m. Pacific Time, equivalent to 20:00 GMT. Set an internal submission target of 18:00 GMT to preserve a buffer. [Official rules](https://paypalaihackathon.devpost.com/rules)

Judging runs from 1–15 December 2026. Keep the submitted build, required access, and dependencies available through the end of judging. [Official rules](https://paypalaihackathon.devpost.com/rules)

The submission requires a functioning project, a public open-source repository, documentation, and a publicly visible YouTube demonstration under three minutes. A hosted URL is useful, although complete local setup instructions can also satisfy functional access requirements. [Submission requirements](https://paypalaihackathon.devpost.com/)

A project can receive at most one sponsor prize, alongside an eligible grand prize or honorable mention. Using all sponsors broadens eligibility; it does not multiply the number of sponsor prizes available to the same project. [Prize rules](https://paypalaihackathon.devpost.com/rules)

### Submission Strategy

Treat PayPal and meaningful AI as the product foundation.

Make AG Studio the strongest sponsor-specific demonstration because analytics, custom widgets, and agent tools fit the central decision problem.

Use Bryntum and Render for real operational behavior.

Use Channel3 to affect the cost calculation, not merely to display shopping cards.

Use APIMatic during implementation and preserve evidence of its actual contribution.

Do not repeat an earlier claim that AG Studio custom widgets are a universal eligibility requirement. The rules list use of AG Grid tools; custom widgets and agent tools are this project’s differentiation strategy, not a substitute for checking the current sponsor guidance.

## Scope Boundaries

### Required MVP

- One merchant account.
- One currency: GBP.
- One seat per booking.
- One workshop category for the main demonstration.
- Short booking campaigns.
- Guest sessions without full customer registration.
- Separate merchant authentication.
- PayPal Sandbox authorization, capture, void, refund, and reconciliation.
- Channel3-backed material selection.
- Deterministic break-even calculation.
- AG Studio dashboard.
- One custom Tipping Meter widget.
- One bounded Rescue Analyst.
- One Bryntum Gantt view.
- Render-hosted application and database.
- At least one genuine Render Workflow.
- Verified webhook processing.
- Audit and integration evidence.

### Optional Extensions

Implement only after the complete MVP passes:

- Alternative material-kit comparison.
- Multiple workshop templates.
- Additional AG Studio widgets.
- Email delivery through a separately configured provider.
- A non-executing preview of merging compatible workshops.
- Additional host roles.

### Explicit Exclusions

- Real-money payments.
- Multi-merchant onboarding.
- Marketplace payouts.
- Platform commissions.
- Subscriptions.
- Automated supplier purchases.
- Autonomous ticket-price changes.
- Moving guests to another date without consent.
- Capturing a higher amount than originally approved.
- Long-running authorization campaigns.
- Full accounting or tax calculation.
- Payment-invoice fallback.
- Arbitrary SQL execution by an LLM.
- A custom general-purpose agent framework.
- A new RAG/vector database subsystem.

Do not add invoices as an automatic fallback for failed captures. A new payment request changes the guest experience and must not be treated as permission to charge.

## Critical Payment Corrections

### Authorization Lifetime

PayPal documents an initial three-day honor period and a longer authorization validity window, with reauthorization rules. Do not assume funds are guaranteed for the whole validity window. [PayPal reauthorization reference](https://developer.paypal.com/api/payments/v2/authorizations-reauthorize)

For the MVP:

- Limit booking campaigns to at most 48 hours.
- Require every accepted authorization to remain within its configured capture window through settlement.
- Reserve a substantial operational buffer before the honor period ends.
- Store provider creation and expiration timestamps.
- Reject unsupported long campaigns.
- Cancel safely when an authorization is stale or cannot be reconciled.
- Defer reauthorization to a later version.

The 48-hour limit is an application policy, not a PayPal product guarantee.

Do not promise a specific date when a temporary hold will disappear from a guest’s bank or card statement.

### Group Collection

Separate guests have separate payment resources.

A successful capture request for one guest does not make the remaining captures succeed. PayPal exposes capture resources and statuses individually. [Capture reference](https://developer.paypal.com/api/payments/v2/authorizations-capture/)

Implement group settlement as a saga:

1. Freeze the accepted booking cohort.
2. Attempt each required capture.
3. Wait for definitive outcomes.
4. Confirm the workshop only when every required capture completes and the financial checks pass.
5. If settlement fails, refund completed captures and release remaining authorizations.
6. Reconcile unresolved operations until their outcomes are known.

Compensation is not instantaneous rollback. Display this honestly.

### SDK Choice

Use a small server-side PayPal adapter backed by documented REST endpoints or a verified server SDK.

Do not adopt an SDK solely because it appears in a previous recommendation.

Do not repeat an unverified claim that a particular PayPal toolkit necessarily causes duplicate charges.

The required property is explicit, operation-scoped idempotency, backed by tests and durable application records.

## Sponsor Integration Map

| Integration | Product responsibility | Evidence |
|---|---|---|
| PayPal Sandbox | Guest payment authorization and settlement | Actual provider references, verified states, sandbox recording |
| AG Studio | Financial command center and Rescue Analyst | Editable dashboard, custom widget, agent tool trace |
| APIMatic | Authoritative API context during implementation | Setup record, sanitized usage evidence, reviewed contract findings |
| Bryntum | Workshop readiness and operational dependency timeline | Real Gantt component driven by application data |
| Channel3 | Material discovery and priced kit inputs | Actual API calls, selected offers, price provenance |
| Render | Hosting and background orchestration | Hosted application, database, genuine workflow runs |

Channel3’s sponsor guidance requires meaningful API or MCP use; merely mentioning the product is insufficient. [Channel3 sponsor guidance](https://paypalaihackathon.devpost.com/details/channel3)

Render’s sponsor guidance describes deploying on Render and using Render Workflows. Do not claim the workflow integration is complete if only the web application is hosted there. [Render sponsor guidance](https://paypalaihackathon.devpost.com/details/render)

APIMatic’s sponsor integration is a development-time Context Plugin for PayPal. It does not need to become a fictitious runtime service in the product architecture. [APIMatic sponsor guidance](https://paypalaihackathon.devpost.com/details/apimatic)

## Technology Decisions

Use a new repository named `tipping-point`.

Recommended stack:

| Layer | Decision |
|---|---|
| Frontend | React, TypeScript, Vite |
| Styling | Tailwind CSS plus a small application component library |
| Backend | FastAPI |
| Validation | Pydantic |
| Persistence | PostgreSQL |
| ORM and migrations | SQLAlchemy and Alembic |
| HTTP integrations | A shared, bounded HTTP client |
| Analytics | AG Studio React |
| Timeline | Bryntum Gantt |
| Agent | One model provider with structured tool calling |
| Background work | Render Workflows |
| Deadline dispatch | Render Cron Job plus database-backed outbox |
| Backend tests | pytest |
| Browser tests | Playwright |
| Deployment | Multi-stage Docker build, Render web service, Render Postgres |

These are project decisions, not claims that this is the only viable stack.

### Why This Stack

React/Vite avoids introducing server rendering into browser-heavy sponsor components.

FastAPI preserves a Python backend workflow.

A single same-origin deployed application simplifies guest cookies, merchant sessions, and CSRF protection.

Render Workflows remains a separate execution environment, but shares the same domain-service package.

Do not introduce Next.js alongside Vite. If a repository already exists in Next.js, explicitly revise this decision rather than keeping both frameworks.

### Version Policy

Before substantial implementation:

- Install a working combination of React, AG Studio, and Bryntum.
- Check their current compatibility guidance.
- Pin the tested versions.
- Commit lockfiles.
- Record the versions in `docs/integration-versions.md`.

Do not guess the current Render SDK package, task decorator, AG Studio agent configuration, or Bryntum wrapper API.

Official documentation currently shows differences between some AG Studio page versions. Compile the chosen integration against the pinned installed packages.

## System Architecture

```text
Guest browser                 Merchant browser
      |                              |
      +--------- HTTPS --------------+
                     |
          Render web service
          FastAPI + built React
                     |
          +----------+-----------+
          |                      |
     PostgreSQL             External services
          |                 - PayPal Sandbox
          |                 - Channel3
          |                 - Model provider
          |
     Outbox + due work
          |
     Cron dispatcher
          |
     Render Workflows
          |
     Shared domain services
          |
     PayPal operations + reconciliation
```

### Deployment Topology

Build the React application into static assets.

Serve those assets and the API under one public origin.

Route:

- `/api/*` to FastAPI endpoints.
- `/assets/*` to built static assets.
- Other frontend routes to the application entry point.
- `/health/live` and `/health/ready` to dedicated health handlers.

Do not let the frontend catch-all swallow API or webhook routes.

### Service Boundaries

| Module | Responsibility |
|---|---|
| Session service | Guest and merchant identity |
| Workshop service | Drafts, publishing, immutable campaign terms |
| Kit service | Channel3 results and approved material snapshots |
| Viability service | Deterministic attendance and cost calculations |
| Booking service | Capacity reservations and guest booking ownership |
| Payment service | Durable operation records and provider normalization |
| Settlement service | Deadline decisions and compensation |
| Analytics service | Sanitized merchant datasets |
| Agent service | Bounded analysis and proposals |
| Timeline service | Bryntum task/dependency projection |
| Workflow adapter | Dispatching and observing Render tasks |

The LLM must not own payment state transitions.

## User Journeys

### Host Publishes Workshop

1. Merchant signs in.
2. Merchant enters workshop title, date, capacity, fixed costs, and ticket price.
3. AI proposes a structured material checklist.
4. Channel3 searches return relevant offers.
5. Merchant confirms quantities, pack sizes, price interpretation, and shipping assumptions.
6. Backend calculates the minimum viable attendance.
7. Merchant reviews campaign cutoff and payment terms.
8. Backend freezes a cost and terms snapshot.
9. Merchant publishes the workshop.

Block publishing if the configured costs cannot be covered at maximum capacity.

### Guest Reserves Place

1. Guest opens a published workshop.
2. Server creates or retrieves an opaque guest session.
3. Guest reviews price, campaign cutoff, workshop date, and payment explanation.
4. Backend reserves one capacity slot for a short checkout period.
5. Backend creates a PayPal order with `intent=AUTHORIZE`.
6. Guest approves through PayPal.
7. Backend authorizes the approved order.
8. Backend verifies the authorization and decides whether it can still be admitted.
9. Guest sees either an authorized reservation or a clear failure/release message.

An order approval is not the same as a successful authorization.

### Deadline Is Reached

1. Dispatcher identifies a due campaign.
2. Render Workflow claims the decision.
3. Backend freezes the eligible booking cohort.
4. Backend evaluates the frozen campaign terms.
5. Below threshold: release authorizations.
6. At or above threshold: run settlement.
7. All required captures complete and economics pass: confirm.
8. Any required capture fails or remains unresolved past the settlement deadline: abort and compensate.
9. Dashboard, timeline, and guest status reflect the persisted result.

### Host Requests Rescue Analysis

Example request:

> “Why is this workshop still below its tipping point, and could a cheaper materials kit make it viable?”

The analyst:

1. Reads permitted campaign data.
2. Calls the deterministic viability tool.
3. Optionally searches for alternative material offers.
4. Produces an explicit scenario.
5. Adds or updates an AG Studio visualization.
6. Explains trade-offs and uncertainty.

It does not silently change a published campaign.

## Financial Model

### Monetary Representation

Store all money as integer pence.

Store currency explicitly.

Use decimal-safe conversion when communicating with PayPal.

For the MVP, reject non-GBP campaigns rather than implementing currency conversion.

Never calculate payment amounts using binary floating-point arithmetic.

### Cost Inputs

Each campaign includes:

- Fixed venue and host costs.
- Materials purchased per attendee.
- Materials purchased in packs.
- One-time material purchases.
- Shipping allowance.
- Contingency.
- A configurable conservative payment-fee estimate.
- Optional minimum operating attendance.

Do not assume a merchant’s real PayPal fee schedule.

The estimated fee configuration is an input that must be labeled and reviewed. Replace estimates with actual returned fee information when available.

### Discrete Attendance Calculation

For each candidate attendance `n` from minimum operating attendance to capacity:

```text
gross_revenue(n) = n × ticket_price

estimated_net_revenue(n)
  = gross_revenue(n) - estimated_payment_fees(n)

materials_cost(n)
  = sum over approved kit items:
      packs_required(n) × selected_pack_price

required_budget(n)
  = fixed_costs
  + materials_cost(n)
  + shipping_allowance
  + contingency

minimum_viable_attendance
  = first n where estimated_net_revenue(n) >= required_budget(n)
```

For a pack-based item:

```text
required_units(n)
  = shared_units + units_per_attendee × n

packs_required(n)
  = ceil(required_units(n) / units_per_pack)
```

Use enumeration instead of a simple division formula because pack boundaries create discontinuities.

### Domain Function

```python
def calculate_viability(terms):
    candidates = []

    for attendance in range(
        terms.minimum_operating_attendance,
        terms.capacity + 1,
    ):
        gross = attendance * terms.ticket_price_minor
        fees = estimate_fees_minor(terms, attendance)
        required = calculate_budget_minor(terms, attendance)

        candidates.append({
            "attendance": attendance,
            "gross_minor": gross,
            "estimated_fees_minor": fees,
            "estimated_net_minor": gross - fees,
            "required_budget_minor": required,
            "surplus_minor": gross - fees - required,
        })

    minimum = next(
        (
            row["attendance"]
            for row in candidates
            if row["surplus_minor"] >= 0
        ),
        None,
    )

    return {
        "minimum_viable_attendance": minimum,
        "feasible_at_capacity": minimum is not None,
        "curve": candidates,
    }
```

This function is the authority for the threshold.

The LLM may explain the result but must not invent or override it.

### Snapshot Rules

At publication, freeze:

- Ticket price.
- Currency.
- Capacity.
- Cost lines.
- Selected product offers.
- Pack assumptions.
- Fee-estimation configuration.
- Shipping allowance.
- Contingency.
- Minimum viable attendance.
- Booking cutoff.
- Workshop date.
- Guest-facing payment terms.
- Algorithm version.
- Snapshot hash.

Do not silently refresh prices or change the threshold after guests have authorized payment.

If a published campaign requires materially different terms, cancel it safely and publish a new campaign.

## State Machines

### Campaign State

```text
DRAFT
  -> OPEN
  -> DECIDING
     -> RELEASING
        -> CANCELLED
     -> SETTLING
        -> CONFIRMED
        -> ABORTING
           -> COMPENSATING
              -> CANCELLED
```

Use `REVIEW_REQUIRED` as a separate operational flag for unresolved cases, not as permission to skip compensation.

#### Approved exception: Sandbox operator-test cleanup (2026-11-07)

`CONFIRMED` remains terminal for all ordinary campaign processing. Deadline work, wakeups, guest cancellation and the generic dispatcher never reopen it.

One narrow exception is explicitly approved. It exists only so that a PayPal Sandbox test campaign can be cleaned up:

```text
Campaign: CONFIRMED -> COMPENSATING -> CANCELLED
Booking:  PAID -> REFUND_PENDING -> REFUNDED
```

- Only the guarded operator action may start it (`scripts/process_settlement_work.py --sandbox-test-cleanup`, implemented in `settlement/operator_cleanup.py`). There is no public, guest or merchant endpoint and no general force-cancel option.
- It applies only when the frozen cohort has exactly one booking with exactly one verified, completed GBP 1.00 capture. The operator must supply the exact campaign, booking and capture IDs, the amount (100 minor units), the currency and a reason. The provider environment must be Sandbox.
- It cancels the whole single-booking test campaign. It is **not** an attendee-refund policy and **not** a production cancellation policy.
- The refund reuses the existing durable refund ledger and worker: the logical operation, request ID, payload hash, lease, version fencing and retrieval-only reconciliation.
- The original confirmation, decision, terms, cohort, capture references and audit evidence are preserved. The cleanup intent and reason are added beside them.
- The campaign becomes `CANCELLED` and the booking `REFUNDED` only after a verified, completed full refund.

Keep workshop delivery separate:

```text
NOT_READY -> READY -> DELIVERED
```

A workshop can be financially confirmed without being delivered.

### Booking State

```text
CHECKOUT_RESERVED
  -> AUTHORIZATION_PENDING
  -> AUTHORIZED
     -> CAPTURE_PENDING
        -> PAID
           -> REFUND_PENDING
              -> REFUNDED
     -> VOID_PENDING
        -> VOIDED

CHECKOUT_RESERVED -> CHECKOUT_EXPIRED
AUTHORIZATION_PENDING -> AUTHORIZATION_FAILED
```

Represent ambiguous operations explicitly.

Do not convert a network timeout into `AUTHORIZATION_FAILED` or `CAPTURE_FAILED` without reconciliation.

### Provider State

Store provider status separately from application status.

Examples include authorization, capture, and refund resource statuses.

PayPal’s capture API can return a resource whose status is `PENDING`; an HTTP success response alone is insufficient to mark a booking paid. [Payments schema](https://developer.paypal.com/api/payments/v2/schema.json)

### Invariants

- Confirmed campaigns have completed required captures.
- Authorized bookings are not paid bookings.
- Refunded bookings retain their original capture references.
- Cancelled campaigns must not leave untracked financial operations.
- A campaign’s decision cohort does not grow after freezing.
- Published terms are immutable.
- Public users cannot trigger merchant settlement actions.
- Payment operations cannot be inferred from browser redirects.
- A late provider event cannot silently regress a terminal business state.
- Every external payment operation has an audit trail.

## Database Design

Use UUID primary keys, UTC timestamps, explicit foreign keys, and indexed lookup fields.

### Core Tables

| Table | Essential fields |
|---|---|
| `merchants` | id, login identity, password hash or approved identity reference |
| `guest_sessions` | id, token hash, created_at, expires_at, revoked_at |
| `merchant_sessions` | id, merchant_id, token hash, expires_at |
| `workshops` | id, merchant_id, title, description, starts_at, timezone |
| `campaigns` | id, workshop_id, status, capacity, cutoff_at, terms_version, settlement_deadline |
| `campaign_terms` | campaign_id, snapshot_json, snapshot_hash, algorithm_version |
| `material_offers` | id, provider, product reference, offer reference, source URL, currency, price, fetched_at |
| `kit_items` | campaign_id, offer_id, pack size, shared units, units per attendee, interpretation status |
| `bookings` | id, campaign_id, guest_session_id, state, price snapshot, slot expiry |
| `payment_resources` | booking_id, provider type/id, provider status, amount, creation/expiry timestamps |
| `payment_operations` | id, booking_id, kind, idempotency key, request hash, state, lease/version |
| `decision_cohorts` | campaign_id, terms hash, frozen_at, outcome |
| `decision_cohort_members` | cohort_id, booking_id |
| `webhook_inbox` | provider event id, event type, verification status, processing state |
| `outbox_events` | event type, aggregate id, payload, availability time, dispatch state |
| `workflow_runs` | task purpose, provider run id, application correlation id, state |
| `settlement_runs` | campaign_id, cohort_id, state, started_at, completed_at |
| `audit_events` | actor, action, resource, correlation id, sanitized details |
| `dashboard_states` | merchant_id, schema version, report JSON |
| `agent_runs` | actor, tool calls, result summary, model configuration reference |

### Constraints

- Unique provider resource IDs.
- Unique provider webhook event IDs.
- Unique operation idempotency keys.
- Unique campaign decision cohort.
- Unique booking membership within a cohort.
- One active settlement run per cohort.
- Non-negative amounts.
- Positive capacity and ticket price.
- Booking cutoff earlier than workshop start.
- Valid state transitions enforced by domain services.
- Foreign keys that prevent orphaned payment evidence.

Do not use destructive cascade deletion for payment records.

### Capacity Policy

Before creating a checkout:

1. Lock the campaign row.
2. Verify the campaign is open and before its cutoff.
3. Count admitted bookings and unexpired slot reservations.
4. Reject if capacity is exhausted.
5. Create a short-lived slot reservation.
6. Commit.

Perform provider calls outside this transaction.

If authorization completes after the reservation or campaign has become inadmissible, persist the provider resource and enqueue its release.

A late authorization must never become an invisible hold.

## API Specification

### Session Endpoints

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/guest/session` | Create or reuse guest session |
| POST | `/api/merchant/login` | Authenticate merchant |
| POST | `/api/merchant/logout` | Revoke merchant session |
| GET | `/api/me` | Return current role and permitted capabilities |

### Public Booking Endpoints

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/workshops` | List published workshops |
| GET | `/api/workshops/{id}` | Public workshop and campaign details |
| POST | `/api/campaigns/{id}/bookings` | Reserve a capacity slot |
| POST | `/api/bookings/{id}/paypal/order` | Create authorization-intent order |
| POST | `/api/bookings/{id}/paypal/authorize` | Authorize approved order |
| GET | `/api/bookings/{id}` | Owner-only booking status |
| POST | `/api/bookings/{id}/cancel` | Request cancellation under campaign policy |

### Merchant Endpoints

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/merchant/workshops` | Create draft |
| PATCH | `/api/merchant/workshops/{id}` | Edit draft |
| POST | `/api/merchant/material-search` | Search Channel3 |
| POST | `/api/merchant/campaigns/{id}/kit` | Save reviewed kit |
| POST | `/api/merchant/campaigns/{id}/preview` | Calculate viability |
| POST | `/api/merchant/campaigns/{id}/publish` | Freeze terms and publish |
| GET | `/api/merchant/campaigns/{id}/timeline` | Bryntum projection |
| GET | `/api/merchant/analytics` | Sanitized AG Studio datasets |
| GET/PUT | `/api/merchant/dashboard` | Persist validated report state |
| POST | `/api/merchant/agent/runs` | Run bounded Rescue Analyst |
| GET | `/api/merchant/operations` | Payment and workflow status |

### Provider Endpoint

```text
POST /api/webhooks/paypal
```

No public endpoint may accept arbitrary payment-resource IDs and operate on them without resolving and authorizing the owning booking.

### Common Requirements

- Explicit request and response schemas.
- Consistent application error codes.
- Request correlation IDs.
- Strict payload size limits.
- Object ownership checks.
- CSRF protection for cookie-authenticated mutations.
- Rate limits on login, checkout, material search, and agent requests.
- Server-side amount calculation.
- No provider secrets in responses.

## PayPal Implementation

### Adapter Contract

```python
class PayPalGateway:
    async def create_authorization_order(self, booking, operation):
        ...

    async def authorize_order(self, provider_order_id, operation):
        ...

    async def get_order(self, provider_order_id):
        ...

    async def get_authorization(self, authorization_id):
        ...

    async def capture_authorization(self, authorization_id, operation):
        ...

    async def void_authorization(self, authorization_id, operation):
        ...

    async def get_capture(self, capture_id):
        ...

    async def refund_capture(self, capture_id, operation):
        ...

    async def get_refund(self, refund_id):
        ...

    async def verify_webhook(self, headers, event):
        ...
```

These are application-owned method names.

Verify the underlying provider contracts through current documentation and APIMatic before implementation.

### Required Provider Operations

```text
POST /v2/checkout/orders
POST /v2/checkout/orders/{order_id}/authorize

GET  /v2/payments/authorizations/{authorization_id}
POST /v2/payments/authorizations/{authorization_id}/capture
POST /v2/payments/authorizations/{authorization_id}/void

GET  /v2/payments/captures/{capture_id}
POST /v2/payments/captures/{capture_id}/refund

GET  /v2/payments/refunds/{refund_id}

POST /v1/notifications/verify-webhook-signature
```

Confirm Orders API details during the initial integration spike. The Payments API documents capture, void, refund, and resource inspection operations. [Payments schema](https://developer.paypal.com/api/payments/v2/schema.json)

### Checkout Validation

Before admitting an authorization:

- Retrieve the provider resource where necessary.
- Verify the order belongs to the booking.
- Verify merchant/payee context.
- Verify amount and currency.
- Verify the authorization is usable.
- Verify capacity reservation ownership.
- Verify campaign status and cutoff.
- Verify the authorization’s timing fits the settlement policy.

Store the provider ID even when the authorization must be rejected and released.

### Idempotency

Create a durable operation record before an external mutation.

Each logical operation gets a unique UUID idempotency key.

Examples:

```text
create-order for booking A -> operation UUID 1
authorize order A         -> operation UUID 2
capture authorization A   -> operation UUID 3
refund capture A          -> operation UUID 4
```

Retries of the same operation reuse its key and immutable payload.

Different operations must not reuse a client-wide key.

Use `PayPal-Request-Id` where supported by the relevant endpoint. The capture endpoint documents this header for idempotency. [Capture reference](https://developer.paypal.com/api/payments/v2/authorizations-capture/)

Do not assume provider idempotency keys are retained forever.

### Operation Lifecycle

```text
PREPARED
  -> IN_FLIGHT
     -> SUCCEEDED
     -> DEFINITIVELY_FAILED
     -> UNKNOWN
     -> PROVIDER_PENDING
```

Worker algorithm:

1. Claim the operation in a short database transaction.
2. Commit the claim.
3. Make the provider request outside the transaction.
4. Persist the returned resource using a version-checked update.
5. Reconcile ambiguous results rather than creating a replacement operation.

A lease protects application ownership, not the external provider from every stale request. Use stable provider idempotency keys and reconciliation as well.

### Settlement Policy

Use the strict policy for the MVP:

> Every booking admitted to the frozen cohort must complete payment before the workshop is confirmed.

If one required capture definitively fails:

- Stop initiating new captures.
- Mark the settlement as aborting.
- Resolve any in-flight or ambiguous captures.
- Refund completed captures.
- Void still-open authorizations.
- Keep unresolved compensation visible.
- Mark the campaign cancelled only when the required financial cleanup is accounted for.

Do not declare cancellation complete while an unknown capture could still succeed unnoticed.

### Post-Capture Economics

Before confirmation:

- Verify completed captured amounts.
- Use actual returned fee information where available.
- Compare net funds against the approved cost policy.
- If actual economics fail the policy, compensate instead of confirming an unviable workshop.

If actual fee information is unavailable, show the limitation and use the approved conservative policy. Do not label estimated margin as audited profit.

### Webhooks

PayPal provides a signature-verification endpoint that returns a verification result. Require successful verification before trusting an event. [Webhook verification](https://developer.paypal.com/api/webhooks/v1/verify-webhook-signature-post/)

Processing:

1. Receive bounded headers and event body.
2. Verify with the configured sandbox webhook ID.
3. Persist the verified event in the inbox.
4. Deduplicate by provider event ID.
5. Return success after durable acceptance.
6. Process asynchronously.
7. Retrieve current provider state for ambiguous or conflicting updates.
8. Apply domain transitions idempotently.

If verification is unavailable, do not apply the event. Return a retryable error or quarantine it without trusting it.

Choose the final event subscriptions from the current provider event catalog and actual sandbox flow. Do not invent event names.

## Channel3 Integration

### Search Behavior

Use actual Channel3 calls for material discovery.

Explicitly request the target market:

```text
country = GB
language = en
currency = GBP
```

Channel3 documents GB/GBP locale support and notes that coverage outside the United States is still growing. Validate useful results before choosing the demonstration workshop. [Locale documentation](https://channel3.mintlify.dev/docs/guides/locale.md)

### Search Pipeline

1. AI extracts a structured material need.
2. Backend validates the search specification.
3. Backend calls Channel3.
4. Backend normalizes returned offers.
5. Merchant reviews material suitability and pack interpretation.
6. Merchant selects an offer.
7. Backend stores the selected price snapshot and provenance.

Store:

- Provider product and offer references when available.
- Product title.
- Merchant.
- Product URL or buy link.
- Image URL.
- Currency.
- Reported price.
- Availability.
- Fetch timestamp.
- Pack-size interpretation.
- Human-review status.
- Shipping allowance source.

Use actual response fields from the installed SDK/API contract. Do not invent a normalized provider response shape.

### Important Limitations

A product search result is not:

- A supplier stock reservation.
- A guaranteed delivered price.
- Proof of pack quantity.
- A purchase order.
- A shipping-time guarantee.

The application must distinguish product price from delivered kit cost.

If shipping is unavailable, require a merchant-entered allowance and label it accordingly.

If a pack quantity cannot be established, block automatic costing until reviewed.

### Failure Handling

- No suitable result: keep the draft incomplete.
- API unavailable: show the failure and previously fetched offers as stale.
- Currency mismatch: reject the offer for this MVP.
- Missing price: do not estimate one using the LLM.
- Missing pack size: require manual interpretation.
- Material availability changes: flag review; do not silently rewrite published terms.

Cached real responses may support review, but must show their original retrieval time.

Do not present fixtures or cached responses as fresh calls.

## AG Studio Implementation

AG Studio is an embedded analytics component with a React package and support for application-defined widgets and agent integrations. [Quick start](https://www.ag-grid.com/studio/react/quick-start/) [Custom widgets](https://www.ag-grid.com/studio/react/custom-widgets/) [Agent overview](https://www.ag-grid.com/studio/react/ai-agents/)

### Dashboard Pages

Create two pages:

| Page | Contents |
|---|---|
| Campaign Health | Tipping Meter, attendance, estimated surplus, cutoff, cost curve |
| Settlement Operations | Authorized, completed, pending, released, refunded, unresolved |

Use domain-derived datasets.

Do not expose raw provider JSON or guest financial details to the browser unnecessarily.

### Data Sources

Provide sanitized arrays such as:

```text
campaign_health
campaign_cost_curve
booking_status_counts
settlement_operations
material_cost_breakdown
```

Avoid joining full guest identities into campaign-level charts.

### Tipping Meter Widget

Implement a genuine registered AG Studio custom widget.

Display:

- Authorized attendees.
- Minimum viable attendees.
- Capacity.
- Places still required.
- Authorized amount.
- Collected amount.
- Current estimated surplus.
- Time to cutoff.
- Current financial state.

Keep “authorized” and “collected” visually distinct.

Suggested states:

- Below threshold.
- Threshold reached, awaiting cutoff.
- Collecting.
- Confirmed.
- Releasing.
- Compensating.
- Cancelled.
- Review required.

Provide loading, empty, stale, and error states.

### Registration Requirements

Use the installed version’s documented widget interface.

The documentation describes custom registration through `createWidgets`, and requires `formatShape` and `ai` metadata for AI-compatible custom widgets. [Custom widget documentation](https://www.ag-grid.com/studio/react/custom-widgets/)

Acceptance:

- Widget appears in Studio’s widget menu.
- Widget renders from permitted data sources.
- Report state can be saved and reloaded.
- Analyst can add/configure it through supported Studio capabilities.
- Invalid configuration is rejected.
- No provider secrets are embedded in widget configuration.

### Rescue Analyst

Implement a bounded analyst using the supported Studio Agent Framework integration.

Required capabilities:

- Explain the current tipping point.
- Compare attendance scenarios.
- Explain material-cost drivers.
- Add a supported visualization.
- Propose a reviewed alternative kit.

Application tools:

```text
get_campaign_health(campaign_id)
simulate_attendance(campaign_id, attendance)
search_material_alternatives(campaign_id, kit_item_id)
simulate_kit_replacement(campaign_id, proposal_id)
```

Studio visualization tools should use the actual installed API.

Do not guess a tool signature from an old example.

### Agent Boundaries

The agent cannot:

- Capture, void, or refund payments.
- Change published terms.
- Increase prices.
- Publish a workshop.
- Execute SQL.
- Access arbitrary URLs.
- Read secrets.
- Transfer bookings.
- Claim a hypothetical scenario has already been applied.

Set bounded tool-call and execution limits.

Persist sanitized tool traces for the demonstration.

### Licensing

AG Studio is commercial, with a documented 45-day trial option. Its license covers built-in grid/chart widgets, but not every standalone AG Grid Enterprise or AG Charts Enterprise usage outside Studio. [License guidance](https://www.ag-grid.com/studio/react/enterprise-licence/)

Request appropriate trial access and verify that its dates cover judging.

Do not strip watermarks or redistribute proprietary package source without authorization.

## Bryntum Implementation

Choose Bryntum Gantt, not Gantt plus Scheduler plus Calendar.

The sponsor describes Gantt as a dependency-aware task timeline. [Bryntum sponsor guidance](https://paypalaihackathon.devpost.com/details/bryntum)

### Timeline Structure

One parent task per workshop.

Child tasks:

```text
Booking campaign
    -> Deadline decision
    -> Payment settlement
    -> Materials purchase readiness
    -> Preparation
    -> Workshop delivery
```

Dependencies should express real application rules.

Examples:

- Preparation cannot be marked ready before payment settlement completes.
- A cancelled campaign marks dependent work cancelled or blocked.
- A settlement under review prevents purchase readiness.
- Confirmed payment updates the readiness milestone.

### Authority Boundary

Bryntum visualizes and edits permitted operational plans.

It is not the source of truth for payment state.

For the MVP:

- Published financial deadlines are read-only.
- Payment milestones are read-only.
- Draft preparation dates may be editable.
- Every permitted edit is validated by the backend.
- UI state reverts when the backend rejects an edit.

Do not let drag-and-drop extend a payment hold or bypass a booking cutoff.

### Acceptance

- Actual Bryntum component loads in the production build.
- Tasks come from backend projections.
- Dependencies are visible.
- Campaign outcomes update the relevant task states.
- Invalid edits are rejected.
- Trial/license terms permit the submitted demonstration.
- Proprietary dependencies are not mistakenly relicensed by the repository.

## APIMatic Implementation

Use APIMatic’s PayPal Context Plugin in the coding environment before implementing or reviewing the PayPal adapter. [Sponsor guidance](https://paypalaihackathon.devpost.com/details/apimatic)

### Required Evidence

Create `docs/apimatic-integration.md` containing:

- Actual coding environment.
- Official setup source.
- Installed plugin/package version where applicable.
- Configuration scope.
- Date used.
- Sanitized examples of context requests.
- Contract findings applied to the adapter.
- Code and test references.

Suggested review topics:

- Authorization-intent order creation.
- Authorizing an approved order.
- Currency and amount formatting.
- Capture payload.
- Idempotency headers.
- Void behavior.
- Refund status handling.
- Webhook verification.

### Guardrails

- Do not guess installation commands.
- Do not assume another IDE’s MCP configuration path.
- Do not provide PayPal secrets to the plugin.
- Do not replace working adapter code merely to generate more sponsor evidence.
- Do not claim plugin use based only on adding a logo or dependency name.

APIMatic’s meaningful role is improving the implementation’s API correctness.

## Render Implementation

### Required Resources

Provision only after approval:

- One application web service.
- One PostgreSQL database.
- One Workflow service.
- One scheduled dispatcher.
- Environment groups or equivalent secret configuration.

Use paid or otherwise non-expiring resources appropriate to the judging window.

Render’s free PostgreSQL instances expire after 30 days. A database created in early November would therefore be unsuitable for uninterrupted mid-December judging without an upgrade. [Render policy](https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90)

### Workflow Tasks

Implement at least:

```text
evaluate_campaign_deadline(campaign_id)
settle_campaign(settlement_run_id)
compensate_campaign(settlement_run_id)
reconcile_payment_operation(operation_id)
```

An additional kit-analysis task is optional.

Render provides official workflow examples with task orchestration and API-to-workflow separation. Use the current examples to establish the installed SDK contract. [Official examples](https://github.com/render-examples/render-workflows-examples-python)

### Scheduling Approach

Do not assume a durable sleep-until API exists.

Use a scheduled dispatcher:

1. Query due campaigns and operations.
2. Insert or claim durable outbox work.
3. Dispatch a Render Workflow.
4. Store the provider run reference.
5. Retry dispatch safely when its result is unknown.
6. Let domain claims make duplicate workflow runs harmless.

A one-minute dispatcher means decisions are not guaranteed to execute at the exact second of the cutoff.

State the difference between booking cutoff time and background processing time.

### Retry Rules

Safe retries must be implemented at the application level.

- Reuse operation-scoped provider idempotency keys.
- Reconcile timeouts.
- Respect provider rate limits.
- Bound exponential backoff.
- Do not retry definitive validation failures indefinitely.
- Do not hold a database transaction open across provider requests.
- Preserve unresolved work across deployments.

### Recovery

Test:

- Duplicate workflow delivery.
- Worker restart before provider call.
- Worker restart after provider success but before database persistence.
- Expired lease.
- Dispatcher crash after remote dispatch.
- Provider pending state.
- Compensation interrupted halfway through.

Workflow success means the task executed correctly. It does not automatically mean the workshop became confirmed.

## Authentication And Security

### Guest Sessions

Use server-issued opaque guest sessions.

- Generate a cryptographically random token.
- Store only its hash.
- Set an HttpOnly cookie.
- Use Secure cookies in hosted environments.
- Use a deliberate SameSite policy.
- Apply expiration and revocation.
- Enforce booking ownership server-side.

The browser must not select another guest’s identity through a header or request field.

If an identity header exists for local tests, hosted startup must reject enabling it.

### Merchant Authentication

Use a separately authenticated merchant account.

For the hackathon, a small server-side username/password flow is acceptable if it uses:

- An established password-hashing implementation.
- No public merchant registration.
- Rate-limited login.
- Opaque server-side sessions.
- Session rotation on login.
- Explicit role enforcement.

Merchant identity must not be minted from a user-supplied merchant ID.

Do not expose unrestricted merchant write credentials in a public README.

### Judge Access

Provide:

- Public guest browsing.
- A read-only merchant overview.
- Clear instructions for obtaining or using appropriately scoped judging access.
- Fresh PayPal Sandbox checkout where needed.
- A sandbox-only demonstration workspace for destructive test actions.

Hosted judging access must not depend on a single pre-existing authorization that will expire before December.

### CSRF

For state-changing cookie-authenticated requests:

- Validate origin.
- Require a CSRF token.
- Restrict content types.
- Use secure cookie settings.
- Do not assume SameSite alone is the entire defense.

The PayPal webhook endpoint is exempt from browser CSRF handling but requires provider verification.

### Agent Security

Treat product descriptions and retrieved content as untrusted input.

Never let product text override system instructions.

Do not place secrets, cookies, or full payment payloads into model context.

Validate tool arguments and tool results.

Use backend permission checks even when the request originated from an authenticated agent UI.

## Interface Plan

### Guest Screens

- Workshop listing.
- Workshop detail.
- Payment-terms review.
- PayPal approval handoff.
- Reservation status.
- Collection/release/refund status.

### Merchant Screens

- Campaign overview.
- Workshop draft editor.
- Material-kit builder.
- Publish review.
- AG Studio financial command center.
- Bryntum readiness timeline.
- Operations audit.

### Visual Direction

Use a focused workshop-operations identity.

- Warm neutral background.
- Dark readable typography.
- One accent color for progress.
- Separate semantic colors for authorized, collected, pending, and failed.
- Clear numbers with plain-language explanations.
- Minimal decorative charts.
- Visible sandbox labeling.

Do not make the interface resemble a generic cryptocurrency dashboard.

### Payment Copy

Use:

- “Payment authorized.”
- “Awaiting booking deadline.”
- “Collecting authorized payments.”
- “Workshop confirmed.”
- “Authorization release requested.”
- “Refund processing.”
- “Payment status requires review.”

Avoid:

- “Money safely in escrow.”
- “Guaranteed to charge everyone together.”
- “Instant refund.”
- “All funds secured for 29 days.”
- “AI approved your payment.”

## Repository Layout

```text
tipping-point/
├── AGENTS.md
├── README.md
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── tip-implementation-plan.md
├── .env.example
├── .gitignore
├── .venv/
├── pyproject.toml
├── render.yaml
├── Dockerfile
├── apps/
│   ├── web/
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── app/
│   │   │   ├── features/
│   │   │   │   ├── workshops/
│   │   │   │   ├── bookings/
│   │   │   │   ├── materials/
│   │   │   │   ├── studio/
│   │   │   │   ├── timeline/
│   │   │   │   └── operations/
│   │   │   └── components/
│   │   └── tests/
│   └── api/
│       ├── main.py
│       ├── routes/
│       └── dependencies/
├── packages/
│   └── tipping_point/
│       ├── config/
│       ├── db/
│       ├── domain/
│       ├── services/
│       ├── integrations/
│       │   ├── paypal/
│       │   ├── channel3/
│       │   ├── render/
│       │   └── model/
│       └── security/
├── workflows/
├── jobs/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── concurrency/
│   └── sandbox/
└── docs/
    ├── architecture.md
    ├── apimatic-integration.md
    ├── integration-versions.md
    ├── sponsor-evidence.md
    ├── payment-state-machines.md
    ├── deployment.md
    ├── judge-guide.md
    └── demo-script.md
```

Keep `.venv/` ignored.

Use the repository-root `.venv` for local Python installation and execution. Do not install into system Python or modify the Perfume Atelier environment.

## Configuration Contract

Document application-owned variables such as:

```dotenv
APP_ENV=development
APP_PUBLIC_URL=http://localhost:8000

DATABASE_URL=
TEST_DATABASE_URL=

PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=

CHANNEL3_API_KEY=

MODEL_PROVIDER=
MODEL_NAME=
MODEL_API_KEY=

RENDER_WORKFLOW_IDENTIFIER=
RENDER_DISPATCH_CREDENTIAL=

CAMPAIGN_MAX_DURATION_HOURS=48
SETTLEMENT_TIMEOUT_MINUTES=10
AUTHORIZATION_SAFETY_BUFFER_HOURS=6

ENABLE_PAYMENT_SIMULATOR=false
ENABLE_LOCAL_IDENTITY_HEADERS=false

MERCHANT_LOGIN=
MERCHANT_PASSWORD_HASH=
```

These are application configuration names, not promises about vendor SDK environment-variable names.

Map them to the verified installed integrations.

### Startup Validation

Hosted application startup must fail when:

- PayPal mode is not sandbox.
- Required credentials are missing.
- Simulator mode is enabled.
- Local identity-header mode is enabled.
- Public URL is insecure.
- Merchant authentication is incomplete.
- Database configuration points to an unsupported backend.
- Required license configuration is invalid or missing under the chosen deployment arrangement.

Never commit actual `.env` files or vendor registry tokens.

## Implementation Sequence

Estimated effort is a planning budget, not a delivery guarantee.

Build vertical slices and stop at evidence-based gates.

| Phase | Focus | Suggested budget |
|---|---|---|
| Foundation | Integration spikes, sessions, schema | 6–8 hours |
| Booking | Draft, viability, actual authorization | 8–10 hours |
| Settlement | Workflow, capture, release, compensation | 10–12 hours |
| Sponsor UI | Channel3, Studio, Bryntum | 10–12 hours |
| Hardening | Concurrency, security, deployment | 6–8 hours |
| Submission | Recording, documentation, access checks | 4–6 hours |

Do not spend the first two days building a polished dashboard without a working authorization flow.

### Foundation Gate

Deliver:

- Fresh repository.
- Existing or explicitly created repository `.venv`.
- PostgreSQL migration.
- Application skeleton.
- Guest session.
- Merchant authentication.
- Minimal AG Studio render.
- Minimal Bryntum render.
- Actual Channel3 search.
- Actual Render Workflow test task.
- APIMatic setup evidence.

Acceptance:

- All six integrations are technically reachable.
- License and package access are resolved.
- No secrets are committed.
- Hosted simulator cannot be enabled.
- PostgreSQL is the integration-test database.

If a sponsor integration is blocked, report the exact blocker immediately.

### Booking Gate

Deliver:

- Draft workshop editor.
- Material-offer selection.
- Deterministic viability function.
- Published immutable terms.
- Capacity reservation.
- PayPal order creation and authorization.
- Owner-only booking status.

Acceptance:

- Real sandbox authorization observed.
- Provider amount and currency verified.
- Approval without authorization does not count.
- Over-capacity reservation is rejected.
- Late authorization is tracked and released.

### Settlement Gate

Deliver:

- Due-campaign dispatch.
- Frozen booking cohort.
- Threshold decision.
- Capture path.
- Below-threshold release path.
- Refund compensation.
- Reconciliation.
- Webhook inbox.

Acceptance:

- One real sandbox capture.
- One real sandbox authorization void.
- One real sandbox refund.
- Duplicate task delivery does not create duplicate logical operations.
- Ambiguous provider outcomes remain visible.
- Campaign is not confirmed on pending captures.

### Sponsor Experience Gate

Deliver:

- Channel3-backed kit costing.
- Tipping Meter custom widget.
- Rescue Analyst with actual tools.
- Dashboard persistence.
- Bryntum dependency timeline.
- Workflow run visibility.

Acceptance:

- Changing a draft kit changes calculated economics.
- Analyst calls deterministic tools.
- Timeline updates after settlement.
- APIMatic evidence references implemented code.
- No sponsor integration is represented by a static mockup.

### Release Gate

Deliver:

- Deployed same-origin application.
- Paid/non-expiring database arrangement.
- Stable workflow configuration.
- Judge access.
- Public repository.
- License and dependency notices.
- Demo video.
- Submission text.

Acceptance:

- Fresh browser can complete guest flow.
- Merchant routes remain protected.
- Fresh checkout works without expired pre-seeded authorizations.
- Build survives restart.
- Documentation matches the deployed commit.

## Six-Day Schedule

### Friday, 6 November

- Resolve package and trial access.
- Run all integration spikes.
- Establish PostgreSQL, sessions, and configuration.
- Create the first real sandbox authorization.
- Record blockers before building presentation layers.

### Saturday, 7 November

- Finish workshop drafting.
- Implement Channel3 offer selection.
- Implement viability calculation.
- Publish immutable campaign terms.
- Complete guest authorization flow.

### Sunday, 8 November

- Implement settlement state machine.
- Connect Render Workflows.
- Implement release, capture, refund, and reconciliation.
- Add deterministic failure tests.

### Monday, 9 November

- Build AG Studio command center.
- Register Tipping Meter.
- Implement Rescue Analyst.
- Build Bryntum timeline.
- Capture sponsor evidence.

### Tuesday, 10 November

- Deploy the full application.
- Run concurrency and security tests.
- Verify webhooks and worker recovery.
- Create judge guide.
- Draft the demonstration script.

### Wednesday, 11 November

- Freeze feature scope.
- Record the video.
- Verify licenses and dependency availability through judging.
- Prepare Devpost materials.
- Test from a clean browser and clean checkout.

### Thursday, 12 November

- Fix only blocking defects.
- Verify public repository and video access.
- Submit before the internal 18:00 GMT target.
- Confirm submission receipt before the official 20:00 GMT deadline.

## Testing Matrix

### Financial Tests

- Integer money arithmetic.
- Exact break-even boundary.
- Capacity below required attendance.
- Zero contribution margin.
- Pack-size discontinuities.
- Shipping allowance included.
- Conservative fee rounding.
- Currency mismatch rejected.
- Published snapshot immutability.
- Actual settlement net below approved budget.

### Booking Tests

- Guest cannot access another guest’s booking.
- Caller-supplied identity headers are ignored or rejected.
- Reservation expiry restores capacity.
- Two requests for the last place admit only one.
- Duplicate PayPal order creation is idempotent.
- Authorization after cutoff is not admitted.
- Late authorization is queued for release.
- Invalid or mismatched provider amount is rejected.

### Settlement Tests

- Below threshold releases all admitted authorizations.
- Threshold reached starts settlement.
- Pending capture does not confirm.
- One failed capture triggers compensation.
- Unknown capture outcome is reconciled.
- Refund pending remains pending.
- Restart after capture does not cause a new logical capture.
- Duplicate workflow dispatch is harmless.
- No new capture is intentionally initiated after settlement enters aborting.
- A late capture success during abort is refunded.
- Incomplete compensation remains visible.

### Webhook Tests

- Invalid signature rejected.
- Verification outage does not apply event.
- Duplicate event handled once.
- Unknown resource quarantined.
- Out-of-order update cannot regress paid/refunded state.
- Event amount and resource ownership verified.
- Durable inbox survives worker restart.

### Agent Tests

- Tool input schemas enforced.
- Deterministic calculation used.
- Product prompt injection ignored.
- No payment tool exposed.
- Unauthorized campaign access rejected.
- Scenario labeled hypothetical.
- Published campaign cannot be edited by agent.
- Tool limit and timeout enforced.
- Model failure preserves normal product usage.

### Sponsor UI Tests

- AG Studio production build loads.
- Custom widget is actually registered.
- Saved dashboard reloads.
- Invalid dashboard JSON is rejected.
- Bryntum tasks reflect backend state.
- Forbidden timeline edits revert.
- Channel3 failure has an honest error state.
- Cached offer timestamp is visible.

### Concurrency Evidence

Use separate PostgreSQL sessions and coordinated synchronization points.

Do not treat `asyncio.gather()` alone as proof that a race condition was exercised.

Cover:

- Last-seat contention.
- Authorization admission versus deadline freeze.
- Duplicate operation claim.
- Webhook versus synchronous response.
- Lease expiry versus old worker completion.
- Cancellation versus in-flight capture.

## Demonstration Data

Separate three classes of data:

| Class | Permitted use | Presentation |
|---|---|---|
| Actual integration data | Sponsor calls and payment evidence | Show genuine provenance |
| Application fixtures | Workshop names, host-entered costs, test cases | Label as demonstration inputs |
| Mocked provider responses | Automated tests only | Never present as live integration |

Do not fabricate Channel3 prices, provider IDs, workflow runs, or customer outcomes.

Do not claim that demonstration inputs represent market research.

### Repeatable Demonstration

Each demonstration run should:

1. Create fresh relative campaign dates.
2. Fetch or explicitly reuse timestamped real offers.
3. Establish fresh sandbox authorizations.
4. Run the actual deadline pathway.
5. Preserve the resulting audit evidence.

A privileged sandbox-only “close booking now” action may move a campaign toward an earlier decision if clearly disclosed and if it invokes the same domain logic.

It must not fabricate elapsed time, rewrite provider timestamps, or manufacture successful payments.

Do not expose unrestricted reset actions to public visitors.

## Three-Minute Demo

Target approximately 2 minutes 45 seconds.

| Time | Action |
|---|---|
| 0:00–0:20 | State the host’s problem and show the workshop |
| 0:20–0:45 | Show real Channel3 offers and the computed threshold |
| 0:45–1:15 | Demonstrate guest PayPal Sandbox authorization |
| 1:15–1:45 | Ask Rescue Analyst to explain viability and add a visualization |
| 1:45–2:10 | Show Bryntum dependencies and the deadline workflow |
| 2:10–2:35 | Show confirmed collection or safe release/compensation |
| 2:35–2:45 | Show integration evidence and product value |

Use a concise caption explaining APIMatic’s development-time role rather than forcing it into the runtime user journey.

A recorded segment may show an actual previously executed sandbox failure path, but label it as recorded evidence rather than a simultaneous live outcome.

Do not claim real workshops ran or real hosts saved money unless that actually happened and can be supported.

## Documentation Requirements

### README

Include:

- Product purpose.
- Required environment variables.
- Local setup.
- Repository `.venv` instructions.
- Database migration.
- Frontend build.
- Workflow setup.
- Test commands.
- Judge access.
- Sandbox limitations.
- Sponsor integration map.
- Hosted URL.
- Submitted commit identifier.

### Sponsor Evidence

For each sponsor, record:

- Feature implemented.
- Actual code location.
- Version.
- How to reproduce.
- Screenshot or recording.
- Known limitation.

Keep secrets and sensitive identifiers out of public screenshots.

### Open-Source Boundaries

Apply the repository’s chosen open-source license to original application code.

Document third-party commercial components separately.

Do not imply that the repository license grants rights to redistribute AG Studio or Bryntum proprietary packages.

Make legitimate dependency installation instructions reproducible.

The contest requires authorized third-party integrations and a public open-source repository. [Official rules](https://paypalaihackathon.devpost.com/rules)

## Risk Register

| Risk | Mitigation | Release condition |
|---|---|---|
| Long-lived authorization assumption | Short campaigns; no MVP reauthorization | Timing policy enforced |
| Partial capture | Saga plus compensation | Failure tests pass |
| Unknown provider result | Reconciliation, no blind replacement | Recovery demonstrated |
| Unusable Channel3 results | Category spike before UI work | Real relevant offers found |
| Wrong pack interpretation | Merchant review | No unreviewed automatic costing |
| AG Studio API drift | Pin tested versions | Production build passes |
| Bryntum license/package access | Resolve on first day | Authorized reproducible setup |
| Workflow API uncertainty | Official minimal spike | Real task run observed |
| Free database expiry | Non-expiring paid arrangement | Judging window covered |
| Authentication spoofing | Opaque sessions and role checks | Negative tests pass |
| AI overreach | Read/propose tools only | No money-moving tool available |
| Scope explosion | One merchant, currency, seat, category | Vertical slice complete first |
| Expired demo data | Fresh authorizations per run | December access remains usable |
| Submission instability | Feature freeze and early submission | Clean-browser check passes |

## Coding-Agent Guardrails

Place these rules in `AGENTS.md`:

```text
Implement tip-implementation-plan.md in bounded phases.

Inspect the repository before proposing changes.
Do not assume previous projects' code exists here.

Use the repository-root .venv for all local Python commands.
Do not install packages into system Python.
Do not modify Perfume Atelier or any other project.

PayPal Sandbox only.
Never enable simulator behavior in a hosted environment.
Never accept browser-supplied identity as authentication.

The backend owns prices, capacity, financial calculations,
payment state transitions, and authorization decisions.

The LLM may analyze and propose.
The LLM may not capture, void, refund, publish, or change
published campaign terms.

Use actual sponsor components and actual integration calls.
Do not fabricate prices, provider references, or workflow evidence.

Do not guess vendor SDK APIs or IDE configuration.
Verify against current official documentation and installed types.

Do not hold database transactions open across external calls.
Use durable operation records and operation-scoped idempotency.
Treat network timeouts as ambiguous until reconciled.

Do not provision paid resources, change external accounts,
delete data, deploy, or publish a submission without approval.

At each phase report:
- Files changed
- Commands executed
- Tests and exact outcomes
- Actual integration evidence
- Remaining blockers
- Next bounded step

Stop at the phase gate for review.
Do not expand scope to compensate for a blocked integration.
```

## Definition Of Done

### Product

- [ ] Host can create and publish a viable workshop.
- [ ] Materials use real reviewed Channel3 offers.
- [ ] Threshold calculation is deterministic and explainable.
- [ ] Guest can authorize through PayPal Sandbox.
- [ ] Deadline processing confirms or safely unwinds the campaign.
- [ ] Guest payment status remains understandable.

### Payment Integrity

- [ ] Approval and authorization are distinct.
- [ ] Authorization and collection are distinct.
- [ ] Pending and completed states are distinct.
- [ ] Group collection is not described as atomic.
- [ ] Partial failures are compensated.
- [ ] Unknown outcomes are reconciled.
- [ ] Duplicate processing is safe.
- [ ] Actual sandbox capture, void, and refund evidence exists.

### Sponsor Integration

- [ ] AG Studio dashboard is interactive.
- [ ] Tipping Meter is a genuine custom widget.
- [ ] Rescue Analyst invokes real permitted tools.
- [ ] APIMatic usage is documented honestly.
- [ ] Bryntum timeline uses real application state.
- [ ] Channel3 materially affects kit costing.
- [ ] Render hosts the application.
- [ ] Render Workflows executes genuine application work.

### Security

- [ ] Guest identity cannot be spoofed through headers.
- [ ] Merchant role is separately authenticated.
- [ ] CSRF protection covers browser mutations.
- [ ] Provider webhooks are verified.
- [ ] Secrets are absent from source and browser bundles.
- [ ] Hosted startup rejects unsafe development flags.
- [ ] Agent tools enforce backend authorization.

### Delivery

- [ ] Clean setup instructions work.
- [ ] Public repository includes a visible license.
- [ ] Commercial dependencies are documented correctly.
- [ ] Judging access works through 15 December.
- [ ] Database will not expire during judging.
- [ ] Trial/license dates cover evaluation.
- [ ] Video is publicly visible and under three minutes.
- [ ] Submission describes limitations accurately.
- [ ] Submitted commit is recorded.

## First Implementation Task

Start with a foundation-and-integration spike, not the complete application.

The first task is:

> Establish the repository, PostgreSQL schema skeleton, guest and merchant session boundaries, and the smallest real integration proof for PayPal, Channel3, AG Studio, Bryntum, APIMatic, and Render Workflows.

Return the working evidence and blockers.

Do not begin broad dashboard styling, multi-workshop features, or autonomous agent behavior until the authorization and workflow foundations are verified.