Implement the next Tipping Point product slice:
a complete host workshop workbench connected to real public discovery.

The public landing page already has an approved visual direction.
Do not redesign it or rebuild the project.

The objective is:
Host signs in → creates/opens a draft → reviews materials →
previews economics → publishes → views the actual public workshop.

Read applicable AGENTS.md instructions, the implementation plan,
relevant skills, existing frontend routes, and actual backend contracts.

Inspect what already works before writing replacements.
Reuse existing components, domain services, authentication, and APIs.
Do not stop after another plan or documentation-only checkpoint.

1. FIX AUTHENTICATED ROUTING

- /host/login is the login form, not the authenticated workspace.
- After successful login, navigate to /host using history replacement.
- An authenticated visit to /host/login redirects to /host.
- Unauthenticated access to protected host routes goes to host login.
- Preserve only validated internal return destinations.
- Logout invalidates the real server session and returns to public browsing.
- Handle session expiry without discarding draft input unnecessarily.
- Keep the homepage and public workshop pages accessible without login.

Preserve existing cookie authentication, CSRF bootstrap, origin checks,
and server-side ownership enforcement.

Do not introduce JWTs or frontend-only authentication flags.

2. UNIFY THE HOST VISUAL SYSTEM

Reuse the public site's typography, spacing, colours, buttons, and branding.

Replace the oversized green host banner with:
- A compact header.
- Tipping Point wordmark.
- “Host workspace” context.
- Public browsing link.
- Merchant identity and logout.

Use white/soft-neutral surfaces, near-black typography, and restrained
red accents. Keep semantic status colours distinct.

The host application should feel related to the public website but
more practical and information-dense.

Do not put oversized marketing headings on every internal screen.

3. IMPROVE THE WORKSHOP LIST

Use actual owned-workshop API data.

Each item should show:
- Title.
- Draft/published status.
- Ticket price, or “Price not set” for an incomplete draft.
- Capacity.
- Booking cutoff with clear timezone.
- Relevant incomplete setup items when determinable.
- One main action: Continue setup / Open workshop.
- View public page only when genuinely published.

Provide loading, empty, error, and retry states.

Do not manufacture booking counts, income, attendance, or payment totals.

Do not insert example workshops into the authenticated merchant list.

4. BUILD OR COMPLETE THE WORKSHOP WORKBENCH

Use a route such as /host/workshops/:id, adapting to existing routing.

Create a useful layout:
- Workshop title, status, and save state at the top.
- Main editor on the left.
- Compact economics/next-action summary on the right.
- Mobile layout that stacks cleanly.

Use these sections or tabs:
A. Basics
B. Materials
C. Economics
D. Review & publish

Reuse working editors rather than replacing them unnecessarily.

A. BASICS

Connect actual supported fields:
- Title and description.
- Workshop date/location/duration only where supported.
- Capacity.
- Ticket price.
- Booking dates.
- Minimum operating attendance where supported.

Use explicit Save actions initially.
Show unsaved changes and validation errors clearly.
Do not claim an input is persisted unless the server saves it.

Distinguish workshop date from booking cutoff.
Use clear GBP entry and decimal-safe conversion to integer pence.

B. MATERIALS

Connect the existing material-costing backend.

Support:
- Merchant-entered material assumptions.
- Existing Channel3 search and selection interfaces where available.
- Pack size.
- Shared quantity.
- Per-attendee quantity.
- Shipping allowance.
- Source and retrieval timestamp for provider offers.
- Human-review status for quantities and suitability.

Separate provider facts from merchant assumptions.

Show “Channel3 not configured”, provider error, no results, and stale
results honestly.

Do not invent product prices or silently fall back to fake offers.

Do not make live Channel3 requests during agent verification.
Search must be explicitly user-triggered, never page-load or per-keystroke.
Do not reset the previously accounted live-request budget.

C. ECONOMICS

Use the existing backend preview endpoint as the financial authority.

Display:
- Ticket price.
- Fixed costs.
- Materials cost at the selected attendance.
- Shipping.
- Contingency.
- Estimated fees.
- Estimated revenue and surplus.
- First viable attendance.
- Whether the selected attendance is actually viable.

