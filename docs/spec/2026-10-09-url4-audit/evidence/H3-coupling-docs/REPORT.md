# url4 hygiene audit, lane H3: duplication, hidden coupling, half-finished migrations, rule drift, knowledge rot

Mode: assessment only. Repo untouched. All paths are under `/Users/junior/workspace/screamingface/packages/url4` unless stated.
Evidence key: S = static read/AST script, G = git history, D = repo docs. Line numbers were checked on 2026-10-09.

## Census

### Duplication sites
| # | What | Places | Size |
|---|---|---|---|
| D1 | Two lowering pipelines: text path (`_compile_text`, `_compile_group_text`, `_slot_from_text`, `_collection_dag`, `_map_from_text`) and AST path (`_lower_top_level`, `_slot_from_ast`, `_lower_expression`, `_lower_iteration`, `_refs_of_ast`) | `dag/_lowering.py` (738 lines), `dag/_wiring.py` | about 250 lines of parallel logic; 11 "twin/text path/AST path" comments in `_lowering.py` |
| D2 | The `/path` charset regex | `core/grammar.py:100 _PATH_RE`; `core/parser.py:55 _CALL_PATH_RE` (byte-identical pattern); `render._check_path` imports the grammar one | 2 definitions, 3 uses |
| D3 | Identifier regex `[A-Za-z_]\w*` | `grammar.py` x3 (`_IDENT_RE`, `_VARREF_HEAD_RE`, `_FIELD_SEG_RE`), `dag/semantics/ensemble.py` x3 (`_ENV_VAR_RE`, `_NAME_ONLY_RE`, `_SEGMENT_RE`), `_lowering.py:101 _GROUP_BINDING_RE` (spelled `[a-zA-Z_][a-zA-Z0-9_]*`) | 7 spellings |
| D4 | Identical patterns in one file | `core/_annotations.py:67 _PARAM_VALUE_RE` and `:78 _EXEC_VALUE_RE` are the same pattern | 2 |
| D5 | The `$name` reference syntax is owned by the grammar (`_VARREF_HEAD_RE`) and re-read as text by `ensemble.find_references` (`_ENV_VAR_RE`) | `core/grammar.py`, `dag/semantics/ensemble.py:45-47`, called from `_lowering.py` x4 (lines 323, 475, `_refs_of_ast`) | 2 grammars for one syntax |
| D6 | `ExecutionContext(...)` built with the same 5 kwargs and the same `Context(bindings=dict(env)) if env else None` | `peer/server.py:240`, `peer/client.py:282` (third, different construction in `dag/_run.py:255`) | 2 near-copies, about 8 lines each |
| D7 | The "render with `check=False`, then `_blaming_render`" front door, with the same 8-line docstring and WHY comment | `peer/server.py:253-275`, `peer/client.py:254+`; helper lives in `client.py` and `server.py` imports it | 2 copies of the policy, 1 shared helper |
| D8 | CLI defaults (host 127.0.0.1, port 4404, eval `/v1`, concurrency 32, max_inflight 16, timeout 120) | `cli/_config.py:72-78` (dataclass), `:201-207` (`resolve` literals), `cli/app.py:63-75` (argparse help strings), plus `peer/server.py:69`, `:277`, `peer/_http.py:58` (host/port/eval_path), README toml sample | 3 certain, 6 in total |
| D9 | `_SERVE_FIELDS` (`app.py:32`) duplicates the argparse `dest`s and the `ServeConfig` field names | `cli/app.py`, `cli/_config.py` | 3 lists of the same 8 names |
| D10 | Usage/cost/finish_reason data shape mirrored by hand on two axes that may not import each other | `observe.py` (events), `dag/node.py` (usage report), `streaming/protocol/{signals,taxonomy}.py` (pydantic) | see C1 |
| D11 | Textual clones (6-line window scan over all of `src/`) | only the D7 docstring, plus a repeated `intent/env` signature in `client.py` | no copy-paste at the text level; duplication is semantic |

