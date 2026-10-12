---
title: url4 audit — formal modeling and codebase hygiene
date: 2026-10-09
package: packages/url4 (url4 1.5.1 in pyproject; 1.4.1 on PyPI)
base: main @ da88b135a
branch: url4-audit-fixes
status: findings complete; fixes not started
---

# url4 audit — formal modeling and codebase hygiene

This report gives the results of an audit of `packages/url4`. The audit uses two skills:

- `formal-modeling`: invariants, state models, property laws, equivalence checks, proofs.
- `hygiene-expert`: decay, dead code, coupling, ratchets, dependencies, process artifacts.

Use this report as the work list for the branch `url4-audit-fixes`. Section 9 gives the fix plan.

## How to read this report

- **ID.** Each finding has an ID. The letter gives the area (section 4 and section 5). The lane ID in brackets gives the source lane. Example: `A1 [F3-1]`.
- **Severity.** High: wrong results, lost data, duplicate side effects, or leaked processes in normal use. Medium: wrong results in less common input, or a broken contract that a consumer can see. Low: edge cases, latent faults, or cost without a visible fault.
- **Evidence.** The formal-modeling skill defines these evidence levels for a model:
  - E0: sketch. E1: `fm check` is clean. E2: `fm mutate` shows the guards are load-bearing. E3: the model has `SOURCE` links to the code and the links do not drift. E4: `fm prove` shows the invariant is inductive (for the model, not for the code).
  - **EXEC** means that a script or a property test ran against the real url4 code and showed the fault.
  - **RE-RUN** means that the orchestrator ran the reproduction again, after the lane finished, with the package's own `.venv`, and got the same result.
- **Hygiene evidence.** Each hygiene verdict uses the skill's fixed shape: `[class] claim — evidence — cannot rule out: …`. The class is `static`, `history`, `cross-repo`, `runtime` or `scream-test`.
- **Bounded claims.** A clean `fm check` means "no counterexample within the stated scope". It does not mean "correct". Only `fm prove` INDUCTIVE is unbounded, and only for the model.
- **Line numbers.** Line numbers refer to `main @ da88b135a`. Check them again before you edit.

## Contents

1. Summary
2. Scope and method
3. Corrections to earlier claims
4. Correctness findings (formal lanes)
   - A. Fan-out and fan-in data semantics
   - B. Language, render and lowering
   - C. Executor, guard and concurrency limits
   - D. Streaming run lifecycle
   - E. Transport, serve and wire
5. Hygiene findings
6. Properties that hold
7. Ratchets and fitness functions to add
8. Decisions for the owner
9. Fix plan for this branch
10. Blind spots
11. Evidence index

---

## 1. Summary

The url4 code base is young (first commit 2026-07-15, about 62 commits) and well tested in the normal sense: 1360 tests pass in 3.25 s with 98% coverage, also on Python 3.14 and at the lowest declared dependency bounds. There is no dead private code, no TODO debt, and no known vulnerability in the locked dependencies.

The formal lanes found real faults that example-based tests do not reach. The faults are in four places:

1. **Substitution and quorum in fan-out and fan-in nodes.** Row data is substituted a second time. `;quorum=N` is ignored on fan-out and broadcast groups.
2. **The two lowering paths and the render/build round trip.** The text path and the AST path give different results for some inputs. `render` and the builders can produce text that means a different expression, and the front doors do not check this.
3. **Retries, timeouts and cancellation.** A guarded retry applies a remote side effect again. `url4 serve` does not kill a command subprocess when the request times out. The streaming lifecycle can publish two terminal frames.
4. **Wire encoding.** `{` and `+` in quoted parameter values are not escaped.

The hygiene lanes found process and structure debt, not decay in the code:

- PyPI stops at 1.4.1. Tags 1.5.0 and 1.5.1 were never published, because the Trusted Publisher entry still names the old org.
- The dual lowering pipeline is a half-finished migration (OME-538, Backlog).
- About 20 imports of private names cross package boundaries. The engine imports url4 private modules.
- Some ratchets are stale, and some smells have no ratchet.

### Top findings

| ID | Sev | Area | Finding | Evidence |
|---|---|---|---|---|
| E1 | High | serve | A command that runs past `--timeout` is never killed. Its side effects land after the 504. `--max-inflight` stops limiting live subprocesses. | E4 (model), EXEC, RE-RUN |
| A1 | High | semantics | Row data is substituted a second time. `costs $$5` becomes `costs $5`. A row value can pull in other bound variables. | EXEC, RE-RUN |
| A2 | High | semantics | `;quorum=N` is ignored on fan-out and broadcast groups. The reducer runs on 1 of 3 responses. | EXEC, RE-RUN |
| C1 | High | guard | A guarded retry applies the remote effect again. `;t=0.05;retry=2` gave 3 effects for one source. | E4 (fix), E3, EXEC, RE-RUN |
| B1 | High | lowering | The text path and the AST path disagree on a call with a chained intent (`/p(x)!a!b`). The text path drops `b`. | EXEC (pinned), RE-RUN |
| B2 | High | parser | A leading `*(` at the envelope becomes an iteration over an empty collection. Nothing is fetched. No error. | EXEC, RE-RUN |
| B3 | High | front doors | `Client` and `Url4Node` render with `check=False`. A builder tree can run as a different expression (26 silent classes). | EXEC (census) |
| D1 | Medium | streaming | A flush failure or a cancel inside `_terminate("succeeded")` publishes a second terminal frame. | E3 model, EXEC, RE-RUN |
| D2 | Medium | streaming | A publish that fails before it writes burns a sequence number. On JetStream the client cannot accept the terminal frame. | EXEC, RE-RUN |
| B6 | Medium | parser | `build("a:")` raises `IndexError`. Over HTTP this is an uncaught exception, not a 400. | EXEC, RE-RUN |
| HY-1 | High (process) | release | PyPI has 1.4.1. Tags 1.5.0 and 1.5.1 never published. 13 commits since the 1.5.1 tag. | cross-repo (PyPI JSON), verified |
| HY-2 | Medium | structure | Dual lowering pipeline is a half-finished migration (OME-538 in Backlog). Three bugs on 2026-08-03 came from it, and B1, B4, B5 come from it. | history |

---

## 2. Scope and method

### Scope

- `packages/url4/src/url4` (about 13k lines): `core`, `wire`, `dag`, `io`, `observe`, `peer`, `cli`, `streaming`.
- `packages/url4/tests` (about 14k lines), `scripts/`, `examples/`, CI workflows for url4.
- In-repo consumers, for cross-repo evidence only: `apps/screamingface-engine`, `apps/screamingface-studio/runtime`, `packages/screamingface`, `url4_playground.py`.

### Lanes

| Lane | Skill | Model | Scope |
|---|---|---|---|
| F1 | formal-modeling | Opus | Executor memo, TaskGroup cancellation, `GuardNode` retry and timeout, `BoundedIOLayer`, existing `tests/formal` models |
| F2 | formal-modeling | Opus | `streaming/lifecycle.py`, port contracts, JobStatus state machine, conformance suite |
| F3 | formal-modeling | Opus | `MapNode`, `ReduceNode`, group nodes, quorum, `parse_collection`, `ensemble` substitution |
| F4 | formal-modeling | Opus | Grammar, parser, `_scan`, render, builders, the two lowering paths, wiring acyclicity |
| F5 | formal-modeling | Opus | `peer/*`, `cli/_serve.py`, `io/http.py`, `io/static.py`, `wire/subrequest.py` |
| H1 | hygiene-expert | Sonnet | Census, hotspots, trends, bus factor, env vars, ratchets, CI |
| H2 | hygiene-expert | Sonnet | Dead code, unused exports, over-engineering |
| H3 | hygiene-expert | Sonnet | Duplication, coupling, half-finished migrations, layering drift, stale docs |
| H4 | hygiene-expert | Sonnet | Dependencies, packaging, consumers, test hygiene, examples, release |

### Tools

- `fm.py` (formal-modeling driver): `audit`, `check`, `mutate`, `prove`, `equiv`, `laws`, `compare`.
- `hygiene.py`: `hotspots`, `coupling`, `trend`, `census`, `bus-factor`, `age`, `env`, `ratchet`.
- `hypothesis` property tests and probe scripts against the real code, in scratch virtual environments.
- `vulture`, `deptry`, `pip-audit` (through `uvx`).
- CodeGraph for structure and call paths.

### Verification by the orchestrator

The orchestrator ran the reproductions for each High finding and the main Medium findings again, with `packages/url4/.venv`. The findings marked RE-RUN gave the same result. The orchestrator also checked the PyPI release state directly (`https://pypi.org/pypi/url4/json`).

### Baseline `fm audit`

`fm audit packages/url4/src` found 11 rule classes. Its hotspots (files that trip 3 or more rules) are `dag/executor.py`, `dag/_context.py` and `cli/_serve.py`. Its suggested order was: state-machine, concurrency, transaction-isolation, merge-conflict, timeout-assume-fail, class-invariant, loop-invariant, guard-complexity, idempotence. The full output is in `evidence/fm-audit.txt`.

---

## 3. Corrections to earlier claims

The first exploration pass (scouts) made some claims that the audit lanes found to be wrong. Do not act on these claims.

