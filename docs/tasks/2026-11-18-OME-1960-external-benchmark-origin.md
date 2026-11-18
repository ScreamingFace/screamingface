---
id: OME-1960
linear_url: https://linear.app/openmined/issue/OME-1960/mark-a-benchmark-from-an-outside-contributor-as-external-and-name-the
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1330
created: 2026-11-18
closed: 2026-11-18
---

# Mark a Benchmark from an outside contributor as external and name the contributor

A Benchmark's `origin` gains a third value, `external`, for one written by someone outside the
team, and such a row names its author's GitHub handles in a new `contributors` field. The
Engine serves both on the catalogue entry; the SDK and the Scoreboard receive the key. A row
with any other origin may not set the field, and an `external` Benchmark keeps its bare id.

- Spec and plan: `docs/spec/2026-11-18-external-benchmark-origin.md` and
  `docs/plan/2026-11-18-external-benchmark-origin.md`
- Ledger: `docs/work/2026-11-18-external-benchmark-origin.md`
