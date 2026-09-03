---
id: OME-978
linear_url: https://linear.app/openmined/issue/OME-978/pin-the-healthbench-scores-with-a-free-ci-replay-of-the-recorded
status: in_progress
type: feature
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-25
closed:
---

# Pin the `healthbench` scores with a free CI replay of the recorded fusion runs

Parent: `OME-956`. Sibling: `OME-977` (draco 5-pass).

Extend the OME-964 bless machinery so the Aug-19 healthbench-worst30 **fusion** run
(recipe `best_open_source`: gpt-oss-120b + nemotron-3-ultra + hy3 answering,
deepseek-v4-pro-0813 synthesizing) replays end-to-end from committed fixtures on every
PR — $0, keyless. The tape is synthesized from the saved SDK report itself (no
production `pg_dump`): a `--report` mode in `slice_snapshot.py` plus an iterative
capture→splice loop that renders one fusion-tree level per round (members → synthesis
→ judges). Correctness gate: the synthesized tape must replay to exactly the report's
score (−0.091) and coverage (0.7898) or the bless refuses.

Full spec: the Linear description. Ledger:
`docs/work/2026-08-27-OME-978-healthbench-fusion-replay.md`.
