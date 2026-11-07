Fix the disabled controls and unclear prerequisites in the existing
Materials and Review & publish workflow.

Inspect the actual disabled expressions, save handlers, preview state,
and publish prerequisites before changing code.

Observed UI:
- Route remains /host/workshops/new.
- Header shows Unsaved changes and Create draft.
- Review shows booking dates Not set.
- Materials says No material lines yet.
- Channel3 budget acknowledgement is disabled.
- Review acknowledgement and publication controls are disabled.

1. Verify draft creation.

Clicking Create draft must either:
- Save successfully and navigate to the persisted workshop's route, or
- Display specific field/server errors.

Do not silently leave the user on /new after successful creation.
Preserve entered data on failed requests.

2. Explain disabled prerequisites beside the affected control.

Examples:
- “Save this workshop before searching for materials.”
- “Add booking dates in Basics.”
- “Save your changes before running the preview.”
- “Run a successful preview of the current saved terms before publishing.”

Use links/buttons to the required action.
Do not make the user guess why a checkbox is disabled.

3. Verify material persistence.

Entering a material is not the same as adding it.
Make the Add material action and subsequent save requirements clear.
Show added lines immediately and distinguish unsaved from saved lines.

Do not accidentally publish without an entered material the user believed
was already included.

4. Fix review-state sequencing.

Enable the review acknowledgement only when its actual prerequisites
are satisfied.

Bind acknowledgement and successful preview to the current saved terms
version/hash. Relevant edits must invalidate stale preview/acknowledgement.

Preserve backend validation and immutable-publication safeguards.
Do not solve this by removing all disabled conditions.

5. Keep Channel3 separate from publication.

The development request-budget acknowledgement is not a financial-terms
acknowledgement and must not block manual-material publication.

Do not make provider calls, reset the existing request budget, or treat
checking the box as permission to exceed it.

If provider search cannot run, explain why while allowing the supported
manual-material workflow to continue.

6. Test the actual sequence:

New workshop → create → persisted route → add material → save →
complete dates → save → server preview → acknowledge → publish.

Also test failed save, invalid dates, preview failure, and editing after
acknowledgement.

Use existing dependencies and repository .venv.
No live provider calls, payment operations, schema changes, deployment,
commits, or pushes.

Report the exact disabled conditions found, changes made, and tests run.