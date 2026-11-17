---
id: OME-1941
linear_url: https://linear.app/openmined/issue/OME-1941/send-the-account-connection-scope-in-the-sdk-hosted-byom-test-fixture
status: in_progress
type: task
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1138
created: 2026-11-17
closed:
---

# Send the account_connection scope in the SDK hosted BYOM test fixture

Since `OME-1781` the gateway sends the model-parameter scope `account_connection`. One SDK test
fixture, in `packages/screamingface/tests/test_hosted_byom_preflight.py`, still sent
`account_profile`; it now sends `account_connection`. The SDK passes the scope through as opaque
text, so no SDK behaviour changes. The gateway part is `OME-1940`, in the same PR.

- Spec: `docs/spec/2026-11-16-ome-1138-leftover-profile-wording.md` §2.4
- Ledger: `docs/work/2026-11-16-retire-leftover-profile-wording.md`
- 2026-11-17: filed under `OME-1138` with `OME-1940`; the PR opened. In Progress.