### Private cross-module imports (AST scan of every `from url4... import`)
Cross-package, underscored name or module (the real coupling debt):
- `cli/_config.py:30` and `peer/server.py:29` import `core.grammar._IDENTITY_NAME_RE`; `core/render.py:42-49` imports 7 `_*_RE` names from `grammar`; `core/builders.py:39` imports 2 more.
- `core/builders.py:60` imports 4 render privates (`_quote`, `_format_number`, `_render_intent`, `_render_source`).
- `peer/client.py:41,50` imports `core.builders._pairs`, `_rewrite_reducer_iteration` and `core.render._render_source`.
- `dag/_lowering.py:68-78` imports 8 `_wiring` privates (same package, but it is a private-module API seam, not a public one).
- `dag/nodes/{fetch,group,guard,iteration}.py` import 15 `_shared` privates (same package).
- `dag/executor.py:32` and `peer/direct.py:26` import `observe._bind_node_sinks`: one private name serves two layers.
- `dag/nodes/fetch.py:11`, `dag/semantics/ensemble.py:31` and `wire/subrequest.py:21-22` import `core._scan` / `core._annotations` (private modules of another package).
- `cli/_serve.py:35-36` and `peer/_http.py:22-24` import `peer._asgi`. `cli/_serve.py:32` imports `cli._config._HEALTH_PATH`.
- `peer/server.py:39` imports `peer.client._blaming_render` (server depends on the sibling client).
- `peer/_dispatch.py:48` imports `peer.server._DataRoute` under `TYPE_CHECKING`. `server` imports `_dispatch`, so this is a type-only cycle.
- `peer/direct.py:66-73,169,184` reads `node._endpoints`, `node._data`, `node._eval_path`; `peer/_dispatch.py:171` reads `node._eval_path` and calls `node._run_text`. Node internals are the real interface.
- Count: about 45 import lines of this kind across 28 files. `tests/unit/test_layering.py` checks none of them.

### Stale or false doc statements (verified)
- K1 `ARCHITECTURE.md:42` says "`url4.observe` ... Only the engine imports it". The table at `:30` and `peer/__init__.py:15` let `peer` import it, and `peer/direct.py:26` does. The document contradicts itself. The scout's `observe.py:30` quote is not in the tree; the claim lives in ARCHITECTURE.md.
- K2 `peer/_dispatch.py:65-70` has two overlapping comment paragraphs. One says "§27.3 delegation semantics are not implemented yet (see OME-506)", but `:175-180` consumes `processor` and runs with it, and `tests/spec/test_processor_delegation.py` pins all three value forms. The comment is stale or contradicts itself: at the eval path it is implemented, at endpoint calls it is dropped.
- K3 `streaming/lifecycle.py:63-66`: "`-O` strips an assert statement but not a call to a method containing one." False. `-O` strips the assert inside the method too. The gap check the comment calls "loud" disappears under `-O`. The assert is also vacuous (`self._n` was just set to `previous + 1`), so it can only fire under a thread race.
- K4 `pyproject.toml:4` says "grammar, parser, AST, interpreter, and scope". No interpreter exists; the layer is called "engine" in all other docs. `core/parser.py:216` and `nodes.py:109` also say "interpreter's choice".
- K5 `CHANGELOG.md`: section compare links use `github.com/ScreamingFace/screamingface`. Per-commit links use `github.com/OpenMined/screamingface`. The `origin` remote and `pyproject` use ScreamingFace. Generated file; low harm, but links break after the rename.
- K6 `tests/formal/*.py` headers (4 files) say `python3 ~/Documents/skills/concepts/formal-modeling/bin/fm.py check ...`. That is a path on one machine. The repo now has `.claude/skills/formal-modeling` (untracked). `tests/unit/test_formal_models.py` may already wrap it; the header is not a usable instruction.
- K7 `ARCHITECTURE.md:38,52-58` says the engine "may import `io.layer`". The code matches (`dag` imports only `io.layer`), but the test allows all of `io` (see R2).
- K8 `docs/tasks/2026-07-22-ome-539-...wire-codec-out-of-core.md` (and 537, 540-546) are `status: Backlog`. `url4/wire/` exists and the #1015 restructure landed; OME-539 at least is done in code. Task docs are not trustworthy as a status source. Not verified for 540-546.
- K9 `core/grammar.py:7,17` and `nodes.py:5,229` cite `url4.dag.compiler`. This is NOT stale. `dag/compiler.py` is the public facade (`ARCHITECTURE.md:90`). The scout's "grammar.py:17 vs `compile_expression`" doubt is cleared. The facade name and the implementation name (`_lowering`) are used loosely; keep one rule: cite the facade.
- K10 `peer/_http.py` docstring "The node's HTTP adapter": accurate. Not stale.
- K11 README "passes `pyright`": true. `.github/workflows/url4-tests.yml:64` runs `uv run pyright`. `pyrightconfig.json` is `basic` mode, so the claim is weaker than it reads.
- `docs/ISSUES.md` items (list verified 2026-06-24, before the package existed on 2026-08-04): I-30 (escape rules) is fixed in code: `core/grammar.py:755 _unescape` defines exactly two escapes and rejects others. Whether the spec doc states it was not checked. I-29 (url4 not a library) is fixed: `packages/url4` shipped v1.5.1. I-18 (comma split in `(...)`) is probably closed by the OME-500 grammar epic and `tests/spec`, but I did not find a test named for it. I-21 (async runs), I-23 and I-25 are gateway or eval concerns with no url4 code evidence either way; the ISSUES file has no status column. All six are stale as written; none was closed in the file.

