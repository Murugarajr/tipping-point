# PayPal Sandbox authorization/void operator test and execution evidence

This document prepares one operator-driven **Sandbox-only** test. It does not
authorize a live API call, does not create an account or credential, and does not
connect the adapter to bookings. The local runner uses the existing standalone
adapter and its server-side configuration only.

## Closed run: user-executed terminal evidence (2026-11-06)

**Evidence attribution:** this section records terminal output reported by the
operator as **USER-EXECUTED** evidence. This documentation update made no
PayPal request, did not independently re-run the stages, and did not alter
provider state.

The existing Sandbox run `paypal-auth-2026-11-06-a` is closed as **successfully
reconciled and voided**:

- Reconciliation reported that the expected merchant/payee, reference, and GBP
  1.00 amount matched the existing order.
- Existing authorization `85J05450SK592051J` was retrieved as `CREATED`.
- No captures were reported for that order observation.
- The operator reported a successful `void`, followed by `verify-void`
  retrieval of the same authorization as `VOIDED`.
- Preserve the ignored private record
  `.private/paypal-sandbox-runs/paypal-auth-2026-11-06-a.json` and its existing
  create, authorize, and void operation IDs. Do not make more PayPal requests
  or manually change provider state for this closed run.

### Root cause resolved without repeating authorization

The original parser searched only top-level `payments.authorizations` and
`payments.captures`. The provider representation placed the authorization at
`purchase_units[*].payments.authorizations`. The corrected parser reads payment
resources embedded in purchase units and recovered the actual authorization.
The authorization was **not retried or repeated**.

### Browser return-flow limitation remains open

The buyer approved the Sandbox checkout, but the provider-hosted checkout
remained loading without completing a return flow. The current create-order
payload does not supply `application_context.return_url` or `cancel_url`.
Proper return/cancel handling remains required before guest-facing checkout.

### Scope not verified by this run

This terminal evidence does not verify capture, refunds, webhooks, booking or
admission integration, group settlement, or any production/live payment flow.

## Safety properties

- The default `preflight` stage is offline and makes no PayPal request.
- Each command executes exactly one named stage. It never advances to the next
  stage automatically.
- Every non-preflight stage additionally requires `--allow-network`; do not add
  that flag until this checklist has been explicitly approved.
- The runner creates a non-secret record at
  `.private/paypal-sandbox-runs/<run-id>.json`. The path is Git-ignored and the
  runner checks that before every write. Records contain IDs, GBP amount,
  reference/payee expectations, operation IDs, exact non-secret request payloads,
  and outcomes only—never OAuth tokens, client secrets, or buyer credentials.
- A resumed run reuses each operation’s exact request ID and payload. It refuses
  to replace a differing create/authorize/void operation. An unknown mutation
  outcome blocks all new mutations until reconciled through retrieval. The
  `reconcile` stage is read-only: it retrieves the saved order and, only if that
  order exposes exactly one authorization, retrieves that authorization before
  preserving its ID. It never creates, authorizes, captures, refunds, or voids.
  The `diagnose-order` stage is also read-only and retrieves only the saved order
  once. It records an allowlisted response-structure diagnostic before domain
  normalization; it never follows resource references or changes an outcome.
- The runner never asks for a buyer password. The operator approves using the
  **actual `approve` link returned by PayPal**, only after it is validated as
  HTTPS on `www.sandbox.paypal.com`; it is never constructed locally.
- The runner does not implement capture, refund, reauthorization, live mode,
  booking admission, database persistence, or webhooks.

## Current local configuration observation

At preparation time, the server-side settings probe reported:

```text
paypal_environment=sandbox
paypal_credentials_configured=false
paypal_client_id_configured=false
paypal_client_secret_configured=false
```

No `.env` value was printed or copied. A future approved run requires the existing
server-side Sandbox credentials to be configured; this runner must not prompt for
or accept secrets on its command line.

## Required approval checklist (complete before any `--allow-network` command)

- [ ] Sandbox merchant/app confirmed, with an existing server-side client ID and secret.
- [ ] Separate Sandbox buyer confirmed; its password will be entered only in PayPal’s browser UI.
- [ ] Expected PayPal merchant/payee identifier is confirmed and supplied as
  `--expected-payee`. `inspect-order` compares this value against the retrieved
  purchase-unit `payee.merchant_id` (or the returned payee email if no merchant
  ID is present) before authorization is permitted.
- [ ] Proposed amount is exactly **GBP 1.00** (this is an input, not an executed transaction).
- [ ] Return/cancel URL decision confirmed. **Current implementation sends neither
  `application_context.return_url` nor `cancel_url`**; browser approval is guided
  by the returned Sandbox `approve` link and provider-hosted completion flow.
