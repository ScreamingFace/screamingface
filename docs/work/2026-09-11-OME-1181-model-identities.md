---
ticket: OME-1181
stack: scoreboard
status: done
started: 2026-09-11
finished: 2026-09-11
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

## Outcome

- **Actual files:** as planned. `classification/openness.py`, `scores/schemas.py`,
  `scores/models/score.py`, `scores/migrations/0013_score_models.py`, `scores/store.py`, and two
  new test modules. Nothing under `portal/` or `routes/` was touched — this unit publishes no
  new number, per the scope boundary with OME-1145.

- **Commits:**
  - `4e5096a6` — `feat(scoreboard): classify openness per model route`
  - `a84383a6` — `test(scoreboard): pin the routing-strip guard on the unknown case`
  - `38edbc7a` — `feat(scoreboard): accept and store declared model routes`
  - `1efe798b` — `feat(scoreboard): derive stored providers from the declared routes`
  - `5b10f5f6` — `feat(scoreboard): let a same-owner replay fill in declared routes` (tests only, see Deviations)
  - `77a426ce` — `feat(scoreboard): restore the replay allowlist and add the chunked route read`

- **Gates:** `run_gates.py scoreboard --base origin/main` ALL GREEN — append-only, ruff check,
  ruff format, pyright, pytest at 88% coverage, and all three portal suites. 63 tests across the
  two new modules; no existing test was edited, so no append-only exception was needed.

- **Migration verified by hand.** Nothing in this repo applies migrations — the test fixture
  builds the schema from the models via `tortoise_test_context`, and neither the gate runner nor
  `scoreboard-tests.yml` runs one. So `0013` was applied to a fresh SQLite database directly:
  the whole chain through `0013_score_models` applied OK and the `models` JSON column landed
  (23 columns). Owner declined filing a ticket for the gate gap.

## Deviations

1. **`5b10f5f6` committed its tests without their implementation, and was red.** The mutation
   harness restores files with `git checkout`, and phase 4's implementation was still
   uncommitted when I ran it, so the trap reverted `store.py` and I staged the result without
   re-running the suite. Restored unchanged in `77a426ce`. Intermediate history is not a
   correctness problem here because the repo squash-merges, but the lesson is: never run a
   git-restoring harness against uncommitted work, and always re-run the suite between a
   mutation run and a commit.

2. **A mutation survived its own restore.** Inverting `_MODEL_RULES` is a same-size edit, and
   `git checkout` landed inside the same mtime second, so Python's bytecode staleness check
   (mtime + size) passed and pytest kept using the mutated `.pyc` while the source on disk was
   correct. Two gate runs failed against code that was already right. The harness now clears
   `__pycache__` before every run and inside the restore trap.

3. **Mutation testing found a real gap in phase 1.** Deleting `_strip_routing_prefix` entirely
   left every prefix-invariance assertion green — the open markers are consulted first, so a
   recognised open model never reaches the `openrouter` marker. The strip is load-bearing for
   the *unknown* case instead, where its absence turns an honest `unknown` into a confident
   `closed`. Guard added in `a84383a6`.

4. **`_confirm_replayable` exceeded its complexity budget** once `models` joined the replay
   allowlist. The allowlist moved into `_replay_updates`, which also gives the three correctable
   fields one place to be read. No behaviour change for `authors` or `metadata`.

5. **Bounds are 32 routes / 255 chars / 4096 bytes** as specced. The route pattern is the
   Client's own grammar, anchored, so the two ends cannot disagree about what a route is.

## Follow-on

`OME-1180` may now be built, but must not be **released** until this is deployed and confirmed
live — `ScoreSubmission` is `extra="forbid"`, so a released Client sending `models` to an
un-upgraded board 422s every submission.
