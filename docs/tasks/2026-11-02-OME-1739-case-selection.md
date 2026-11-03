---
id: OME-1739
linear_url: https://linear.app/openmined/issue/OME-1739/let-a-benchmark-run-use-only-a-fixed-set-of-its-questions-for-separate
status: done
type: feature
priority: none
labels: [screamingface-engine, agentic, user-request, autonomous]
parent: OME-1294
created: 2026-10-27
closed: 2026-11-03
---

# Let a Benchmark run use only a fixed set of its questions (Case ids)

A run can name a fixed list of Case ids, `cases=[3, 17, 42]`, beside `limit=N` (which always
means Cases 1 to N), so a researcher's development and held-out sets are separate, scattered
and replayable. Two PRs: Engine, then SDK.

- PR 1 (Engine): `POST /v1/benchmarks/{id}/selection` takes `{"cases": [...]}` and returns the
  resource whose recipe serves and grades only those Cases, echoing `selected_case_ids`. The
  list rides today's intent text (`3` count, `[3,17,42]` ids, 1..N written as the count), so no
  `limit=` recipe moves. Stacked on OME-1790's offset index (#1629).
- PR 2 (SDK): `sf.evaluate(..., cases=[...])`, the echo check, the post-run roll-call check,
  `selected_cases` + `selection_fingerprint` on the Report, and a refused `submit()`. Partial
  replay with `cases=` is refused (replay the run, or `limit=`), not built.

Owner decisions: explicit id lists now (no named splits), ids are our positions, selected runs
stay off the leaderboard, cap 1,000 ids, Scoreboard untouched.

Ledgers: `docs/work/2026-11-02-engine-case-selection.md` (PR 1, #1636),
`docs/work/2026-11-03-sdk-case-selection.md` (PR 2).
