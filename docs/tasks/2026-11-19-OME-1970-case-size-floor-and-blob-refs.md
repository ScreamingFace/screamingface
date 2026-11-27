---
id: OME-1970
linear_url: https://linear.app/openmined/issue/OME-1970/check-every-case-against-the-hosts-size-floor-when-it-is-sealed-and
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, design-session]
parent: OME-1330
created: 2026-11-19
closed:
---

# Check every Case against the hosts' size floor when it is sealed, and send Case files by blob reference

OpenRouter picks the host for every model call, and the smallest host (Amazon Bedrock) refuses
pictures and requests that our 8 MB Case limit lets through. So a sealed Case could pass or fail
depending on the host. The team decided on 24–25 Nov: every Case fits the measured floor of
every host, checked once at seal time (5,242,880 bytes of base64 per picture, 8000 px a side,
about 20 MB of base64 per PDF, 30,000,000 bytes per Case), and Case files travel to the gateway
by blob reference so a Fusion's memory stops multiplying with its member count. Planned as a
stack of 9 PRs.

- 2026-11-26: PR 1 fits HLE's one picture over 8000 px (Case 250, HLE Diamond Case 35), which
  failed on every Claude Candidate and on GPT-6 Astra Pro and GPT-6.1 Terra Pro in the 6 Nov
  runs. PR 2 adds the per-picture check at seal (bytes, side, GPT's 32 px patch count) and re-sends
  `labbench2_figqa2_img` Cases 4 and 82 as lossless WebP (published id held, owner's call).
  PRs 3 and 4 build the gateway's cache key for a reference request and its upload route and
  file store.
