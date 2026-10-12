# Recovery duplicate claims and retained storage — OME-1503

The user approved fixing and pushing both PR #1269 review findings.

When multiple saved member manifests claim the same expected candidate name,
recovery must not choose one by filesystem ordering. Settle the ambiguous name
as `result_metadata_invalid`, preserve healthy unambiguous siblings, and retain
the existing `candidates_failed`/`partial_report` contract. Detect ambiguity even
when one claimant's full metadata cannot decode. A canonical candidate-name list
does not establish which duplicate run owns that slot.

Listing's `size_bytes` counts every locally identified saved member directory in
the evaluation, independently of full metadata decoding. Preserve the existing
exclusion of hidden temporary files and canonical evaluation metadata directories.
No new metadata schema, public API, dependencies, or Engine changes are required.
