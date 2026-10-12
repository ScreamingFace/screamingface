---
ticket: OME-1503
stack: screamingface
status: done
started: 2026-10-11
finished: 2026-10-11
---

# Recovery URL validation and bounded artifact encoding

## Intent

The user authorized fixing both findings from the review of PR #1269 at
512144064a96d4c0a34128d393aec4cdb73d9345. Invalid saved Engine URLs must settle as
named metadata failures without discarding healthy siblings. Successful artifact
responses must not allocate an unbounded decompressed body before ticket verification.

## Planned changes

- Validate saved Engine origins and HTTP URL syntax in `_results/store.py`.
- Request identity encoding and reject encoded success responses in `_engine/result_download.py`.
- Add regression tests without changing inherited tests or assertions.
- Record this approved correction in focused spec and plan documents.

## Test plan

First reproduce both failures in sync and async APIs. Cover invalid origins and ports,
healthy partial reports, no authentication for invalid saved metadata, encoded success
responses rejected without consuming their bodies, bounded memory, identity negotiation,
and existing successful verified downloads. Run all SDK card gates.

## Acceptance

Both findings are fixed with preserved public APIs, metadata schema and dependencies.
Existing tests remain unchanged. No paid model calls or review comments.

## Outcome

- **Actual files:** the two planned SDK modules, one new regression file, and the
  focused spec, plan and work record. Existing tests and assertions are unchanged.
- **Commits:** `fix(screamingface): isolate invalid origins and bound encoded downloads`
  (this follow-up to reviewed head 512144064a96d4c0a34128d393aec4cdb73d9345).
- **RED:** all twelve new regression cases failed on the reviewed head: eight
  invalid-origin cases, two encoded-success cases and two encoding-negotiation cases.
- **GREEN:** 95 focused tests passed. The original independent reproduction scripts
  now recover the healthy partial report in both APIs; compressed-response peak
  allocations fell from approximately 100 MB to 23,530 bytes sync and 29,574 bytes async.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface` reported ALL GATES
  GREEN: append-only tests, Ruff lint/format, Pyright, full parallel pytest, 96%
  coverage (11,630 statements, 460 missed; 95% floor), deterministic notebooks,
  wheel/sdist builds and distribution checks.
- **Wisdom review:** reuse existing origin validation and HTTPX's URL parser;
  share one encoding guard across both download paths. Invalid metadata is rejected
  before authentication, encoded successful bodies before consumption. No public API,
  metadata schema, dependency or Engine changes. Existing HTTP errors remain classified.
- **Deviations:** none. OME-1503 remains open for draft review and merge. No paid
  model calls, hosted validation or review comments.
