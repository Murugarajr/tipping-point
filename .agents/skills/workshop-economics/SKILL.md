---
name: workshop-economics
description: Use when implementing or reviewing Tipping Point workshop material quantities, pack pricing, shipping allowances, fee estimates, break-even attendance, campaign viability, or immutable published terms.
---

# Workshop Economics Workflow

## Establish inputs
1. Read root instructions, the approved financial model, and existing calculation tests.
2. Identify currency, ticket price, capacity, minimum operating attendance, fixed costs, approved material offers, pack quantities, shipping, contingency, and fee-estimation policy.
3. Distinguish provider-returned facts from merchant inputs and explicit assumptions.
4. Missing prices or pack quantities must block automatic costing or require labeled merchant review; never ask the LLM to invent them.

## Calculate deterministically
- Use integer pence for stored amounts and decimal-safe parsing/rounding at boundaries.
- Enumerate every permitted attendance from minimum operating attendance through capacity.
- For each material item, calculate shared units plus per-attendee units.
- Round required packs upward, then multiply by the approved pack price.
- Distinguish consumables bought for this workshop from reusable equipment and make the chosen costing policy explicit.
- Add fixed costs, approved shipping allowance, and contingency exactly once.
- Subtract conservative configurable fee estimates from gross receipts.
- Select the first attendance that covers the approved budget.
- Return the complete attendance/cost curve and an infeasible result if no attendance fits.
- Do not use a simple division formula when pack boundaries make costs discontinuous.
- Label estimated surplus as an estimate, not audited profit.

## Freeze published terms
- Store a versioned snapshot and hash covering prices, offers, assumptions, costs, fees, dates, capacity, threshold, and algorithm version.
- Do not silently update published costs using newly fetched offers.
- Scenario analysis must return hypothetical results without mutating the live campaign.
- A material terms change requires the approved cancellation/new-campaign path, not rewriting existing guest consent.
- Payment settlement must recheck the approved post-capture economics policy.

## Required tests
- Exact threshold; one attendee below threshold; feasible/infeasible at capacity.
- Pack boundaries; shared plus per-attendee quantities; reusable-item policy.
- Fee rounding; shipping/contingency inclusion; mixed/missing currency rejection.
- Zero/negative inputs; capacity limits; impossible margins.
- Snapshot immutability and reproducible calculations using its algorithm version.
- Agent results match the deterministic service, not model arithmetic.

## Deliverable
Report the formula implementation, validated input sources, rounding policy, tested boundary cases, and remaining assumptions.
Do not fabricate supplier prices or claim that search results guarantee delivered stock or shipping costs.
