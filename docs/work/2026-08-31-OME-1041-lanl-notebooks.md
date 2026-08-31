---
ticket: OME-1041
stack: py-screamingface
status: in_progress
started: 2026-08-31
finished:
---

# OME-1041 — Add LANL researcher onboarding notebooks and outreach email

## Intent

Produce three artifacts targeting Los Alamos National Laboratory researchers who authored
"Beyond Leaderboards: Tokenomics of Agentic Small Language Model Ensembles" (OpenReview
XSIYfTm2h7). They achieved 97.34% strict prompt accuracy on IF-Eval using a CorrectiveLoop
ensemble (Ens-1: gemini-3.1-flash judge + gpt-5.4-mini/gemini-3.1-flash members) and have
already seen a ScreamingFace demo. These materials give them enough depth to reproduce their
work and understand the engine internals.

## Planned changes

- `packages/screamingface/examples/colab/ScreamingFace_BYOK_Guide.ipynb` — BYOK walkthrough
- `packages/screamingface/examples/colab/ScreamingFace_Platform.ipynb` — hosted engine walkthrough
- `packages/screamingface/examples/colab/LANL_outreach_email.md` — outreach email draft

## Test plan

- Notebooks are valid JSON / valid nbformat 4.5
- Output cells are empty (CI deterministic check)
- Code patterns match confirmed API (sf.configure, sf.connect, sf.Model, sf.Fusion, sf.Pipeline, sf.evaluate)
- Provider canonical IDs match gateway plugin values (openrouter, openai, anthropic, huggingface)

## Acceptance

- BYOK notebook covers: local engine boot, 4 provider options, IF-Eval internals, caching, Solo/Fusion/Pipeline + composition explanation, URL4, cost readout
- Platform notebook covers: hosted engine, .gov auth note, same API surface, leaderboard
- Email is warm, peer-level, references their paper + the demo, points to both notebooks

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
