---
id: OME-1077
linear_url: https://linear.app/openmined/issue/OME-1077/make-the-studio-compose-builder-recipe-native-solofusionpipeline-with
status: in_progress
type: feature
priority: 3   # Medium
labels: [desktop/ensemble, agentic, autonomous]
created: 2026-09-02
closed:
---

# OME-1077 — Make the Studio compose builder recipe-native (solo/fusion/pipeline) with live url4

Reshape `apps/screamingface-studio/frontend`'s compose panel from the flat "Loop + Reduce /
strategy / judge" model to a recipe-native builder (Solo / Fusion+required-synthesizer /
Pipeline, nested arbitrarily) that generates url4 live, plus UX cleanup (nav, run controls,
templates). Frontend-only / mock this pass. Delivered as lightweight live iteration under one
ticket. Ledger: `docs/work/2026-09-02-OME-1077-studio-recipe-native-builder.md`.

**Temporary label** `desktop/ensemble` — Studio has no landing leaf yet; owner to create
`screamingface-studio` and relabel. **Before PR:** register the stack in `.claude/sdlc.local.md`,
add a vitest/Testing-Library harness + `typecheck` script, run gates green.
