---
ticket: OME-1492   # PR 2 of 3, stacked on PR 1 (#1268)
stack: screamingface-engine
status: done
started: 2026-10-07
finished: 2026-10-07
---

# case-hash-seal — a broken seal says whether only the order moved

## Intent

OME-1492 PR 2. A Case Digest mismatch read only "digest X does not match Y", whether the rows were
reshuffled or rewritten. Each declaration gains an order-blind `case_set_digest`; on a mismatch
Case Preparation says "same N Cases in another order" or "same count, different Cases: text
changed", never any Case text. Spec: `docs/spec/2026-10-07-OME-1492-pr2-case-hash-seal.md`; plan:
`docs/plan/2026-10-07-OME-1492-pr2-case-hash-seal.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/case_set.py` (new):
  `case_set_digest`, `what_moved`.
- `.../prepare.py`: the `case_set_digest` field, and the 57 backfilled values.
- `.../task_replay.py`: the explanation on a Case Digest mismatch.
- `.../import_replay.py`, `.../task_replay_rows.py`: seal and write it at import.

## Test plan

- `tests/unit/inspect/test_case_set.py` (new): reorder keeps it, rewrite changes it, both
  reasons, no Case text, rows without it add nothing.
- `test_task_replay.py`, `test_import_replay.py`, `test_task_replay_rows.py` (appended).

## Acceptance

- See the spec's Acceptance (5 items).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see PR (one feature commit, one docs commit).
- **Gates:** `run_gates.py screamingface-engine --base upstream/OME-1492-pr1-bundle-provenance`
  green, no skip flag (no prior test edited: appends only). Inspect lane 1162 passed, including
  `test_published_revisions.py` (no Revision moved). Extra-less pyright clean on touched files.
- **Backfill:** 57 of 57 declarations replayed to their sealed Case Digest on 2026-10-07 (dataset
  downloads only, nothing paid); each got its `case_set_digest`, verified equal to its replay's.
- **Deviations:**
  - Design changed mid-unit (owner call 2026-10-07): the first draft stored a per-Case fingerprint
    list, `case_hashes/<key>.txt`. Its backfill showed 192,440 lines (~3.3 MB) and two files over the
    500 KB hook (bbq 58,492 Cases, worldsense 40,176). One order-blind digest per declaration keeps
    the "order only vs text changed" answer for 57 lines.
  - A Case's `id` and `case_id` are its serving position, so they're excluded from the content
    hashed; the stand-in reorder test caught this.
  - Review fixes (2026-10-07, one commit): a test that a repeated Case counts every time it
    appears ([A, A, B] vs [A, B, B] reads "text changed"; a mutation that drops copies fails it);
    the lab_bench choice-shuffle caveat in the spec's limitations and the import doc; runbook
    wording for both explanations in `adding-an-imported-benchmark.md`; a Case Set Digest
    glossary entry; the mirror's PR 2 line no longer promises a per-Case list.
- **Owner-verify:** none beyond PR 1's next paid press; a broken seal needs a dependency bump to
  observe live.
