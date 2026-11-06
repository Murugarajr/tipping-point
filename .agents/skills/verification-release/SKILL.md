---
name: verification-release
description: Use when closing a Tipping Point implementation phase, reviewing security or concurrency, preparing real sandbox evidence, validating deployment, or preparing the hackathon submission and judge access.
---

# Verification and Release Workflow

## Scope the gate
1. Read root instructions, current phase acceptance criteria, repository diff, and existing failures.
2. Identify what must be proven locally, against PostgreSQL, with actual sandbox calls, and in hosting.
3. Use the existing repository `.venv`; inspect configured test/build commands before executing them.
4. Confirm target database and permitted test records before migrations or financial mutations.

## Verify
- Run focused regression tests first; then run relevant backend/frontend/build checks.
- Use separate PostgreSQL sessions and deliberate barriers for concurrency tests.
- Check guest identity spoofing, booking ownership, merchant access, CSRF, rate limits, and verified webhooks.
- Check hosted startup rejects live payments, payment simulation, local identity headers, and incomplete security configuration.
- Cover duplicate dispatch, worker crash after provider success, unknown outcomes, pending capture/refund, and compensation recovery.
- Verify dependency installation and production builds without global tooling or copied workstation environments.
- Scan tracked/staged changes and browser bundles for accidental secrets; never print discovered secrets.
- Check actual custom-widget registration, real Bryntum rendering, real Channel3 offers, and real workflow runs where relevant.

## Classify evidence
- Mocked unit/integration tests prove application behavior under controlled inputs, not live vendor integration.
- Actual PayPal Sandbox calls prove only the operations and environment observed.
- Hosted checks prove only the deployed commit and configuration tested.
- Never mark an unrun check passed or a cached result fresh.
- Record sanitized references and timestamps; keep sensitive raw payloads out of public artifacts.

## Before release
- Require approval before provisioning, deployment, account changes, publication, commits/pushes, or destructive cleanup.
- Verify hosting/database retention and legitimate component access through the judging period.
- Fresh judge checkout must not depend on expired pre-seeded authorizations.
- Provide safe judge access without publishing unrestricted merchant write credentials.
- Verify public repository, original-code license, third-party notices, setup guide, and demo accessibility.
- Keep demo video below the official limit and distinguish recorded evidence from live execution.

## Handoff format
1. Scope completed and files changed.
2. Exact commands/checks run, with pass/fail/skip totals where available.
3. Actual integration evidence versus mocked checks.
4. Security/concurrency findings and remaining blockers.
5. Data/resources preserved and any external changes made with approval.
6. Next bounded step.

Stop at the agreed gate. Report an observed blocker promptly rather than adding unrelated hardening or new features.
