---
id: OME-1439
linear_url: https://linear.app/openmined/issue/OME-1439/show-researchers-when-a-benchmark-is-scored-by-refusal-rate
status: done
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1299
created: 2026-09-30
closed: 2026-10-01
---

# Show researchers when a Benchmark is scored by refusal rate

The SDK half of OME-1400's PRs 2–3. A Benchmark whose Case scores are already 1 − its eval's
grade (a should-refuse safety Benchmark such as `xstest_unsafe`) is marked `inverted_grade`: the
SDK reads the mark from the Engine's Benchmark resource (cross-checked against the run result) or,
on a replay, from the run result alone, and report.json states it in every `benchmark` block —
`false` for an ordinary Benchmark. PR 3 shows it in the catalogue listing and the notebook report
view. An SDK older than this refuses a flipped Benchmark's run result, so this SDK is released
before the Engine that sends the mark.

- 2026-09-30: filed with PR 2 (branch `OME-1439-inverted-grade-report-mark`, ledger
  `docs/work/2026-09-30-inverted-grade-report-mark.md`, spec
  `docs/spec/2026-09-30-safety-refusal-score.md` §5); PR 3 closes it.
- 2026-10-01: closed with PR 3 (branch `OME-1439-inverted-grade-views`, ledger
  `docs/work/2026-10-01-inverted-grade-views.md`): the catalogue chip, card line and report-view line.
