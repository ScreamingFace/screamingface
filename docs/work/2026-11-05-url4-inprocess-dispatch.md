---
ticket: OME-1834
stack: url4
status: done   # planned | in_progress | done | blocked
started: 2026-11-05
finished: 2026-11-05
---

# url4-inprocess-dispatch — hand an in-process endpoint its call without the wire round trip

## Intent

Memory fix 1 for the MMLU-Pro `memory_budget_exceeded` kill (approved by Sergey and Kevin,
2026-11-05). The aggregate call carries all ~12k Case rows (~150 MB) as its context; today
`RelUrlNode` percent-encodes it into a `?q=` URL and the node, in the same process, parses it
back (`encode_subrequest` → `extract_expression_params` → `decode_subrequest` →
`unquote_plus`), peaking at ~15x the input (~2.3 GB vs a 2,560 MiB budget). When the target
is an endpoint the node serves in-process, the endpoint now gets the structured call (path,
context, intent, params) directly. Remote calls and every other adapter keep today's wire
bytes. Spec: `docs/spec/2026-11-05-url4-inprocess-dispatch.md`.

## Planned changes

- `packages/url4/src/url4/wire/subrequest.py` — `SubrequestCall`: the structured form of a
  relative sub-request, with `encode()` (today's exact bytes) and `endpoint_parts()` (what an
  endpoint receives: intent and params decoded through the real codec from a context-free
  envelope, context passed through untouched).
- `packages/url4/src/url4/dag/nodes/_subrequest_fetch.py` (new) — `SubrequestFetch`, a
  `FetchRequest` whose `target` is encoded lazily, on first read; equal to its wire request.
- `packages/url4/src/url4/dag/nodes/fetch.py` — `RelUrlNode` sends a `SubrequestFetch`
  instead of encoding eagerly (line-neutral; module at its cap).
- `packages/url4/src/url4/peer/_inprocess.py` (new) — `fetch_ex`: a `SubrequestFetch` aimed at a
  registered endpoint calls the handler directly; anything else falls through to
  `_dispatch.fetch_ex` unchanged.
- `packages/url4/src/url4/peer/server.py` — `Url4Node.fetch_ex` delegates to `_inprocess`
  (line-neutral; module at its cap).
- Tests (new files only): `packages/url4/tests/unit/test_inprocess_dispatch.py`.

## Plan

1. RED: memory test (50 MB heavily escaped JSON context, tracemalloc peak < 3x), equivalence
   test (fast vs wire, edge chars, unicode, empty values), remote/wire encoding pin.
2. GREEN: `SubrequestCall` → `SubrequestFetch` → `RelUrlNode` → `_inprocess.fetch_ex`.
3. Gates: `run_gates.py url4` and `run_gates.py screamingface-engine`, plus
   `scripts/check_module_size.py` (CI-only gate, not in the card).
4. Repro harness at 12,032 Cases; record the before/after peak.

## Test plan

- Memory: `/sink(/api/big)!'go'` on a `Url4Node`, context ~50 MB of JSON dense in `{ } ( ) ' % + & #` and
  spaces; tracemalloc peak during the call < 3x `len(context)`.
- Equivalence: for contexts/intents/params with `% + & = ( ) ! ' ,`, unicode, empty context,
  empty/None intent, flag params, quote on/off — the `Request` an endpoint sees via the fast
  path equals the one it sees via `dispatch_result(node, encode_subrequest(...))`.
- Wire pin: `SubrequestCall.encode()` == `encode_subrequest(...)`; a `SubrequestFetch`'s
  `target` and equality match a plain `FetchRequest` of those bytes; a `StaticIOLayer` and a
  remote `url4://` fetch see the same target as before.
- Fallbacks: an eval-path target, a data route, and an unknown path take the wire path.

## Acceptance

- New tests green; all prior tests unchanged and green; both gate runs exit 0.
- Repro harness peak drops well below the 2,560 MiB budget at 12,032 Cases.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `packages/url4/ARCHITECTURE.md` (owner-table rows) and
  `packages/url4/src/url4/peer/__init__.py` (module list). `fetch.py` 289/290 and `server.py`
  315/315 stay within their module-size caps; no new suppressions; no `__all__` pin changed.
- **Commits:** `feat(url4): hand an in-process endpoint its call without the wire round trip`
  (sha in the PR).
- **Gates:** `run_gates.py url4 --base origin/main` ALL GREEN (exit 0; 2,720 passed, 17 xfailed,
  coverage 99%); `run_gates.py screamingface-engine --base origin/main` ALL GREEN (exit 0).
  `scripts/check_module_size.py` and `scripts/check_suppressions.py` (CI-only) green.
- **Memory:** unit probe (50 MB escaped-JSON context through `/sink(/api/big)!'go'`): tracemalloc
  peak 39.1x → 2.0x the context. The repro harness at 12,032 Cases on the same base
  (`24d979a5e`): peak RSS 3,010.8 MiB → 1,425.5 MiB; 195.3 s → 95.6 s; outcome `succeeded`
  on both.
- **Deviations:** the plan had the structured call as a new port method; it rides inside the
  request instead (`SubrequestFetch`, a lazily encoded `target`). Reason: `dag/_context.py`
  (`BoundedIOLayer`) and `peer/server.py` are at their size caps, and a request-borne call
  passes through every `fetch_ex` wrapper (bounded layer, the engine's fair-share gate) with no
  change to any wrapper. The ledger was created under the slug branch; the branch was renamed to
  `OME-1834-url4-inprocess-dispatch` mid-unit on the coordinator's instruction.