| Earlier claim | Correction | Source |
|---|---|---|
| `packages/screamingface` imports url4 without a dependency, so `import screamingface` fails in a clean install. | False. `packages/screamingface/scripts/runtime_build_hook.py:32-64` copies `packages/url4/src/url4` into each wheel as a top-level `url4/`. Editable installs get a `.pth` to the live source. A smaller risk remains (see HY-14). | H4, verified |
| `ErrorEvent`, `HeartbeatEvent`, `StopEvent`, `AttachEvent` are dead wire types. | False. The engine WS bridge produces and handles all four (`engine/ws/bridge.py`, `engine/schemas/protocol_schemas.py`). | H2, F2 |
| `dispatch_direct`, `bare_root_ok` and the five `Supports*` protocols are unused. | False. `dispatch_direct` is called at `engine runner/executor.py:1032`. `bare_root_ok` is passed at `dag/executor.py:276`. `FairShare` checks four `Supports*` protocols. | H2 |
| There are two `serve` implementations. | False. `Url4Node.serve` is a 2-line wrapper over `peer/_http.serve`. | H2 |
| `observe.py:30` says "only the engine imports it". | The statement is in `ARCHITECTURE.md:42`, not in `observe.py`. | H3 |
| The 95% coverage gate is in `screamingface-tests.yml`. | It is in `.github/workflows/url4-tests.yml`. | orchestrator |
| v1.5.1 is the release that PyPI users have. | PyPI stops at 1.4.1. Any API added after 1.4.1 has no PyPI users. | orchestrator (PyPI JSON) |
| The `_Sequencer` assert comment explains how the assert survives `python -O`. | The comment is about the cost of a method call. The assert is a tautology and guards nothing (D5). | orchestrator, F2, H3 |

---

## 4. Correctness findings (formal lanes)

### A. Fan-out and fan-in data semantics (lane F3)

Files: `dag/nodes/iteration.py`, `dag/nodes/group.py`, `dag/nodes/_shared.py`, `dag/semantics/collection.py`, `dag/semantics/ensemble.py`, `dag/_wiring.py`.

#### A1 [F3-1] High — row data is substituted a second time

- **Where:** `dag/nodes/_shared.py:101-108`.
- **Fault:** the code runs `substitute_item`, and then runs the `$name` pass over the result. This breaks the docstring at `_shared.py:95-97`, which says a row value is not scanned again.
- **Effect (EXEC, RE-RUN):**
  - Row `costs $$5` arrives as `costs $5`.
  - Row `see $index here` arrives as `see 1 here`.
  - Row `literal $item` arrives as the whole row JSON.
  - Row `$x`, with `x` in scope, arrives as the value of `x`.
- **Risk:** row values come from fetched data. Fetched content can read other bound variables into a prompt.
- **Fix:** do the `$item` and `$name` substitution in one regex pass over the original template. Compute the `{...}` JSON spans one time. See A5, which has the same root cause.
- **Tests to land:** `test_row_value_opaque_through_leaf_pipeline`, `test_item_path_value_not_rescanned` (`evidence/F3-semantics/test_props.py`).

#### A2 [F3-2] High — `;quorum=N` is ignored on fan-out and broadcast groups

- **Where:** `dag/_wiring.py:170-178` and `:198-238`. These lines build `FanoutReduceNode` and `BroadcastCollectNode` with no quorum.
- **Effect (EXEC, RE-RUN):** `(/a(x)!'y', /b(x)!'y';optional, /c(x)!'y';optional)!'merge';quorum=3` with 1 of 3 calls resolved:
  - fan-out: the reducer runs on one response;
  - broadcast: the result is returned as if all sources succeeded;
  - local group with the same sources: raises `quorum_not_met` (correct).
- **Fix:** pass quorum to `FanoutReduceNode` and `BroadcastCollectNode`, and enforce it with the shared helper in `_shared.py:253-260`.
- **Test to land:** `test_fanout_quorum_enforced`. Probe: `evidence/F3-semantics/probes/probe_quorum.py`.

#### A3 [F3-3] Medium — broadcast does not drop a failed optional source

- **Where:** `dag/nodes/group.py:214` (the check can never be true) and `group.py:180` (`MergeNode` turns the failure into `""` and still calls `process`).
- **Effect (EXEC):** n=2, source 1 fails. The parts are `[1,2]`, not `[2]`. This breaks the §6.1.3 docstring.
- **Fix:** make `MergeNode` return the `SourceFailure` unchanged.
- **Test to land:** `test_broadcast_omits_failed_optional_sources`.

#### A4 [F3-4] Medium — the `$$` escape collapses two times in a call intent

- **Where:** `dag/nodes/fetch.py:117-118` and `:171-172` substitute an intent that a `TextNode` already substituted. `group.py:276` does the same for fan-out instructions.
- **Effect (EXEC):** `/echo(x)!'literal $$a'` with `a` bound gives `literal BOUND`. The context position is correct.
- **Fix:** substitute a call intent one time only.

#### A5 [F3-5] Medium — `substitute_item` substitutes two times and can emit invalid JSON

- **Where:** `dag/semantics/ensemble.py:296-304`. The bare-`$item` pass scans inserted values again and computes the `{...}` spans again on the changed text.
- **Effect (EXEC):**
  - `substitute_item("<$item.a>", '{"a":"$item"}')` gives `<{"a": "$item"}>`.
  - Template `$item.a {"k": "$item"}` with row `{"a":"{"}` gives invalid JSON.
- **Fix:** same as A1.

#### A6 [F3-6] Medium — collection sniffing changes the row count and the row text

- **Where:** `dag/semantics/collection.py:154-207`.
- **Evidence:** `fm equiv sniff_line_count.py` (exit 1) shows that the CSV branch is the only place where "N text lines give N items" fails. EXEC:
  - `"red,green\nblue,yellow"` gives 1 item.
  - `"Paris,France\nTokyo,Japan\nLima,Peru"` gives 2 rows keyed by `Paris`.
  - Header `a,a` drops a column.
  - `"2.50\n3.10"` gives `['2.5','3.1']`. `"1e3\n2"` gives `['1000.0','2']`.
  - `[0]` and `["0"]` parse to the same items.
  - Declared `application/jsonl` raises, but the same body with no declared type parses.
- **Also:** `fm equiv sniff_csv_guard.py` is EQUIVALENT, so the comma pre-check at `:173` is redundant.
- **Fix:** keep the text of scalar JSONL lines. Reject duplicate CSV headers. Map `application/jsonl` to the NDJSON parser. Write the two-line comma rule into the spec, or remove the CSV sniff for 2-line inputs. This needs a spec decision (section 8, D-4).

#### A7 [F3-7] Low-Medium — the `collected_errors` count does not match the output

- **Where:** `dag/nodes/iteration.py:187`, `dag/_context.py:230`.
- **Evidence:** `fm check map_modes.py` exit 1 with two 4-step traces. EXEC (`probe_tally.py`): collect mode gives count 3 but the output has 2 error objects. Fail mode raises with count 1.
- **Impact:** no production code in the monorepo reads `ctx.collected_errors`.
- **Fix:** give each row a child error count. Merge it into the run count only when the map returns. The fixed model (`map_modes_fixed.py`) is E1.

#### A8 [F3-8] Low-Medium — an explicit inner `on_error=collect` loses to the outer policy

- **Where:** `core/parser.py:353` (`_merge_directives`), `core/nodes.py:208`.
- **Cause:** the code cannot tell "collect" from "not set", because `collect` is the default value.
- **Evidence:** EXEC. `fm laws` on `_merge_directives`: idempotent, associative, and has an identity over reachable values. Not commutative (by design).
- **Fix:** change the type to `on_error: OnErrorPolicy | None = None`.

#### A9–A12 — Low

- **A9 [F3-9]:** quorum counts expanded elements and leaves out instrumental sources (`_shared.py:255`). The spec says "N sources to resolve". Spec decision (D-4).
- **A10 [F3-10]:** `GatherNode` leaks instrumental values (`group.py:99`). It tests the joined text for empty, not the sources. `("", "INSTRUMENTAL")` gives `"\nINSTRUMENTAL"`. RE-RUN.
- **A11 [F3-11]:** `_rows_to_json` emits non-standard JSON for NaN (`_shared.py:127`). Row `"[NaN]"` comes out as `[NaN]`. Use `allow_nan=False` and decide on an error.
- **A12 [F3-12]:** `ExpandNode` (`iteration.py:54-57`) has no fast path for a list. `["one row"]` raises "not iterable". No surface syntax reaches it today (latent).

#### Review questions (F3)

- **Invariant written down?** Row opacity: written, broken (A1, A5). Quorum: enforced on 2 of 4 group routes (A2). Broadcast omission: dead check (A3). Output order and the collect/skip/fail rules: written and hold.
- **Success with a lost response?** A row can fail locally after its remote side effect happened. There is no dedup key and at most one try for each row, unless the body uses `;retry` (then see C1).
- **Loop variant?** Every loop is a bounded `for`. A row is bound, not parsed again, so a row cannot add a `*` level.

---

### B. Language, render and lowering (lane F4)

Files: `core/grammar.py`, `core/parser.py`, `core/_scan.py`, `core/render.py`, `core/builders.py`, `core/nodes.py`, `dag/_lowering.py`, `dag/_wiring.py`, `peer/client.py`, `peer/server.py`.

All counterexamples in this section are pinned in `evidence/F4-language/tests/test_findings_pins.py` as 19 `xfail(strict=True)` tests. RE-RUN: 19 xfailed.

#### B1 [F4-F3] High — the text path and the AST path disagree on a call with a chained intent

- **Where:** `dag/_wiring.py:193-194`, `dag/_lowering.py:279-283`, `core/parser.py:66-71`.
- **Effect (EXEC):** `/p(x)!a!b`.
  - Text path: one call, `b` is dropped with no error. Cause: `_fold_intent_into_call` sets the outer intent, and then `deps.update(node.deps)` overwrites it with the call's own intent.
  - AST path: fans out and reduces with `b`. Cause: the root that `build` wraps around a bare source is lowered with `from_list=True`.
  - Inside `(…)` the grammar reads a third way: the intent is `a!b`.
- **Fix:** decide the meaning in the spec (D-1). Then give both paths one classification. Long term: HY-2 (collapse to one path).

