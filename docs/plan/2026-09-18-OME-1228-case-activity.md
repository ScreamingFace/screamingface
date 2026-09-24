# Implementation plan

1. Add failing tests for actual URL4 request transport and byte-identical plain/structured candidate input.
2. Add explicit optional candidate request envelope and run-bound benchmark context. Update shared builder and shipped call sites.
3. Attach safe Case identity in the activity plugin; keep core independent.
4. Test concurrent cases, nested runs, missing IDs, exceptions/cancellation, disabled activity and real emitted model-call records.
5. Run all Engine gates; open an independent draft against main. Keep Linear In Progress.


## Selected-case numbering — 2026-09-18

Add transport tests first. Implement shared selected-cases endpoint and protocol source, optional builder envelope metadata and scope. Verify isolated multi-candidate numbering, exact input parity and error validation. Forward safe facts and render in #980/#983. Reconcile expression fixtures only after behavioral replay; run full gates and keep PRs draft.

## Review fix — 2026-09-22

1. Add a registry regression using the shared selected-case protocol; prove a missing dataset
   fails installation and a registered dataset still evaluates successfully.
2. Extend registry discovery through local-call context source lists using the existing URL4
   parser. Cover nesting, quoted text, prose/holdings fallback and remote context boundaries.
3. Run the Engine gates against the pre-fix PR head, review the diff, and update PR #988.
