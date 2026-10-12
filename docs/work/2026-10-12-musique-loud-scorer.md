---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# musique-loud-scorer — MuSiQue's support-F1 scorer fails loudly on missing metadata (Work order #5, MuSiQue item)

## Intent

`musique_support_f1` read `supporting_idx` with a default of `[]`, so a Case missing its gold
paragraphs scored a reply that cites nothing 1.0 ("cited nothing, expected nothing"). Every
real MuSiQue question has 2 to 4 gold paragraphs, so a missing key means a broken Case. The
scorer now raises, as upstream bbeh's does, and the scorer adapter records a `scorer_error`.
The no-network grading lane, which used to rely on the default, now supplies realistic
stand-in metadata. The scorer's source is hashed into MuSiQue's revision, so the revision
moves once; the owner approved that on OME-1527 Work order #5. This was held out of the
`ome1513-review-leftovers` unit for that reason and is stacked on it.

## Planned changes

- `local_tasks/musique/musique.py`: `musique_support_f1` raises `ValueError` on a missing `supporting_idx`.
- `tests/unit/inspect/test_inspect_task_replay_benchmarks.py`: a stand-in metadata table
  (musique: `supporting_idx` [3, 11]) that the no-network lane merges into the stand-in Cases.
- `tests/unit/inspect/test_local_task_musique.py`: the missing-metadata test asserts the raise.
- `tests/unit/inspect/test_published_revisions.py`: musique `1ae798e073477a54` → `9ba23547b22e70ff`.
- `docs/adding-an-imported-benchmark.md` ("Importing a local Task"): the rule for the next author.

## Test plan

- The flipped test: support F1 raises with no metadata and with metadata that lacks the key;
  it still scores 1.0 when the citation matches.
- The no-network lane for musique: red after the scorer change (`[None, None]`, both Cases
  scorer errors), green with the stand-in entry.

## Acceptance

- Only MuSiQue's revision moves; every other literal in `test_published_revisions.py` holds.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except that the stand-in table lives in the shared
  `tests/unit/inspect/replayed_cases_helpers.py` as `STAND_IN_METADATA`, because a second lane
  needs it too: `test_imported_catalogue_activity.py`, which runs every judge-free Benchmark
  through the connector over one stand-in Case. Also `.claude/test-change-approvals/OME-1527.json`
  holds only this branch's entries (#1352's left with it when it merged). The guide's old
  "a scorer must tolerate missing metadata" bullet is deleted, since it contradicted the new
  rule, and #1352's ledger Gates line is corrected here (its append-only green was `OME-1575`).
- **Commits:** this branch, `OME-1527-pr5b-musique-loud-scorer`, on main after #1352 merged.
- **Gates:** `test_local_task_musique.py`, `test_published_revisions.py`,
  `test_inspect_task_replay_benchmarks.py`, `test_benchmark_declaration.py`,
  `test_imported_catalogue_activity.py`: 307 passed. Ruff and extra-less pyright are clean on the
  touched `.py` files. The first pre-push run caught the activity lane (musique solo and fusion
  scored None); the second is green. The append-only check, run by hand without `GIT_DIR`
  (the hook's own run checks nothing from a worktree, `OME-1575`), passes against main
  `1c7def312`: the four edited tests through `OME-1527.json`, no deletions.
- **Deviations:** the second stand-in lane above was not in the work order.
- **Owner-verify:** the next image build re-prepares MuSiQue under the new revision
  `9ba23547b22e70ff`. Scores recorded under `1ae798e073477a54` stay on that revision.
