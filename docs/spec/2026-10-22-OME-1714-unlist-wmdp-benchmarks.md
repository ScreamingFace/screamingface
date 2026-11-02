---
ticket: OME-1714
status: implemented (owner-approved 2026-10-22: unlist, do not delete)
date: 2026-10-22
related: OME-1253 (the import that landed the three rows), OME-986 (the Scoreboard retire tool)
---

# Take the WMDP Benchmarks off the public catalogue without deleting them

## 1. Problem

The Engine's catalogue (`GET /v1/benchmarks`) lists every installed Benchmark. The SDK's
`sf.benchmarks.list()` reads it, and the Scoreboard's seed job reads it to register the rows the
Leaderboard shows. One other place enumerates the registry: the SDK's local stack projects it by
import into the local Scoreboard's seed (`_runtime/bootstrap.py`), the local twin of that job.

Three Imported Benchmarks probe hazardous knowledge: WMDP-Bio, WMDP-Chem, WMDP-Cyber
(`inspect-wmdp_bio`, `inspect-wmdp_chem`, `inspect-wmdp_cyber`). Product asked for their
Leaderboards to come off the public catalogue: listed, they read as an invitation to optimise
Fusions for hazardous-knowledge elicitation, which can cost AI-safety funding.

Measured on 2026-10-22 against `https://leaderboard.screamingface.ai`: all three rows exist,
public, with 0 entries and 0 baselines.

## 2. Decision

**Unlist, do not delete.** Think of a YouTube unlisted video: it exists and the link works, but
it is off the index. The three Benchmarks stay installed, revisioned and runnable by id; they
stop appearing in any listing.

- **R1 — an Unlisted Benchmark is absent from `GET /v1/benchmarks`.** The SDK listing and the
  Scoreboard seed therefore never see it.
- **R2 — `GET /v1/benchmarks/{id}` still serves an Unlisted Benchmark.** A run by id keeps
  working. `sf.benchmarks.get(id)` keeps working too: it reads the listing first and, when the
  listing has no entry, reads the resource by id (review finding on this PR: `get` used to be
  list-then-filter, so an Unlisted id raised "not installed"). A wrong id still raises
  `unknown_benchmark` with the same message. The ticket's worry is perception on the
  catalogue, not access.
- **R3 — the mark is declared on the Benchmark in code, not in deployment configuration.** A
  fresh deploy cannot expose the rows by forgetting a setting. Each marked row names the ticket.
- **R4 — the mark never enters `revision` and never reaches the wire.** Every listed entry and
  every resource stays byte-identical to today, so no recorded Score looks incomparable.
- **R5 — the Scoreboard rows are removed by the existing operator tool, not by code.** The seed
  never deletes. After the Engine deploy, once per id on prod and dev:
  `python -m scoreboard.retire_benchmark --benchmark <id> --include-engine-owned --yes`.
  The rows hold no Scores, so the tool allows it.
- **R6 — the SDK's local stack applies the same skip.** Its seed twin reads the registry by
  import, so it must drop Unlisted Benchmarks itself or a local leaderboard shows a board the
  deployed one hides (review finding on this PR).

## 3. Out of scope

- A deployment setting that re-lists them on an internal Engine (add when someone needs it).
- A Scoreboard-side "hidden" visibility (the rows hold no data; the retire tool suffices).
- Refusing `GET /v1/benchmarks/{id}` for an Unlisted Benchmark.

## 4. Acceptance

1. `GET /v1/benchmarks` on a registry holding one listed and one Unlisted Benchmark returns
   exactly the listed one; the listed entry equals the entry served with no Unlisted sibling.
2. `GET /v1/benchmarks/<unlisted id>` answers 200 with the resource.
3. The set of Unlisted rows in the inspect plugin is exactly `{wmdp_bio, wmdp_chem, wmdp_cyber}`.
4. The three published revisions in `test_published_revisions.py` are unchanged.
5. SDK notebook 12 no longer names the three ids; `check_notebooks.py` passes.
6. `sf.benchmarks.get(id)` returns an Unlisted Benchmark the listing omits; an id the Engine
   serves nowhere still raises `unknown_benchmark`; the local seed twin omits an Unlisted row.
