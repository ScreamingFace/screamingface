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
- `tests/unit/inspect/test_inspect_task_replay_benchmarks.py`: a `_STAND_IN_METADATA` table
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

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1527.json` extended
  (its `branch` now names this stacked branch, since the gate matches one branch per manifest).
- **Commits:** this branch, `OME-1527-pr5b-musique-loud-scorer`, stacked on `OME-1527-pr5-ome1513-leftovers`.
- **Gates:** `test_local_task_musique.py`, `test_published_revisions.py`,
  `test_inspect_task_replay_benchmarks.py`, `test_benchmark_declaration.py`: 197 passed. Ruff and
  extra-less pyright are clean on the touched `.py` files. The pre-push hook runs the full gate.
- **Deviations:** none.
- **Owner-verify:** the next image build re-prepares MuSiQue under the new revision
  `9ba23547b22e70ff`. Scores recorded under `1ae798e073477a54` stay on that revision.
