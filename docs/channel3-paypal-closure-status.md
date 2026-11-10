# Narrow closure — incomplete

> **Historical review (2026-11-06).** Superseded by the current status in `README.md` and the
> hosted evidence in `docs/evidence-log.md` §10. The text below is unchanged.

Review date: 2026-11-06. Material-costing code provisionally accepted;
**live Channel3 verification incomplete**.

## Execution

Fresh-shell root/venv probe returned exit 0. Root `.venv/bin/python` prefix,
isolation and pip location were observed. Initial tree was clean at existing
HEAD `8e7ea9a`; initial `git diff --check` passed. Instructions/skills, source,
tests and portions of committed diff were read. No tests ran here.
A later read-only documentation fetch encountered HTTP 301 and terminal
completion could not be observed. Shell work stopped. Final diff check and full
implementation review remain outstanding. Historical 41/127 test results,
migration/schema and sentinel preservation remain unsupported. No database
inspection/mutation, migration, installation or provider retry occurred here.

## Channel3 partial contract review

Official sources fetched on review date:

- https://docs.trychannel3.com/api-reference/v1/search.md
- https://docs.trychannel3.com/guides/localization
- https://docs.trychannel3.com/guides/localization.md
- https://docs.trychannel3.com/guides/offer.md

POST https://api.trychannel3.com/v1/search and x-api-key agree with installed
adapter. Search input or page_token is required (otherwise 422); reference lists
400/401/402/422 errors. Full schema/pagination/error alignment is incomplete:
reference output was truncated and direct OpenAPI retrieval encountered redirect.
No alternate API was substituted.

Locale REST example uses top-level country=GB/language=en/currency=GBP; installed
request tests expect nested config plus mode. Nested SDK overrides are also
shown; verify the complete REST schema before correcting. Offer guide uses
product id/title/offers, offer domain/url/availability/condition/price and example
price `{amount: 395, currency: USD}`; fixture uses `{price: 5.99, currency: GBP}`.
Reconcile this mismatch with response schema/normalization. No code correction
was made; neither fixture nor successful HTTP status proves live compatibility.

## Budget / costing

Original budget 5; prior unknown submissions charged 3; new provider calls 0.
At most 2 original slots remain; closure permits at most 1 additional attempt
only after reconciliation. No usable sanitized response was located in inspected
repository candidates or limited `/tmp` filename search. Not an exhaustive
absence claim. No credentials were printed. No live status/count/offer obtained;
no genuine offer reached costing. Demonstration blocked; fixtures are mocked.

Inspect existing records first. If one new request is demonstrably within budget,
reserve it durably before submitting. Use existing credentials, relevant material
query, GB/en/GBP, no retries/pagination. Record UTC time/local attempt ID,
method/endpoint/query/locale, observed status, validation result, product count
and documented fields of one usable offer, never secrets/arbitrary headers.
Failure/unknown/no suitable offers means stop. Use a labeled draft for a usable
offer through normalization/costing; pack size/usage/shipping remain merchant
review assumptions. Do not change published terms.

## PayPal adapter recovery (offline only)

Official sources fetched:

- https://developer.paypal.com/docs/api/orders/v2/
- https://developer.paypal.com/docs/api/orders/v2/orders-create/
- https://developer.paypal.com/docs/api/orders/v2/orders-authorize/
- https://developer.paypal.com/api/orders/v2/schema.json
- https://developer.paypal.com/docs/api/payments/v2/
- https://developer.paypal.com/docs/api/payments/v2/authorizations-void/
- https://developer.paypal.com/api/payments/v2/schema.json
- https://developer.paypal.com/api/rest/authentication/

The sandbox REST origin is `https://api-m.sandbox.paypal.com`. OAuth
`POST /v1/oauth2/token` uses Basic credentials and form
`grant_type=client_credentials`; resources use bearer tokens. The recovered
standalone adapter in `packages/tipping_point/paypal/client.py` creates an
`AUTHORIZE` order, retrieves orders, authorizes an approved order, retrieves an
authorization, and voids an uncaptured authorization. It pins the sandbox host,
keeps credentials server-side, formats integer minor units safely, and requires a
durable caller-provided operation ID for create/authorize/void. It deliberately
does not implement booking endpoints, capture, refund, webhooks, persistence, or
automatic mutation retries.

Create/authorize/void send `PayPal-Request-Id`; the adapter applies a conservative
100-character application limit even though the current documented API limit is
10,000 characters. A mutation timeout, transport failure, malformed mutation
response, or non-definitive provider result is surfaced as an unknown outcome with
the same operation ID for caller reconciliation, never as proof that no payment
state changed. Void supports both 200-with-representation and 204 responses;
fully captured authorizations cannot be voided. Approval remains distinct from
authorization.

Offline `httpx.MockTransport` tests in `tests/unit/test_paypal.py` cover OAuth,
token reuse, authorization-intent payloads, request IDs, read-only retrieval,
authorization, both void responses, sanitized transport errors, and ambiguous
mutation timeouts. On this recovery session, `17` focused PayPal/settings tests,
`75` unit tests, and the full `141`-test suite passed; this is mocked local
evidence only. No credentials, live PayPal requests, financial mutations,
database changes, APIMatic invocation, or deployment occurred. APIMatic
availability remains separately recorded in `docs/apimatic-integration.md`.

## Remaining bounded work / human sandbox prerequisites

1. Human confirms sandbox merchant/app, separate buyer, existing client ID/secret
   via server config, expected payee, small GBP amount, return/cancel URLs and
   explicit one-test approval. Resolve APIMatic availability separately. No
   implicit account/credential creation.
2. After approval: create -> buyer browser approval -> retrieve/validate APPROVED
   order/amount/currency/payee -> authorize -> retrieve/validate authorization ->
   void -> retrieve/confirm VOIDED. Persist operation UUID/key/payload before HTTP,
   no DB lock across HTTP. Reconcile unknown calls before retry; preserve keys/
   payloads. Record sanitized IDs/statuses/times. Never capture/refund here.
3. Implement booking-domain persistence, ownership/payee/amount/currency/capacity
   validation, and admission only as a separately approved phase. The current
   adapter does not make a booking paid or authorized by itself.

No dependencies/schema/deployment/account changes, production payments, credential
creation, guest endpoints, commits or pushes were made.
