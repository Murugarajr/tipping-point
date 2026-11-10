# APIMatic PayPal Context Plugin — installation and contract review

Date: 2026-11-10. Supersedes the 2026-11-06 "availability blocker" note, which recorded that no plugin
had been invoked. This review is **read-only**: no application code, dependencies, live PayPal calls or
payments were involved.

## Environment and installation (actual)

| Item | Value |
| --- | --- |
| Coding environment | **Claude Code** (VS Code extension 2.1.319). No other assistant was configured. |
| Plugin | `paypaldev/server-sdk-context-plugin-preview` — manifest `paypal` v0.1.0, a preview "not an official long term supported PayPal product" |
| Plugin source commit | `6aa057126f0d4709a42e15002aab832a94935d92` (installed copies verified byte-identical; the installer records only `ref: main`) |
| Installer | npm `context-plugins@0.12.0` (`apimatic/context-plugins-installer` @ `a5aadc36f683eae8d78f17e080a6a9ec52f880ad`, MIT) |
| Command | `CP_TELEMETRY=off PATH="<claude-code-extension>/resources/native-binary:$PATH" npx --yes context-plugins@0.12.0 install https://github.com/paypaldev/server-sdk-context-plugin-preview --targets claude --yes` |
| Scope | Claude Code **user** scope: marketplace `context-plugins-local` (`~/.context-plugins/marketplace`), plugin `paypal@context-plugins-local`, status enabled. No other assistant configured. |
| Telemetry | Disabled (`CP_TELEMETRY=off`); no telemetry record created. |
| Plugin content | 48 Markdown skills + JSON manifests; **no hooks, no MCP servers** (no component that executes code or makes network requests). |
| Activation | `/reload-plugins` → "1 plugin · 48 skills"; the `paypal:python-*` skills then appeared in the session's skill list. |

## Evidence of actual plugin use

Skills invoked in this session, in the plugin's own workflow order (via the Skill tool, after activation):

1. `paypal:python-getting-started` — SDK identity; required checking out the tag matching the pinned
   version (done, see below) and reading controller source for signatures.
2. `paypal:python-authentication` — the SDK's single scheme is OAuth 2 client credentials; warns that the
   SDK's own token `expiry` uses local time read as UTC.
3. `paypal:python-calling-endpoints` — directs per-operation contract checks to `paypalserversdk/controllers/`
   and `doc/controllers/`.
4. `paypal:python-models` — wire names (`_names`), `_optionals`, enum members.
5. `paypal:python-error-handling` — treat a transport failure on a non-idempotent write as **outcome
   unknown**; which statuses each operation registers.
6. `paypal:python-configuration-resilience` — read the generated retry/timeout defaults rather than assume
   them; a read timeout on a `POST` is the duplicate-write risk.
7. `paypal:python-testing` — route the OAuth token path separately in stubs; assert on the outgoing request.

The plugin's guidance is SDK-oriented. It contains **no** content on order authorization, void, refund,
`PayPal-Request-Id` or REST paths; for those it points to the SDK's generated source, which was read
here as directed:

| Source | Identity |
| --- | --- |
| SDK repository | `https://github.com/paypal/PayPal-Python-Server-SDK` |
| Tag read | `2.4.0` = `b1460117a5618fb1a5b36b3ea0b1a49e124220c3` (tree `c455ed12…`, identical to `main` @ `778277d9e4f23f80a2c150433af2f49754c76a66`); matches the plugin's pinned `paypal-server-sdk==2.4.0` |
| Files used | `paypalserversdk/controllers/{o_auth_authorization,orders,payments,base}_controller.py`, `paypalserversdk/configuration.py`, `paypalserversdk/models/*`, `paypalserversdk/exceptions/error_exception.py`, `doc/controllers/{orders,payments}.md` |

The SDK was only read, never installed or executed; the application keeps its own `httpx` client
(`packages/tipping_point/paypal/client.py`). No secrets, source or environment files were given to the plugin.

## Contract review

Sources: **P** = plugin skill guidance, **S** = SDK 2.4.0 generated source/docs, **A** = our application.

