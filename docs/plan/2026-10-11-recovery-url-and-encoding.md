# Recovery correction plan

1. Add sync/async regressions for invalid saved Engine URLs and encoded successful downloads.
2. Confirm they fail at PR head 512144064a96d4c0a34128d393aec4cdb73d9345.
3. Reuse Client origin validation and HTTPX URL validation when loading saved manifests.
4. Negotiate identity artifact responses and reject encoded successes before iteration.
5. Run focused regressions and all screamingface card gates; review the final diff.
6. Record evidence and commit the follow-up on the existing PR branch.
