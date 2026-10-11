# url4 hygiene audit, lane H2: dead code and over-engineering (ASSESSMENT ONLY)

Repo state: main @ da88b135a. Last PyPI tag: `url4-v1.5.1` (2026-08-27).
Since that tag, src has 53 changed files (+5144/-3596), so a symbol first added after the tag has no PyPI users.
Evidence files in this directory: `vulture.txt`, `vulture_withconsumers.txt`, `vulture_all.txt`, `exports.txt` (per-export consumer counts), `exports.py`, `cg.sh`.

## 1. Census

| Item | Count |
|---|---|
| url4 src LOC | 13,026 (streaming/ is 1,426) |
| vulture hits (src only, conf >= 60) | 52 |
| ... after adding engine/screamingface/playground as consumers | 22 |
| ... after also adding url4 tests, engine tests, examples | 9 |
| Hits that are false positives (pydantic fields/validators, Protocol/ABC methods, `__getattr__`, `_repr_html_`, CloudEvents spec fields) | 48 |
| True dead private code | 0 (no unreferenced `_name` helpers found) |
| Real survivors | 4, all public dataclass fields of `observe.py`: `RunStarted.expression_hash`, `NodeFinished.engine_seq`, `RunFinished.engine_seq` (written, never read outside tests/invariant) |
| Test-only-in-src symbols (used by tests, no production caller) | 3: `LoweringRegistry.register/copy`, `ExecutionContext.collected_errors`, `make_command_handler(stdin=)` (other consumer is external) |
| `__all__` exports with 0 in-repo production consumers (engine src, studio, screamingface, playground) | 46 of 152 (see `exports.txt`) |
| ... of those with 0 test use too | 8: `FrameAdapter`, `InboundFrame`, `HeartbeatData`, `is_eval_path`, `ParamsLike`, `SourceLike`, `ProcessFn`, `RouteInfo` (tests only) |
| Single-implementer abstractions (real) | 4 (section 3) |
| Scout candidates cleared (live) | 9 |

## 2. Findings (verdict format: `[class] claim - evidence - cannot rule out`)

### F1. `is_eval_path`, `RouteInfo` (and `describe_routes`) exported with no outside caller (tier: public API, but UNRELEASED)
- `[cross-repo]` `is_eval_path` has no caller outside `peer/direct.py:182`. `RouteInfo` is used only by `describe_routes`, which the engine calls (`world/serving.py:50`). Neither name exists at `url4-v1.5.1` (`git grep` empty). Introduced 2026-09-27 (d64d5e942, "one executor for every engine request").
- Cannot rule out: engine code on unmerged branches; the engine docs `docs/plans/uniform-executor/*` name `describe_routes` and `dispatch_direct` only, not `is_eval_path`.
- Interest: low. Each extra export widens the API that must be versioned.
- Action: drop `is_eval_path` from `peer.__all__` (make it private). Keep `RouteInfo` as the return type of `describe_routes`. No deprecation window needed (never released). Tier: unreleased public API, delete with tests green.

### F2. Streaming wire adapters/aliases with zero consumers: `FrameAdapter`, `InboundFrame`, `HeartbeatData` (tier: wire protocol package, cross-repo)
- `[cross-repo]` 0 uses in engine src, engine tests, studio, screamingface, url4 tests. `InboundFrame` is used only to build `InboundFrameAdapter` (which the engine uses). `HeartbeatData` is used only as a field default of `HeartbeatEvent` (live in `ws/bridge.py:91`).
- Cannot rule out: external PyPI users and the url4-cloud runner repo (docs reference a "url4-cloud Runner"). All three exist at v1.5.1, so they ARE released.
- Interest: low (3 names). Do NOT delete. Option: stop re-exporting from `streaming/protocol/__init__`, with a one-release deprecation. Priority low; skip unless the API surface is being reduced anyway.
- The four events `ErrorEvent`, `HeartbeatEvent`, `StopEvent`, `AttachEvent` are LIVE: the engine builds and parses all four (`ws/bridge.py:28,91,370`, `schemas/protocol_schemas.py:12-46`, tests `test_ws.py`, `test_docs_ops.py`). Scout candidate cleared.

