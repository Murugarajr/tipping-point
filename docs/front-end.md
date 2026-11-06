You are implementing the Tipping Point frontend in this repository.

Act as a senior product designer and frontend engineer. Build a distinctive,
polished, information-first experience inspired by the attached image.

Do not start with a login page. Do not produce only a design proposal or
another documentation checkpoint. Inspect the existing repository briefly,
then implement the approved frontend scope below.

────────────────────────────────────────
1. REPOSITORY AND EXECUTION RULES
────────────────────────────────────────

Read:
- Applicable AGENTS.md instructions
- docs/tip-implementation-plan.md
- Relevant .agents/skills documents
- Existing frontend/package configuration, if present
- Existing backend routes, schemas, authentication and CSRF behavior

Preserve all current backend, database, payment, and test work.

Use the existing repository-root .venv for every Python command.
Frontend tools use the repository's Node environment and package manager;
they do not run inside the Python virtual environment.

Inspect existing frontend code before deciding to scaffold.
If a frontend exists, improve it rather than creating a competing app.

If none exists, use the planned apps/web React + TypeScript + Vite structure.
Use the existing package manager and styling system where available.
If new scaffolding is necessary, minimal frontend dependency installation
is approved: React, React DOM, Vite, TypeScript, React Router, and one
consistent icon library such as Lucide React. Use compatible stable
versions and commit-ready lockfiles.

Do not add another backend, replace FastAPI, introduce Next.js alongside
Vite, modify database roles, or recreate .venv.

Do not read or display .env contents.
Never expose Channel3 or PayPal secrets to frontend code.
Do not perform live provider calls, payments, migrations, deployment,
account changes, staging, commits, or pushes.

Do not bypass applicable parent repository instructions. Report any actual
instruction conflict rather than silently changing those instructions.

If command execution is unreliable, distinguish NOT RUN from passed.
Do not repeatedly retry mutations through a broken runner.

────────────────────────────────────────
2. PRODUCT AND AUDIENCE
────────────────────────────────────────

Product:
Tipping Point helps independent hosts plan materials-based workshops that
only proceed after sufficient bookings and successful payment checks.

Guests discover workshops and reserve places.
Hosts understand material costs, attendance requirements, and readiness.

Core product story:
- Work out what a workshop needs.
- Understand the attendance required to cover approved costs.
- Collect reservations.
- Check viability and payments at the booking cutoff.
- Confirm the workshop or safely unwind the payment authorizations.

The interface must explain this before asking anyone to sign in.

Audience:
- Guests looking for small, hands-on creative experiences.
- Independent workshop hosts managing costs and uncertainty.

Use British English and GBP formatting.

────────────────────────────────────────
3. ART DIRECTION — FOLLOW THE REFERENCE
────────────────────────────────────────

Interpret the attached image's design language, not its literal content.

Extract:
- Bright white and soft grey backgrounds.
- Strong editorial typography.
- An asymmetric, carefully aligned bento composition.
- Large and small rounded tiles.
- One vivid red hero tile.
- Smaller cobalt-blue accents.
- Charcoal/black contrast moments.
- Simple consistent line icons.
- Close-cropped, relevant workshop photography.
- Generous whitespace between groups.
- A few oversized graphic elements with a clear purpose.

Do not copy the reference's branding, icons, photos, or text.

The result should feel like a modern creative studio meets a thoughtful
workshop platform—not a banking portal or generic SaaS template.

Avoid:
- Purple gradients.
- Glowing blobs.
- Glassmorphism everywhere.
- Repeated identical three-column feature cards.
- Giant dashboard screenshots as the entire hero.
- Emoji as interface icons.
- Excessive shadows.
- A login modal appearing on page load.
- A sidebar on the public homepage.
- Generic “unlock your potential” copy.
- Cards containing only an icon and two vague sentences.

Suggested visual system:
- Paper white page background.
- Soft grey and pale blue-grey neutral tiles.
- Near-black text.
- Vivid vermilion/red as the main expressive accent.
- Cobalt blue for a few secondary interactive/graphic moments.
- Semantic success/warning/error colours kept separate from branding.

Define reusable CSS tokens for colours, spacing, radii, type, and motion.
Check contrast instead of assuming white text works on every accent.