#### B2 [F4-F2] High — a leading `*(` at the envelope becomes an iteration over an empty collection

- **Where:** `core/parser.py:141` and `:159` call `iter_iteration_stars` without `skip_leading`.
- **Effect (EXEC, RE-RUN):** `*(https://a, https://b)!go` gives `Iteration(collection=Expression(()), …)`. Nothing is fetched. The result is `[]` with no error. The grammar reads the same text as expansion (`grammar.py:177`). The text path also applies this inside lazy nested groups, so the two paths disagree: `(x, (*(https://a.io)!'i')!'j')!'k'`.
- **Fix:** pass `skip_leading=True` for envelope iteration detection.

#### B3 [F4-F7] High — the front doors can run a different expression with no error

- **Where:** `peer/client.py:263-281`, `peer/server.py:264-269`. Both render with `check=False` and verify only when the run raises `ParseError`.
- **Effect (EXEC; census: 26 silent classes):**
  - `src("https://x.io", mode="a!b")` renders `https://x.io;mode=a!b`. This runs as `mode=a` with intent `b`.
  - `Binding("src", SelfRef())` renders `src=@`. This parses again as a bare `@`.
- **Root causes:** the render guards do not forbid `!` in values. `_render_binding` does not validate the name. An intent that fails to parse silently becomes `Text`. The full list of 11 root causes is in the F4 record (section B-record below).
- **Fix:** keep `check=True` at the front doors (cost: one extra parse for each request), or make the render guards complete. Do the cheap fix first.

#### B4 [F4-F4] Medium — nested `;broadcast`

- **Where:** the grammar keeps it as a param (`grammar.py:421-426`). `decode_envelope` folds it into the flag (`parser.py:282-283`).
- **Effect (EXEC):** `(()!'h';broadcast)!'t'`: text path gives `t\n\n[]`, AST path gives `t\n\nh`. Render rejects the tree the parser made.
- **Fix:** fold `;broadcast` in `grammar._attach_tail` and treat it as a reserved key (type change T3).

#### B5 [F4-F5] Medium — `_GROUP_BINDING_RE` does not reserve `src`

- **Where:** `dag/_lowering.py:101`.
- **Effect (EXEC):** `(src=(https://a.io)!'i', $src)!'k'`: `$src` is bound on the text path and stays literal on the AST path. `src:(g)!i` runs on the text path, but `build` rejects it.
- **Fix:** take the binding classification from the grammar, not from a second regex.

#### B6 [F4-F1] Medium — `IndexError` instead of `ParseError`

- **Where:** `core/grammar.py:223`, reached from `_parse_attrib_chain` (`grammar.py:264`).
- **Effect (EXEC, RE-RUN):** `build("a:")`, `build("0:")`, `build("(x, a:)!go")` raise `IndexError`. Over HTTP, `GET /v1?q=(x,%20a:)!go` ends in an uncaught exception, because `peer/_http.py:79` catches only `Url4Error` (see E7). The response should be 400 `malformed_source`.
- **Fix:** add `if not rest: raise ParseError(...)` before the `_is_value_shaped` call. Do this first: it is one line and it closes a crash path.

#### B7 [F4-F9] Medium — a canonical-form call is rejected at top level

- **Where:** `core/parser.py:100-106` (`_is_call_target` knows only the sugar form).
- **Effect (EXEC):** `/p?t=90&q=(x)!go` gives `MISSING_INTENT`. `(/p?t=90&q=(x)!go)!r` parses.
- **Fix:** ask the grammar if a head token is a call target.

#### B8 [F4-F6] Medium — `render` is not total on what `build` accepts

- **Evidence (EXEC; census: 111 classes).** Families:
  - control characters in bare text (related to I-30);
  - quoted param values: `(a)!go;note='a b'`;
  - bare roots: `@`;
  - a relative URL with parens in the query: `/p?a=(1)`;
  - the `!*(` ambiguity: `(x)!*(y)!z` parses as an iteration.
- **Fix:** close each family in render, or reject it in `build`. Land `test_L2prime_render_total_on_build_image` as the gate.

#### B9 [F4-F8] Low-Medium — the builder promise "every builder output renders" is false

- **Evidence (EXEC):** fails in all 10 builder families tested. Examples: `text("\x1f")`, `src(weight=inf)`, `ref("a",-1)`, `iterate(concurrency=True)`.
- **Fix:** validate in the builders, or (better) in `__post_init__` of the node types (types-as-specs, below).

#### B10–B13 — Low

- **B10 [F4-F10]:** `src*(b)!*go` and `;broadcast` after an iteration are dropped with no error.
- **B11 [F4-F11]:** `build("")` returns an empty `Expression`. `(x)!` is accepted with an empty intent.
- **B12 [F4-F12]:** `iter_top_level` counts `(` and `{` as one depth. An unmatched `{` in bare text swallows the commas after it. `(a{b, c)!x` gives one source. Related to I-18.
- **B13 [F4-F13]:** the envelope keeps iteration-body whitespace and the grammar strips it.

#### Types as specifications (F4 §6)

These invariants are checked only by the parser or render today. Move them into the node types.

| ID | Invariant | Recommended carrier |
|---|---|---|
| T1 | `Expression.intent=None` has 4 roles (paren-collection, envelope carrier, bare root, empty build) | Split into `ParenCollection` and a fragment root type. Make the intent required. |
| T2 | Intent forms | An `Intent` union without `Iteration`, `VarRef`, `Binding` or `Source` |
| T3 | Reserved keys (`broadcast`, `iteration.*`, `expand`) | `__post_init__` check. Fold `;broadcast` in `grammar._attach_tail`. |
| T4 | Weight ≥ 0, finite, writable as a decimal. Structured values have a depth limit. | `Weight.of` smart constructor, `StructValue` alias |
| T5 | Names are ASCII identifiers and not `src` | `__post_init__` on `Binding` and `Source` |
| T6 | `Source` shapes with no grammar form | `__post_init__` or a smart constructor |
| T7 | `Text` and control characters | Define `\n`, `\t`, `\uXXXX` escapes in the spec (closes I-30) |
| T8–T10 | `VarRef`, `IdentityRef`, `IterationDirectives` | `__post_init__` checks that use the grammar regexes |
| T11 | `Iteration.intent` required; collection is not an `Iteration` | Type change |
| T12 | Relative URL query part | Validate in the grammar |
| T13 | Expression path segments are not empty (except root `/`) | Grammar check |

#### B-record — F4 evidence

- **Round-trip laws** (`tests/test_roundtrip.py`, 3000 examples for each law; `tests/census.py`, 15000):
  - L1 `build(render(n)) == n` when render accepts: holds (tautological, because render checks its own output).
  - L2i `render∘build` idempotent: no counterexample in 3000 grammar strings.
  - L2, L2′ (render total on the image of build), L3 (no misreading), L3s (no silent misreading), F (`build` raises only `ParseError`), B (builder output renders): counterexamples.
  - Census: 26 silent L3 classes, 577 loud L3 classes, 111 L2′ classes, 4 crash buckets (one root cause, B6).
- **Silent-misreading root causes (L3s):** `!` in a param, query or annotation value; binding names not validated (`src=`, `é=`, `topic:` + `//`); reserved `expand` as an annotation; nested intent params hoisted; top-level bare `Source` around an expression loses its wrapper; relative URL or URL intent with `!`, unbalanced `(` or `*(`; relative call with a group intent at top level; `intent_atom` turns any unparseable intent into `Text`; Unicode digits accepted by `str.isdigit` in `VarRef` names (`VarRef('١')` → `Text('$١')`); `*()` reads as an iteration (B2); whitespace normalization of the iteration intent.
- **Lowering refinement** (`tests/test_lowering_equiv.py`, `census_lowering.py 3000`): claim `obs(run(s)) == obs(run(build(s)))`. Counterexample. 54 classes reduce to B1, B4, B2-nested, plus fetch-count differences on runs that fail on both paths (excluded: cancellation timing). B5 comes from the classifier review. The two iteration-body reference readers share `_body_intent_refs` and agree.
- **Regex equivalence:** `fm equiv equiv_call_vs_expr_path.py` EQUIVALENT (exit 0, ASSUME length ≤ 12). `tie_regexes.py`: identical pattern text and flags; `render._PATH_RE is grammar._PATH_RE`; 0 differences over 19608 strings. Expression path vs data path: INCOMPARABLE (witnesses `"/"`, `"/:"`). The defect is the classifier (B7), not the regex.
- **Acyclicity:** see section 6.
- **`_scan.py` loop invariants and variants:** all scanners terminate (variant n−i or n−j). `_parse_attrib_chain` (`while True`) has variant `len(rest)` and crashes when `rest` is empty (B6). `balanced_braces` cannot close after a stray `}`. The docstring understates this. Use one shared depth model for all scanners (B12).

---

### C. Executor, guard and concurrency limits (lane F1)

Files: `dag/executor.py`, `dag/_run.py`, `dag/_context.py`, `dag/nodes/guard.py`, `dag/_lowering.py`, `core/builders.py`, `tests/formal/*`.

#### C1 [F1-1] High — a guarded retry applies the remote effect again

- **Where:** `dag/nodes/guard.py:69-77` and `:83-88`.
- **Fault:** a timeout is a non-result. The remote call can succeed after the timeout. The retry then applies the effect again. The docstring says guarded effects "must be idempotent", but nothing sends an idempotency key.
- **Evidence:**
  - `fm check guard_retry_as_written.py`: "'effect_at_most_once' fails after 7 transition(s)". E3 (SOURCE links hold).
  - EXEC, RE-RUN: case G1 in `repro.py`, `;t=0.05;retry=2`, gave **3 effects** for one source.
  - Fixed design `guard_retry_fixed.py`: `check` exit 0 (112 states), `--sweep RETRIES=0..5` exit 0, `mutate` exit 0 (24 of 45 edits killed). `prove_guard.py --bmc 6`: INDUCTIVE and TERMINATES (E4 for the model).
  - `--challenge`: the fix depends on the remote deduplicating, on `;t=` being set, and on cancellation being honoured.
