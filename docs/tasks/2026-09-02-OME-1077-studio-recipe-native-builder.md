---
id: OME-1077
linear_url: https://linear.app/openmined/issue/OME-1077/make-the-studio-compose-builder-recipe-native-solofusionpipeline-with
status: In Progress
priority: P2
labels: [desktop/ensemble, agentic, autonomous]
created: 2026-09-02
---

# Make the Studio compose builder recipe-native (solo/fusion/pipeline) with live url4

Reshape the ScreamingFace Studio frontend so the compose panel matches ScreamingFace's real
artifacts (Solo / Fusion+required-synthesizer / Pipeline, nested arbitrarily) and generates
url4 live as the user builds. Frontend-only/mock this pass; real engine/leaderboard/
param-discovery wiring is a later, separate effort.

Spec: `docs/spec/2026-09-02-OME-1077-studio-recipe-native-builder.md`.
Plan: `docs/plan/2026-09-02-OME-1077-studio-recipe-native-builder.md`.
Ledger: `docs/work/2026-09-02-OME-1077-studio-recipe-native-builder.md`.

This mirror, and the spec/plan pair above, were backfilled 2026-09-28 to close a code-review
finding (#7) that no `docs/spec`/`docs/plan`/`docs/tasks` artifacts existed for this ticket
despite substantial shipped implementation. Label is temporary — `desktop/ensemble` is used
because the Studio app has no landing leaf of its own yet.