Typography:
Use a distinctive, readable grotesk family such as Satoshi or General Sans,
with a robust fallback. Use one display family and at most one body family.

Large expressive typography belongs on the public landing page.
Forms, workshop details, and merchant tools should use practical UI sizes.

Use 16px minimum body/input text, fluid heading sizes, and a 4px-based
spacing system. Keep long-form copy to comfortable line lengths.

Create a small original Tipping Point mark: a simple dot/threshold motif
that works at favicon size and beside the wordmark.

Light mode should closely reflect the reference.
If adding dark mode, preserve contrast and visual hierarchy rather than
simply inverting colours. Do not let theme work delay the core experience.

────────────────────────────────────────
4. PUBLIC NAVIGATION AND ROUTES
────────────────────────────────────────

The root route "/" must be public and information-first.

Suggested navigation:
- Wordmark
- Workshops
- How it works
- For hosts
- Host sign in — visually secondary
- Explore workshops — primary CTA

On mobile, collapse navigation accessibly without hiding the main CTA.

Suggested routes; adapt to existing routing rather than duplicating it:
- /                         Public landing page
- /workshops                Public discovery
- /workshops/:id             Public workshop detail
- /continue                 Email-first guest continuation
- /host/login               Existing merchant sign-in
- /host                     Authenticated merchant workspace

Never redirect anonymous visitors from "/" to login.
Never require an email to read the homepage or browse workshop details.
Never grant merchant access through a guest route.

────────────────────────────────────────
5. HOMEPAGE CONTENT AND COMPOSITION
────────────────────────────────────────

Build a substantive page with varied section layouts—not a thin hero
followed by filler.

A. Header

Compact, refined navigation with a subtle Sandbox prototype indicator.
No technical warning wall that overwhelms the product story.

B. Editorial bento hero

Use a desktop grid with a strong text block and several unequal visual
tiles. Reflow naturally into a clear mobile reading order.

Suggested headline:

“Good workshops.
Enough people.
Let’s make it happen.”

Supporting copy:

“Discover hands-on experiences and help independent hosts turn a good
idea into a workshop that can actually run. See the booking goal,
understand the deadline, and know what happens next.”

Primary CTA: “Explore workshops”
Secondary text link: “See how it works”

Hero tiles should have different jobs:
- Red graphic tile: people/seats assembling around a clear threshold.
- Workshop photography tile: hands making or learning something.
- Neutral explainer tile: “Every workshop has a tipping point.”
- Small blue tile: “No account needed to explore.”
- Small status/example tile illustrating the booking journey.

Any numbers used in a graphic must be explicitly labelled as an
illustrative example, not live bookings or business results.

Do not imply the example proves every attendance above a threshold is
viable; pack costs and final settlement checks still matter.

C. Clear explanation

Section title:
“Not another ticket page.”

Explain in plain language:
“Small workshops have real costs before the first guest arrives:
materials, space, preparation and time. Tipping Point connects those
costs to a clear booking decision, so hosts and guests can see the plan.”

Use an editorial split layout, not three identical cards.

D. How it works

Present one connected sequence with four short stages:

1. Find your workshop.
   Browse creative sessions and read what is included.

2. Reserve your place.
   Continue as a guest. Where Sandbox booking is enabled, approve a
   payment authorization rather than an immediate completed charge.

3. Reach the booking decision.
   At the cutoff, the application checks the actual booked cohort,
   approved costs, and payment outcomes.

4. Know where you stand.
   The workshop is confirmed after successful checks, or authorizations
   are released and any collected payments are handled through the
   appropriate refund process.

Use progressive detail: short visible explanations plus optional expanded
payment detail. Do not bury essential payment information in an accordion.

E. Workshop discovery preview

Show workshop cards with:
- Useful image or intentional illustration.
- Title and category.
- Date, location, and duration when known.
- Price and what is included.
- Booking deadline.
- Clearly distinguished booking and payment status.
- “View workshop” action.

Use actual public API data where available.
If none exists, use a clearly labelled “Example workshops” collection.
Do not present demo cards as real bookable inventory.

Include functional category filters and a reset/empty state.

F. Difference section

Title:
“Built around the decision to run.”