### Coupled pairs (`hygiene.py coupling`, 24 months, scoped to `packages/url4/src`)
History is young and shallow (62 commits since 2026-08-04), so counts are small and only structural pairs show up.
| shared | pct | pair | honest? |
|---|---|---|---|
| 7 | 100% | `dag/node.py` + `observe.py` | static import: honest |
| 5 | 62% | `dag/executor.py` + `dag/node.py` | honest |
| 3 | 43% | `dag/executor.py` + `observe.py` | honest |
| 3 | 60% | `streaming/protocol/signals.py` with `dag/node.py` and `observe.py` | HIDDEN: no import (by rule) |
| 2 | 100% | `streaming/protocol/taxonomy.py` with `dag/node.py` and `observe.py` | HIDDEN |
Commits `ac888c5c5`, `f51d3d37d`, `0d2c00f82` each touched `observe.py` + `dag/node.py` + a `streaming/protocol` file for one change (usage, cost, finish_reason). `signals.py` also changed alone in `b594d6fcc` and `63cbf96f7`, so 3 of 5 of its commits needed a mirror edit. No `_lowering`/`_wiring`/`grammar`/`parser` pair crosses the threshold: the dual-path cost shows in commit messages (a4a5a2c61, 238c51c87, 84f9d38eb, 27510dd5f, 494389e36), not in file pairs.

## Findings

Format: `[class] claim — evidence — cannot rule out: ...`. Interest = what it charges. Tier = reversibility (T0 doc/test only, T1 internal refactor, T2 behaviour or public surface).

