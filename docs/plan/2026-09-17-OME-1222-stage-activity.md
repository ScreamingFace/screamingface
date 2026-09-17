# OME-1222 revised implementation plan

1. Add RED tests calling shared endpoint factories directly under an observer and log sink, plus async decorator failure/parentage coverage.
2. Expose one observe_stage decorator backed by the existing optional observer and fault guard; no stage_scope or reports_stage APIs. Document partial-entry cleanup and ignored suppression.
3. Move shared aggregation, case reduction, rubric checking and candidate answering emission into the implementations that own the work. Move remaining board-owned stage scopes into their actual producers; remove installation-time wrappers.
4. Keep URL4, grading hooks, route definitions, payloads, deployment policy and old tests unchanged. Run stage tests and full Engine gates; independent review.
5. Update justified PR/ticket descriptions, push to the existing draft. Keep Linear In Progress.
