# OME-1135 — Show live run activity and failures in the evaluation widget

Status: In Progress
Labels: py-screamingface, agentic, autonomous
Parent: OME-887
Linear: https://linear.app/openmined/issue/OME-1135

Local notebook Client consumes current Engine #980 activity; no older-Engine compatibility. Four stage labels in candidate status; independent expandable rows with model calls grouped by explicit activity parentage; bounded ephemeral retention and honest loss/unknown-state disclosure. No scores inferred from telemetry. Draft until owner moves PR to review.

Spec: ../spec/2026-09-17-OME-1135-live-activity-logs.md
Plan: ../plan/2026-09-17-OME-1135-live-activity-logs.md

Case-grading summary validation: 32 focused activity tests pass, including exact candidate/run/case matching, leading-zero IDs, terminal-before-start handling and preserved failures/model calls. Real local HTTP/URL4 IFEval with two fixed answers renders exactly one numbered Graded line per case and zero invalid records. Verified the resulting production HTML in Jupyter Case-grading-preview.ipynb. Engine #980 restarted locally on port 9108. No paid model calls. Full Client gates passed; final regression-inclusive gates/pre-push recorded separately. Keep draft/In Progress.

Copy control outcome: native button stays top-right inside the scrollable log box and copies only the displayed candidate/page, including timestamps and partial-history notices. Two new tests passed after RED, prior tests unchanged. Actual mouse/keyboard copy and paste verified in Jupyter; exact text and clipboard-rejection feedback checked against the generated handler. No dependencies, raw payloads, Engine changes or new data retention. Full Client gates passed: append-only, lint, formatting, Pyright, full tests with 95% coverage, notebook checks, build and distribution.

Neutral-call wording verification: 27 focused tests pass, including same-line start/retry/completion under answering and grading, original timestamp retention and safe failure details. Existing test edits are wording-only; identity, unknown-case, parentage, history, icons, retries and token-limit assertions remain. Full gate run uses --skip-append-only solely for this owner-authorized text migration; no lint/type/test/coverage gate is skipped. No Engine, wire schema, state model or new dependency changes.
