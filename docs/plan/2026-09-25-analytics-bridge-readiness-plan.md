# Bridge-aware readiness plan

1. Add regression tests covering all readiness combinations and consent/disabled
   delivery through both event endpoints. Observe failure before changing code.
2. Update only the readiness predicate and its README description.
3. Run analytics quality gates and existing Helm verification.
4. Review the diff, record results, commit and open a PR related to the existing
   bridge issue. Do not merge without a request to do so.
