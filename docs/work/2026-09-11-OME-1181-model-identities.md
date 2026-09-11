---
ticket: OME-1181
stack: scoreboard
status: in_progress
started: 2026-09-11
finished:
---

# OME-1181 — Accept and store model identities, and classify openness per model

## Intent

The Scoreboard cannot tell an open-weights model from the router that carried it. The Client
truncates every declared model route to its first path segment, so all seven live
`draco-3pass` entries store `ran_with_providers = ["openrouter"]` and an entry named
`best_open_source` is classified closed.

This unit gives the Scoreboard the **inputs** to do better: accept and store the declared
model routes, derive providers from them, and classify a route rather than a provider prefix.
It does not change any published number — `OME-1145` owns the metric and the response shape.

It ships and **deploys** before `OME-1180`, because `ScoreSubmission` is `extra="forbid"` and
an older Scoreboard 422s an unknown top-level field.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py` — `models` on `ScoreSubmission` with its
  bounds validator; `models` on `ScoreSchema`; `ModelRoute` annotated type.
- `apps/scoreboard/src/scoreboard/scores/models/score.py` — nullable `models` JSONField.
- `apps/scoreboard/src/scoreboard/scores/migrations/0013_score_models.py` — the AddField,
  mirroring `0012_score_authors.py`.
- `apps/scoreboard/src/scoreboard/scores/store.py` — `_submission_to_kwargs` carries `models`;
  `_score_to_schema` projects it; `_derived_providers()`; the chunked frontier-scoped read.
- `apps/scoreboard/src/scoreboard/classification/openness.py` — `classify_model()`, route
  normalisation, the three registry carve-outs.
- `apps/scoreboard/tests/unit/...` — additive tests only.

## Test plan

RED first. Full list in the spec's acceptance section; the invariants that need a guard rather
than a restatement of the diff:

- a route with and without the `openrouter/` prefix classify identically
- `gemma`, `gpt-oss` and `kimi` each classify open, and each fails if its carve-out is removed
- `unknown` is distinguishable from `closed` in the return value, not merely in the log
- an oversized `models` payload returns a field error, not a 500
- `models` is absent from `_content_hash`, so a resubmission carrying it dedups to the same row
- the chunked read is exercised above one chunk boundary

## Acceptance

See `docs/spec/2026-09-11-OME-1181-model-identities.md`. Summary: an optional `models` is
accepted, bounded, stored, projected and classifiable; a submission without it still succeeds;
the migration ships in this iteration; full Scoreboard gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
