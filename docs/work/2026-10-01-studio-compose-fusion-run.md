---
ticket: OME-1553 (A), OME-1554 (B), OME-1555 (D1); C and D2 filed at their PR-open
stack: repo
status: planned
started: 2026-10-01
finished:
---

# studio-compose-fusion-run — Compose Fusion runs a real fusion against a real Engine benchmark

## Intent

Make Studio's Compose Fusion page work end to end against the local Engine. The benchmarks
come from `/v1/benchmarks`. A run uses the Engine's token, WebSocket and run protocol. The
results are the Engine's `CandidateResult`. This replaces the timer-driven mock run, the
made-up scores and the canned results. It is part of OME-1308 (E18 · A local app), the
next step after the Models page (OME-1415).

## Planned changes

- Spec: `docs/spec/2026-10-01-studio-compose-fusion-run.md` (approved 2026-10-09)
- Plan: `docs/plan/2026-10-09-studio-compose-fusion-run.md` (draft)
- Code, in five PRs:
  - (A) benchmark picker;
  - (B) run client + `recipe.ts` fixes;
  - (C) Run panel wiring;
  - (D1) runtime `--benchmark-assets-dir`;
  - (D2) bundled datasets.

## Test plan

- See the plan; each slice's RED tests are listed per task

## Acceptance

- On a local Engine, a user composes a two-model fusion with a synthesizer, picks an
  installed benchmark, and runs it with a sample size. They see real progress and can
  cancel. The result shows the Engine's score, coverage, cost and per-case outputs.
- No fabricated score, latency, baseline, ranking or question text is left on the page.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

## Notes

- 2026-10-01, research: Studio's `recipeToUrl4` output with no params is canonical url4.
  Wrapping it as `(candidate:0.0:'<escaped>', <bench>)!''` matches the SDK's
  `link_candidate` byte for byte. With params, the output cannot be parsed, because
  `paramQuery` is missing `&q=`. The SDK form is `?temperature=0.7&seed=3&q=($input)`.
- 2026-10-05, live checks: these are recorded in the plan's table.
  - The attach frame's `from_sequence` must be null.
  - The result body is a JSON string.
  - A provider that is not connected gives a null score, but the run still succeeds.
  - Missing datasets give `benchmark_unavailable`; datasets work read-only.
  - DRACO needs Tavily.
- 2026-10-05, D10 measurement: two real `tauri build` DMGs, 227.3 → 304.9 MiB.
