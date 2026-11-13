---
ticket: OME-1811
stack: python
status: in_progress
started: 2026-11-03
finished:
---

# engine-remote-node-refusal — engine runs refuse url4:// remote-node calls

## Intent

Probe "Gap B" (2026-11-02): `Url4Executor._evaluate` calls `url4.dag.run` directly, outside
`Url4Node.evaluate`, so no remote-node policy is set and a `url4://` remote call reaches the
world node's outbound layer (an empty peer allowlist blocks it with the wrong code
`x.source_destination_blocked`; a populated one lets it reach the peer). Spec #1450 F1b / §4:
every node evaluation, the engine's included, refuses with `x.remote_node_unsupported`
(permanent) before any DNS lookup or request. Parent epic OME-1529.

## Planned changes

- `packages/url4/src/url4/dag/__init__.py`: export `refuse_remote_nodes` (the existing
  awaitable wrapper `Url4Node` already uses) as the supported public hook.
- `packages/url4/src/url4/dag/remote_nodes.py`: AIDEV-NOTE updated; `allow_one_remote_hop` and
  `check_remote_node` stay private.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`: wrap both `url4_run`
  calls in `refuse_remote_nodes(...)`.

## Test plan

- url4 `tests/unit/test_refuse_remote_nodes_public_hook.py`: the hook is in `url4.dag.__all__`;
  under it a remote call, an ensemble member and a `url4://` reduce processor each fail
  `x.remote_node_unsupported` permanent with 0 DNS / 0 requests, empty and populated allowlist;
  control: without it a bare run reaches an allowlisted peer; a local run is unchanged.
- engine `tests/unit/test_engine_remote_node_refusal.py`: `Url4Executor.execute` over a world
  node with the guarded transport, the same three cases x {empty, populated} x {no trace, trace}
  (both call sites); a local run still completes with 0 outbound calls.

## Acceptance

- Engine runs refuse every `url4://` remote-node call with `x.remote_node_unsupported`,
  permanent, 0 DNS lookups, 0 requests; local runs and data fetches unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the two new test files.
- **Commits:** see branch `OME-1811-engine-remote-node-refusal`.
- **Gates:** `run_gates.py screamingface-engine --base origin/OME-1545-engine-attachment-parts`:
  ALL GATES GREEN. `run_gates.py url4` (same base): ruff, format, pyright, pytest (2844 passed,
  98.92% coverage) green; the append-only check fails on one line, see Deviations.
  `check_module_size.py`: all capped modules within baseline (`dag/_context.py` untouched, 455).
- **Deviations:** the url4 H2 ratchet (`tests/unit/test_hygiene_ratchets.py`, `EXPORTS`) pins
  `url4.dag.__all__` at 38; the new export makes it 39. The ratchet says to update it in the same
  diff, but that is a prior-test edit, so it sits in its own commit and needs an owner approval
  manifest (`.claude/test-change-approvals/OME-1811.json`, as OME-1543 did for 59 -> 61) before
  the append-only check passes. The engine test avoids private url4 imports (the engine's
  private-import ratchet): a recording outbound wrapper plus a fail-closed resolver instead of
  mocking `url4.io._guarded_transport`. RED verified: with the executor change reverted, 12/12
  engine refusal cases fail.
- **Moved to main (2026-11-11, owner decision):** the change does not depend on the OME-1543/1545
  stack, so its three commits were cherry-picked onto `origin/main` (efca18049) as branch
  `OME-1811-remote-node-refusal-main`. The ratchet merge took main's base (`url4` 59) plus this
  change (`url4.dag` 39), and the approval manifest was re-pinned to main's blobs (same one-value
  change). Gates on that base: `run_gates.py url4`, `screamingface-engine` and `repo --base
  origin/main` ALL GATES GREEN. The stacked branch `OME-1811-engine-remote-node-refusal` is
  superseded.
