# OME-822 — Require run cost on direct submissions

Status: owner-approved · Stack: scoreboard

## Problem

`OME-770` deliberately made `run_cost_usd` optional while no producer existed. That gate is now
satisfied: OME-303, OME-304, OME-306, and OME-1029 are Done, and the SDK publishes the run total.
Leaving the request field optional now lets a new direct submission enter without the economic
dimension required by the cost column and Pareto frontier.

## Decisions

### D1 — Required at the direct request boundary

`ScoreSubmission.run_cost_usd` is a required, non-null `Decimal`. Omitting it or explicitly sending
JSON `null` returns a `422` field error, and OpenAPI lists the field in the schema's `required` set.

### D2 — Nullable storage and reads stay intact

The `Score.run_cost_usd` database column and all read DTOs remain nullable. Imported and historical
rows legitimately have unknown cost and continue to serialize as `null`. There is no migration or
backfill.

### D3 — Zero is real data, not an unknown fallback

`0` remains valid and normalizes to `0.000000`; it means the run genuinely cost nothing. Neither an
omitted nor a null direct cost is coerced to zero.

### D4 — Existing money normalization is unchanged

The OME-770 limits and normalization remain the only validator: finite, non-negative, at most
`999999.999999`, six decimal places, positive sub-quantum values rounded away from zero, and
negative zero normalized.

### D5 — Dedup and historical rows do not mutate

Cost remains excluded from recipe identity. A pre-existing null-cost row can still win dedup and
remain null; this is the accepted OME-770 behavior and no fill-in or backfill is added here.

### D6 — Unpriced direct runs are rejected deliberately

OME-1029 preserves a possible `None` from upstream rather than inventing zero. After this contract
lands, such a direct publish receives `422`. That is the enforcement requested by this ticket: a
client must obtain a real total before publishing, while old/imported rows remain readable.

## Verification contract

- schema validation rejects omitted and explicit-null cost;
- the real POST route returns `422` at `body.run_cost_usd` for both shapes;
- OpenAPI marks the field required;
- all existing direct-submission fixtures supply explicit realistic costs;
- nullable read-path regressions remain green;
- the deployment smoke request includes an explicit zero-cost value.

## Confidence-Gate exception

This contract change necessarily updates existing direct-submission fixtures and the prior test
that asserted omission becomes `None`. The owner explicitly approved that append-only-test
exception in the implementation session. Production behavior—not the tests—defines the new
contract, and the full Scoreboard gate must remain green with the exception recorded.