- [ ] Scope is one order, one authorization, and void cleanup of that same uncaptured authorization.
- [ ] Ambiguous create/authorize/void outcomes will be reconciled by order or
  authorization retrieval with the preserved request ID and payload; no new order
  or mutation will be used to bypass uncertainty.

This preparation stops before live execution.

## Exact commands (all use the repository virtual environment)

Choose a unique human run ID and a non-secret reference ID. Substitute the expected
merchant/payee identifier only after the checklist is approved.

```bash
# Offline only; safe now. It reports credential presence only and makes no HTTP request.
.venv/bin/python scripts/paypal_sandbox_authorization_test.py \
  --stage preflight --run-id paypal-auth-2026-11-06-a \
  --reference-id operator-test-2026-11-06-a \
  --expected-payee 'confirmed-sandbox-payee'
```

After explicit approval of this exact test, run each following command separately,
inspect its result, and do not continue automatically:

```bash
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage create --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
# Open only the provider-returned URL printed by create; approve in the separate Sandbox buyer browser.
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage inspect-order --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage authorize --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage diagnose-order --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage reconcile --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage inspect-authorization --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage void --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
.venv/bin/python scripts/paypal_sandbox_authorization_test.py --stage verify-void --allow-network --run-id paypal-auth-2026-11-06-a --reference-id operator-test-2026-11-06-a --expected-payee 'confirmed-sandbox-payee'
```

If a post-authorization check fails, preserve the saved authorization ID and use
the `void`/`verify-void` stages for cleanup if provider state permits. If cleanup
cannot be confirmed as `VOIDED`, the record remains unresolved; do not report it
as cleaned up.
## Sandbox operator-test cleanup of a confirmed £1 campaign (added 2026-11-07)

This is the approved exception described in `docs/tip-implementation-plan.md` ("Approved exception: Sandbox operator-test cleanup"). It cancels **one** confirmed PayPal Sandbox test campaign whose frozen cohort holds exactly one booking with one verified, completed GBP 1.00 capture. It does this by fully refunding that capture through the existing durable refund ledger.

Ordinary `CONFIRMED` behaviour is unchanged. This is not a production cancellation or attendee-refund policy.

**Status:** implemented and tested offline only (MockTransport, `tipping_point_test`). No real capture or refund has been executed with it.

### Safety properties

- **Inspection is the default.** Without `--execute`, the command takes no locks, writes nothing and makes no provider request. It prints `eligible` and a rejection code.
- **`--execute` without `--allow-network`** commits only:
  - the cleanup intent and reason;
  - the audit event;
  - the guarded re-arm of the campaign's single `settlement_work` row.

  The campaign becomes `COMPENSATING` and the booking `REFUND_PENDING`. No provider call is made.
- **`--execute --allow-network`** revalidates eligibility, then runs one exact-campaign cleanup pass. That pass only claims work for this campaign with purpose `OPERATOR_TEST_CLEANUP`. It never runs deadline discovery and never claims other campaigns' work. The generic dispatcher in turn never claims cleanup work.
- **Every identifier is mandatory:** `--campaign-id`, `--booking-id`, `--capture-id`, `--expected-amount-minor 100`, `--expected-currency GBP` and `--reason`. `--limit` plays no part in cleanup scoping.
- **It rejects:**
  - multi-booking cohorts;
  - mismatched campaign, booking or capture references;
  - any amount or currency other than GBP 1.00;
  - a non-Sandbox environment;
  - any unresolved or conflicting operation;
  - unrelated bookings that are not yet resolved;
  - an active work lease;
  - an existing refund;
  - any campaign that is not `CONFIRMED` on the first request.
- **Repeats are idempotent.** A repeated or concurrent request resumes the same logical cleanup and refund operation. Resuming does not require `CONFIRMED`.
- **Unknown or crashed refund outcomes are never re-posted.** They stay unresolved and need review until reconciled by retrieval, using `--known-refund-id`.
- **Completion is shown only when it is real.** The campaign becomes `CANCELLED` and the booking `REFUNDED` only after a verified, completed full refund. Pending, failed, cancelled and unknown refunds keep the campaign `COMPENSATING`, with a durable review reason.

### Commands

These use the repository virtual environment. PayPal settings come from the process environment only, as for the existing worker.

First confirm the database target with `.venv/bin/python scripts/verify_db_identity.py`. Do not run any unscoped dispatcher. The command below targets only the campaign you name.