### F1 [half-finished migration] The text and AST lowering pipelines coexist and the collapse is parked
Claim: `dag/_lowering.py` has a lazy text path and an eager AST path. The planned fix is `docs/tasks/2026-07-22-ome-538-url4-collapse-dual-compile-pipelines.md` (Backlog, "highest-risk item in the epic"). Neither path was removed or rolled back; only parity tests were added.
Evidence: S. `_compile_text` docstring (`:603-612`) admits the paths agree on results, not graph shape. The task doc says `LoweringRegistry` covers only the AST half, so a custom lowering silently does not apply to a text-path group segment (this breaks the documented extension point). `_GROUP_BINDING_RE` (`:101`), `_is_lazy_group` (`:464`) and `_slot_from_text` re-classify syntax the grammar owns. The `(a)!x` fold decision exists in `_lower_top_level` (`:726-738`) and `_wiring._reduce_graph` (`:181-182`). Iteration body refs are read as text twice (`_body_intent_refs` `:314-323` and `_refs_of_ast` `:647-659`); the code itself calls this "the ONE reading", which is an invariant held by comments. G: three bug fixes on 2026-08-03 (a4a5a2c61, 238c51c87, 84f9d38eb) were "the AST path missed what the text path already had". Tests `test_characterization.py:92,120,249` and `test_iteration.py:416,449,504` pin result parity.
Cannot rule out: the text path is a deliberate laziness design (docstring "hybrid laziness"), so deleting it may change when errors surface (`Graph.validate()` relies on `LazyExprNode`). I did not run the parity corpus.
Interest: every new surface form, bare-group rule or intent rule is written twice; a divergence is silent (the leaf receives a literal `$ans` and the run succeeds). Custom `LoweringRegistry` users get half the pipeline. 11 comments exist only to explain the split.
Action: finish it. Strangler-fig: (1) add a `DeferredGroup` AST node (laziness as a node property); (2) make the grammar emit it; (3) route `compile_expression(str)` through `parse` then AST lowering; (4) delete `_slot_from_text`, `_collection_dag`, `_map_from_text`, `_GROUP_BINDING_RE`, `_is_lazy_group`; (5) keep the parity corpus until step 4 lands, then convert it to golden graph-shape tests. Do not leave it at 50%. If the team will not fund OME-538, roll back by writing the decision in the task doc and stating that `LoweringRegistry` only extends AST lowering. Tier T1 (internal), with T2 risk in error timing.

### F2 [duplication] The path regex is defined twice; the "reads this same pattern" comment is half true
Claim: `parser._CALL_PATH_RE` duplicates `grammar._PATH_RE`.
Evidence: S. Identical pattern (`parser.py:55`, `grammar.py:100`). `grammar.py:98` says render reads the same pattern; that is true for `render._check_path` (`render.py:492`) but not for `parser.py:105-106`, which keeps its own copy. `parser.py` already imports from `grammar`'s neighbours.
Cannot rule out: `parser` may avoid importing `grammar` on purpose (import cost or cycle). I did not check for a cycle; `render` already imports `grammar`, so a cycle is unlikely.
Interest: one grammar change (`OME-507` already needed this once) must be made in 2 places; parse accepts what render rejects.
Action: delete `_CALL_PATH_RE`, use `grammar._PATH_RE` (promote to a public `PATH_RE`). Tier T0/T1.

### F3 [hidden coupling] Core exposes its regex/format internals as the de facto API for three packages
Claim: `grammar._*_RE`, `render._*`, `builders._*` and `_scan` / `_annotations` are imported by `render`, `builders`, `cli`, `peer`, `dag`, `wire`, with the underscore as the only warning.
Evidence: S. See census (about 45 import lines). `_IDENTITY_NAME_RE` is enforced in three layers (render, `cli/_config.py:139`, `peer/server.py:183`) through a private import. `peer/direct.py` reads node privates and `peer/server` imports `client._blaming_render`.
Cannot rule out: some underscore modules (`_scan`, `_annotations`, `_asgi`) are meant as package-internal and the scan counts same-package uses. I split these in the census; the cross-package rows are the ones to fix.
Interest: renaming a private name breaks other packages; no test says it is allowed; the underscore stops meaning "private".
Action: extract a public home per shared concept: `core.syntax` (the identifier/path/identity patterns), `observe.bind_node_sinks` (public), `peer.errors`/a small `peer._shared` for `blaming_render`, `Url4Node.routes()`/`.is_eval_path()` methods for `direct.py`. Rename only after the fitness function in F8 is in place. Tier T1.

### F4 [duplication] Front-door logic is copied between `Url4Node` and `Client`
Claim: `ExecutionContext(...)` construction and the render-then-blame wrapper are duplicated (D6, D7); the shared helper sits in the wrong file.
Evidence: S. `server.py:240` vs `client.py:282`; `_blaming_render` docstring says it exists "so the two front doors cannot drift", but each front door still repeats the `check=False` + `request, rendered` branching and a 6-line justification comment.
Cannot rule out: the two differ legitimately (client builds a remote sub-request, node uses itself as IO).
Interest: a fix to `env` scope or `strict_fields` handling must land twice. Low churn today (peer files rarely co-change in history).
Action: extract one `evaluate_front_door(io, request_tree, env, ...)` in `peer/_evaluate.py`; both call it. Tier T1. Priority low.

