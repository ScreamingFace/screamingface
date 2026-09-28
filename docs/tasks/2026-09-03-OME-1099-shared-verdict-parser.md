---
id: OME-1099
linear_url: https://linear.app/openmined/issue/OME-1099/merge-the-three-drifted-judge-verdict-parsers-into-one-typed-shared
status: done
type: task
priority: medium
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-03
closed: 2026-09-11
---

# Merge the three drifted judge-verdict parsers into one typed shared parser

Verdict parsing (judge reply → record with mandatory audit fields) exists four times —
the check surface in `rubric_check.py` and per-board copies in `draco/verdict.py`,
`healthbench/verdict.py`, `gdpval/verdict.py` — and the copies have drifted (OME-1023:
the newest copy silently dropped the raw reply on valid verdicts, and nothing caught it).

Merge the parsing into one spine module with a typed record whose audit fields (raw
reply among them) are required constructor arguments, so omitting one fails typecheck.
Boards keep their own verdict semantics by declaring their shape (schema, status field,
enum vs strict boolean, reason vocabulary). Delivers OME-1025. Wire records stay
byte-identical; draco-3pass and healthbench-worst30 goldens stay green.

Ledger: `docs/work/2026-09-09-OME-1099-shared-verdict-parser.md`