### F3. `LoweringRegistry` plugin system (tier: public API, released)
- `[static]` One lowerer set. `register()` has 0 production callers in url4 src and 0 in engine, studio, screamingface, playground. Only `tests/unit/test_dag.py:305,342,412,741` call `register()` (to inject fakes), and `copy()` is used only at `test_dag.py:739-741`. `run(..., registry=)` and `compile_expression(registry=)` are only passed by internal callers or test spies.
- Exported via `url4.dag.__all__` (`LoweringRegistry`, `default_registry`), and `Lowerer` is importable from `dag/compiler.py` but not in `__all__`. Exists at v1.5.1 (`url4/dag/compiler.py` era; introduced 56f932b61, 2026-07-15, v1 SDK).
- Cannot rule out: external users extending lowering (the module docstring advertises "Extensibility"); the tests use it as a test double seam (they inject `CachedNode`, `boom`).
- Interest: moderate. Every new surface form must go through a registry indirection, and `_lowering.py` is 738 lines (the largest dag file).
- Action: KEEP the seam (tests rely on it), but demote: remove `LoweringRegistry`/`default_registry`/`Lowerer` from the documented public surface (mark "internal, test seam"), and delete `LoweringRegistry.copy` only after a deprecation (it has one test caller). Do not inline now. Tier: public API, deprecation window.