```bash
# 1. Inspect only (safe; no writes, no provider calls)
.venv/bin/python scripts/process_settlement_work.py --sandbox-test-cleanup \
  --campaign-id <campaign-uuid> --booking-id <booking-uuid> --capture-id <capture-id> \
  --expected-amount-minor 100 --expected-currency GBP \
  --reason "Sandbox GBP 1.00 operator test campaign cleanup"

# 2. Optional: commit intent/audit/re-armed work only (no provider call)
.venv/bin/python scripts/process_settlement_work.py --sandbox-test-cleanup --execute \
  --campaign-id <campaign-uuid> --booking-id <booking-uuid> --capture-id <capture-id> \
  --expected-amount-minor 100 --expected-currency GBP \
  --reason "Sandbox GBP 1.00 operator test campaign cleanup"

# 3. Approved live Sandbox refund pass (requires separate explicit approval)
.venv/bin/python scripts/process_settlement_work.py --sandbox-test-cleanup --execute --allow-network \
  --campaign-id <campaign-uuid> --booking-id <booking-uuid> --capture-id <capture-id> \
  --expected-amount-minor 100 --expected-currency GBP \
  --reason "Sandbox GBP 1.00 operator test campaign cleanup"

# 4. Reconcile an unknown refund by retrieval with a verified refund ID (never re-posts)
.venv/bin/python scripts/process_settlement_work.py --sandbox-test-cleanup --execute --allow-network \
  --campaign-id <campaign-uuid> --booking-id <booking-uuid> --capture-id <capture-id> \
  --expected-amount-minor 100 --expected-currency GBP \
  --reason "Sandbox GBP 1.00 operator test campaign cleanup" \
  --known-refund-id <verified-refund-id>
```

Rerun step 3 to poll a `PENDING` refund. A `FAILED` or `CANCELLED` refund, or one that stays unknown, remains visible as `REVIEW_REQUIRED`. It is not reported as completed cleanup.

## Hosted demo reactivation (Sandbox only; added 2026-11-10)

**Current status is separate from this procedure.** Hosted Sandbox authorize → cancel → void was
demonstrated on 2026-11-10 (`docs/evidence-log.md` §10.5). PayPal checkout is **currently
disabled** on the hosted web service: no PayPal credentials are loaded. Use this procedure only to
re-enable checkout temporarily for a demonstration. Hosted capture, refunds, below-threshold
release and automatic deadline settlement remain unverified, and this procedure does not
exercise them.

Every step below that writes to the hosted service, changes a setting, deploys or calls PayPal
needs its own explicit approval. Never retry a payment action blindly.

1. **Booking window.** Choose one campaign whose booking window covers the demonstration,
   normally a fresh hidden GBP 1.00 workshop with capacity 2, minimum attendance 1, no costs and a
   window of at most 48 hours. The authorization must cover the cutoff plus the 30-minute settlement
   deadline plus the 6-hour safety buffer, within 72 hours of authorization. Hiding a workshop from
   discovery is not booking isolation.
2. **Set a firm credential-removal deadline**, then run the campaign-risk check below in the web
   service Shell. Set `S` to at least one hour before credential activation, `E` to at least one
   hour after the removal deadline, and `TEST` to the demo campaign UUID. Proceed only with exactly
   one `PERMITTED` line and `RESULT: PASS`. Any `STOP` line ends the attempt.
3. **Credentials.** On the web service only, restore `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and
   `PAYPAL_EXPECTED_PAYEE` from the existing Sandbox REST app with "Save only". `PAYPAL_ENV` accepts
   only `sandbox`; confirm `APP_PUBLIC_URL` is present. Do not change the Workflow service,
   remote-settlement settings or the dispatcher.
4. **Same-commit redeploy** of the currently live commit. Saved variables are not loaded by a
   running process. Verify `/health/ready`, that the demo campaign reports `available`, and that no
   other campaign does.
5. **One Sandbox buyer flow** in a private window at `/continue?workshop=<WORKSHOP_UUID>`: reserve
   → create order (approval host must be `www.sandbox.paypal.com`) → approve as the Sandbox buyer →
   authorize. Steps must fit within the 10-minute reservation hold.
6. **Cancel and void.** Request cancellation (`RELEASE_PENDING`; no provider call). In the Shell:

   ```bash
   python scripts/reconcile_guest_booking.py <BOOKING_UUID>                                 # inspect only
   python scripts/reconcile_guest_booking.py <BOOKING_UUID> --allow-network --release       # void, once
   ```

   Expect `VOIDED`, captured 0, refunded 0, then confirm "Voided" in the Sandbox business account.
   If the void fails or is uncertain, do not re-run it; record the exact state as unresolved.
7. **Cleanup before the deadline.** Delete the three variables ("Save only") **and** redeploy the
   same commit: deleting alone does not unload them from the running process. Verify the demo
   campaign reports `payment_unconfigured` and health checks pass.

### Read-only campaign-risk check (web service Shell, from `~/project/src`)

It mirrors the reservation route's conditions for every campaign, whatever its status or
visibility, and flags existing bookings that enabled credentials could act on. It prints IDs,
titles, times and states only, inside a read-only transaction.

```bash
python - <<'PYEOF'
import datetime as dt
from sqlalchemy import text, select, func
from tipping_point.db.engine import SessionLocal
from tipping_point.db.models import Campaign, CampaignTerms, Workshop, Booking
from tipping_point.economics import CampaignFinancialsInput, build_snapshot_hash
from tipping_point.guest.service import capacity_count

