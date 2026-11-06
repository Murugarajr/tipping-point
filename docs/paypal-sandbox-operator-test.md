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