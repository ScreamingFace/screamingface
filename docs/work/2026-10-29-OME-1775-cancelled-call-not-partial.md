---
ticket: OME-1775
stack: screamingface-engine
status: spec
started: 2026-10-29
---

# OME-1775 — a call cancelled in a failed Case Attempt does not make a capture partial

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