| Area | Application (A) | Reference (P/S) | Result |
| --- | --- | --- | --- |
| OAuth token | `client.py:57,737-789`: `POST /v1/oauth2/token`, Basic credentials, form `grant_type=client_credentials`; `Bearer` on calls | S `request_token`: same path, verb, form field, Basic header; P authentication | **Verified match** |
| Token expiry | Monotonic clock, buffer, validated `expires_in` (`client.py:772-789`) | P: SDK's own expiry uses a skewed local-time clock | **Verified match**; expiry is computed on a monotonic clock, so the local-time skew the plugin describes for the SDK does not apply |
| Endpoints and verbs | `client.py:922-1163`: create/get/authorize order; get/capture/void authorization; get capture; refund capture; get refund | S `orders_controller`, `payments_controller`: identical paths and verbs for all 9 | **Verified match** |
| Idempotency header | `PayPal-Request-Id` on every mutation; required for capture/refund (`client.py:61-66,805-806,1117-1122`); max 100 chars, UUIDs used | S: optional header on all POSTs. `doc/controllers/orders.md` (Create Order :44, Authorize Order :274): length 1–108, "The server stores keys for 6 hours" (up to 72 hours via an Account Manager). `doc/controllers/payments.md` (Capture :95, Void :215, Refund :322): "The server stores keys for 45 days", no length constraint stated | **Verified match** (see R2) |
| `Prefer` | `return=representation` on authorize/capture/void/refund | S: `Prefer` accepted on those operations | **Verified match** |
| Create-order body | `client.py:620-650`: `intent: AUTHORIZE`, `purchase_units[{reference_id, amount{currency_code,value}, description?, payee{email_address|merchant_id}?}]`, `payment_source.paypal.experience_context{return_url, cancel_url, shipping_preference: NO_SHIPPING, user_action: CONTINUE}` | S models `OrderRequest` (required `intent`, `purchase_units`), `PurchaseUnitRequest` (required `amount`), `Money`, `PayeeBase`, `PaypalWalletExperienceContext`; enums `CheckoutPaymentIntent.AUTHORIZE`, `PaypalWalletContextShippingPreference.NO_SHIPPING`, `PaypalExperienceUserAction.CONTINUE` | **Verified match** |
| Authorize body | `json_body={}` (`client.py:991-997`) | S `OrderAuthorizeRequest` — optional body, all fields optional | **Verified match** |
| Capture / refund bodies | `{amount, final_capture: true}` / `{amount}` (`client.py:609-617`) | S `CaptureRequest`, `RefundRequest` — all fields optional, wire names match | **Verified match** |
| Money | Integer minor units ↔ decimal string via `Decimal` (`client.py:151-190`); GBP exponent 2 | S `Money{currency_code, value}` as strings | **Verified match** |
| Error statuses | `_check_response` (`client.py:850-875`): 401/403 auth; 400/404/409/422 definitive rejection; **any other status on a mutation = outcome unknown** | S registers 400/401/403/404/409/422/500 (+`default` for create/authorize); 500 raises base `ApiException` | **Verified match**; a 500 (or any status not listed) on capture/void/refund is classified as outcome unknown, so it is reconciled by retrieval instead of being recorded as failed |
| Transport failures | Timeout/connection error on a mutation → `PayPalOutcomeUnknownError` (`client.py:811-848`) | P error-handling: a failed write's transport error is outcome unknown | **Verified match** |
| Malformed 2xx | Non-JSON or non-object body on a mutation → outcome unknown (`client.py:879-905`) | P: typed-exception trap on non-object bodies | **Verified match**; on a mutation, a non-object body is classified as outcome unknown and no fields are read from it |
| Error body | Keeps `name`, `details[].issue`; drops message text (`_provider_issues`) | S `ErrorException` also unboxes `debug_id`; `ErrorDetails{field,value,location,issue,description}` | Match; **R1** |
| Retries | None automatic; one POST per mutation; unknown outcomes claimable for retrieval only (`guest/payments.py:121-146`) | S default `max_retries=0`; P: never add `POST` to retry methods | **Verified match** |
| Replay vs. key retention | Authorize and void are retrieval-first: read order/authorization state, mutate only if still required (`guest/payments.py:350-375`, `600-640`) | S: Orders keys stored 6 h (source above) | **Verified (static)**: a later retry reads provider state before any mutation, so it does not rely on PayPal deduplicating the key (see R2) |
| Timeout | 10 s default, validated ≤ 30 s (`client.py:686,700-703`; `settings.py:207`) | S default 60 s, per request; P: token fetch can consume a second timeout | **Verified match**; per-request timeout 10 s by default versus the SDK's 60 s |
| Sandbox vs. production | `_validate_sandbox_base_url`; `from_settings` passes the Sandbox URL; `paypal_env: Literal["sandbox"]` | S environments: Sandbox `https://api-m.sandbox.paypal.com`, Production `https://api-m.paypal.com` | **Verified match**; production unreachable by construction |
| Authorization status | Only `CREATED` admitted, plus timestamps and 72 h honor-period coverage (`guest/payments.py` `validate_authorization`) | S `AuthorizationStatus`: CREATED, CAPTURED, DENIED, PARTIALLY_CAPTURED, VOIDED, PENDING | **Verified match**; every status other than `CREATED` is rejected |
| Status vocabularies | Provider statuses used ⊆ S enums (`CaptureStatus`, `RefundStatus`, `OrderStatus`); `EXPIRED`/`CANCELLED` used only as our booking states | S enums | **Verified match** |
| Tests | `tests/unit/test_paypal.py`, `test_paypal_related_links.py`, `test_paypal_settlement.py`, `test_paypal_operator_runner.py`: `httpx.MockTransport` routing the token path separately; outgoing header assertions | P testing: route token path separately; assert the outgoing request | **Verified match** |

