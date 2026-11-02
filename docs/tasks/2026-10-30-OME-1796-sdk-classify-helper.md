---
id: OME-1796
linear_url: https://linear.app/openmined/issue/OME-1796/add-clientclassify-and-sfclassify-for-the-engine-classification
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1306
created: 2026-10-30
---

# Add Client.classify and sf.classify for the Engine classification endpoint

SDK slice of hosted BYOM Unit 3. It calls the Engine endpoint from the sibling OME-1795, which
calls the Gateway operation from OME-1794; all three land in one PR.

- `Client.classify` and `sf.classify`, sync only, after the `fetch_media` precedent. Not a chat
  Model, a Router or a Recipe.
- The context is built with `json.dumps` and the url4 subrequest encoder; an input whose encoded
  request exceeds 8 KiB is refused before any network call.
- The call is never marked safe to replay. It sends `Prefer: wait=30` with a 45 second read
  timeout, so the Engine's own timeout answer arrives first whatever its configured limit.
- Typed result `Classification` with `LabelScore` pairs in upstream order, re-exported from
  `screamingface` and pinned through the top-level snapshot. url4 error envelopes, `303` artifact
  redirects and an Engine without the endpoint (capability error before any paid call) are
  handled.
- After review (spec decisions 8 and 10): an error is retryable only after a confirmed refusal
  before sending; if the classification may have run, the SDK does not recommend a retry. A lone
  surrogate is refused before any request, and a score past the float range is
  `engine_contract_error`.
- After the second review (spec decision 11): a `303` is followed only when its `Location`, as
  received, is the Engine's exact signed artifact form, so a redirect can never send the
  classification a second time.
- After the third review (spec decision 12): an Access login on the artifact fetch sends that
  fetch once more and never the classification, and every other failure there is
  `result_unavailable`, not retryable; the Engine's `result_unavailable` at any status is that
  same error; the unreachable `admission_timeout` branch is gone.

Acceptance: tests with a fake Engine transport; public surface snapshot regenerated on the
current origin/main base, keeping main's entries, and pinned by
`.claude/test-change-approvals/OME-1796.json` with both blobs from that base; a `CHANGELOG.md`
entry; `run_gates.py screamingface` green.

Spec: `docs/spec/2026-10-30-hosted-byom-unit3-classification.md`. Ledger:
`docs/work/2026-10-30-hosted-byom-unit3.md`.
