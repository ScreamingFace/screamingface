# OME-822 — Implementation plan

## Frame

Tighten only the direct Scoreboard write DTO after the SDK producer has shipped. Preserve nullable
storage and reads, including historical/imported behavior and the existing dedup decision.

## Changes

1. Record the now-satisfied upstream gate and binding null/zero decisions.
2. Change `_validate_run_cost` and `ScoreSubmission.run_cost_usd` to non-null `Decimal` types.
3. RED/GREEN the schema, HTTP `422`, and OpenAPI-required contracts.
4. Add explicit costs to every existing direct-submission fixture under the owner-approved
   Confidence-Gate exception; retain explicit legacy-null tests through controlled model copies.
5. Update the deployment smoke payload and Client guide so shipped examples match the contract.
6. Run focused tests, full Scoreboard gates, and the public-docs checks affected by the guide copy.
7. Complete the ledger, commit, push, open the PR, link it from Linear, and move OME-822 to In
   Review.

## Non-goals

- a database `NOT NULL` migration or historical backfill;
- changing read DTO nullability or how the portal renders unknown cost;
- adding cost to recipe identity or mutating a deduplicated legacy row;
- fabricating a cost in the SDK when upstream accounting reports none.