### F5 [duplication / knowledge] CLI defaults and field names live in 3 to 6 places
Claim: D8, D9. `_config.py` has the dataclass defaults and `resolve` repeats each literal as the `_pick_*` default; `app.py` hard-codes the numbers inside help strings; `URL4_CONFIG` is read in `app.py:131` while every other `URL4_*` goes through `_config._pick` (`:226`).
Evidence: S. `resolve()` ignores the dataclass defaults, so changing `ServeConfig.port` alone changes nothing in a run. README toml sample repeats them.
Cannot rule out: tests may pin the literals (good: that would catch drift).
Interest: a default change needs 3 edits; one missed edit gives `--help` text that lies.
Action: `resolve` takes defaults from `ServeConfig`'s field defaults (`dataclasses.fields`); build help with `argparse` `%(default)s` from the same constants; move `URL4_CONFIG` into `_config`; derive `_SERVE_FIELDS` from `fields(ServeConfig)`. Add a test that `--help` contains every default. Tier T1, no behaviour change.

### F6 [hidden coupling, by design] The usage/cost event shape is mirrored on observe and streaming
Claim: `observe.py`, `dag/node.py` and `streaming/protocol/*` carry the same fields; the layering rule forbids the import, so a human keeps them in step.
Evidence: G. 3 commits touched all three; 3 of 5 changes to `signals.py` needed a mirror edit. Coupling output above.
Cannot rule out: this may be a deliberate anti-corruption seam (streaming must import no url4 module).
Interest: each new usage field is an edit in 3 files with no test of field parity.
Action: keep the seam, add a contract test that maps every `observe` usage field to a `TokenUsage`/signal field (or lists the exclusions). Tier T0.

### F7 [architecture-rule drift] ARCHITECTURE.md, package docstrings and `test_layering.py` disagree
| Rule | Written | Enforced by `test_layering.py` |
|---|---|---|
| observe imported by "only the engine" (`ARCHITECTURE.md:42`) | contradicts the same file's table, `peer/__init__.py` and `peer/direct.py:26` | no (peer allowed) |
| observe imports "standard library only" (table) | yes | NOT enforced: `_FORBIDDEN["observe"]` omits `core` and `wire` |
| io imports `core`, `wire` only (table) | yes | NOT enforced: io may import `observe` |
| dag imports only `io.layer` (`:56`, `:63`) | yes | NOT enforced: dag may import any `io.*`, so `dag -> io.http` would pass |
| streaming imports no url4 module | yes | enforced |
| cli: "all of the above" | table row | cli may not import streaming (test); README does not list it, so the gap is in the prose |
| private-name imports across packages | not written | not enforced (F3) |
| "engine names no transport at module scope" | yes (`:78`, `:85`) | partly, by `test_import_isolation.py` (runtime) |
| root `url4/__init__.py` and `_log_attributes` are skipped | only in the test docstring | skipped |
Core `__init__`, `wire/__init__`, `peer/__init__` list observe differently: core and wire list it in "Must not import"; peer lists it under "may import"; dag and io lists are in `ARCHITECTURE.md` only.
Cannot rule out: `observe` may need a `core.errors` import in future; the doc rule can be the thing to change.
Interest: the document and the gate have drifted both ways; a reviewer cannot tell which is authoritative.
Action: make the test table the single source, tighten `_FORBIDDEN` to the written rules (add `observe: {core, wire}`, `io: {observe}`, and a `dag` rule limiting `io` to `io.layer` plus the lazy `_run.py` import), fix K1, and have `ARCHITECTURE.md` generate its table from the test (or cite it). Tier T0.

