---
id: OME-2011
linear_url: https://linear.app/openmined/issue/OME-2011/declare-every-error-code-the-gateway-can-write-and-check-it-against
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1306
created: 2026-11-24
closed: 2026-11-24
---

# Declare every error code the Gateway can write and check it against the source

The Gateway declares every error code it can write, in
`apps/aigateway/tests/fixtures/gateway_error_codes/codes.json`: `codes`, the 95 codes the source
can write as a response `code`, and `retired`, the 5 codes written on `main` since frozen-copy
capture began and no longer written. A sealed copy can still replay a retired code.

An `ast` check of `src/aigateway/` fails closed. Every code write and every outbound error sink
must resolve to literals in `codes`, or be a reviewed site with its codes and its reason. A new
code fails until it is declared, a code no longer written fails until it moves to `retired`, and
`retired` must equal the audited list in the test exactly. A synthetic self-test proves the check
fails on every shape it cannot prove. No Gateway runtime code changes.

The Engine lifts only these codes (OME-2010, same PR).

Spec: `docs/spec/2026-11-23-gateway-code-provenance.md`.
Plan: `docs/plan/2026-11-23-gateway-code-provenance.md`.
Ledger: `docs/work/2026-11-23-gateway-code-provenance.md`.
Branch: `OME-2010-gateway-code-provenance`.

Merged [PR #2025](https://github.com/ScreamingFace/screamingface/pull/2025) as `afe8ec8ea`.
Linear is Done.
