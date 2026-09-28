---
id: OME-1390
linear_url: https://linear.app/openmined/issue/OME-1390/reports-say-a-case-is-missing-when-the-model-actually-ran-out-of
status: done
type: bug
priority: medium
labels: [screamingface-engine, agentic, design-session]
parent: OME-1299
created: 2026-09-28
closed: 2026-09-28
---

# Reports say a case is missing when the model actually ran out of tokens

On the shared scored path, a Case whose row was lost to a collected error published
`missing_case_row`, with the real cause (`model_token_cap`, `provider_error`, …) one level down in
`metadata.source_error`. IFEval already published the real cause at the top.

Owner decision (2026-09-28): lift any declared source code onto the missing-row Failure's
top-level code; a source error with no code keeps `missing_case_row`; `case_error` and DRACO's
`case_result_missing` are out of scope; `metadata.source_error` stays.

- 2026-09-28: filed.
- 2026-09-28: owner decision recorded; implementation on branch
  `OME-1390-lift-missing-row-source-code`.
- 2026-09-28: PR #1088 green (24 checks pass). Closed on merge.
