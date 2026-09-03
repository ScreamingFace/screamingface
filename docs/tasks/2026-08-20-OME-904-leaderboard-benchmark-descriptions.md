---
id: OME-904
linear_url: https://linear.app/openmined/issue/OME-904/show-benchmark-descriptions-on-the-leaderboard-engine-text-as-the-only
status: in_progress
type: bug
priority: 2
labels: [scoreboard, agentic, autonomous]
created: 2026-08-20
closed:
---

# Show benchmark descriptions on the leaderboard — engine text as the only copy

Requested by Irina (2026-08-20). Investigation (verified live 2026-08-20):
`GET /v1/benchmarks` on the deployed scoreboard returns `description: null` (and
null focus/dataset_url) for all three benchmarks while `revision` is correct — the
deployed seed list overrides the repo chart defaults (Helm replaces lists) and
carries no text. The notebook rendering code is fine; the data is empty. Good 2-3
line descriptions already exist in the engine benchmark definitions AND hand-copied
in `apps/scoreboard/charts/scoreboard/values.yaml` — two drifting copies.

Locked decision (owner-approved 2026-08-20): the engine's benchmark text becomes the
ONLY copy — the scoreboard takes description/focus/dataset link from the engine
definitions so a deploy override cannot lose the text again. Mechanism: the seed job
reads the engine catalogue at deploy (`GET {engineUrl}/v1/benchmarks`, public), and the
engine `Benchmark` gains `focus` + `dataset_url`. Shipped as one PR spanning both apps
(owner override of the cross-cutting split rule).

Deploy action required: set `seedBenchmarks.engineUrl` in the deploy repo values, or the
board keeps seeding only the legacy demo entries.

Surfaced during implementation: the revisions pinned in `values.yaml` are STALE relative
to this checkout's engine (chart `1c58b3085912e304` vs computed `66a463248586b277` for
draco, and likewise for ifeval and healthbench-worst30). Pre-existing drift, not caused
here — and the reason the quick unblock would seed stale revisions.

Quick unblock (owner, outside this repo): re-seed the deployed scoreboard with the
full `values.yaml` entries — seeding is idempotent.

Full body + sf-dark diagram: the Linear issue.
