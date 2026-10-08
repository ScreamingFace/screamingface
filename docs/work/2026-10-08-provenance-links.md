---
ticket: OME-1524   # filed before work start (owner-authored)
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-08
finished: 2026-10-08
---

# provenance-links — each paid-smoke dataset source links to its pinned commit, and the labels ship in the debug bundle

## Intent

OME-1492 gave every bundle a `provenance.json` label and the paid smoke's run page a "Where the
Cases came from" table, but the "Read from" cell is plain text that cannot be turned into a link
from the text alone (`TsinghuaC3I/MedXpertQA/Text` is a config, `dgslibisey/MuSiQue/<file>` is a
file, IFEval's vendored file is on GitHub), and the labels die with the CI runner. This unit adds
a `url` to every Case Source, built by the code that read it and pointing at the pinned commit;
renders it as a link on the run page; and copies each picked Benchmark's label into the debug
bundle as `provenance/<benchmark>.json`. No existing label field, Case or score changes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/bundle_provenance.py`: the one
  link builder (Hugging Face tree/blob at a commit, GitHub blob at a commit, only for a full
  40-hex commit); `hugging_face_source` adds `url`.
- `.../benchmarks/ifeval/prepare.py`: the vendored-file source gets its GitHub `url`.
- `.../screamingface_engine_inspect/case_sources.py`: `CaseSource.url` (optional, outside
  equality), filled by each describer at record time.
- `.../screamingface_engine_inspect/replay_provenance.py`: the label omits `url` when None.
- `packages/screamingface/tests/paid/_case_provenance.py`: link vs plain text, Markdown
  escaping, http(s)-only links; `copy_labels` into the log folder.
- `packages/screamingface/tests/paid/test_imported_board_smoke.py`: copy the labels beside
  `summary.md`.
- Prior-test edits (owner-approved, pinned in `.claude/test-change-approvals/OME-1524.json`):
  `tests/unit/_bundle_provenance_checks.py::hugging_face_source` and the IFEval vendored-file
  literal in `tests/unit/test_ifeval_prepare.py` gain the `url` key.

## Test plan

- Engine: one test per source-kind row (HF load with/without config → tree; HF single file →
  blob; GitHub vendored file → blob; http(s) URL → itself; unpinned / non-commit revision /
  package file / non-dataset repo → none), through the recorder and the hand-built preparers.
- Replay label: a source with no link has no `url` key.
- SDK paid helper: link rendered, plain text without one, `|`/`]` escaped, a `javascript:` url
  never becomes a link, one copied file per picked Benchmark (shared bundles resolved), missing
  label skipped, never `cases.json`.

## Acceptance

- After a prepare, musique's label carries the `blob/<sha>/musique_ans_v1.0_dev.jsonl` link,
  medxpert's the `tree/<sha>` link, gdpval's unpinned source none.
- The run page row for a linked source is `[location @ pin](url)`.
- The debug bundle has `provenance/<benchmark>.json` per picked Benchmark, never `cases.json`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/test_bundle_provenance_links.py` and
  `tests/unit/inspect/test_case_source_links.py` (new; `test_case_sources.py` is past 450
  lines), the spec, the plan, the task mirror and `.claude/test-change-approvals/OME-1524.json`.
- **Commits:** see the PR (one commit).
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN; `run_gates.py screamingface`
  ALL GATES GREEN (needs `uv sync --extra notebook --inexact` first); extra-less Engine pyright
  0 errors; paid lane free tests with `SCREAMINGFACE_TEST_PAID=1`: 50 passed, 1 skipped (the
  smoke itself, no stack).
- **Deviations:** (1) `web_url()` is unchanged and the link is a new `url` field, because the
  importer writes `web_url()` into new declarations; (2) one link builder in core, which the
  plugin imports, instead of one per side; (3) the paid lane's code under `tests/` reads as
  prior tests to the append-only check, so `_case_provenance.py` and
  `test_imported_board_smoke.py` are pinned in the approvals file too (as OME-1492 and
  OME-1500 did); (4) two recorder tests use stand-in repo ids, because the real MedXpertQA
  and MuSiQue repos can sit in the local Hub cache and the offline call then succeeds.
- **Owner-verify:** on the first press after merge (which re-prepares every bundle once,
  because the asset cache key moves), the MuSiQue row on the run page is a link that opens
  `musique_ans_v1.0_dev.jsonl` at `c8f4f8c9…`, and the debug bundle holds
  `provenance/<benchmark>.json` for every row and no `cases.json`.