Provide an attendance selector driven by the returned cost curve.

Important:
Pack-cost jumps can make a higher attendance non-viable.
Do not assume all attendance above the first viable point is viable.
Represent viable/non-viable points accurately.

Label estimated figures as estimates.
A preview is not a booking, authorization, or confirmation.

Use a clear, lightweight cost breakdown.
Do not install a new charting platform for a single chart.

D. REVIEW & PUBLISH

Show the exact terms about to become public:
- Price and capacity.
- Booking dates.
- Relevant workshop details.
- Approved cost assumptions and reviewed material provenance.
- Sandbox limitations.

Explain:
“Publishing freezes these campaign terms. Review them before continuing.”

Call the existing authenticated publish endpoint.
Preserve its locking, validation, and repeat-request guarantees.

After success:
- Display the actual campaign reference/status.
- Make frozen financial inputs read-only.
- Offer “View public workshop”.
- Do not enable booking if its backend is still absent.
- Do not treat OPEN as payment-confirmed.

Do not manufacture an editable published campaign or fake publish success.

5. CONNECT REAL PUBLIC DISCOVERY

First inspect whether public workshop listing/detail endpoints exist.

If present, use them.

If absent, adding minimal read-only public listing/detail endpoints is
approved, using existing tables and publication state.

Public responses must:
- Include only deliberately public fields.
- Resolve details from the authoritative published campaign/frozen terms.
- Exclude drafts and private merchant records.
- Exclude credentials, sessions, private cost breakdowns, private material
  sourcing records, guest emails, and payment resources.
- Return 404 for unpublished/private workshop references.
- Distinguish accepting-reservations, booking-closed, and unavailable
  states without falsely claiming payment capability.

Expose only the public metadata needed for discovery:
title, public description, price, capacity, relevant dates, safe venue
information if supported, and publication/availability status.

Do not expose the full ORM model or raw JSON terms.

When real published inventory is empty, show an intentional empty state.
If example workshops remain, keep them in an explicitly separate
“Examples” area—not mixed into the real results.

6. GUEST CONTINUATION BOUNDARY

Retain public browsing without login.

If guest reservation endpoints are not implemented:
- Keep guest email/booking continuation clearly unavailable or preview-only.
- Do not save guest emails to an invented endpoint.
- Do not display “reservation confirmed” or “email sent”.
- Do not authenticate someone merely because they enter an email.

This slice does not implement guest sessions or payment operations.

7. SCOPE AND EXECUTION

Use the existing .venv for all Python commands.
Use existing frontend tooling and dependencies.

No new dependencies or schema migrations are approved in this slice.
If a genuinely required persisted field is missing, report that precise
gap rather than pretending it is supported or redesigning the schema.

No live provider calls, PayPal operations, account changes, deployment,
database-role changes, commits, pushes, or unrelated cleanup.

Do not add fake AG Studio or Bryntum panels.
Those integrations will follow on top of the real campaign data.

Preserve the public landing page except for necessary routing/data wiring.
Do not expand into another marketing redesign.

8. ACCEPTANCE

Demonstrate:
- Successful host login ends at /host.
- A real draft can be created, saved, reopened, and edited.
- Materials feed the existing calculator.
- Attendance scenarios reflect backend results.
- Invalid/incomplete terms cannot publish.
- Publication returns the actual persisted campaign.
- Published terms cannot be edited.
- The actual public listing/detail shows that published workshop.
- Draft/private workshop IDs cannot be accessed publicly.
- Guest payment remains clearly unavailable if not implemented.
- Cross-merchant protections and CSRF still work.
- Mobile layouts remain usable.

Use an isolated test database and registered test-owned records.
No destructive schema teardown or unapproved development-data seeding.

Run frontend typecheck/build/tests and relevant backend regressions.
Report checks as NOT RUN if execution tools are unavailable.

Return:
- What now works end to end.
- Files changed.
- Actual API connections versus explicitly unavailable capabilities.
- Executed test/build results.
- Desktop/mobile screenshots where tools support them.
- Remaining blockers for guest reservations and Sandbox payments.

Implement the journey, not just navigation tabs and placeholder panels.