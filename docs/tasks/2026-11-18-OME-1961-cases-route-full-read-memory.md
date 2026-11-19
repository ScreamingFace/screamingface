---
id: OME-1961
linear_url: https://linear.app/openmined/issue/OME-1961/a-run-of-every-case-of-a-large-benchmark-is-stopped-for-memory-before
status: done
type: bug
priority: high
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-11-18
closed: 2026-11-18
---

# A run of every Case of a large Benchmark is stopped for memory before the first model call

A run of all 1,158 EnigmaEval Cases read its 381 MiB `cases.json` as one Python text. One Case
holds the character U+1F815, so the text cost 4 bytes a character and the Cases route peaked at
5,048 MiB against the run's 2,560 MiB budget. The indexed read now walks one Case at a time and
serves each as ASCII text (non-ASCII as JSON escapes): 840 MiB for the same read, and url4 hands
on the same Case texts as before.

- Blocks `OME-1874` (EnigmaEval, https://github.com/ScreamingFace/screamingface/pull/1833).
- Ledger: `docs/work/2026-11-18-cases-route-full-read-memory.md`
