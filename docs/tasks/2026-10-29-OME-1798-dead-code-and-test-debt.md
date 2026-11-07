---
id: OME-1798
linear_url: https://linear.app/openmined/issue/OME-1798/remove-profile-era-dead-code-and-clear-the-close-out-test-debt-l4b
status: done
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-30
closed: 2026-11-02
---

# Remove Profile-era dead code and clear the close-out test debt (L4b)

`ProfileNotFoundError`, `ProfilePendingAuthError`, `PairAuthorityStore.providers()`,
`ORMStore.mutate` with `CredentialBlobMutationConflict`, and `core/credential_names.py` are gone;
`credential_name_for` lives in the test helper `tests/credential_names.py`. Profile-era comments
read in Connection terms, the import-boundary, retired-module, K4 and T-F5 guards are
non-vacuous, and the spec §4.4 test-debt table is cleared as amended on 2026-11-02 (T-F2: the
async probe is live, only its `mutate` goes). No request-visible behaviour changes.
Built on OME-1784 (L4a), merged first; the PR targets `main`. Spec `docs/spec/2026-10-29-ome-1138-closeout.md`
§4.4, plan `docs/plan/2026-10-29-ome-1138-closeout.md` section L4b, ledger
`docs/work/2026-10-29-dead-code-and-test-debt.md`.

- 2026-10-30: filed, implemented, PR opened.
- 2026-11-02: squash-merged to `main` as `3009c8362` (PR #1642). Linear closed the issue Done
  the same day with the close comment.