- **Fix:** one idempotency key for each guarded resolve. Reuse it for every attempt. The `IOLayer` forwards it (for HTTP: a header). This changes the wire contract (decision D-2).
- **Also under `;optional`:** an effect that was applied is dropped from the result.

#### C2 [F1-2] Medium — `;t=` also counts the time in the run-wide I/O queue

- **Where:** `dag/nodes/guard.py:83` with `dag/_context.py:145`.
- **Evidence:** `fm check`: "'timeout_implies_io_issued' fails after 2 transition(s)". EXEC, RE-RUN (`concurrency=1`): a 10 ms source fails as "source timed out". With `;retry=3` it issued **0 fetches**.
- **Fix:** do **not** start the timer later. `mutate` shows the deadline must cover queue time, or the guarantee that a guarded source finishes is lost. Instead, set an "I/O issued" context variable after the permit is acquired. When it is not set, raise a separate admission-timeout code, and optionally do not use up a retry.

#### C3 [F1-3] Medium — `;retry=` and `;t=` values are not range-checked on the text path

- **Where:** `dag/_lowering.py:385-406` (no check). `core/builders.py:207-216` does check.
- **Evidence (EXEC, RE-RUN):**
  - `;retry=-1`: `AssertionError` (a `TypeError` under `-O`). Neither is a `Url4Error`.
  - `;retry=-5;optional`: the source is dropped with no error and never fetched.
  - `;t=0` and `;t=-1`: always time out.
  - `;t=nan`: the timeout never fires. The call hangs.
  - `;retry=` has no upper cap. One expression can make an unbounded number of requests.
- **Fix:** one validator for `t` (finite, > 0) and `retry` (0 to a cap), shared by `_lowering.py` and `builders.py`. Replace the `assert` at `guard.py:76` with a `Url4Error`.

#### C4 [F1-4] Low — a hand-built graph can fetch a shared node two times

- **Where:** `dag/executor.py:296`, `:80-87`.
- **Evidence:** EXEC case E2: a node shared inside and outside a `GuardNode` is fetched 2 times. The debug resolve-once check does not see it, because it counts for each executor. Compiled graphs do not have this fault (case E3).
- **Fix:** make `_resolve_counts` count for each run, not for each executor.

#### C5 [F1-5] Low — reusing an `Executor` after a failed run raises `CancelledError`

- **Where:** `dag/executor.py:80`, `:148-152`. EXEC case E1.
- **Fix:** make `Executor` single-use (raise a clear error on the second call), or reset the memo.

#### C6 [F1-6] OK with conditions — executor memo and TaskGroup abort

- `executor_taskgroup.py`: `check` exit 0 (1524 states), `mutate` exit 0 (52 of 72 killed). E3.
- The property "the run finishes" holds only if (a) no code swallows `CancelledError` (if it does: deadlock, `-D CANCEL_HONOURED=0`) and (b) the remotes answer. There is no run-level deadline. The httpx `timeout=30` applies to each operation, not to the total.

#### C7 [F1-7] Info — nested semaphores do not deadlock

- `semaphore_nesting.py`: `check` exit 0 at MAP=1/RUN=1 and MAP=2/RUN=2.
- Exception: an `IOLayer` whose `fetch` calls back into the same `BoundedIOLayer` (`-D REENTRANT_IO=1` gives a deadlock). No url4 adapter does this today. Write the rule in the `IOLayer` docstring.

#### Existing `tests/formal` models

- The fixed models check clean. The buggy models still violate. `mutate` exits 0 with one load-bearing guard each. The stand-in pytest passes.
- They have no `SOURCE` links and no `FAILURE_ACTIONS`. As evidence about the code they are E0.
- The docstrings cite `executor.py:154-174`. The code is now at `134-152` (drift).
- The headers point at `~/Documents/skills/...`. The in-repo skill is untracked.
- **Action:** add `SOURCE` links, add `FAILURE_ACTIONS = []` with a reason, fix the line numbers.

#### Review questions (F1)

- **`executor.py`:** resolve-once is written down, but only for each executor. Span pairing and "no live task at exit" are not written anywhere. A sibling cancelled mid-fetch loses its result, but there is no retry, so no duplicate. `check_acyclic` is bounded by nodes plus edges (not written down).
- **`guard.py`:** "effects are idempotent" is in the docstring only. Retries duplicate the effect (C1). The variant `retries+1-i` is valid only when `retries ≥ 0`, and there is no upper cap (C3).
- **`_context.py`:** `next_seq` has an inline assert and is correct. An observer that raises uses up a sequence number with no event. Deadlock freedom of the semaphore is not written down. A fetch cancelled while it waits for the permit is reported as a source timeout (C2).

---

### D. Streaming run lifecycle (lane F2)

Files: `streaming/lifecycle.py`, `streaming/interfaces/*`, `streaming/testing/stream_contract.py`. Adapters read for context: `apps/screamingface-engine` (`jetstream.py`, `memory.py`, `inprocess.py`, `queue_runner.py`, `client/_engine/contract.py`, `run_evidence.py`, `supervisor.py`).

Model: `model_lifecycle.py` (fingerprint `06f281e6e11e`), 45 `SOURCE` links (all ok), 29 failure actions (publish raises before or after the write; cancel before or after the write; flush raises or is cancelled; deadline at each await; executor raises, ends without `Completed`, or hangs; `ensure_stream` fails). Scope MAX_TEL=1, FAULTS=2, CANCELS=1 (412 states); also MAX_TEL=3, FAULTS=3, CANCELS=2. As built: `check` exit 1 on `at_most_one_terminal`, `terminal_is_last`, `seq_gap_free` and the leads-to. `fm prove` was not run (z3 was not installed in that lane).

All reproductions are in `evidence/F2-streaming/repro_lifecycle.py`. RE-RUN: R1–R6 reproduced.

#### D1 [F2-F1] Medium — a second terminal frame

- **Where:** `streaming/lifecycle.py:221-240`. Line 226 is inside the `try`.
- **Effect (EXEC R1, R2):** if flush or publish raises, or a cancel lands, inside `_terminate("succeeded")`, another `except` arm publishes a second terminal frame: `4:succeeded 5:failed`, or `4:succeeded 5:stopped`. The `_terminate` docstring promises one terminal frame.
- **Why Medium, not High:** deployed adapters mask it. On JetStream, `publish` pops `_offsets` after a terminal frame (`jetstream.py:747-748`). The second terminal publish reads the tail again and drops the frame (I-EV4). `Nats-Msg-Id` removes a late duplicate. `InMemoryEventStream` never raises or suspends here. Any other adapter is exposed. `TerminalWatch` and `QueueJobRunner.status()` keep the **last** terminal frame.
- **Fix (FIX=3, chosen by the lane):** set `seq.terminal_sent = True` after the terminal publish returns. Each `except` arm re-raises when the flag is set.
  - `model_lifecycle_fix3_safety.py`: `check` exit 0 (273 states), `mutate` exit 0, the new guard is load-bearing. `--challenge`: depends on LOST_RESPONSE (a publish never writes and then raises). This assumption holds for JetStream's sequenced path and for InMemory.
  - `model_lifecycle_fix3_live.py`: the leads-to "a started run gets a terminal frame" holds under weak fairness, within scope, only with a reliable termination path and a non-None `deadline_s`. E2.
- **Tests to land:** R1 and R2 as unit tests.

#### D2 [F2-F2] Medium — a failed publish burns a sequence number

- **Where:** `lifecycle.py:117,166,177,181,182`. `seq.next()` runs before `await publish`.
- **Effect (EXEC R4):** a publish that fails before it writes leaves a hole: `1:started 2:log 3:usage 5:terminated:failed`. On JetStream, the terminal frame is then behind a hole that cannot be filled. The client (`client/_engine/contract.py:152-171`) does not accept it and raises `event_stream_replay_exhausted` with `permanent=False`. So the real outcome is lost and the error looks retryable. The OME-949 "maximum payload exceeded" failure on the Result frame is this kind of failure.
- **Fix:** split `_Sequencer.next()` into `peek()` and `commit()`. Call `commit()` only after publish returns. Write "a publish that raises wrote nothing" into `EventPublisher.publish`. Replace the tautological assert (D5) with a check in `commit()`. Also accept a root `TerminatedEvent` after a gap in the client's `_accept_sequence`.
- **Trade-off:** with LOST_RESPONSE=1, a reused number makes `Nats-Msg-Id` dedup drop the terminal frame (`model_lifecycle_fix3_commit.py` shows the trace).

#### D3 [F2-F3] Low-Medium — the failed arm's flush can raise again; the terminal flush has no bound

- **Where:** `lifecycle.py:229/240`, `jetstream.py:859-918`.
- **Effect (EXEC R3):** if a second ack is rejected after the first failure surfaced, the failed arm's flush raises again and `run` raises out of that arm. This contradicts `stream.py:41-43`. The terminal flush is outside the deadline, and nats-py ack futures have no timeout.
- **Context:** the system-level guarantee comes from the worker backstop (`supervisor.py:730-772`), whose hard kill bounds the hang.
- **Fix:** bound the terminal flush with `asyncio.timeout` inside `_terminate`. Do not let the failed arm's flush raise again. State in `run`'s docstring that the guarantee needs a reliable termination path and a non-None `deadline_s`.

#### D4 [F2-F4] Low-Medium — nats-py turns cancellation into `TooManyStalledMsgsError`