### F8 [knowledge rot] Comments that state the opposite of the code
K2, K3, K4 above. K3 is the most serious: a comment gives a wrong reason for the assert's placement, and the assert is vacuous (it checks the line just above it). K2 tells a reader that §27.3 is unimplemented while tests prove it is.
Cannot rule out: K2 may mean "delegation to a remote processor" is unimplemented even though selection works; the comment does not say so.
Interest: reviewers trust "INVARIANT" and "WHY" comments in this repo; a false one costs more than an absent one.
Action: delete the duplicate paragraph in `_dispatch.py:65-70` and say precisely what `processor` does at the ingress; rewrite K3 as "gap detection is for the threaded-producer case; use `if ...: raise` if it must survive `-O`", or drop it; change `pyproject` description to "grammar, parser, AST, engine, and scope". Tier T0.

### F9 [knowledge rot] Status documents outside the package are stale
K5 (changelog URLs), K6 (machine-local formal model path), K8 (task docs say Backlog for finished work), and the ISSUES file (six url4 items with no closing note). Move closed items to the "resolved" section that file's header asks for, or delete them. Tier T0. No runtime effect; it wastes triage time.

## Recommended sequence (3 items)
1. T0 batch, one PR, about a day. Fix F2 (one regex), fix K1-K6, F7 test tightening (new `_FORBIDDEN` entries plus a cross-package private-import test), CLI-default test from F5. These are safe, and the new tests make the rest of the work hold.
2. T1 consolidation, a few days. F3 (promote shared privates to named public modules), F4, F5. Do it after item 1 so the private-import test fails on any new offender.
3. T1/T2 strangler-fig for F1 (OME-538). Run the existing parity corpus (`test_characterization.py:249`) as the safety net; delete the text path in the 5 steps above; convert parity tests to graph-shape tests. Decide go or roll back in the task doc first. Do not leave it half done.

## Fitness functions (proposed)
- FF1 `test_no_cross_package_private_imports`: extend `test_layering.py`'s AST walk. Fail when a file in package A imports a name or module starting with `_` from package B (A != B). Ratchet with an allow-list that only shrinks, seeded with today's list (about 20 cross-package rows).
- FF2 `test_path_regex_single_definition`: assert `url4.core.parser` has no `re.compile` of the path charset, or `parser.<path_re> is grammar.PATH_RE`.
- FF3 `test_one_pattern_per_identifier`: scan `src/` for `re.compile` strings equal to a known grammar pattern outside `grammar.py`; allow-list `ensemble.py` until F1 lands.
- FF4 layering matrix equals the document: parse the table in `ARCHITECTURE.md` and compare with `_FORBIDDEN`; fail on any allowed edge the document does not list.
- FF5 `test_cli_defaults_single_source`: `--help` output contains `ServeConfig` defaults; `resolve({}, {}, None) == ServeConfig()`.
- FF6 `test_usage_seam_field_parity`: every field of the observe usage events maps to a `streaming.protocol` field or is in a named exclusion list.
- FF7 `test_lowering_one_pipeline`: after F1, assert `_lowering` has no function named `*_text` and `compile_expression(str)` calls `grammar.parse`.
- FF8 doc-rot gate: `hygiene.py census todos --max-age-days` is not useful on this young history; instead add a test that greps docstrings for `not implemented yet` and requires an open task id.

## Blind spots
- Git history is 62 commits over about 9 weeks, so temporal coupling is weak evidence; the dual-path cost comes from commit messages and in-code incident notes.
- I did not run the test suite, the parity corpus, pyright or any import-linter; claims are from reading and an AST scan.
- Not read: `streaming/*` body logic beyond headers, `dag/executor.py`, `dag/nodes/*` internals, `io/*` behaviour, `examples/`, `scripts/` (module-size and suppression gates), README claims other than pyright.
- ISSUES.md items I-21, I-23, I-25 depend on gateway and eval code outside this package.
- `docs/tasks` statuses 540-546 not checked against code.
- Same-package private imports (for example `dag.nodes._shared`) were listed but not judged; they may be fine as module-private helpers.
- Dead-code and complexity are other lanes; I did not check whether `_PATH_SEGMENT_RE` and similar grammar constants are used.
