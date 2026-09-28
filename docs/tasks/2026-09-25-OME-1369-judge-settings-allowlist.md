---
id: OME-1369
linear_url: https://linear.app/openmined/issue/OME-1369/an-imported-benchmarks-judge-settings-can-be-silently-ignored-changing
status: done
type: improvement
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-09-25
closed: 2026-09-28
---

# An imported benchmark's judge settings can be silently ignored, changing the exam

The judge provider refused 10 named sampling settings and silently dropped the rest of
inspect's ~40 `GenerateConfig` fields, so a judge asked for `reasoning_effort="high"` graded
at the gateway default. Fix: allow only delivery-only fields, refuse everything else by
name, and refuse tool-bearing judge calls.

- 2026-09-25: filed from the two #1032 review findings, carried over from OME-1240.
- 2026-09-28: verified the allowlist and tools refusal already merged in #1051
  (`6ca658a2`). Remaining gap: `cache`, one of the five settings inspect passes down from an
  eval to every model, was missing from the allowlist. Branch
  `OME-1369-allow-inherited-judge-cache`.
- 2026-09-28: PR #1089 merged (`054a06a8`). Closed Done.
