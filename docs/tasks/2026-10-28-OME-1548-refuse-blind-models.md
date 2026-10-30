---
id: OME-1548
linear_url: https://linear.app/openmined/issue/OME-1548/image-support-benchmark-path-apply-a-per-type-file-policy-and-refuse
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1271
created: 2026-10-09
closed: 2026-10-28
---

# IMAGE SUPPORT - BENCHMARK PATH: Refuse a model that can't take pictures, by name, before a picture run spends anything

A picture Benchmark (LAB-Bench FigQA, MMMU, HLE) must never pay for a model that can't see the
picture.

- Before the first paid call, the Cases route checks the Benchmark's Cases. If any Case in the
  file has a picture, the selected count doesn't matter: a 5-Case HLE smoke run that draws only
  text Cases gets the same answer.
- It then reads the gateway's `/v1/models` once, as the run's caller, and fails the whole run
  with the permanent `intent_error` naming each member, synthesizer or reducer that lacks
  `image`. A model the gateway doesn't list counts as text-only.
- Benchmark graders are not checked; they read text only.
- A text Benchmark never reads the list, so no text run changes.
- An unreadable list fails the run as retryable, before any chat call.

Narrowed on 2026-10-28 to pictures. The PDF, office-file and url4-source rows of the per-type
policy move to OME-1681, for when a PDF Benchmark or the url4 path needs them.

Accepted limitation: OpenRouter models admitted on the fly report text-only, so they are refused
until the gateway threads their evidence through admission.

Owner verify: the FigQA smoke run (OME-1327) with a vision lineup passes this check, and one
text-only model in the lineup is refused by name.

Ledger: `docs/work/2026-10-28-refuse-blind-models.md`.
