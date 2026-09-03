# OME-922 — Partial submission warning

Status: approved by owner, 2026-08-20 · Stack: screamingface

## Problem

`sf.evaluate(..., limit=N)` can produce a valid score with 100% coverage of the selected
Cases even though it covers only part of the Benchmark. Submitting that Candidate currently
looks identical to submitting a full run. The public leaderboard currently accepts and ranks
partial submissions, but their scores cover fewer Cases and are not directly comparable with
scores from full runs.

## Contract

- `sf.leaderboards.submit(candidate)` and its async equivalent surface this message for a
  partial but otherwise valid score:

  > Partial submission. This score may appear on the public leaderboard, but it is based on
  > fewer benchmark cases and is not directly comparable with a full-run score.

- A Candidate is full only when both conditions hold:
  - its Case count equals `candidate.benchmark.case_count`; and
  - its Engine-owned `coverage` is `1.0`.
- In notebooks, a branded, non-error-looking `Partial submission` notice is displayed after
  the Scoreboard confirms publication. It remains visible when the returned score is assigned,
  collected in a list, or captured by papermill/nbconvert; it does not also emit a Python warning.
  If the host's rich display publisher fails, plain stderr carries the advisory and the already
  persisted `LeaderboardScore` is still returned.
- Outside notebooks, the Client emits the existing `sf.EvaluationWarning` before the write so
  scripts and logs do not lose the advisory. Warning filters retain normal Python semantics:
  treating that category as an error aborts before any Scoreboard side effect.
- The advisory does not modify the submitted payload. With the ordinary warning policy, a valid
  partial score is still published unchanged.
- A full run emits no warning.
- Existing validation remains authoritative; an unscored Candidate is rejected rather than
  described as a successful submission.
- A serialized `CandidateResult` retains its Benchmark's complete Case count. The enclosing
  `Report.case_count` continues to record how many Cases that Evaluation selected, so a saved
  limited Evaluation remains recognisably partial when reconstructed for later publication.

## Non-goals

- Enforcing full-run ranking in `apps/scoreboard`.
- Adding a new public result type or notice field to `LeaderboardScore`.
- Changing warning-filter configuration or introducing another warning category.

## Presentation

- Follow the canonical `OpenMined/screamingface-brand` status recipe at commit `7ea35a1`:
  persimmon warning semantics, a solid status square, square edges, no shadow, and no
  decorative gradient.
- Scope the canonical light and dark persimmon tokens to this submission notice. Existing Report
  warning states keep their amber palette so warning and error surfaces remain distinguishable.
- Keep the returned `LeaderboardScore` and its `Score published` receipt unchanged. When it is
  the cell's final expression, the branded advisory appears once before the ordinary score card.

## Design note

- The submission result remains the existing public `LeaderboardScore`. A process-local
  `ClientNotice` is displayed after a successful notebook write; it is not stored on the score,
  pickled, copied, compared, hashed, or sent to the Scoreboard.
- `ClientNotice` is a reusable internal primitive with a stable code, `info` or `warning`
  severity, title, and body. OME-922 migrates only its own advisory; converting unrelated
  client warnings is deliberately separate scope.
- Notebook presentation uses the shared host-environment capability detector, including hosted
  shells whose concrete Colab/Databricks class inherits from ipykernel. Evaluation progress
  retains its established, separately named `ipykernel_loaded` capability because it can safely
  fall back when a rich panel cannot be constructed.
