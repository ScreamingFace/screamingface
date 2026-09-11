---
id: OME-1181
linear_url: https://linear.app/openmined/issue/OME-1181/accept-and-store-model-identities-and-classify-openness-per-model
status: In Progress
type: task
priority: 2
labels: [scoreboard, agentic, autonomous]
parent: OME-1179
created: 2026-09-10
closed:
---

# Accept and store model identities, and classify openness per model

Scoreboard half of `OME-1179`. Provides the **inputs** to classify openness by model rather
than by the reseller that carried the request. Publishes no new number — `OME-1145` owns the
metric and the response shape.

| | |
| -- | -- |
| Accept | optional `models` on `ScoreSubmission`, capped at 32 routes / 255 chars / 4096 bytes |
| Store | nullable `models` JSON column + migration `0013_score_models` |
| Derive | stored `ran_with_providers` computed from the routes |
| Classify | `classify_model(route) -> open \| closed \| unknown`, structural owner matching |
| Replay | a same-owner republish may **fill** a null value, never replace one |
| Read | `models_for_score_ids()`, chunked, two columns |

## Ships and DEPLOYS first

`ScoreSubmission` is `extra="forbid"`, so a Client sending `models` to a Scoreboard that does
not know the field gets a **422**. Merging is not sufficient — this must be deployed and
confirmed live before `OME-1180` is released.

## Review corrections (PR #922, 2026-09-11)

Four findings, all confirmed empirically, two of which invalidated claims made without checking:

1. `models` is **not** internal. `ScoreSchema` is the response model for `POST /scores` and
   `GET /scores/{id}`, and feeds the private JSONL export whose bytes authorize a purge. Now
   carries `exclude_if`; legacy export digests verified byte-identical to `origin/main`.
2. Substring matching on a client-submitted route let a crafted name buy an open verdict.
   Matching is now structural — owner matched exactly, family exceptions scoped to their owner.
3. A replay could replace an existing declaration. Now fills only a null value.
4. `gemini-cli`, `codex` and `antigravity` are registered Gateway providers and were missing
   from the closed-owner set, corrupting the unrecognised-model count.

## Artifacts

- Spec: `docs/spec/2026-09-11-OME-1181-model-identities.md`
- Plan: `docs/plan/2026-09-11-OME-1181-model-identities.md`
- Ledger: `docs/work/2026-09-11-OME-1181-model-identities.md`
- PR: #922

Related: `OME-1180` (the Client half, PR #923), `OME-1145` (the bug this chain serves),
`OME-1056` (the case-count rule this leaves alone).
