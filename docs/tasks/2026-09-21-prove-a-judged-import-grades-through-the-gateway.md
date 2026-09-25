---
id: OME-1240
linear_url: https://linear.app/openmined/issue/OME-1240/prove-an-llm-judged-imported-benchmark-grades-through-our-gateway
status: done
type: feature
priority: Medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-21
closed: 2026-09-25
---

# Prove an LLM-judged imported benchmark grades through our gateway

An imported eval's LLM judge becomes one of our own metered model calls: a
`screamingface` inspect model provider forwards judge generation through the
aigateway connector (routed, metered into `cost_usd`, identity-stamped), the
judge joins the board's revision, and misdeclarations refuse at assembly.
Proof board: **FrontierScience** (the ticket's original xstest turned out to be
a gated HF dataset; uccb carries a non-commercial licence; coconot/sosbench
fail the deterministic bake — evidence in the ticket body, 2026-09-23 reshape).

- Spec: the reshaped ticket body (2026-09-23) carries the design; spec §3.3 of
  `docs/spec/2026-09-09-OME-1113-inspect-evals-import.md` corrected in place.
- Ledger: `docs/work/2026-09-23-OME-1240-judge-gateway-provider.md`
- PR stack: #1032 (provider + context plumbing) → #1034 (judge = exam identity
  + transport binding) → #1037 (sample-metadata opt-in + importer flag) →
  #1040 (FrontierScience board) → docs PR (this one).
- Remaining after merge: the owner-run `limit=2` live run (gateway meter,
  `cost_usd`, revision pins observed on a real deployment).
