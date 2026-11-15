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
  (5 refused cases + Form-3 pin + control). RED verified (corrected in round 6): all 9 url4 + 5 engine refused
  cases red on f0a02382a; the 2 url4 + 1 engine security-review cases (fragment-only segment,
  uncompilable body) also red on the first round-5 commit 761f3553f. Also
  fixed the stale `MapNode.fragment` docstring. No ratchet / `url4.dag.__all__` change. Merged
  `origin/main` (01e8c8fa0).
- **Round 6 (2026-11-13, independent re-check of 174ba12f9):** (1) a grammar-blind group in a
  LOCAL call's context (`/c((('r1','r2')*(url4://…($item)!'i'))!'g')!'k'`) still ran members
  first: `_walk_rel_expr` sent skipped context segments only to `malformed`, but the lowering
  (`_lowering._slot_from_text`) defers such a segment into a caller-side `LazyExprNode`. My
  round-5 "shipped verbatim" assumption was wrong (only a context with an unparseable
  NON-group segment ships as prose). Fix: skipped context segments also go to
  `SourceScan.opaque`. (2) The fail-closed regex now blanks `'…'` quote runs first
  (a regex mirroring `core._scan.skip_quoted`; importing it would add a private-module crossing): a quoted `url4://` mention in an
  uncompilable body was refused, even over an empty collection that completed on f0a02382a.
  (3) The walk is iterative (`_total`: one unit per compiled text, post-order, calls counted per
  occurrence capped at 2); a 300-deep run under a node policy escaped `run()` as a raw
  `RecursionError`. Under a policy a spawned text is compiled one level at a time, as the spawn
  hook does, with no strict re-parse at each level (that made a deep run cubic, 16 s). A
  compile that still raises `RecursionError` is read like an uncompilable fragment: its
  unquoted URIs are coded `maybe` refusals. (4) Round-5 RED counts corrected above. (5) Prose
  contexts: an unparseable non-group context still lowers to a verbatim `RelUrlNode`, whose scan
  is what it was, so plain prose and prose naming `url4://` both run (pinned). Tests (new files
  only): url4 `test_remote_node_call_context_preflight.py` (7 refused cases, quoted/prose/deep
  controls, too-deep compile fail-closed), engine `test_engine_remote_node_call_context.py`
  (5 refused cases + quoted control). RED on 174ba12f9: 10 url4 + 6 engine; 4 url4 controls
  green throughout. No ratchet / `url4.dag.__all__` change.
- **Round 7 (2026-11-14, independent re-check of 84b8bb310; owner decision "always compile"):**
  the strict scan still missed (1) a remote call in an iteration's per-row intent
  (`_walk_iteration` never walks `node.intent`, but the map spawns `(body)!intent`), plain, over
  `https://` rows (the rows were fetched first), in a group, and in a map inside a map; and (2) a
  holdings context sent to the node's own eval path (`/v1(@, url4://…)`), which the scan skips.
  Round 6 also regressed (3): a run-text `RecursionError` inside the precheck was read as "no
  calls", and at one exact depth `/a` ran. Fix: under a remote-node policy `RemoteWalk` ALWAYS
  compiles — the run text as `run()` does, every `MapNode.fragment` / `LazyExprNode.text` and a
  holdings context (`(context)`) as the spawn hook does — and walks those graphs; no scan-first
  shortcut. `SourceScan.opaque` (rounds 5/6) is removed, so `source_scan.py` matches main again.
  A compile that cannot finish (`RecursionError`, run text or fragment) adds its unquoted
  `url4://` URIs as `maybe` calls, or, naming none, is refused `malformed_source` (permanent).
  The quote-blanking regex fallback for uncompilable fragments stays. Also coded the raw
  `AssertionError` in `core/descriptor_head.deferrable_group` (`{"k":"it's"}` body) as a
  `ParseError` (`assert in src` ratchet count drops by one). Tests (new files only): url4
  `test_remote_node_compile_first_preflight.py` (5 refused shapes, a 12-text corpus checked both
  ways — refused for free under the policy, and really calling the peer without one — 2 controls,
  too-deep run text and fragment, the descriptor row error), engine
  `test_engine_remote_node_compile_first.py` (4 refused shapes + control; the too-deep case is
  url4-only: patching url4's private walk from the engine would grow its private-import ratchet,
  7). RED on 84b8bb310: 10 url4 + 4 engine. Precheck cost on the deep lazy chain (blind group +
  N nested groups), CPython 3.13: N=300 0.8 s (bare run 0.8 s; policy run 1.6 s); N=900 6.9 s
  (bare run 7.0 s; policy run 13.9 s) — the same quadratic compile the run itself does, once
  more; no hang, no stack overflow. No `url4.dag.__all__` / hygiene-ratchet file change.
