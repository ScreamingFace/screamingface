---
id: OME-1790
linear_url: https://linear.app/openmined/issue/OME-1790/store-imported-boards-one-file-per-case-so-runs-never-load-the-full
status: in_review
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-10-30
closed:
---

# Store imported boards so runs never load the full bundle (Option B: offset index)

An Imported Benchmark's Cases are one `cases.json`; every Cases-route call read and parsed all
of it, so a 2-Case FigQA run paid for 330 MB. The prepare step now also writes
`cases.offsets` (16 bytes per Case: offset and length of each row inside `cases.json`) and
`board.json` (`case_count`, `has_pictures`, `cases_bytes`), both before `cases.json`, which
stays byte-for-byte the same and stays the completion marker.

- The Cases route reads only the selected rows through the index; envelope boards wrap only
  those rows.
- Picture admission reads `has_pictures` from `board.json` instead of scanning every row.
- A bundle with no index (old local/CI cache) falls back to the full read and logs a warning;
  a stale index is a bounded "cases are unavailable" error, never wrong rows.

Owner decisions: Option B, wider scope (route + admission here). Out of scope: check-surface
lookup, ContractEval dedupe (OME-1675), per-run budget, aggregation (OME-1789).

CI: no cache-key change; the content-hashed bundle keys already rebuild with this writer.
Follow-up: OME-1789 grading moves onto `board_store` after #1628 and this PR merge.

Spec: `docs/spec/2026-10-30-OME-1790-board-per-case-storage.md`.
Ledger: `docs/work/2026-10-31-board-offset-index.md`.
