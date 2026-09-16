---
id: OME-1191
linear_url: https://linear.app/openmined/issue/OME-1191
status: In Review
priority: Medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-11
closed:
---

# Define and retain Client version provenance at the Engine run boundary

Engine follow-up to OME-416. The owner selected the existing run-history lifetime.
Spec: `docs/spec/2026-09-11-OME-1191-engine-client-provenance.md`.
Implementation and draft PR approved on 11 September 2026.

PR [924](https://github.com/ScreamingFace/screamingface/pull/924) is ready for review.
Implementation: 63a3d361; scheduling simplification: 1486e151. Awaiting review and merge.

Review refresh (2026-09-16): rebased onto `f31084a5`, preserving answer_seed and client_version. Clarified direct-runner environment responsibility and consolidated the test import. Fixed main's new fake signature without assertion changes; 50 focused tests and full Engine gates pass, coverage 93.35%. See `docs/work/2026-09-16-OME-1191-review-refresh.md`. PR remains in review.