- **Where:** `nats/js/client.py:255-258` (engine venv). EXEC R5 with a fake.
- **Effect:** a deadline that fires while publish waits on the in-flight semaphore ends the run `failed`, not `timed_out`. An external cancel there is swallowed.
- **Fix:** write "publish and flush must let `CancelledError` through" into the port. In `JetStreamPublisher.publish`, catch `TooManyStalledMsgsError` and raise `CancelledError` again when `current_task().cancelling()` is non-zero. (Engine change.)

#### D5–D10 — Low and Info

- **D5 [F2-F5]:** the `_Sequencer` assert (`lifecycle.py:64-66`) is a tautology. It checks the line just above it. EXEC R4 shows it stays silent at a real hole. The comment about `-O` is misleading (H3-F8). Replace with the `commit()` check (D2).
- **D6 [F2-F6]:** in-process `status()` (`engine inprocess.py:61-72, 248-250`) reads the asyncio task. Failed and timed-out runs read `succeeded`. It never returns `timed_out`. A finished topic can be scheduled again, so a terminal status is not absorbing. No production caller found (latent). Fix: return `TerminalWatch.outcome`.
- **D7 [F2-F7]:** the JobRunner port never writes its transition set (`jobs.py:16-25`). The queue runner has `scheduled→stopped`, `scheduled→not_found`, `not_found→stopped` (`queue_runner.py:416-426`). Benign. `model_jobstatus_queue_spec2.py` (adds `not_found→stopped`): `check` exit 0, `mutate` exit 0. Fix: write the set into `jobs.py`.
- **D8 [F2-F8]:** on `InMemoryEventStream`, a resume after `delete_stream` blocks for ever instead of raising `StreamNotFoundError` (`engine memory.py:77, 103-107`; contradicts `:83-85`). Local mode only. Fix: `purge` deletes the topic key from `_log` and keeps `_next_seq`.
- **D9 [F2-F9]:** `run` breaks out of the executor generator and never closes it (`lifecycle.py:168-171`). The asyncgen finalizer closes it later in another task, so errors in `_aclose_world` go to the loop handler. EXEC R6. Fix: `contextlib.aclosing(...)`.
- **D10 [F2-F10]:** `ensure_stream` is outside the `try` (`lifecycle.py:209`). A failure there exits with no frame. Info: there may be no stream to publish to. Fix the docstring, or move the call into the `try`.

#### Conformance suite gaps (`streaming/testing/stream_contract.py`)

The suite's `_frame()` (`:27-33`) builds frames with no sequence. On JetStream this goes to `publish_next`, so the suite never tests the sequenced path that `lifecycle.run` uses.

Tested: call order; `from_sequence < 1` raises; inclusive replay then live; subscribe before first publish; `delete_stream` does not rewind; `ensure_stream` idempotent.

Not tested: deferred durability; deferred failure on the next call; `flush` raises once then discards; one publishing task per topic; `delete_stream` idempotent; `purge` keeps counting; resume after reclaim raises `StreamNotFoundError` (InMemory breaks it, D8); separate counters for two topics; nothing stored after a terminal frame (I-EV4); port calls let cancellation through (D4).

---

### E. Transport, serve and wire (lane F5)

Files: `cli/_serve.py`, `peer/*`, `io/http.py`, `io/static.py`, `wire/subrequest.py`.

#### E1 [F5-1] High — `url4 serve` never kills a command that runs past `--timeout`

- **Where:** `cli/_serve.py:252` gives the command `config.timeout`. `_serve.py:297` starts a request timeout of the same length earlier, so it always fires first. It cancels the handler with `CancelledError`. The `except TimeoutError` at `_serve.py:154` does not catch `CancelledError`, so the kill at `:155` never runs. Read-side command providers (`:189`) have the same fault.
- **Effect (EXEC, RE-RUN):**
  - `repro_subprocess_orphan.py`: the side effect lands 1.5 s after the 504.
  - A command with a lot of output (`yes`) blocks for ever on a full pipe. Each such request leaks one process and 3 file descriptors.
  - `--max-inflight` stops limiting live subprocesses. With `max_inflight=1`, 3 children were still alive after 5 s.
- **Formal:** `model_admission.py` (fingerprint `1b7b5a455ea7`): 3-step counterexample `admit, spawn, outer_timeout`. `fm prove` on the current code: real violation at depth 5. With the fix, the counter model is proved inductive for every scale (E4 for the model).
- **Fix:** in `_run_command`, add a `finally` block: `if proc.returncode is None: proc.kill(); await asyncio.shield(proc.wait())`. `verify_fix_run_command.py` patches this in and shows 0 orphans (RE-RUN: statuses `[504, 504, 504, 504]`, live children 0, late side effect False).
- **Test to land:** a `yes` command under `build_asgi_app` with a short timeout. After the 504, assert that no child process is alive.

#### E2 [F5-2] Medium — a `{` in a quoted parameter value hides `q=`

- **Where:** `wire/subrequest.py:34` (`_WIRE_UNSAFE` does not escape `{` or `}`) and `core/_scan.py:78` (the receiver counts them as nesting).
- **Effect (property test):** `(r:0:/echo?note='{'&q=(x)!'go')!'$r'` fails as `malformed_source`. The handler never runs.
- **Fix:** add `{` and `}` to `_WIRE_UNSAFE`.

#### E3 [F5-3] Medium-Low — a `+` in a quoted parameter value arrives as a space

- **Where:** `subrequest.py:34` and `:229`. The encoder leaves `+` raw. The receiver decodes with `unquote_plus`.
- **Effect:** `note='a+b'` reaches the handler as `'a b'`.
- **Fix:** escape `+`.

#### E4 [F5-4] Low — trailing Unicode whitespace is dropped from an intent (in-process)

- **Where:** `subrequest.py:99` (`.strip()`). `\xa0`, `\x85`, `　` are removed. `/echo(c)!'go　'` gives intent `go`. Over HTTP these characters are percent-encoded and survive. Fix: strip ASCII whitespace only.

#### E5 [F5-5] Low — `_fully_encoded` misreads a payload with `+` and no `(`

- **Where:** `subrequest.py:159-171`. The "inert" docstring claim is false. `q=summarize+this` keeps the `+`, although the sender meant a space. `q=a+b%20c` decodes to `a b c`.

#### E6 [F5-6] Low-Medium — HTTP dispatch and direct dispatch differ

- **Evidence:** `fm equiv` over the router encoding. All 12 reachable rows match the real routers (`test_dispatch_rows.py`, 13 passed).
- "A handler runs": direct is stricter. Only the eval row differs. This is intended (spec D1: direct calls never evaluate).
- "Data route served": direct is weaker. A data route under the eval path (`/v1/models?q=…`) is evaluated over HTTP. This contradicts the `_dispatch.py:160` docstring. `fetch_ex` then labels the eval result `application/json` (`:90,100`).
- "404": incomparable. `GET /echo` on a registered endpoint without `q` gives HTTP 404 "has no endpoint", but direct gives 400 `missing_intent`.
- **Fix:** refuse data routes under the eval path at registration (`_check_routable`), or document the HTTP behaviour. Make `data_media_type` follow the branch that actually ran. Align the no-`q` status (decision D-5).

#### E7 [F5-7] Low — status mapping edges

- `status_for` is total and deterministic over all 20 `ErrorCode` values × 4 exception shapes. The node and direct tables do not overlap. 12 codes use the 500/502 fallback, as the spec says.
- A handler that raises a non-`Url4Error` exception gets a 500 with an empty body and no content type (`peer/_http.py:80`). The spec requires the JSON error body. B6 reaches this path from user input. Fix: catch `Exception` and write the JSON error body with code `internal_error`.
- A built-in `TimeoutError` from a Python handler gets 504 "exceeded 5s" after 0 s (`_serve.py:299`). Fix: tell the request deadline apart from the handler's own `TimeoutError` (the same technique as `deadline.expired()` in `lifecycle.py`).

#### E8 [F5-8] Low — closing is not final

- **Where:** `io/http.py:87-91`, `peer/_owned.py:43-47`.
- A fetch after `aclose` silently creates a new client.
- A fetch while `aclose` is waiting raises a raw `RuntimeError`, not `ResolutionError`.
- After lifespan shutdown, `Url4Node` creates an outbound adapter that nothing closes.
- Double close and concurrent close are safe (`test_lifecycle.py`, 6 passed).
- **Fix (class invariants):**
  - `HttpIOLayer`: injected client ⇒ `_owned is None`. `_closed ⇒ _owned is None`. `_closed` is final; `fetch` then raises `ResolutionError`. Set `_closed` and drop the reference before the await.
  - `_OwnedIO`: injected ⇒ `_owned is None`. `_closed ⇒ _owned is None`, and `outbound()` raises.
  - Call `_check_invariants()` at the end of `__init__`, `_get_client`/`outbound` and `aclose`.

#### E9 [F5-9] Info — identity gate

- For `Url4Node`, the policy check is EQUIVALENT: no path serves identity holdings without calling the identity handler. Probes over the eval path, groups, `;broadcast`, `/v1/<collection>`, direct calls and data routes agree.
- `StaticIOLayer._holdings_key` (`io/static.py:105-113`) maps `(None,"emily/secret")` and `("emily","secret")` to the same key. A self reference can return emily's holdings. This is the public test double only. Fix: use a tuple key.
- `url4 serve` identity handlers have no gate. Requestor auth is deferred by design (`peer/server.py:14-16`).

---

## 5. Hygiene findings

### Census

