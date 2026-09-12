---
id: OME-1042
linear_url: https://linear.app/openmined/issue/OME-1042/raise-providerconnectionerror-before-evaluation-starts-when-no
status: Needs Owner
type: bug
priority: medium
labels: [py-screamingface, autonomous, agentic]
created: 2026-08-31
closed:
---

# Raise ProviderConnectionError before evaluation starts when no provider is connected

Prevent dispatch when required provider access is authoritatively missing; preserve
local BYOK, hosted profiles, and supported profileless use.

Investigation found the existing connections API is insufficient for execution
access (Gemini environment-key dispatch works without a stored connection).
Awaiting decision on the proposed Gateway → Engine → Client implementation.

See docs/spec/2026-09-12-OME-1042-provider-preflight.md and
docs/plan/2026-09-12-OME-1042-provider-preflight.md.
