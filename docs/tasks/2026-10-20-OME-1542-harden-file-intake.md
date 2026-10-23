---
id: OME-1542
linear_url: https://linear.app/openmined/issue/OME-1542/harden-file-intake-in-the-gateway-body-cap-data-uris-only-anthropic
status: done
type: feature
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1529
created: 2026-10-09
closed: 2026-10-23
---

# Harden file intake in the gateway: body cap, data: URIs only, Anthropic system images

A configurable request body cap (413 naming the limit), image and file parts accepted only as
`data:` URIs so the gateway never fetches a caller's URL (Codex keeps forwarding https image URLs,
which OpenAI fetches), and a typed 422 for media in an Anthropic system prompt instead of a silent
drop. Spec `docs/spec/2026-10-20-harden-file-intake.md`, plan
`docs/plan/2026-10-20-harden-file-intake.md`, ledger `docs/work/2026-10-20-harden-file-intake.md`.

- 2026-10-09: ticket filed by the owner (Backlog).
- 2026-10-20: Khoa's input on the cap: MMMU's largest Case is 3.78 MB inline; 8 MB proposed.
- 2026-10-20: implemented on branch `OME-1542-harden-file-intake`; PR [#1479](https://github.com/ScreamingFace/screamingface/pull/1479) opened (Refs: OME-1542), reviewer HupBaHa.

Merged in PR #1479 as `a2cbf70ba` on 2026-10-23.