| Item | Count | Source |
|---|---|---|
| Source / test lines | 13,026 / 14,130 | H1 |
| Tests (pass / fail / skip), runtime, coverage | 1360 / 0 / 0, 3.25 s, 98% | H4 |
| TODO / FIXME / XXX | 0 | H1 |
| Skipped or xfail tests | 0 | H1 |
| `importorskip` | 1 (`tests/unit/test_lifecycle_terminal_frame.py:25`) | H1, H4 |
| Suppressions counted by the ratchet (src) | 7 of baseline 7 (5 `type: ignore`, 2 `noqa`) | H1 |
| Suppression comments, broad census (src + tests) | 55, all under 90 days old | H1 |
| `# noqa` for rules ruff does not run | 17 (2 in src) | H1 |
| `pragma: no cover` | 8 | H1 |
| `assert` as runtime invariant in src | 21 (14 in `dag/_lowering.py`) | H1 |
| Private-name imports across modules | about 45 lines in 28 files; about 20 cross packages; 6 cross packages in src (H1 count) | H3, H1 |
| url4 private imports in consumers | 9 (3 in engine src, 6 in engine tests) | H4 |
| `__all__` exports with no production consumer | 46 of 152 (8 also have no test use) | H2 |
| vulture hits / real survivors | 52 / 4 (public `observe.py` fields, keep) | H2 |
| `sleep` in tests | 11 (one real timing wait) | H4 |
| Spec citations that cannot be checked | 566 `§N.N` citations in 69 files | H4 |
| Known vulnerabilities (pip-audit) | 0 | H4 |
| Locked deps a major version behind | 0 | H4 |
| Files with no active author | 0 | H1 |

### Hotspot quadrants (H1)