UTC = dt.timezone.utc
S = dt.datetime(YYYY, MO, DD, HH, MI, tzinfo=UTC)   # activation minus at least 1 h
E = dt.datetime(YYYY, MO, DD, HH, MI, tzinfo=UTC)   # removal deadline plus at least 1 h
TEST = None  # or "<CAMPAIGN_UUID>": the only campaign permitted to be bookable

with SessionLocal() as s:
    s.execute(text("SET TRANSACTION READ ONLY"))
    now = s.scalar(text("SELECT now()"))
    print("db_now", now, "| window", S, "->", E, "| permitted", TEST)
    print("campaigns_by_status", dict(s.execute(select(Campaign.status, func.count()).group_by(Campaign.status)).all()))
    stop = 0
    permitted_seen = False
    for c in s.scalars(select(Campaign).order_by(Campaign.created_at)):
        t = s.get(CampaignTerms, c.terms_id)
        w = s.get(Workshop, c.workshop_id)
        why = []
        if c.status != "OPEN":
            why.append("status=" + c.status)
        if t is None or t.workshop_id != c.workshop_id or t.version != c.terms_version:
            why.append("terms mismatch (route returns 503)")
        else:
            if not t.is_frozen:
                why.append("terms not frozen")
            if t.currency != "GBP":
                why.append("currency=" + t.currency)
            if t.opens_at is None or t.closes_at is None:
                why.append("no open/close dates")
        if not why:
            close = min(c.cutoff_at, t.closes_at)
            if not (t.opens_at <= E and close > S and t.opens_at < close):
                why.append(f"outside window (opens {t.opens_at:%Y-%m-%d %H:%M}Z, closes {close:%Y-%m-%d %H:%M}Z)")
        if why:
            print("NOT_BOOKABLE ", c.id, c.workshop_id, "; ".join(why))
            continue
        try:
            i = CampaignFinancialsInput.model_validate(t.financial_inputs)
            integrity = (i.capacity == c.capacity and i.ticket_price_minor > 0 and i.fee_estimate is not None
                         and build_snapshot_hash(i, opens_at=t.opens_at, closes_at=t.closes_at) == t.snapshot_hash)
        except Exception as exc:
            integrity = "error:" + type(exc).__name__
        seats = c.capacity - capacity_count(s, c.id, now)
        label = "PERMITTED   " if TEST is not None and str(c.id) == TEST else "STOP        "
        if label.startswith("STOP"):
            stop += 1
        else:
            permitted_seen = True
        print(label, "campaign", c.id, "workshop", w.id, repr(w.title[:60]),
              "hidden" if w.hidden_from_discovery_at else "listed", "(hiding does not block booking)",
              f"| opens {t.opens_at:%Y-%m-%d %H:%M}Z closes {close:%Y-%m-%d %H:%M}Z",
              "| seats_now", seats, "| integrity_ok", integrity)
    print("bookings_by_state", dict(s.execute(select(Booking.state, func.count()).group_by(Booking.state)).all()))
    for b in s.scalars(select(Booking).where(Booking.state.in_(("AUTHORIZATION_PENDING", "REVIEW_REQUIRED"))).order_by(Booking.created_at)):
        stop += 1
        print("STOP         booking", b.id, "campaign", b.campaign_id, b.state, "created", b.created_at)
    for b in s.scalars(select(Booking).where(Booking.state.in_(("CHECKOUT_RESERVED", "AWAITING_APPROVAL")),
                                             Booking.cancelled_at.is_(None), Booking.reservation_expires_at > S)):
        stop += 1
        print("STOP         booking", b.id, "campaign", b.campaign_id, b.state, "hold until", b.reservation_expires_at)
    if TEST is not None and not permitted_seen:
        stop += 1
        print("STOP         permitted test campaign", TEST, "was not found as bookable in the window (wrong ID or dates)")
    print("RESULT:", "PASS" if stop == 0 else f"STOP ({stop} item(s) above)")
    s.rollback()
PYEOF
```

Replace the `YYYY, MO, DD, HH, MI` placeholders (year, month, day, hour, minute) with integers before running; the block is not
runnable as written.