### Verified mismatches

None found **within this static contract review**: the areas in the table above, for the 9 operations the
application uses, compared against the plugin's guidance and the SDK 2.4.0 source and docs. This does not
establish live API behaviour, and it does not cover the areas listed under coverage gaps below.

### Recommendations (not defects)

Neither item below is a contract mismatch or a payment-correctness defect.

- **R1 — keep PayPal's `debug_id`.** The SDK's `ErrorException` carries `debug_id`, the correlation id
  PayPal support uses. Our gateway errors keep only issue codes; only the operator runner records the
  `paypal-debug-id` header (`paypal/operator_runner.py:310`). Retaining the header value on
  `PayPalRequestError` / `PayPalOutcomeUnknownError` would help reconcile an unknown outcome with
  PayPal. It does not affect payment correctness.
- **R2 — record the idempotency-window assumption.** The SDK 2.4.0 docs state that Orders keys are
  stored for 6 hours (`doc/controllers/orders.md:44,274`) and Payments keys for 45 days
  (`doc/controllers/payments.md:95,215,322`). These periods were not verified against PayPal directly.
  The current design does not depend on them: it never replays a mutation outside `PREPARED`, and it
  checks provider state first. A short code comment beside `claim_operation` would keep a future change
  from relying on PayPal deduplication beyond those windows.

### Coverage gaps (stated, not inferred)

- **Webhooks:** the SDK 2.4.0 has no webhook-verification controller, and the plugin skills do not cover
  webhooks. The application currently implements no webhook handling, so this was not reviewed.
- **Related-link host parsing** (Sandbox `up` links on `api.sandbox.paypal.com` versus `api-m…`): neither
  the plugin nor the SDK models link hosts; covered by our own tests (`test_paypal_related_links.py`)
  and the 2026-11-07 Sandbox evidence, not by this review.
- **Live behaviour:** this review is static. No live call was made to verify any conclusion here. Earlier
  Sandbox runs are recorded separately in `docs/evidence-log.md` (authorize and void on 2026-11-06; the
  GBP 1.00 capture and refund in section 9, 2026-11-07); they were not re-run for this review.

## Limitations

- The plugin documents the SDK, not the REST API directly; operation-level conclusions rest on the SDK's
  generated code, which mirrors PayPal's API specification as of SDK 2.4.0.
- The plugin is a preview and may be removed; the commit identity above is what was used.
- No application code was changed as a result of this review.
