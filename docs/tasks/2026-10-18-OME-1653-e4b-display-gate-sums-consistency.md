---
id: OME-1653
linear_url: https://linear.app/openmined/issue/OME-1653/add-combine-display-gate-signal-sums-and-consistency
status: done
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-18
closed: 2026-11-05
---

# Add combine display, gate, signal sums and consistency

Mirror of OME-1653 (parent epic OME-1290, E4b). E4b parts 4 to 7 in one PR, stacked on parts 2
and 3 (OME-1652). Branch `OME-1653-e4b-display-gate-sums-consistency`.

Scope: part 4 shows the combine steps in the report and adds the `trace` key to `report.v1`;
part 5 adds `sf.Gate` on a vote with the abstain, judge and writer fallbacks; part 6 adds `sf.Sum`
and the abstain band; part 7 adds `sf.Consistency` samples and the recompile rule for a url4 that
declares signals.
Added 2026-10-20/21 (owner): the map → select → reduce recipe surface replaces the public recipe
API (`sf.Fanout(...) >> [sf.Judge] >> [sf.Rank | sf.Filter]* >> <reducer | sf.Synthesize>`; no
backward compatibility; `sf.Fusion` kept as a shortcut), plus an Engine narrow step so a selection
can come before a reducer in one combine call.

Design: `docs/spec/2026-10-15-e4b-show-signals/`, `docs/spec/2026-10-16-e4b-gate-record/`,
`docs/spec/2026-10-16-e4b-signal-sums/`, `docs/spec/2026-10-16-e4b-consistency/`, `docs/spec/2026-10-20-e4b-mapreduce-surface/`.
Ledgers: `docs/work/2026-10-15-e4b-show-signals.md`, `docs/work/2026-10-16-e4b-gate-record.md`,
`docs/work/2026-10-16-e4b-signal-sums.md`, `docs/work/2026-10-16-e4b-consistency.md`,
`docs/work/2026-10-20-e4b-mapreduce-surface.md`, `docs/work/2026-10-20-e4b-narrow-step.md`.
Test approvals: `.claude/test-change-approvals/OME-1653.json`.

## Close

- 2026-11-05: E4b parts 4 to 7 and the map → select → reduce surface are on `main`. #1460 and #1461
  first merged on 2026-10-30 into their parent stack branches, not into `main` (the repo keeps a
  branch after merge, so GitHub did not retarget them). PR #1680 then squash-merged the same parts 2
  to 7 change onto `main` as `ea79d69e4` on 2026-11-05. Close in Linear is an owner action.
