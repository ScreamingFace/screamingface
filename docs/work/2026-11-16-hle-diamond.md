---
ticket: OME-1863
stack: screamingface-engine
status: in_progress
started: 2026-11-16
finished:
---

# hle-diamond — add HLE-Diamond as its own Benchmark

## Intent

[HLE-Diamond](https://huggingface.co/datasets/cais/hle-diamond) is the authors' cleaned
successor to Humanity's Last Exam: 1,000 vetted questions. `hle` cannot stand in for it (397
questions missing, 80 corrected answers, 124 reworded questions), so a score comparable with
the Diamond leaderboard needs its own Benchmark. This unit adds `hle_diamond` as a local Task
that reuses inspect_evals' hle prompt and judge over the Diamond dataset. `hle` does not change.

Owner decisions (2026-11-16): the dataset card's "do not re-share" ask is accepted as for
`hle`; the Benchmark publishes the overall score and the stated confidence only, no per-half
scores.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/hle_diamond/`
  (`__init__.py`, `hle_diamond.py`, `README.md`) — the local Task.
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py` — the generated
  Case Preparation entry.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — the catalogue
  row, filled by hand from `hle`'s.
- `apps/screamingface-engine/tests/unit/inspect/test_local_task_hle_diamond.py` — the Task's
  own contract (dataset pin, ids, metadata, prompt and scorer are inspect_evals').
- `apps/screamingface-engine/tests/unit/inspect/test_hle_diamond_cases.py` — parity: the
  Candidate and the judge read what the Task hands them.
- Shared tables the importer and the row machinery need (fingerprint literal, stand-in
  metadata).
- `docs/benchmarks-fidelity/` — the Fidelity Record.
- `docs/tasks/OME-1863-*.md` — the mirror, closed at PR-open.

## Test plan

- Task contract: the loader reads `cais/hle-diamond` at the pinned commit; a row becomes the
  Sample inspect_evals' `record_to_sample` builds, except the id (`hle_diamond_` prefix) and
  the added `partition` metadata; the system prompt and scorer spec equal hle's defaults.
- Parity: one text row and one picture row through the real Task, capture and scorer adapter;
  the Candidate sees the system prompt + question (+ picture bytes), the judge's prompt is
  inspect's byte for byte.
- Row: registration, fingerprint and the extra-less catalogue lanes pass with the new row.

## Acceptance

- `hle_diamond` registers with 1,000 Cases from `cais/hle-diamond@04eeb7ef`, Case Digest
  sealed, judge glm-5.3-flash, `failure_policy="withhold"`.
- `hle`'s row, Case Digest and published revision are unchanged.
- Touched tests, ruff and pyright pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
