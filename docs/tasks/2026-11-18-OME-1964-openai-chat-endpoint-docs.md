---
id: OME-1964
linear_url: https://linear.app/openmined/issue/OME-1964/document-the-openai-compatible-chat-endpoint-in-the-public-docs
status: in_review
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1297
created: 2026-11-18
closed:
---

# Document the OpenAI-compatible chat endpoint in the public docs

The public docs get the guide page `/sf-client/guides/openai-api`: the base URL, the two forms
of the `model` field, hosted access, examples for the OpenAI Python SDK, pi and opencode, the
answer shape, streaming, tools, the error codes, and each limit of the feature. Engine tests run
the Python examples and check that the page states each limit.

- Parent epic: `OME-1297`. It ships in the PR of `OME-1963`.
- Spec: `docs/spec/2026-11-17-engine-openai-chat-endpoint/prd/docs.md`
- Ledger: `docs/work/2026-11-17-engine-openai-chat-endpoint.md` (unit U7)
- Not checked: the pi and opencode examples against the clients (the page says so).