Explain concrete differences without unsupported competitor claims:
- Costs first: approved material and fixed-cost assumptions inform planning.
- Visible booking goals: guests can understand the decision.
- No mandatory account for discovery.
- Clear payment states: authorized is not the same as collected.
- A readiness plan: hosts see preparation alongside booking progress.
- Traceable inputs: sourced material offers and reviewed assumptions
  remain distinguishable.

Use mixed-width panels, typography, and a meaningful visual.
Do not fabricate testimonials or “trusted by” statistics.

G. Host section

Title:
“You bring the idea. See what it takes to run.”

Describe:
- Draft the experience.
- Review materials and pack quantities.
- Preview attendance and cost scenarios.
- Publish clear terms.
- Track readiness and booking/payment outcomes.

CTA: “Host sign in”
Secondary action: “Explore an example plan”

The example plan is public/read-only and visibly labelled.
It must not expose real merchant data.

H. Honest technology section

Create a quiet “Built with” area, not a wall of sponsorship logos.

Explain the intended roles:
- PayPal Sandbox: authorization and payment operations.
- Channel3: material-offer discovery.
- AG Studio / AG Grid: host analytics.
- Bryntum: operational timeline.
- APIMatic: API integration context during development.
- Render: hosting and workflow execution.

Inspect the repository and accurately distinguish:
Implemented, offline-tested, live-verified, planned.

Do not claim an integration is live because a logo or mock component exists.
Do not imply any sponsor endorses the product.
Do not substitute fake AG Studio or Bryntum components for their real
integrations and describe them as complete.

I. FAQ

Answer:
- Do I need an account?
- What is a workshop's tipping point?
- Am I charged immediately?
- What happens if it cannot run?
- Can I use this as a host?
- Is this currently a real-money service?

Be explicit that this is a PayPal Sandbox prototype and does not accept
real payments.

J. Closing invitation and footer

A short, strong final invitation.
Primary CTA: “Find your next workshop”

Footer:
- Product navigation.
- Host sign in.
- Sandbox/prototype notice.
- Privacy/data-use explanation appropriate to actual functionality.

Do not fabricate legal-company details, certifications, guarantees,
customer reviews, or usage metrics.

────────────────────────────────────────
6. GUEST EMAIL EXPERIENCE
────────────────────────────────────────

Interpret “guest access” as no mandatory account creation—not as
permission to bypass authentication.

Flow:
Browse publicly → choose workshop → “Continue as guest” →
enter email → proceed to the next actually supported step.

Guest form:
- Heading: “Your place starts here.”
- Label: “Email address”
- Helper text: “No password or account creation required.”
- Explain the actual use of the email.
- Explicit submit action.
- Secondary route to host sign-in, clearly separate.
- Accessible inline validation and pending/error states.
- No preselected marketing checkbox.
- No unnecessary name/address fields.

Security:
- An entered email is contact information, not proof of identity.
- Never retrieve existing bookings merely by entering an email.
- Never expose another guest's records.
- Never use email, query parameters, localStorage, or frontend state
  to mint merchant permissions.
- Do not store passwords, session tokens, or sensitive booking details
  in frontend storage.

Inspect whether server-issued guest sessions and booking endpoints
actually exist.

If they exist:
Integrate their real contract and ownership rules.

If they do not:
Implement the form UI and a clearly labelled guest-flow preview.
Explain that booking is not enabled yet.
Do not claim the email was saved, an email was sent, a reservation was
made, or payment was authorized.
Do not silently send emails to an invented endpoint.
Do not add unauthenticated backend mutation endpoints in this task.

Keep email input in transient component memory when persistence is not
supported. Do not include it in URLs, analytics, console logs, or demo data.

Likewise, do not implement magic links or email verification without a
real backend and delivery mechanism.

────────────────────────────────────────
7. HOST SIGN-IN AND EXISTING BACKEND
────────────────────────────────────────

Keep merchant sign-in accessible but secondary.

Use the actual existing endpoints and CSRF flow discovered in the repo,
including the CSRF bootstrap, login, logout, and /api/me where applicable.

Send credentials only to the same-origin backend.
Use server-issued HttpOnly session cookies.
Do not replace existing session auth with JWTs or a frontend-only flag.

Implement:
- Properly labelled login fields.
- Password visibility control.
- Generic invalid-credentials error.
- Pending state preventing duplicate submissions.
- Logout with real invalidation.
- Safe handling of session expiry.
- Clear path back to public browsing.

