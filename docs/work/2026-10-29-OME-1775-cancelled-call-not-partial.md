---
ticket: OME-1775
stack: screamingface-engine
status: plan
started: 2026-10-29
---

# OME-1775 — a capture is not partial for an outcome that a replay reproduces exactly

## Intent

Stop marking a capture `partial` when the only unstored calls are sibling calls that the Engine
cancelled after their Case Attempt had already failed. Spec:
`docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md`. Order: spec → owner approval →
plan → code.

## Evidence (2026-10-29, prod, read-only plus one $0 replay)

- 10 of 135 linked scores were `partial`. All 10 were fusions with failed cases (7
  healthbench-professional, 3 frames_oracle). Every single-model score and every fusion with no
  failed case was `complete`.
- The 7 healthbench copies: 1 entry per key, no error-then-200 key, no multi-200 key, max
  occurrence 0. So no retry caused `partial`.
- Replay of healthbench `pareto_cross` (score `22f3f25a`, copy `40bb8797`) through the SDK, with
  only the Scoreboard lookup skipped: `_classify` = `exact`. Score 0.503 = 0.503, 525 cases,
  `case_digest` equal, the same 49 `model_token_cap` case ids. Gateway: 3073 hits, 0 misses, 3
  `ClientDisconnect` (replay-time sibling cancels).
- Data fix (owner order): the 10 rows were set to `complete`. Backup:
  `~/sf-backups/partial-to-complete-2026-10-29/`.

## Log

- 2026-10-29: OME-1775 filed under OME-1307 (project ScreamingFace Q4, milestone Reproducibility
  & credit). Worktree `.claude/worktrees/ome-1775-cancelled-call-not-partial` from `origin/main`
  4909d7128. Spec drafted.
- 2026-10-29: owner decisions D2 (Case level), D3 (no new count), D5 (test changes approved).
- 2026-10-29: D4 = no SDK verdict change; accept the rare false `failed` verdict.
- 2026-10-29: owner asked for a check of every outcome for false `partial` labels. Two scouts read
  the gateway capture path and the url4 failure path. Findings: the gateway stores before it
  responds and strips `cache` from the key digest; a failed `;optional` member is dropped with no
  code or text downstream; a replay miss is permanent; `_deadline_exceeded` and 429/5xx are
  retryable. New rules: R1 widened to all no-answer outcomes in a failed Case, with a retry guard
  (§4.1, a url4 retry that the replay does not make); R2 `max-age` re-issue; R3 connect-phase
  failure. Owner accepted D1a–D1e ("yup"). Spec rewritten.
- 2026-10-29: Linear title renamed to "Do not mark a capture partial for an outcome its replay
  reproduces exactly". Plan written: `docs/plan/2026-10-29-OME-1775-replay-exact-not-partial.md`.
  Scouts confirmed one tally per run, the final Case results all pass `finalize_candidate_result`,
  and the aggregation ends before the summary. So the tally collects the Case results itself (spec
  E5/E6 changed, no executor change). Five prior tests change (R2/R3). Open: P1 (aigateway contract
  test sub-issue), P2, P3.
