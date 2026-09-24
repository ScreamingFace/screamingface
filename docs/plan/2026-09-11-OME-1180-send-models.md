---
title: Send the declared model identities — plan
ticket: OME-1180
spec: docs/spec/2026-09-11-OME-1180-send-models.md
status: approved
date: 2026-09-11
---

# OME-1180 — implementation plan

One phase. The change is a single payload key; the work is in the guards around it and in the
one approved edit to an existing test.

## Steps

1. **RED.** Add to `packages/screamingface/tests/test_leaderboards.py`:
   - the full routes are sent verbatim — a regression to provider prefixes fails
   - `models` and `ran_with_providers` describe the same set, so the two cannot drift
   - a **fusion** sends its members *and* its synthesizer, not just the members
   - a solo sends exactly one route
   - the payload still survives `json.dumps`, as the cost tests require of theirs
2. **GREEN.** `"models": list(candidate_result.models)` in `_submission()`. Already written.
3. **Rule-5 edit (approved).** Add `"models"` to the expected key set in
   `test_the_submission_payload_gains_only_the_cost_key`. One string; nothing removed, nothing
   loosened, the set stays exhaustive.
4. **CHANGELOG.** An entry under `## Unreleased`.
5. **Gates.** `run_gates.py screamingface --base origin/main`.

## Gates for this stack differ from the scoreboard's

Coverage is **95%**, not 80%, and there are three extra gates: the deterministic notebook check,
`uv build`, and the distribution check. `uv sync --all-extras` is needed first or the suite
fails to collect on a missing `ipywidgets`.

## Stop conditions

Return to the owner rather than working around, if:

- any existing test other than the one approved in the spec needs to change
- `CandidateResult.models` turns out not to include a fusion's synthesizer
- the public surface snapshot moves (it should not — `_submission` is private)