Never provide a “guest host” backdoor.
Do not invent registration or password-reset functionality.

If the merchant dashboard exists, preserve it and connect navigation.
If absent, provide a restrained host overview connected only to supported
APIs. Do not let dashboard expansion consume the landing-page task.

────────────────────────────────────────
8. API, DEMO DATA, AND CLAIMS
────────────────────────────────────────

Create a typed frontend API layer and explicit view models.

Keep separate:
- Real server data.
- Clearly labelled example content.
- Loading, empty, unavailable, and error states.

Do not quietly fall back from a failed real request to fake success.

If a public listing API is missing, report it and show labelled examples.
Never expose a merchant-only endpoint publicly to fill a marketing page.

When calculating displayed economics:
Use the existing backend authority where available.
Do not create a second financial engine with subtly different rules.
A frontend-only visual scenario must be labelled illustrative and must
not drive publishing, payments, or authoritative decisions.

Keep approved terms and payment status authoritative on the backend.

Never display:
- “Escrow”
- “Guaranteed group payment”
- “Instant refund”
- “Funds guaranteed for 29 days”
- “Workshop confirmed” based only on reaching a displayed headcount
- “Email sent” without an actual delivery result

Appropriate status distinctions:
Authorized / collecting / completed / release requested /
refund processing / review required.

No PayPal mutation may occur automatically on route load or button demos.

────────────────────────────────────────
9. INTERACTION, ASSETS, AND ACCESSIBILITY
────────────────────────────────────────

Use CSS Grid for the bento layout.
Do not use inaccessible absolute positioning for the entire page.

Add a few restrained details:
- Short reveal/entrance transitions.
- Subtle interactive-card hover.
- A purposeful threshold visual.
- Smooth accordion expansion.
- Clear button feedback.

Respect prefers-reduced-motion.
Do not run endless distracting animations or scroll hijacking.

Use relevant, legitimately usable workshop imagery.
Do not copy imagery from the reference or invent remote image URLs.
If no suitable licensed assets are available, use purposeful original
graphic compositions instead of broken placeholders.
Do not add a runtime AI-image-generation dependency.

Set image dimensions, responsive sizing, alt text, and error fallbacks.
Do not lazy-load the principal above-the-fold image.

Accessibility:
- Semantic landmarks and one h1 per page.
- Logical heading order.
- Skip link.
- Keyboard navigation.
- Visible focus.
- Proper modal focus/dismissal behavior if using overlays.
- Form labels and accessible error announcements.
- No colour-only status distinctions.
- At least 44px touch targets.
- Readable contrast.
- No horizontal overflow at 375px width or 200% zoom.

Keep heavy sponsor dashboards off the public landing-page bundle.
Lazy-load them only on the relevant routes if installed.

────────────────────────────────────────
10. IMPLEMENTATION AND ACCEPTANCE
────────────────────────────────────────

After a short repository assessment:
1. State the chosen design direction in a few lines.
2. Implement tokens and the public page first.
3. Implement workshop browsing/detail and guest continuation.
4. Integrate existing merchant authentication.
5. Test, inspect visually, and fix actual issues.

Do not stop after writing a plan or a component skeleton.

Verify:
- "/" opens without authentication.
- Visitors understand the product before seeing a login form.
- Main CTAs lead somewhere useful.
- Navigation and category filters work.
- Example content is labelled.
- Guest email does not grant account access.
- Unsupported booking remains honestly unavailable.
- Real host login preserves existing CSRF/session behavior.
- Existing backend tests remain unaffected.
- Frontend typecheck, lint, tests, and production build pass when run.
- Desktop and mobile layouts have been visually checked.

Use the existing browser/test tools where available.
If a tool is unavailable, report that check as NOT RUN.
Do not claim screenshots or successful tests without actual execution.

Return:
- Brief implementation summary.
- Files changed.
- Actual commands and results.
- Screenshots at approximately 1440px and 390px if supported.
- Which API integrations are real.
- Which views are labelled demonstrations.
- Remaining backend prerequisites for genuine guest booking.

The quality bar:
The first viewport should feel like the attached reference was translated
into an original, coherent Tipping Point identity—not a standard login
template with a few decorative cards added.