# Score text validation implementation — OME-1658

Spec: `docs/spec/2026-10-30-score-text-validation-spec.md`.

1. Add HTTP regressions and demonstrate failures on existing code.
2. Add shared traversal of JSON keys/values using the existing text check; call it
   for author lists, paper URLs and submission metadata before persistence.
3. Register a validation-error handler preserving normal responses and escaping
   invalid Unicode on the fallback path.
4. Run targeted tests on both database backends, then full scoreboard gates.
5. Review the diff, record results, commit and open a linked review PR.

Review follow-up: strengthen the existing error-echo assertion, prove it detects
lost input with an isolated mutation, run both backends and gates, and update PR #1620.
