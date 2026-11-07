# url4 in-process dispatch — skip the wire round trip for a node's own endpoints

Status: approved (Sergey, Kevin — 2026-11-05). Ledger: `docs/work/2026-11-05-url4-inprocess-dispatch.md`.

## Problem

A relative call `/path(context)!intent` is fetched as `/path?[params&]q=(context)!intent`
(`url4.wire.subrequest.encode_subrequest`, built in `RelUrlNode.resolve`). When the io layer is
the `Url4Node` that serves `/path`, the node parses that URL straight back in the same process
(`extract_expression_params` → `decode_subrequest_http` → `unquote_plus`). For MMLU-Pro the
aggregate call's context is a JSON array of ~12k Case rows (~150 MB); the encode, the query
split, the payload slices and `unquote_plus`'s per-escape fragments hold ~15x the input at
once (~2.3 GB) against a 2,560 MiB memory budget, and the run is killed with
`memory_budget_exceeded`.

## Change

`RelUrlNode` keeps the call structured: it sends a `SubrequestFetch` — a `FetchRequest` that
carries a `SubrequestCall` (path, context, intent, params, quote) and encodes its `target`
only when something reads it. `Url4Node.fetch_ex` recognises that request: when the path is a
registered endpoint, it builds the endpoint's `Request` directly — the context is passed
through, and the intent and params are decoded by the real codec from a context-free
envelope (`/path?[params&]q=()!intent`, a few bytes). Every other case — eval path, data
route, unknown path, any other adapter — reads `target` and runs today's path.

## Invariants

- **Equivalence.** An endpoint receives byte-identical `context`, `intent` and `params` on the
  fast path and on the wire path, for every input (edge characters `% + & = ( ) ! ' ,`,
  unicode, empty values, flag params, quoted and verbatim intents). Intent and params go
  through the same codec functions, so validation errors are the same too.
- **Wire compatibility.** `SubrequestFetch.target` is exactly `encode_subrequest(...)`, and a
  `SubrequestFetch` equals (and hashes as) the plain `FetchRequest` of those bytes. Remote
  `url4://` calls (`RemoteFetchNode`) are not touched. Adapters other than `Url4Node`
  (`StaticIOLayer`, `HttpIOLayer`, wrappers) see the same request they see today.
- **Wrappers stay transparent.** The structured call rides inside the request, so
  `BoundedIOLayer`, the engine's `FairShareIOLayer` and any other `fetch_ex` pass-through
  keep admitting, gating and counting the call with no change.

## Layering

`SubrequestCall` lives in `url4.wire.subrequest` (the codec owner; dag and peer may import
it). `SubrequestFetch` lives in `url4.dag.nodes` (it needs `io.layer` and `wire`). The fast
path lives in `url4.peer._inprocess`; `peer/server.py`, `peer/_dispatch.py` and
`dag/nodes/fetch.py` sit at their module-size caps, so their edits are line-neutral.

## Test plan

1. Memory: a 50 MB, heavily escaped JSON context through an in-process endpoint keeps the
   tracemalloc peak under 3x the context size (today ~15x).
2. Equivalence: fast path vs wire path, parametrised over the edge inputs above.
3. Wire pin: encoded bytes, `target`, equality and hash unchanged; static and remote adapters
   see today's target.
4. Fallbacks: eval path, data route and unknown path still take the wire path.
5. The full url4 and screamingface-engine gate suites, plus the MMLU-Pro repro harness at
   12,032 Cases for the before/after peak.
