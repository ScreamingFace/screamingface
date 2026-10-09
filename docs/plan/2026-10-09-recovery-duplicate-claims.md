# Recovery review corrections — implementation plan

1. Append function-style regressions proving duplicate-name misattribution in both
   recovery APIs, both filesystem orders, and with a malformed duplicate claimant.
   Add an unaffected third candidate and verify its partial-report provenance.
2. Add listing regressions for mixed healthy/corrupt members, counting all minimally
   identified member directories while excluding transient files.
3. Detect duplicate expected names before loading group members; ambiguous names
   produce metadata errors and never enter successful results. Calculate group sizes
   with the existing identity-based member enumeration.
4. Run focused tests and all SDK card gates; record evidence and push a normal
   follow-up commit to PR #1269. Preserve every inherited assertion.
