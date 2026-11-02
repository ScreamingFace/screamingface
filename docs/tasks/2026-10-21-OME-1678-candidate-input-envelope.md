---
id: OME-1678
linear_url: https://linear.app/openmined/issue/OME-1678/image-support-benchmark-path-send-a-cases-inline-pictures-to-the-model
status: done
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1271
created: 2026-10-20
closed: 2026-10-21
---

# IMAGE SUPPORT - BENCHMARK PATH: Send a Case's inline pictures to the model as image parts

A picture Benchmark (MMMU, HLE, MathVista, LAB-Bench FigQA) carries each picture inside the Case as
an inline `data:` URI in the v2 candidate-input envelope. The connector used to refuse any message
whose content was not one string.

- New envelope module `benchmarks/candidate_input.py`: reads v1 and v2, enforces the v2 part rules,
  refuses unknown `candidate-input.*` schemas. The inspect plugin moves onto it in OME-1271 PR 1.
- The connector uses it, so a v2 Case reaches the gateway as OpenAI content parts; v1 Cases send
  the same bytes as before.
- Only inline `data:` URIs pass, so a Case can never make the gateway or Codex fetch a URL it
  picked. Blob refs stay with the url4 half (OME-1545).

Owner verify: acceptance 4 (MMMU `validation_Geography_16` end to end on the local stack) needs
the importer (OME-1271 PR 2) and a vision model behind the gateway.

Ledger: `docs/work/2026-10-21-candidate-input-envelope.md`.
