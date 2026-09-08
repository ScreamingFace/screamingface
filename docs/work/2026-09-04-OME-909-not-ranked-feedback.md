---
ticket: OME-909
stack: repo
status: done
started: 2026-09-04
finished: 2026-09-04
---

# OME-909 — Not-ranked submission feedback

## Intent

Tell a submitter at the successful write seam when their persisted score will not rank because its
benchmark revision differs from the board's registered revision, and carry that fact into the
Python Client's score card without changing ranking.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py` — typed POST-only ranking notice.
- `apps/scoreboard/src/scoreboard/routes/scores.py` — snapshot, compare, and return the notice.
- New Scoreboard tests — API contract, replay, boundaries, OpenAPI, and ranking regression.
- `packages/screamingface/src/screamingface/leaderboard.py` and public exports — immutable notice.
- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` — strict decoding.
- `packages/screamingface/src/screamingface/_ui/score_view.py` — SFDS warning in the receipt.
- New Client tests — value, malformed response, matching card, mismatch card, and escaping.
- task, spec, plan, and this work ledger.

## Test plan

- RED: mismatched create/replay succeeds, stores, and names both revisions.
- Boundaries: matching revision and revisionless board omit the field; missing submitted revision
  mismatches a registered board.
- Contract: OpenAPI exposes the stable reason code without changing GET score responses.
- Regression: a mismatched stored row still does not enter the leaderboard.
- Client: absence is backward-compatible; mismatch decodes to a public typed value; malformed
  notices fail closed; the warning card is accessible, escaped, and matching cards stay unchanged.
- Run both stacks' complete official gates.

## Acceptance

- Mismatched submissions remain successful and persisted with machine-readable feedback.
- Both persisted/submitted and registered revisions are present in that feedback.
- Matching submissions are unchanged.
- The Client score card says the published score is not ranked and why.
- The ranking filter is byte-identical to `origin/main` and full gates are green.

## Outcome

- **Actual files:** the planned Scoreboard schemas/route and additive route tests; the planned
  Client public value/export, decoder, card, and additive Client tests; the Client changelog and
  deliberately regenerated public-surface snapshot required by its communication guard; and the
  task/spec/plan/ledger set. No model, migration, leaderboard query, or store change exists.
- **Commits:** one conventional feature commit on `OME-909-not-ranked-feedback` (squash target;
  final merge sha will be recorded in Linear).
- **Gates:** Scoreboard `run_gates.py scoreboard --base origin/main` ALL GREEN (append-only, Ruff,
  format, Pyright, full pytest coverage ≥80%, and all three portal suites). Client
  `run_gates.py screamingface --base origin/main --skip-append-only` ALL GREEN (Ruff, format,
  Pyright, full pytest coverage ≥95%, deterministic notebooks, build, and distribution check).
  The integrated public-surface plus leaderboard modules pass 98 focused tests.
- **Deviations:** the first design used a POST-specific response subclass, but the full gate exposed
  an existing OpenAPI invariant that both POST and GET reference `ScoreSchema`. The final shared
  schema conditionally excludes only an absent notice, preserving matching/GET/private-export wire
  output while documenting the reason. `#830` merged during implementation; the branch was rebased
  onto it and both co-author and ranking-notice fields/card content were retained, with a small
  validator extraction to stay under the complexity cap. The Client's generated public-surface
  snapshot necessarily changed for `LeaderboardRankingNotice` and `LeaderboardScore.ranking_notice`;
  the owner explicitly approved this narrow Confidence-Gate exception, no existing behavioral test
  logic/assertion changed, and the changelog records the public addition. The SFDS review reused the
  existing warning semantic and palette; no visual-system token changed.