### F4. `make_command_handler(stdin=)` / `COMMAND_STDIN_SOURCES` (tier: public-ish CLI helper, released 2026-07-31 in 1eef71796)
- `[static]` `build_node` calls `make_command_handler(argv, config.timeout)` (`cli/_serve.py:252`) and never passes `stdin`. No TOML key sets it. Only `tests/unit/test_serve_command_stdin.py` passes it. The docstring (line 47-52) says a second consumer, "the url4-cloud Runner's `[commands]` table", validates through it.
- `[cross-repo]` No such consumer in this repo (`grep url4.cli` finds only the engine's `world/config.py:65` and tests importing `url4.cli._config`, not `_serve`).
- Cannot rule out: the url4-cloud repo (outside this monorepo) calling `make_command_handler(stdin=...)`. Cannot be checked from here.
- Interest: low (about 15 lines of code plus a `ValueError` branch).
- Action: keep until the url4-cloud repo is checked. If confirmed unused, hardcode `stdin="context"` and delete the selector. Tier: public/cross-repo, needs owner confirmation.

### F5. `Url4Node.serve` vs `_http.serve` (scout said "two implementations") - NOT a duplicate
- `[static]` `Url4Node.serve` (`peer/server.py:277`) is a 2-line delegate to `peer/_http.serve`. One implementation, one wrapper. `url4_playground.py:235` and tests (`test_server.py:337`) call `node.serve`.
- The CLI path (`cli/_serve.build_asgi_app`) wraps `node.asgi()` with its own overload/health layer, so it legitimately bypasses `serve()`.
- Cannot rule out: n/a. Verdict: keep. No action.

### F6. `Client.query/broadcast/iterate/reduce` have no production caller in this repo (tier: public API, headline surface)
- `[cross-repo]` 0 uses of `Client` in engine src, studio runtime, packages/screamingface. The engine uses `Url4Node.evaluate` and `node.fetch` directly. Callers: `url4_playground.py:27,218` and the notebooks (`url4_client.ipynb`) and url4 tests (`query` used 17 times in tests/notebooks, `broadcast` 3, `iterate` 3, `reduce` 2).
- Cannot rule out: external PyPI users. `Client` is the documented entrypoint in `__init__` and README.
- Interest: low. The methods are thin builders over `evaluate`.
- Action: keep. Record in the audit that the in-repo product does not dogfood `Client`, so regressions in it will not be caught by the engine suite. Tier: public API, do not touch.

### F7. `observe.py` fields never read: `RunStarted.expression_hash`, `NodeFinished.engine_seq`, `RunFinished.engine_seq` (vulture survivors, tier: public observation API)
- `[cross-repo]` Engine src never reads these (engine `runner/executor.py:395` reads `node_kind`, `detail`, `parent_span_id` only; `RunFinished` is not imported by the engine at all). Engine tests only construct them. url4 `_context.py:82-91` asserts `engine_seq` is monotonic (internal use). `RunFinished` has 8 uses in url4 src/tests and 0 outside.
- Cannot rule out: external observers; the docstring says "a downstream" consumer relies on `engine_seq` ordering.
- Interest: low. Frozen dataclasses with a few fields each.
- Action: keep. Reason: they are the observer protocol's documented contract and the `engine_seq` gap-free invariant is tested. Tier: public API.

### F8. `_LogAttributes` deep-copy and pickle hooks (tier: private, delete-with-tests)
- `[static]` Only constructor use is `observe.Log.__post_init__` (`observe.py:77`). `__deepcopy__`/`__reduce__` exist so `dataclasses.asdict` and pickling of `Log` return plain dicts (comment in `_log_attributes.py:34`). Added 2026-09-09 (cfd3eb38d), after the tag.
- Cannot rule out: engine code that `asdict`s or pickles a `Log` (engine has 16 files that mention `Log`; not traced in this lane).
- Interest: low. This is a defensible immutability wrapper, not speculative. Action: keep.

### F9. `StaticIOLayer` `routes` vs `fetch_map` vs `holdings` vs `media_types` (tier: public API)
- `[static]` All four are live: engine uses `StaticIOLayer()` empty as a "deny all outbound" sentinel (`world/factory.py:132,149`, `world/connector.py:465`); notebooks and tests use the populated forms. Each Support* protocol on it is needed by the engine's `FairShare` wrapper (`runner/fair_share.py:55-58,298-311`), which isinstance-checks all of `SupportsFetchEx`, `SupportsHoldings`, `SupportsDefaultRoute`, `SupportsProcessorRoutes`.
- Verdict: keep. See also section 3.

### F10. Formal-model stand-in BFS (`tests/unit/test_formal_models.py`, 75 lines + `tests/formal/*.py`, 264 lines) (tier: private test code)
- `[static]` `fm.py` is NOT in the package. It is an untracked local skill (`.claude/skills/formal-modeling/` is `??` in `git status`), so the stand-in is not a duplicate of a CI-available tool today. If that skill is committed, the stand-in becomes a true duplicate.
- Interest: the 4 models test themselves (their own invariants), not `Executor._run`; they do not exercise url4 code, so they cannot fail on a real regression. Only the docstring ties them to `dag/executor.py` INVARIANT comments.
- Action: keep until the skill is committed; then replace the BFS with `fm.py` or move the models to docs. Tier: private test code, delete with tests green.

### F11. Engine imports private url4 modules (hygiene lead for other lanes, not dead code)
- `apps/screamingface-engine/src/screamingface_engine/world/config.py:65` imports `from url4.cli._config import (...)`, and tests import `url4.cli._config.ProviderSpec` (`test_world_read_side.py:340,354`). A private module is a de facto public API, so renaming or trimming `_config` breaks the engine. A guard test exists for `peer` (`test_no_private_url4_dispatch_import.py`) but not for `cli._config`.

### Cleared candidates (live; no action)
- `bare_root_ok`: passed by url4 itself at `dag/executor.py:276` (spawn path), added 2026-07-23. Not an engine-passed flag; docstring wording "engine" means the DAG engine, not screamingface-engine.
- `dispatch_direct`: not called by `Url4Node`, but called by the engine run child (`runner/executor.py:53,1032`) and `describe_routes` by `world/serving.py:50`. Live public API (unreleased: added after the v1.5.1 tag).
- `SupportsClose`: one real adapter (`HttpIOLayer.aclose`) plus `_owned.py:46` as the only consumer; test double in `test_owned_io.py`. Weak but cheap; keep.
- `SpawnHook`/`ExecuteNodeHook`: constructor kwargs `_spawn_hook`/`_execute_node_hook` are only used by `_clone`; `executor.py:298-299` assigns the private attributes directly. The only hook installer is the url4 executor itself (single implementer). Low-value indirection: could collapse into methods on the executor, but the guard node and iteration use `ctx.spawn` and `ctx.execute_node`, so the seam is real. Defer.
- `ExecutionContext.strict_fields`: passed by `run(strict_fields=)` and tests; no engine or CLI caller sets True. See below.
- `ExecutionContext.collected_errors`: 0 production callers (only 4 url4 tests, docstrings); engine's `collected_errors` is an unrelated name. Public property, keep.
- `url4.streaming.interfaces`: `JobRunner` has one in-repo concrete (`IdentityAwareJobRunner` in `ports.py:31` is an extension, plus `InProcessJobRunner`/`QueueJobRunner` in engine adapters); `Executor` is implemented by the engine plus about 8 test doubles; `EventStream` by `InMemoryEventStream` plus test fakes. Ports are real seams.

## 3. Over-engineering summary (single-implementer or single-user abstractions)

| Abstraction | Implementers / users | Verdict | Tier |
|---|---|---|---|
| `LoweringRegistry` + `Lowerer` (register/copy) | 1 default set; only tests register | Demote from public docs; keep seam for tests; delete `copy` after deprecation | public API |
| `make_command_handler(stdin=)` | 1 value ever passed in-repo ("context"); second consumer external | Keep pending url4-cloud check, then hardcode | public/cross-repo |
| `SpawnHook`/`ExecuteNodeHook` via `ExecutionContext` | installed once (url4 executor); `_clone` copies them | Low value; defer (collapse only with an executor refactor) | private |
| `SupportsClose` | 1 impl (`HttpIOLayer`), 1 consumer (`_owned.py`) | Keep (test double exists) | public API |
| `ExecutionContext.strict_fields` | no CLI/engine setter; spec §5.3.4.1 mode | Keep (spec-required, tested) | public API |
| `url4.streaming` package (1,426 LOC) in a "standalone core library" | consumed only by the engine and external runner | Not dead; architectural placement question for H-architecture lane | n/a |

Not over-engineered: Supports* protocols (engine wrapper implements all four), `StaticIOLayer` options, `Url4Node.serve`, `_LogAttributes`.

## 4. Recommended sequence (3 items)
1. Add a `__all__`/API-surface ratchet: pin `url4.__all__` plus each subpackage `__all__`, so new exports need a stated consumer (tier: tooling). Then trim the unreleased exports (F1: `is_eval_path`), the cheapest change, with no deprecation needed.
2. Resolve the cross-repo unknowns in one pass: check the url4-cloud repo for `make_command_handler(stdin=)` (F4), `LoweringRegistry.register` (F3) and `FrameAdapter`/`InboundFrame` (F2). Only then decide delete versus keep.
3. Add a guard test forbidding `from url4.cli._config` in the engine (F11), and either promote `ProviderSpec` etc. to a public module or inline them.

## 5. Blind spots
- No PyPI download stats or code search across the OpenMined/url4-cloud repos; every "public, 0 callers" item says "cannot rule out: external PyPI users".
- No runtime evidence (coverage or tombstone counters) for engine or CLI paths. Suggest `coverage run` on the engine integration suite and a debug-log counter on `LoweringRegistry.register`.
- Notebooks were counted by text match, not executed.
- Studio runtime (`apps/screamingface-studio`) was grepped for exports; the search was a Python/notebook/markdown text search (`.py`, `.ipynb`, `.md`), so TypeScript or Rust consumers of wire event names are not covered.
- Vulture cannot see dynamic dispatch via pydantic validators, ABC overrides or `__getattr__`; these were triaged by hand (48 of 52).
- `_LogAttributes` pickling consumers in the engine were not traced.