- **Round 8 (2026-11-14, re-check of 863e27fff; still the owner's always-compile approach):** two
  blockers, both from round 7's holdings-only branch in `_remote_walk._spawned_text`. (1) A raw
  `ValueError` under any node policy, a regression vs main: compiling a holdings context or body
  with an empty comma segment (`/c(@,)!'k'`, `/c(@, ,optional)`, `('r1')*(/c(@, $item,)!'k')!'p'`)
  hit `descriptor_head.deferrable_group('')`, and `RemoteWalk._compile` caught only
  `Url4Error` / `RecursionError`. Fix: `deferrable_group('')` is a coded `ParseError`, and ANY
  exception from a fragment's compile means "does not compile" (none escapes the precheck). (2)
  A verbatim context with a quoted `'a@b'` beside a grammar-blind group holding a `url4://` call
  ran `/a` first (in a map body the refusal became error rows after `/b` ran): the lowering ships
  any context containing `@` verbatim, but the walk compiled only real holdings contexts. Fix:
  EVERY verbatim context is compiled as `(context)` and walked. A verbatim context that does not
  compile is prose and is read as the scan always read it — DEVIATION from the requested
  unquoted-URI fallback for contexts: that fallback refuses the round-6 pinned prose
  `/c(see url4://n2.example/v1 for docs, thanks)!'k'`, and existing tests are append-only. Tests
  (new files only): url4 `test_remote_node_verbatim_context_preflight.py` (7 refused quoted-`@`
  shapes: run text, map body, nested group, normal route, beside a local member; a control; the
  4 empty-comma texts with and without a policy and via `Url4Node.evaluate`, values as on main;
  `deferrable_group('')`), engine `test_engine_remote_node_verbatim_context.py` (3 refused shapes,
  the 3 empty-comma texts complete with main's values; no private-transport stub, so the engine's
  private-import ratchet stays at 7). RED on 863e27fff: 13 url4 + 6 engine. Rounds 5-7 tests and
  the 12-text corpus re-run green.
  Recorded: (a) ACCEPTED FALSE REFUSAL — under a node policy a holdings (or
  any verbatim) context that compiles to a real `url4://` call is refused even when sent to a
  normal route, which would only receive it as text; the walk cannot tell which route is the
  node's eval path. (b) KNOWN LIMIT, owner-accepted and documented (2026-11-14) — text that becomes an
  expression only at the eval path (`/v1`), i.e. a quoted literal or a `$name` value sent there,
  is not an expression in the outer run; it is checked by the inner run's own precheck, with zero
  DNS lookups and zero requests, but after the outer run's siblings ran. Inside a map body this
  limit can let the run COMPLETE with `x.remote_node_unsupported` error rows (still zero DNS
  lookups and zero requests) — the same as on main (owner, 2026-11-15).
- **Round 9 (2026-11-14, security review of 623e8305b):** three fail-open paths in
  `_remote_walk.py`, all fixed. (1) HIGH: a holdings context (no scan) was given prose mode and,
  on a compile failure, an empty scan; now a holdings context is a fragment — any compile failure
  adds its unquoted `url4://` URIs as `maybe` calls, and a too-deep one naming none is refused
  `malformed_source`. Only TRUE prose (no holdings ref, has a scan) may fall back to its scan. (2)
  HIGH: a `RecursionError` on a prose context skipped the URI check; now a too-deep compile always
  adds its URIs first, and only true prose naming none falls back to its scan. (3) MEDIUM: units
  and the prose table were keyed by text alone, so a map/lazy fragment equal to a context's
  `(context)` could inherit prose mode; keys are now `(kind, text)` and fragments never use prose
  mode. Tests (new file only): url4 `test_remote_node_context_fail_closed.py` — a holdings context
  that does not compile and names `url4://`; too-deep holdings and prose contexts naming `url4://`;
  a too-deep holdings context naming none (`malformed_source`); a map body equal to a prose
  context; control: that prose context alone still runs. RED on 623e8305b: 5 of 6 (the control
  green). Round-6 prose pins and rounds 5-8 tests green.
- **Round 10 (2026-11-14, re-check of fcc257943; owner: "with remote nodes blocked, compile each
  /v1 call exactly the way /v1 will run it"):** two shapes still ran members first, both through
  a call to the node's own eval path. (1) A verbatim context such as
  `'r1' *(url4://…($item)!'i') zz(y)!'p'` is prose as `(context)` but an iteration once `/v1`
  runs `(context)!intent` (`peer/_dispatch.py` + `_reassemble.py`). (2) A `processor=` param on a
  `/v1` call (`;processor=url4://…` or `?processor=…&q=`) was never read. Fix: a new optional port
  `SupportsEvalPath.eval_expression(target)`, declared by its consumer (`dag/_remote_walk.py`;
  the engine may name io only through `url4.io.layer`, and that module is at its size cap) and
  implemented structurally by `Url4Node` with its OWN dispatch code (`_dispatch.eval_expression`,
  sharing `_eval_parts` with `dispatch_result`: endpoint-first routing, `/v1` and
  `/v1/<collection>`, `reassemble`). `run()` hands the precheck the unwrapped io world (`world=`),
  since `BoundedIOLayer` forwards no such port. `RelUrlNode.static_target()` rebuilds the target the call
  requests (`SubrequestCall.encode`) when it is known before the run. Under a policy the walk
  compiles that exact text as `run()` does and walks it; the `processor=` value is read like the
  run's own (literal or static `url4://` → `maybe` hop; an expression's graph walked; a malformed
  one fail closed by its URIs). A slotted (resolved) context is run-time data there. The rounds
  8/9 `(context)` check still runs beside it (an existing round-9 test pins it). Performance:
  nested quoted-`@` contexts were super-cubic because every level scanned (and so re-parsed) all
  contexts nested in it up front; the prose/holdings classification now happens only when a
  context's compile fails. 1.5 KB nested `'a@b'` contexts (100 levels): precheck 20.85 s → 0.06 s
  (policy run 21.6 s → 0.77 s; run without a policy 0.75 s). Deep lazy chain unchanged: N=300
  precheck 0.78 s, N=900 6.9 s (each about the run's own compile time). url4 has no expression-
  size cap that would bound this. Tests (new files only): url4
  `test_remote_node_eval_path_preflight.py` (7 refused: iteration context to `/v1`, beside a
  local member, in a map body (raises, no error rows), unquoted collection, `processor=` on the
  call and in the query, `/v1/<collection>`; controls: same context to `/c` runs as text, `/v1`
  calls with no `url4://` run, incl. `processor=/a`), engine `test_engine_remote_node_eval_path.py`
  (6 refused + control). RED on fcc257943: 7 url4 + 6 engine. KNOWN LIMIT unchanged
  (owner-accepted 2026-11-14): text that becomes an expression only inside `/v1` (a quoted
  literal, a `$name` value, a resolved context) is checked by the inner run, with zero DNS and
  zero requests, after siblings ran; inside a map body the run can complete with
  `x.remote_node_unsupported` error rows, as on main.
- **Round 11 (2026-11-15, re-check of 832e1a1ee):** local mode switched the round-10 check off.
  The engine always wraps the node's io in `FairShareIOLayer` (local mode builds the gate and
  `runner/main.py` wraps whenever a gate and run key exist), and it forwarded only `fetch_ex`,
  `fetch_holdings`, `processor_routes` and `default_route`, so `RemoteWalk._evaluated` saw no
  eval-path port and every round-10 shape ran members first again (map bodies completed with
  error rows). Fixes: (1) `FairShareIOLayer` forwards `eval_expression` when the inner layer has
  it (a pure lookup, not I/O, never gated; `getattr`, because the port Protocol sits in url4's
  private engine layer). (2) Owner decision, FAIL CLOSED: when the precheck cannot ask what the
  eval path runs — the io in hand lacks the port, or `static_target()` is `None` because the route
  needs a run-time value (`/$item…`, `/v$item(…)`) — every unquoted `url4://` URI in the call's
  static text (path, verbatim context, params) is a `maybe` call; never silently skipped. The
  `$`-route shapes were already refused at row time by the path grammar and already refused by
  the precheck before this round; they are now pinned. Tests (new files only): engine
  `test_engine_remote_node_fair_share_eval_path.py` (all 7 round-10 cases through
  `Url4Executor(io_wrap=FairShareIOLayer)` with a real `FairShareGate`, map body raises; control
  completes), url4 `test_remote_node_eval_port_fail_closed.py` (5 eval-path cases through a bare
  wrapper without the port + a control that runs; 3 `$`-route shapes + a control naming no
  `url4://`). RED on 832e1a1ee: 7 engine + 5 url4 (the `$`-route pins and controls green).
  /v1 limit wording extended (map-body error rows, as on main).
- **Round 12 (2026-11-15, re-check of f993a278b):** one gap under the owner's "computed routes
  fail closed" decision: a percent-encoded `url4://` call in the `q=` of a computed route
  (`/$item?q=%28url4%3A…`) or of a call on an io without the eval-path port passed the
  fallback (the run completed with an `x.remote_node_unsupported` error row after local members
  ran; zero DNS and requests). The fallback scanned raw text while `/v1` decodes `q=` with
  `unquote_plus`. Fix: the fallback text is `unquote_plus`-decoded until it stops changing (at
  most 8 rounds, so double encoding and `+` are covered) before quote blanking and the URI scan;
  one change covers both fallback paths. Tests (new files only): url4
  `test_remote_node_encoded_fallback.py` (percent-encoded in a map body and beside a local member,
  `+`-encoded, double-encoded, a bound-name route, the port-less io in a map body; a control that
  names no `url4://` and runs); engine `test_engine_remote_node_fair_share_port.py` (the
  fair-share layer exposes the inner port; prose naming `url4://` to `/c` completes under fair
  share as on a bare node). RED on f993a278b: 5 url4 (the bound-name route and control green —
  that route is refused by the walk already). Mutations: dropping the computed-route fallback
  turns 4 of the new url4 cases red (the round-11 `$`-route pins stay green, as the re-check
  found); dropping the `FairShareIOLayer` forward turns all 3 new engine tests red (plus the
  round-11 control). Merged `origin/main` c9293d04f (#1830, OME-1925).
  Security-review follow-up (two MEDIUM fail-open paths in that fix): joining path, context and
  params let a quote run span two fields, and blanking quotes only on the final decoded text let
  a decoded `%27` hide a URI visible earlier. Now each field (path, context, each param value) is
  scanned alone, raw with quote runs blanked AND every decode round unblanked (bounded), union
  taken (`_readings`). Tests: url4 `test_remote_node_fallback_field_scan.py` (a pre-built call
  whose path opens a quote the context closes; `%27…%27` around the URI; a URI visible only after
  round 2); RED on d79f0800c: 3, GREEN after. Round-6 prose / quoted-mention controls and the full
  url4 suite stay green. Mutation re-run with the final code: dropping the computed-route fallback
  turns 6 of the new round-12 url4 tests red.
