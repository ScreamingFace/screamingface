---
id: OME-1809
linear_url: https://linear.app/openmined/issue/OME-1809/image-support-refuse-a-url4-runs-attachments-for-models-that-cant-read
status: in_review
type: feature
priority: 0
labels: [screamingface-engine, agentic, autonomous]
created: 2026-11-02
closed:
---

# Refuse a url4 run's attachments for models that can't read them, before any call

At run admission the engine reads `/v1/models` input modalities once per run and refuses a url4 run
whose files a member, synthesizer or reducer can't read: `intent_error`, permanent, naming the model
and the modality, before any chat call (no spend). A Benchmark run checks only its Candidate. Fails
closed when the model list is unreadable.

Parent epic `OME-1529`. Depends on `OME-1545` (#1588, merged).
Ledger: `../work/2026-11-09-blind-model-admission.md`.
