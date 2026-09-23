---
id: OME-1222
linear_url: https://linear.app/openmined/issue/OME-1222
status: In Progress
type: feature
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-17
closed:
---

# Stream benchmark-stage activity through the existing Engine logs

Instrument benchmark-owned loading, answering, grading and aggregation boundaries through the removable activity plugin. Reuse existing lifecycle, privacy and emission controls. No Client UI, exact semantic attribution, aggregate privacy policy, scoring or native URL4 redesign.

Spec: ../spec/2026-09-17-OME-1222-stage-activity.md
Plan: ../plan/2026-09-17-OME-1222-stage-activity.md
Ledger: ../work/2026-09-17-OME-1222-stage-activity.md

Validation: full Engine behavioral gates green (owner-approved append-only exception for the enum migration); 43 focused feature cases, seven healthy built-in board runs compared full/off with unchanged results/requests; independent Standards and Spec reviews clear. Endpoint implementations now own emission; shared factories declare once, installers only register routes. URL4 is unchanged. PR remains draft, not merged.

Owner workflow: remain In Progress while PR #980 is draft; move to In Review only when marked ready for review.

One shared ActivityKind defines four stages plus model_call detail. Compact/detailed client presentation does not reduce emitted records; privacy, admission and best-effort delivery still apply.

Case-phase validation: full Engine gates passed (lint, format, types, dependency layering and all tests/coverage). Seven focused signal tests passed with the Inspect extra, including actual match scorer, pending bound/cleanup, observer failure, disabled mode and candidate-check exclusion. Real HTTP/URL4 two-case IFEval with literal answers emitted both numbered case-phase outcomes through the Client, with zero invalid records. Existing expressions and golden fixtures are unchanged. Draft/In Progress retained.

2026-09-22: updated on #988, including ContractEval and MedXpertQA's shared serving spine. All eight built-in boards preserve full/off results and requests; full Engine gates pass. Inspect grading test moved to the extra-enabled CI directory with assertions intact. PR #980 remains draft / In Progress.