- **Review round 1 (HupBaHa, 2026-11-11, #1750):** the guard fired only when the remote node
  resolved, so concurrently scheduled local siblings (paid model calls in the engine) ran first.
  Fix: `url4.dag._remote_preflight.preflight_remote_nodes` walks the graph before scheduling and
  refuses every `RemoteFetchNode` and a literal `url4://` reduce processor; `run()` calls it, and
  `spawn` calls it once per compiled fragment. The check is non-consuming
  (`remote_nodes.preflight_remote_node`), so a `Client` hop is still spent by the call itself; the
  execution-time checks stay for dynamic (Form-3) processors. Tests with endpoint tripwires:
  url4 `test_remote_node_preflight.py`, engine `test_engine_remote_node_preflight.py`. RED
  verified: 8 url4 and 6 engine cases fail without the fix. Gates: url4, screamingface-engine and
  repo `--base origin/main` ALL GATES GREEN; `dag/executor.py` 312, at its cap.
- **Review round 2 (HupBaHa, 2026-11-13, #1750 at 62c735a1c):** (1) a remote node in a deferred
  fragment (map body, lazy group) was checked only when the fragment spawned, after the outer
  collection fetch, and `on_error=collect` folded the refusal into a successful error row;
  (2) a statically computable Form-3 processor (`(p:0:'url4://n2/v1')!'$p'`) refused only after
  the reduce members ran. Fix: the preflight also compiles and walks every `MapNode.fragment` /
  `LazyExprNode.text`; `_static_processor.static_processor_value` computes a Form-3 processor made
  only of inline text under text-intent groups with the default merge (anything else stays the
  run-time check). Defence in depth: the policy records every refusal; `MapNode` re-raises one from
  its rows, and `run()` re-raises any refusal its graph swallowed (an `;optional` guard), so the
  run ends `error`, not `ok`. Tests: url4 `test_remote_node_deferred_preflight.py`, engine
  `test_engine_remote_node_deferred_refusal.py`; RED verified (7 url4 cases, engine map and
  processor cases). No prior test changed; module-size ratchet within baseline.
- **Review round 3 (HupBaHa, 2026-11-13, #1750 at 2b06deb3e):** a Form-3 processor whose own graph
  calls another node (`(url4://n2.example/v1(x)!"go")!"processor"`) was only evaluated at reduce
  time, so members `a`/`b` ran first. Fix: the preflight compiles (behind the same `build` grammar
  gate) and walks every Form-3 processor graph for structural remote calls, map bodies and deferred
  groups included, before any member runs; the static-value check and the run-time check stay.
  Tests: url4 `test_remote_node_processor_graph_preflight.py`, engine
  `test_engine_remote_node_processor_graph.py` (probe + controls); RED verified (4 url4, 4 engine
  cases). url4 `notebooks (examples/)` CI job reproduced locally: 3/3 notebooks ok.
- **Round 4 (merge `origin/main` 4f7bb6e15, with #1587 / OME-1543):** both PRs had a run-start
  remote-node refusal. Now ONE mechanism: #1587's `_run_files._precheck_remote` →
  `remote_nodes.precheck_remote_nodes(calls, maybe=)` (AST scan, pre-built walk, Form-3 processor
  scan; every run, nested too; before any attachment I/O). Folded from this PR:
  `_static_processor.static_processor_value` now feeds the precheck's processor hop
  (`_run_files._processor_hop`, node context only), as a `maybe` call like a literal one.
  Removed as duplicates: `_remote_preflight.py`, `remote_nodes.preflight_remote_node`, and the
  `_wire_spawn` preflight (claimed: the AST scan already covers map bodies and lazy groups —
  FALSE for text the strict grammar rejects; corrected in round 5). Kept: sticky
  refusals (`refusal_mark` / `reraise_refusals_since` / `reraise_remote_refusal`, now recorded by
  the precheck too) and the public `refuse_remote_nodes`. Hygiene ratchet: union (`url4` 61,
  `url4.dag` 39). No test changed. Static-value fold is load-bearing: without it 2
  `test_remote_node_deferred_preflight` cases fail. Gates: url4, screamingface-engine, repo
  `--base origin/main` green; module-size within baseline; notebooks 3/3 ok. The OME-1811
  ratchet approval needs re-pinning to the new base blob (owner).
- **Round 5 (2026-11-13, regression from the round-4 merge; owner approach "fallback graph
  walk"):** the round-4 claim above was wrong. The precheck read only the strict AST scan, so run
  text holding a nested group the grammar rejects but the spawn compiles
  (`(('r1','r2')*(/b($item)!'i'))!'g'`) parsed to nothing and was taken as call-free: a
  `url4://` call beside / inside it, in a sibling map body, or beside an `https://` collection
  group refused only after `/a` (and the rows) ran. Fix: new `dag/_remote_walk.py`
  (`RemoteWalk`): the strict scan is used only where it read the WHOLE text; otherwise (run text
  that does not parse, a `LazyExprNode.text`, a `MapNode.fragment` whose body has a segment the
  grammar rejects — new `SourceScan.opaque`) the text is compiled as `run()` / the spawn hook
  compiles it and that graph walked recursively (round-15 pre-built walk folded in; one walk).
  Security-review follow-up: the whole `MapNode.fragment` is compiled, not each segment (a
  segment may compile only inside it), and a fragment that still does not compile FAILS CLOSED:
  each `url4://` URI in it is a `maybe` call (refused unless it is the client's unspent hop).
  The run's own uncompilable text stays exempt (run() fails at compile, before any node). All
  findings feed the one `precheck_remote_nodes(calls, maybe=)`; the Form-3 processor scan uses the
  same walk. Compiles are policy-gated (a bare run compiles nothing extra); valid text keeps its
  scan. Tests (new files only): url4 `test_remote_node_grammar_blind_preflight.py` (9 refused
  cases + 4 controls + the Form-3 widening pin), engine `test_engine_remote_node_grammar_blind.py`
  (5 refused cases + Form-3 pin + control). RED verified: 6 url4 + 4 engine on f0a02382a, then
  2 url4 + 1 engine (fragment-only segment, uncompilable body) on the first round-5 commit. Also
  fixed the stale `MapNode.fragment` docstring. No ratchet / `url4.dag.__all__` change. Merged
  `origin/main` (01e8c8fa0).
