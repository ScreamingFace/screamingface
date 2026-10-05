---
ticket: OME-1448
stack: screamingface
status: complete
started: 2026-10-01
finished: 2026-10-01
---

# Report regression audit

## Intent

Review the full PR against fixed base fd565a2fdff92c70f648f25f999f7101ddca2217, independently check standards/spec, and reproduce/fix regressions beyond the existing suite.

## Planned changes

Investigate limited-evaluation recovery, saved metadata isolation, concurrent report work and shared-cache compatibility. Add regression tests before any confirmed fix; update draft PR with outcomes.

## Test plan

Independent read-only standards/spec reviews; adversarial reproductions against actual saved reports; targeted tests and full SDK gates for fixes. Existing full workload and production-platform limitations remain explicit.

## Acceptance

Confirmed actionable regressions fixed and tested, reviews resolved or reported, all required gates pass. No unsupported claim of production validation.

## Outcome

Independent Standards and Spec reviews reproduced the premature-ready marker and unrelated-manifest poisoning. Parent reproduced recovery failure when an evaluation selected fewer cases than the benchmark contains. Seven new adversarial regression tests failed before fixes and now pass: limited sync/async recovery, damaged/unsupported unrelated metadata isolation and explicit diagnostics, incomplete damaged-sibling reporting, second interruption during grouped recovery, and disk work off the async event loop.

Recovery now rebuilds the selected case count as a limit, marks the evaluation running before decoding and ready only after the complete group is assembled. Invalid saved records are isolated and warned about during listing; explicit access still raises a structured error, files remain untouched, and missing siblings produce a partial report. Async recovery moves copying, integrity verification and decoding/indexing to worker threads.

Remaining Spec finding: clicking a case rail row changes CSS radio selection only. Changing candidate preserves the last Go-to/page focus rather than the manually selected row. This finding was open at audit completion and is resolved by the subsequent persistence follow-up: ipyevents synchronizes typed selection, with callback tests and live JupyterLab verification. See 2026-10-01-report-persistence-followup.md. No claim of zero regressions is made. Real hosted and Ubuntu/VSCode validation remains pending.

Full SDK gates passed: append-only tests, Ruff lint/format, Pyright, full pytest with >=95% coverage, deterministic notebook verification, package build and distribution checks. Independent reviewer rechecked fixes and ran all 30 focused recovery/notice tests successfully. Existing committed tests unchanged; new tests are append-only.