The history is short (62 commits). Commit `cba47c0f` (#1015) restructured many files at once and inflates churn. The hot files have had no commits since 2026-09-23.

- **REFACTOR:** only `dag/executor.py` (churn 9, complexity 496, density 1.84, 4 authors, 2 fixes). Complexity went 436 → 677 → 496 after the 2026-09-22 split. With `--no-tests` there is no REFACTOR file.
- **WATCH:** `observe.py`. Complexity went from 59 to 425 in 7 weeks (+620%). It is at its size cap (483 lines). Check it again in a month.
- **DOCUMENT and leave alone:** `core/render.py` (complexity 1500), `peer/client.py` (1160), `core/grammar.py`, `core/builders.py`, `dag/_lowering.py`. Each has churn 2 and is flat or stable. Note: the formal lanes found faults in render, grammar and `_lowering` (section B). Fix those faults with targeted changes. Do not restructure these files for hygiene reasons alone, except through HY-2.
- **Verified refactor:** `dag/node.py` complexity fell from 1238 to 196 (−61%).

### Findings

#### HY-1 High (process) — PyPI is behind the tags

`[cross-repo] url4 1.5.0 and 1.5.1 are tagged but not on PyPI — PyPI JSON shows latest 1.4.1; tags url4-v1.5.0 and url4-v1.5.1 exist; 13 url4 commits since the 1.5.1 tag; release-url4.yml:12-15 says the Trusted Publisher still names OpenMined/screamingface — cannot rule out: a manual publish elsewhere (not seen on PyPI).`

- **Interest:** external users do not get 1.5.x fixes. Any API added after 1.4.1 has no PyPI users, so it can still change without a deprecation window.
- **Action:** update the PyPI Trusted Publisher to `ScreamingFace/screamingface` (needs a PyPI project admin). Then re-run the release for 1.5.1, or release 1.5.2 from this branch's fixes.
- **Tier:** outside the code. Not reversible after publish.

#### HY-2 Medium — dual lowering pipeline is a half-finished migration

`[history] dag/_lowering.py runs a text path and an AST path side by side — docs/tasks/2026-07-22-ome-538-url4-collapse-dual-compile-pipelines.md is Backlog, marked highest risk; commits a4a5a2c61, 238c51c87, 84f9d38eb (2026-08-03) fixed "AST path missed what the text path had"; B1, B4, B5 and B2-nested in this report are the same class — cannot rule out: an intent to keep the text path for lazy compilation.`

- **Interest:** every grammar change must be made in two places. The two paths drift with no error. `LoweringRegistry` covers only the AST path, so a custom lowerer skips text-path group segments.
- **Action:** decide OME-538 (D-1). Then collapse with a strangler-fig sequence. The safety net is the parity corpus (`test_characterization.py:92,120,249`) plus F4's `test_lowering_equiv.py` and `census_lowering.py`.
- **Tier:** internal. Big change. Do it after the High fixes.

#### HY-3 Medium — layering rules drift in both directions

`[static] ARCHITECTURE.md and tests/unit/test_layering.py disagree — ARCHITECTURE.md:42 says only the engine imports observe, but its own table, peer/__init__.py and peer/direct.py:26 let peer import it; the test does not enforce "observe imports only stdlib", "io imports only core and wire", or "dag reaches io.layer only"; ARCHITECTURE says cli may import streaming, and cli does not — cannot rule out: rules that are intentionally aspirational.`

- **Action:** make `test_layering.py` the single source. Tighten it. Generate or update the ARCHITECTURE table from it.
- **Tier:** doc and test only. Safe.

#### HY-4 Medium — private modules are the shared API

`[static] about 20 cross-package imports of underscored names — grammar._IDENTITY_NAME_RE used by render, cli and peer; peer/client.py imports builders._pairs and render._render_source; core._scan and core._annotations used by wire, dag/nodes/fetch.py and dag/semantics/ensemble.py; cli/_serve.py imports peer._asgi; direct.py reads node._endpoints, _data, _eval_path; server.py imports client._blaming_render; no test guards them — cannot rule out: none needed, all are in-repo.`

- **Engine side:** `engine world/config.py:65,68` imports `url4.cli._config` (including three `_toml_*` functions). `engine world/factory.py:48` imports `url4.cli._serve`. Engine tests import `_error_payload` (3×), `_error_info`, `peer._owned`, `cli._config.ProviderSpec` (2×). A url4 release can break the engine with no warning.
- **Action:** promote the shared concepts to public modules (for example `url4.core.scan`, `url4.core.names`, `url4.cli.config`). Add an AST test that no package imports another package's underscored names, with a ratchet baseline. Add an engine-side guard test for `url4.cli._config` until it is public.
- **Tier:** internal plus in-repo consumer. Do both sides in one PR.

#### HY-5 Medium — ratchets are stale

`[static] module-size baselines drifted — io/layer.py 194 vs baseline 197 and cli/_serve.py 339 vs 340 were not lowered; render.py 694 (cap 697), dag/nodes/iteration.py and peer/_dispatch.py have 3–4 lines of slack; peer/client.py, dag/_context.py, core/nodes.py and dag/semantics/ensemble.py have no cap — cannot rule out: nothing.`

`[static] 17 "# noqa" comments name rules ruff does not run (ARG, SLF, S603, BLE, FBT); RUF100 is off; the suppression ratchet counts src only — cannot rule out: nothing.`

- **Action:** lower the two baselines. Add caps for the 4 uncapped files. Enable `RUF100` and delete the inert `noqa` comments. Add the new ratchets in section 7.

#### HY-6 Medium — release and CI gaps

`[static] release-url4.yml publishes with no test gate on the tagged commit; actions use mutable tags, including pypa/gh-action-pypi-publish@release/v1; url4-tests.yml has no concurrency group — cannot rule out: branch protection that makes the gate implicit.`

`[static] streaming has no coverage floor of its own — url4 omits url4.streaming; the engine job covers it inside an 80% aggregate shared with the engine — cannot rule out: high real coverage (not measured).`

- **Action:** gate the release job on a green test run for the tag. Pin the publish-path actions to commit SHAs. Add `concurrency`. Add a per-package coverage floor for `url4.streaming`, or stop omitting it in url4's own run.
- **Note:** the Python matrix (3.12/3.13) matches the classifiers. 3.14 works (H4) but is not in the matrix.

#### HY-7 Medium — examples are broken and not run in CI

`[runtime] examples/url4_examples.ipynb cell 0 raises ImportError — "from url4 import run": run is not in url4.__all__, it is in url4.dag; cells 1–2 call the live host syfthub.openmined.org; examples/ last touched 2026-07-15, 38 url4 source commits since; pyright covers only src and tests — cannot rule out: none.`

- **Action:** fix the import. Remove or mock the live-host cells. Add a CI job that runs the notebooks (for example `nbclient`) against `StaticIOLayer`. Decide if `run` belongs in the top-level API (D-6).

#### HY-8 Low-Medium — duplication

- `[static] parser._CALL_PATH_RE (parser.py:55) is byte-identical to grammar._PATH_RE (grammar.py:100) — F4 fm equiv EQUIVALENT and tie_regexes 0 differences — cannot rule out: nothing.` Action: delete the parser copy and import the grammar object.
- `[static] CLI defaults in 3–6 places — ServeConfig defaults (_config.py:72-78), literals in resolve (_config.py:201-207), argparse help (app.py:63-75), _SERVE_FIELDS (app.py:32-40); URL4_CONFIG read in app.py:131 while other URL4_* go through _config._pick — cannot rule out: nothing.` Action: one source of defaults, plus a test.
- `[static] ExecutionContext construction and the render-then-_blaming_render flow are copied in peer/server.py (~240-287) and peer/client.py (~261-292) — cannot rule out: nothing.` Action: one shared front-door function. Do this together with B3.
- `[history] usage/cost shape is mirrored by hand in observe.py, dag/node.py and streaming/protocol/* (3 commits touched all three, no import between them) — cannot rule out: an intended seam (streaming must not import url4).` Action: keep the seam; add a field-parity contract test.

#### HY-9 Low-Medium — dead or speculative public surface (H2)

- `[cross-repo] peer.is_eval_path and RouteInfo — only call to is_eval_path is peer/direct.py:182; RouteInfo is used only through describe_routes (engine calls describe_routes); neither name exists at v1.5.1 and so not on PyPI — cannot rule out: unmerged branches.` Action: make `is_eval_path` private. Tier: unreleased, delete with tests green.
- `[static] LoweringRegistry / Lowerer / default_registry plugin seam — only tests/unit/test_dag.py calls register() and copy(); no production code registers a lowerer — cannot rule out: external PyPI users (released since 1.0, docs advertise it).` Action: keep for tests; remove from the documented public surface; deprecate `copy`. Revisit after HY-2.
- `[static] make_command_handler(stdin=) and COMMAND_STDIN_SOURCES — build_node never passes stdin; no TOML key; only a test passes it; docstring claims a url4-cloud consumer — cannot rule out: the url4-cloud repo.` Action: check url4-cloud first (D-7).
- `[cross-repo] FrameAdapter, InboundFrame, HeartbeatData — no consumer in this repo — cannot rule out: external users, url4-cloud runner.` Action: re-check against `url4-v1.4.1` (the PyPI release), not v1.5.1. If they were added after 1.4.1, they are unreleased and can be removed.
- `Client.query/broadcast/iterate/reduce` have no caller in engine, studio or screamingface. Only the playground, notebooks and tests use them. The engine suite does not protect them. Keep (public API).
- `SpawnHook` / `ExecuteNodeHook`: installed only by url4's own executor. Low-value indirection. Collapse during an executor refactor, not alone.

#### HY-10 Low — false or stale comments and docs (H3)

- `lifecycle.py:63-66`: wrong `-O` reason; assert is vacuous (D5).
- `peer/_dispatch.py:65-70`: duplicated paragraph; says `processor` delegation is "not implemented yet", but it is used at `:175-180` and pinned by `tests/spec/test_processor_delegation.py`.
- `pyproject.toml:4`: says "interpreter". The package has a DAG engine.
- `CHANGELOG.md`: commit links use OpenMined, compare links use ScreamingFace.
- `tests/formal/*.py` headers point at `~/Documents/skills/...` and cite stale line numbers (`executor.py:154-174` → `134-152`).
- `docs/ISSUES.md` url4 items were last checked 2026-06-24, before the package existed. I-29 and I-30 are fixed in code (I-30 only partly: see T7). I-18 is probably closed (but see B12). I-21, I-23, I-25: no evidence either way.
- Task docs OME-537 to OME-546 all say Backlog. OME-539 (wire codec out of core) looks done (`url4/wire/` exists). Only 539 was checked.
- `README.md`: documents only part of the `URL4_*` env vars (H1-F5).
- Spec citations: 566 `§N.N` citations in 69 test files point at a language spec that is not in the repo. In the in-repo v1 spec, §3.3 does not exist and §5.3 means something else (H4). Decide where the language spec lives (D-8).

#### HY-11 Low — test hygiene

- `test_serve_app.py:111` uses `sleep(0.1)` to let a request take the only slot. Replace it with an event.
- `test_lifecycle_terminal_frame.py:25` uses `importorskip("pydantic")`. CI is safe today (dev group includes `url4[streaming]`). Use a plain import, so a missing dependency fails loudly.
- No `hypothesis` in the dev group. Add it to land the property tests from this audit.
- The formal-model stand-in BFS (`tests/unit/test_formal_models.py`) is sound. Keep it until the `formal-modeling` skill is committed. Then run the models with `fm.py` in CI.

#### HY-12 Low — dependency bounds and Python versions

- `pydantic>=2.13.4` copies the engine's pin. The code needs only the pydantic 2.0 API. Lower the bound, or say why it is high.
- `requires-python` has no upper bound. Python 3.14 works but is not in the CI matrix or the classifiers. Add 3.14 to the matrix.

#### HY-13 Low — consumer declarations

- `apps/screamingface-studio/runtime/pyproject.toml:12` has a `[tool.uv.sources] url4` line with no dependency that uses it. Remove it, or add the dependency.
- Extras are correct: the engine uses `url4[streaming]` and has its own uvicorn. Studio needs no extra.

#### HY-14 Low — vendored url4 in the screamingface wheel

`[static] packages/screamingface wheels contain a top-level url4/ copied by runtime_build_hook.py, with no dist-info — if a user also installs url4 from PyPI, both own site-packages/url4 — cannot rule out: pip or uv resolving the clash safely (not tested).`

- **Action:** test the clash. Then either vendor under a private name (`screamingface._vendor.url4`) or declare `url4` as a dependency once PyPI is current (HY-1).

---

## 6. Properties that hold

These checks found no counterexample within their scope. Keep them as regression tests.

| Property | Where | Evidence |
|---|---|---|
| A node resolves at most once per executor (diamond) | `dag/executor.py:134-152` | Existing model, `mutate` exit 0; F1 `executor_taskgroup.py` E3 (1524 states) |
| Observability span pairing and gap-free `engine_seq` when a dep fails mid-fetch | `dag/executor.py`, `_context.py` | EXEC case E4 |
| Nested map semaphores do not deadlock (no reentrant I/O) | `iteration.py:104,164`, `_context.py:145` | E3 at two scopes |
| Slot wiring is acyclic by construction | `dag/_wiring.py:84-93,105` | `wiring_acyclic.py` E3 (15552 states, `mutate` exit 0); rank invariant `prove_rank.py` INDUCTIVE + TERMINATES (model only). Forward, self and mutual refs stay literal text. Not covered: recursion through routes (A calls B calls A). |
| `render∘build` is idempotent | `core/render.py`, `core/parser.py` | L2i, 3000 grammar strings |
| The duplicated path regexes are one regex | `parser.py:55`, `grammar.py:100`, `render.py` | `fm equiv` EQUIVALENT; identical objects |
| `MapNode` keeps input order; collect loses no row; skip drops exactly the failed rows; fail is all-or-nothing | `dag/nodes/iteration.py` | hypothesis, random delays |
| `serve` in-flight counter: never negative, never above max, each request releases once | `cli/_serve.py:286-305` | `model_admission.py`; inductive for current code; depends on the decrement staying in `finally` |
| Context and intent cannot add a parameter or a second `q=` | `wire/subrequest.py` | hypothesis law L3 |
| `status_for` is total and deterministic; node and direct tables do not overlap | `peer/_http.py`, `peer/direct.py` | enumeration of 20 codes × 4 shapes |
| No path serves identity holdings without the identity handler (`Url4Node`) | `peer/*` | `fm equiv` EQUIVALENT; probes |
| Double close and concurrent close are safe | `io/http.py`, `peer/_owned.py` | `test_lifecycle.py` (6 passed) |
| `_scan.py` scanners terminate | `core/_scan.py` | loop variants stated (F4 §7) |
| The test suite is green at the lowest declared bounds and on Python 3.14 | package | H4 |

---

## 7. Ratchets and fitness functions to add

Each item keeps a fixed category of rot fixed. Counts are today's values (H1 `evidence/H1-metrics/ratchet.json`).

| Ratchet / test | Baseline today | Note |
|---|---|---|
| `url4-pragma-no-cover` | 8 | `hygiene.py ratchet` |
| `url4-tyignore-tests` | 23 | tests are outside the current suppression ratchet |
| `url4-assert-src` | 21 (excluding `streaming/testing`) | check intent first; many are type-narrowing asserts |
| `url4-importorskip` | 1 → 0 after HY-11 | |
| `url4-sleep-tests` | 11 | low value |
| Enable ruff `RUF100` | 17 inert `noqa` → 0 | better than a count ratchet |
| No cross-package private imports (AST test, like `test_layering.py`) | 6 in src (H1 count) | include an engine-side test for `url4.*._*` imports |
| Module-size caps for `peer/client.py`, `dag/_context.py`, `core/nodes.py`, `dag/semantics/ensemble.py` | current sizes | |
| `test_layering.py` enforces every rule in `ARCHITECTURE.md` | — | HY-3 |
| `__all__` ratchet (export count, consumers listed) | 152 | H2 |
| Property tests from this audit (round trip, lowering parity, substitution opacity, wire laws, lifecycle fault schedule) | — | needs `hypothesis` in the dev group |
| `fm check` + `fm mutate` on the models in `tests/formal/` in CI | — | after the skill is committed; treat exit 4 as failure |
| `fm audit --baseline .fm-baseline.json --fail-on-new` | today's findings | optional; new-code gate |
| Field-parity contract test for usage/cost shapes in `observe`, `dag/node`, `streaming/protocol` | — | HY-8 |
| CLI defaults single-source test | — | HY-8 |
| Notebook execution job | — | HY-7 |

---

## 8. Decisions for the owner

These items need a decision before the fix can be made. The fix plan marks them.

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| D-1 | OME-538: collapse the dual lowering pipeline? | (a) collapse to the AST path; (b) keep both, add parity gates | (a). Fix B1/B4/B5/B2 first with parity tests, then collapse. |
| D-1b | Meaning of a chained intent `/p(x)!a!b` | one call with intent `a!b`; call then reduce with `b`; parse error | Pick one in the spec. A parse error is the safest. |
| D-2 | Idempotency key for guarded retries (C1) | (a) key in the `IOLayer` request and an HTTP header; (b) forbid `;retry` on non-idempotent targets; (c) document only | (a). It is the only option that the model shows is safe. Needs a wire/spec change. |
| D-3 | Front-door render check (B3) | `check=True` always; complete render guards | `check=True` now; complete guards later. |
| D-4 | Collection sniffing and quorum counting (A6, A9) | spec the 2-line comma rule; require a declared type for CSV; count sources not elements | Require a declared type or ≥3 lines for CSV; count sources. |
| D-5 | No-`q` request to an endpoint: 404 (HTTP) or 400 `missing_intent` (direct)? Data routes under the eval path? | align; refuse at registration | Use 400 `missing_intent` on both. Refuse data routes under the eval path. |
| D-6 | Is `run` part of the top-level API? | export it; fix the notebook | Fix the notebook; keep `run` in `url4.dag`. |
| D-7 | `make_command_handler(stdin=)` and the url4-cloud consumer | check url4-cloud | Check first. |
| D-8 | Where does the url4 language spec live? (566 citations) | add it to `docs/spec/`; change citations | Add it to the repo. |
| D-9 | Release: who fixes the PyPI Trusted Publisher? Release 1.5.1 as is, or 1.5.2 with these fixes? | — | Fix the publisher now; release 1.5.2 after Phase 1. |

---

## 9. Fix plan for this branch

The repository rules apply: spec → plan → code; every change lands by PR; a PR needs a Linear issue under an epic (or a `bug` issue in Triage). This branch holds the report. The fix PRs can branch from it, one PR for each group below.

Rules for every fix:

- Land the reproducing test first, as `xfail(strict=True)`. Then fix. Then remove the `xfail`.
- Keep structural changes and behavioural changes in different commits.
- Add `hypothesis` to the url4 dev group in the first PR that needs it.
- Check line numbers again before you edit. They refer to `da88b135a`.

### Phase 0 — safety net (one PR)

1. Add `hypothesis` to the dev group.
2. Move the pinned counterexamples into `packages/url4/tests/regressions/` as strict xfails:
   - F4 `test_findings_pins.py` (19 pins);
   - F3 `test_props.py` (the failing properties);
   - F1 `repro.py` and `repro_t.py` cases as tests;
   - F2 R1–R6 as tests;
   - F5 orphan-subprocess test, wire-law pins, dispatch rows.
3. Add the round-trip laws L2i and L1 (they pass today) as normal property tests.

### Phase 1 — High-severity correctness (one PR for each item)

| Order | Fix | Findings | Size | Decision |
|---|---|---|---|---|
| 1 | Kill and reap the command subprocess in a `finally` block | E1 | S | — |
| 2 | `ParseError` for an empty attribution chain; JSON 500 for non-`Url4Error` handler exceptions | B6, E7 | S | — |
| 3 | One-pass `$item`/`$name` substitution; one-pass call-intent substitution | A1, A5, A4 | M | — |
| 4 | Enforce quorum on fan-out and broadcast; `MergeNode` keeps `SourceFailure` | A2, A3 | M | D-4 for counting rule |
| 5 | `check=True` at the front doors; one shared front-door function | B3, HY-8 (part) | S | D-3 |
| 6 | `skip_leading=True` for envelope iteration detection | B2 | S | — |
| 7 | Range validator for `;t=` and `;retry=`; remove the `assert` | C3 | S | — |
| 8 | Lifecycle: `terminal_sent` guard; sequence `peek`/`commit` | D1, D2, D5 | M | — |
| 9 | Guard idempotency key through `IOLayer` | C1 | L | D-2 |

### Phase 2 — Medium correctness

- Wire: escape `{`, `}` and `+`; strip ASCII whitespace only; fix `_fully_encoded` (E2–E5).
- Guard: separate admission-timeout code (C2).
- Lowering parity for B1, B4, B5 and B7 (after D-1b), then start HY-2.
- Collection sniffing (A6, after D-4); `on_error` type change (A8); per-row error count (A7).
- Dispatch alignment and `data_media_type` (E6, after D-5).
- Lifecycle: bounded terminal flush; `aclosing`; `ensure_stream` inside the `try` (D3, D9, D10).
- Close semantics and class invariants for `HttpIOLayer` and `_OwnedIO` (E8).
- `StaticIOLayer` holdings key (E9).

### Phase 3 — hygiene quick wins (one PR)

- Lower the stale module-size baselines; add caps for the 4 uncapped files (HY-5).
- Enable `RUF100`; delete the 17 inert `noqa` comments (HY-5).
- Delete `parser._CALL_PATH_RE`; import the grammar object (HY-8).
- Fix the false comments: `lifecycle.py:63-66`, `_dispatch.py:65-70`, `pyproject.toml:4`, CHANGELOG org links, `tests/formal` headers and line numbers (HY-10).
- Make `test_layering.py` enforce all `ARCHITECTURE.md` rules; fix the `observe` rule text (HY-3).
- Fix the notebook import; remove the live-host cells (HY-7).
- Plain `pydantic` import in the lifecycle test; replace `sleep(0.1)` with an event (HY-11).
- Make `is_eval_path` private (HY-9).
- Add the new ratchets from section 7.

### Phase 4 — structural

- HY-2 / OME-538: collapse the dual lowering pipeline (strangler fig, parity corpus as the net).
- HY-4: promote shared private names to public modules; add the private-import test; update the engine imports in the same PR.
- Types as specs (T1–T13).
- CLI defaults single source (HY-8).
- `observe.py` review after one month (H1 WATCH).

### Outside this package

- PyPI Trusted Publisher and release (HY-1, D-9).
- Release gate, SHA pins, `concurrency`, streaming coverage floor (HY-6).
- Engine-side: D4 (`TooManyStalledMsgsError`), D6 (in-process `status()`), D8 (`InMemoryEventStream.purge`), conformance-suite gaps, client `_accept_sequence` (D2).
- `docs/ISSUES.md` url4 items and OME-537..546 task-doc statuses (HY-10).
- Studio runtime stray `url4` source (HY-13); vendoring clash test (HY-14).

---

## 10. Blind spots

- **Bounded results.** Every `fm check` result holds only within its stated scope. `fm prove` was run for some models (C1 fix, E1 fix, wiring rank). It proves the model, not the code.
- **Formal lanes did not cover:** recursion between nodes through routes; usage events for abandoned guard attempts; retries across separate `run()` calls; a raising observer; a timeout between response start and body in `serve`; the server process being killed; performance.
- **F2 did not run `fm prove`** (z3 was not installed in that lane).
- **No runtime evidence.** There is no traffic data, no PyPI download data, and no telemetry on which features are used. Dead-code verdicts for public names stay `[static]` or `[cross-repo]`.
- **url4-cloud repo** was not searched (HY-9, D-7).
- **Consumer search was text only** (`.py`, `.ipynb`, `.md`). TypeScript or Rust consumers of the wire event names are not covered.
- **Not run:** the engine test suite, `uv lock --check`, ruff, pyright, `gh run list`. CI findings come from reading the workflows.
- **Hygiene history is short** (62 commits, one big restructure). Hotspot and coupling data show the build phase, not long-term pain.
- **Notebooks** were text-matched, not executed (except the import check).
- **Same-package private imports** were listed but not judged (H3).
- **H3 did not read** `executor`, `nodes/*`, `io/*`, `examples/`, `scripts/` for duplication.

---

## 11. Evidence index

All files are in `evidence/`. They are copies of the lane scratch directories, without virtual environments and caches. The scripts were run against scratch virtual environments. Some files contain absolute scratch paths in `sys.path` lines; change these paths before you run them.

To re-run a reproduction with the package's own environment:

```bash
cd packages/url4
uv sync            # a new worktree has no .venv yet
.venv/bin/python -I ../../docs/spec/2026-10-09-url4-audit/evidence/F1-executor/repro.py
```

Property tests need `hypothesis` (`uv pip install hypothesis` into a scratch virtual environment, or add it to the dev group first). `fm` commands need the `formal-modeling` skill: `python3 .claude/skills/formal-modeling/bin/fm.py check <model>`.

| Folder | Contents | Key files |
|---|---|---|
| `fm-audit.txt`, `fm-doctor.txt`, `hy-doctor.txt` | Baseline tool output | — |
| `F1-executor/` | Guard, executor, semaphore models; reproductions | `guard_retry_as_written.py`, `guard_retry_fixed.py`, `prove_guard.py`, `executor_taskgroup.py`, `executor_guard_boundary.py`, `semaphore_nesting.py`, `repro.py`, `repro_t.py` |
| `F2-streaming/` | Lifecycle and JobStatus models; reproductions; mutation output | `model_lifecycle.py`, `model_lifecycle_fix3_{safety,live,commit}.py`, `model_jobstatus_*.py`, `repro_lifecycle.py`, `repro_memory_resume.py`, `repro_out.txt`, `run_all.sh`, `evidence.txt` |
| `F3-semantics/` | Property tests, `fm equiv` and `fm laws` files, MapNode models, probes | `test_props.py`, `pytest_out.txt`, `equiv/*`, `laws/*`, `model/map_modes{,_fixed}.py`, `probes/*.py` (with `.out`) |
| `F4-language/` | Round-trip and lowering property tests, censuses, regex and acyclicity models, pinned counterexamples | `tests/gen.py`, `tests/test_roundtrip.py`, `tests/test_lowering_equiv.py`, `tests/test_findings_pins.py`, `tests/census*.py`, `models/*`, `*_run*.txt` |
| `F5-transport/` | Admission model and proofs, dispatch equivalence, identity gate, wire laws, close tests, reproductions | `model_admission.py`, `prove_admission*.py`, `equiv_dispatch_*.py`, `equiv_identity_gate*.py`, `test_dispatch_rows.py`, `test_wire_laws.py`, `test_lifecycle.py`, `repro_subprocess_orphan.py`, `repro_yes_persist.py`, `verify_fix_run_command.py`, `probe_*.py` |
| `H1-metrics/` | Full H1 report, raw tool JSON, ratchet config | `REPORT.md`, `ratchet.json` |
| `H2-deadcode/` | Full H2 report, vulture output, export census | `REPORT.md`, `vulture*.txt`, `exports.txt` |
| `H3-coupling-docs/` | Full H3 report | `REPORT.md` |
| `H4-deps-tests/` | Full H4 report, consumer census, pytest output | `REPORT.md`, `consumers.py`, `pytest.out`, `req.txt` |

The formal lanes (F1–F5) could not write their own `REPORT.md` files. Their full findings are in section 4 of this report.
