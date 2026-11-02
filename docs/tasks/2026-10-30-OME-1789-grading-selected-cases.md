---
id: OME-1789
linear_url: https://linear.app/openmined/issue/OME-1789/grading-reads-only-the-selected-cases-not-all-of-casesjson
status: in_progress
type: improvement
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-10-30
---

# Grading reads only the selected Cases, not all of cases.json

The aggregate's roll-call reader (`shared_grading/case_grades.py::read_selected_cases`) no
longer reads and parses the whole `cases.json`. A new `shared_grading/case_rows.py` streams the
top-level array one element at a time (chunked `json.JSONDecoder.raw_decode`) and the reader
keeps only the selected rows, so aggregation memory scales with the selected Cases (plus one
row), not with the board. Same selection rule, same error prefixes; no per-Case storage
(OME-1790) and no change to the Cases route (OME-1675).

Measured on a synthetic FigQA-shaped board (181 Cases, 328 MB), peak RSS added by the reader:
2 Cases 946 MiB -> 50 MiB; 181 Cases 946 MiB -> 404 MiB. Selected rows byte-identical.

Ledger: ../work/2026-10-30-grading-selected-cases.md
