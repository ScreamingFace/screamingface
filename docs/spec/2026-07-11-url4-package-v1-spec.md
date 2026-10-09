---
title: url4 — technical specification of the SDK (packages/url4, v0.2.0)
status: as-built — describes the implemented url4 SDK (engine core + product surface + package integration)
created: 2026-07-11
author: Claude (Opus 4.8) + ionesio
ticket: OME-397
related:
  - https://linear.app/openmined/issue/OME-397/package-and-commit-url4-sdk-v1-under-sdlc
  - docs/plan/2026-07-11-url4-package-v1.md
  - docs/diagrams/url4-pipeline.svg (parse → compile → execute pipeline)
  - docs/diagrams/url4-hexagonal-ports-adapters.svg (core, ports & adapters)
  - docs/diagrams/url4-dag-execution-model.svg (DAG & ensemble runtime)
  - .claude/skills/url4-engine/SKILL.md (execution & telemetry doctrine)
  - packages/url4/tests/spec/ (executable conformance suite — one file per spec area)
---

# url4 — technical specification

## 0. Status of this document

This is a **descriptive (as-built) specification** of the `url4` package as it exists at
`packages/url4` v0.2.0 — reverse-derived from the source and its conformance tests, not a
forward design proposal. It is the document an engineer reads to understand how url4 turns an
expression string into a resolved result, how to drive it from Python, and how it is wired
into the monorepo. The package is one SDLC unit (OME-397) in three layers, each covered here:
the **engine core** (§2–§12 — parse → compile → execute, hexagonal I/O), the **SDK product
surface** (§13 — renderer, builders, client, node/server), and its **package integration**
(§15 — CI, coverage gate, release lane). Section references of the form `§N.N` that carry a
decimal beyond this document's own numbering point at the url4 *language* spec that the code
cites in its own docstrings and in `tests/spec/`; that language spec is the normative authority
for surface semantics, this document describes the *implementation architecture* that realizes
it.

## 1. Purpose & scope

### 1.1 What url4 is

url4 is a standalone, framework-free **core library for the url4 expression protocol** — a
small language for expressing *multi-source computation* as data. The atomic form is

```
(sources)!intent          "given these sources, do this"
```

which composes recursively: a source may itself be another `(…)!…` expression, a fetch, a
reference to a prior result, or an iteration over a collection. url4 compiles such an
expression into an executable **dataflow graph** whose independent nodes run concurrently,
and evaluates it against a pluggable I/O layer. It is the engine underneath ScreamingFace's
AI-ensemble runs: fan-out to several model backends, then reduce — expressed as one URL-like
string.

### 1.2 What the package provides

- A **parser** (`grammar`, `parser`, `nodes`) that turns surface text into a typed AST.
- A **compiler** (`dag.compiler`) that lowers the AST — or the surface text directly — into a
  graph of executable nodes, with an extension registry.
- An async **executor** (`dag.executor`) that schedules the graph as a memoized, structurally
  concurrent dataflow.
- A **hexagonal I/O port** (`io_layer`) plus two batteries-included adapters
  (`io_static.StaticIOLayer` for deterministic/offline runs, `io_http.HttpIOLayer` over httpx).
- The `(context)!intent` **sub-request wire codec** (`subrequest`), the scope/`$`-substitution
  machinery (`context`, `ensemble`), and a spec-coded **error hierarchy** (`errors`).
- A **Python SDK product surface** on top of the engine (§13): a **renderer** (`render`, the
  AST→text inverse of `parse`), Python **builders** (`builders`), a **client** façade
  (`client.Client` + `Url4Result`), and a **node/server** SDK (`server.Url4Node` + a
  framework-free ASGI shim). These are pure consumers of the engine — the core never imports
  them.

Package facts: distribution `url4`; version `0.2.0`; `requires-python >= 3.12`; a single
runtime dependency (`httpx`, imported lazily) plus an optional `server` extra (`uvicorn`);
hatchling build backend; ruff + pyright + pytest tooling. The engine façade is
`url4.run(...)` / `url4.compile_expression(...)`; the SDK façade is `url4.Client` /
`url4.Url4Node` plus the builder functions. The package is CI-gated and release-registered as a
monorepo component (§15).

### 1.3 Non-goals

- **No model/provider logic.** url4 never talks to an LLM directly; a "model call" is just a
  fetch of `/claude?q=(…)!…` through the injected I/O layer. What that fetch *does* is the
  adapter's concern.
- **No transport in the core.** Only `io_http` imports httpx, and it is imported lazily; the
  language/execution core's static import graph is transport-free.
- **Not a scheduler/queue/persistence layer.** One `run()` is one in-process async evaluation.

## 2. The url4 language

### 2.1 Surface grammar (informal EBNF)

The recursive-descent grammar in `grammar.py` and the envelope decoders in `parser.py`
implement, in essence:

```
expression   := source_expr [ "!" ["*"] intent ] [ ";" param_chain ]
source_expr  := group | source
group        := "(" [ source ("," source)* ] ")"
source       := ["*"] head [ ";" annotation_chain ]           # leading '*' = expansion
head         := value | NAME "=" value | attrib_chain          # descriptor (§4.3)
attrib_chain := seg (":" seg)* ":" ("src=" value | value)      # name / weight / budgets
value        := text | url | rel_url | rel_expr | remote_expr
             |  ref  | varref | struct | group | iteration
iteration    := value "*" "(" body ")" [ "!" intent ]          # per-row map (§5.3)
url          := SCHEME "://" ...                                # any scheme; url4:// is special
rel_url      := "/" path
rel_expr     := "/" path "(" context ")" [ "!" intent ]        # sugar (§3.1.1.1)
             |  "/" path "?" [params "&"] "q=(" context ")" [ "!" intent ]   # canonical
remote_expr  := "url4://" authority rel_expr
ref          := "@" | "@" NAME [ "/" collection ]              # holdings (§5.6)
varref       := "$" (NAME | N) ( "." field | "[" N "]" )*      # standalone reference (§5.2 r8)
struct       := "{" key ":" value ("," key ":" value)* "}"     # inline object (§5.3.11.3)
text         := "'" quoted "'" | bare_text                     # quotes are delimiters (§5.1)
```

Two orthogonal axes decorate a source (spec §4.3, the **two-axis descriptor**):

- **Attribution** (who/how-much): `name=`/`name:` binding, `weight` (a scalar *or* a
  structured domain-conditional mapping, §4.1.1), and ordered `budgets`.
- **Execution** (`;`-chain annotations): `;optional`, `;t=<seconds>`, `;retry=<n>`,
  `;accept=<media-type>`, `;expand`, and the `;iteration.*` directives.

### 2.2 Operators & forms (semantic summary)

| Form | Meaning |
|---|---|
| `(a, b)!intent` | **base**: merge resolved sources under one intent |
| `(/x(c)!i, /y(c)!i)!reduce` | **fan-out + reduce**: parallel relative-expression calls, then a reducer call |
| `(a, b)!*intent` | **broadcast**: apply the intent once per source → JSON array (§6.1) |
| `src*(body)!intent` | **iteration**: evaluate `body` per collection row (per-row `!intent` reduces each row) |
| `(src*(body)!peri)!reducer` | iteration with a **cross-row** reducer over the JSON row array |
| `*source` / `;expand` | **expansion**: splice a collection-valued source into N sibling positions (§5.3.12) |
| `$name` / `$N` / `$item` / `$current` | references: named/positional slot, current row, current broadcast source |
| `@` / `@name/coll` | **holdings**: the node's own / a principal's policy-governed data (§5.6) |
| `;quorum=N` | require ≥ N sources to resolve (§9.1) |

## 3. Architecture overview

url4 is a **pipeline of four layers** with a strict, cycle-free internal import graph
(leaves: `errors`, `context`, `_scan`, `_annotations`, `nodes`, `io_layer`, `subrequest`).

```
 surface text  "(a=/x, /claude($a)!'sum')!go"
      │
      ▼   parser.decode_envelope       (depth/quote-aware string scanners)
 envelope      {source_expr, intent, broadcast, params, iteration?}
      │
      ▼   grammar.parse                 (recursive-descent, per §-rule)
 AST (url4.nodes.Node)                  closed union of frozen dataclasses
      │
      ▼   dag.compiler.LoweringRegistry (AST→node, OR text→node w/ laziness)
 Graph(sink: DagNode)                   open set of executable nodes
      │
      ▼   dag.executor.Executor         (asyncio TaskGroup, memoized, pull-based)
 result: str                            via the injected IOLayer + process hook
```

> **Diagram — the pipeline & its data flow:** `docs/diagrams/url4-pipeline.svg`
> (`.png` rendered alongside). It carries the same stages, the running example, and the
> design invariants (the flip, the transport-free import graph, the shared `decode_envelope`).

### 3.1 The expression-problem flip (a load-bearing design decision)

The two typed layers deliberately invert each other's open/closed axes:

- **`url4.nodes` (AST)** — a *closed* union of pure-data nodes (`Node = Text | Url | … |
  Expression`) with an *open* set of external operations (`walk`, `children`, lowering). New
  operations are added without touching the nodes.
- **`url4.dag` (executable)** — an *open* set of nodes behind one *closed* operation: the
  `DagNode` protocol (`deps` + `resolve`). Any object implementing it executes. New node
  *types* (custom surface forms, custom backends) are added without touching the executor.

Rationale: parsing wants a fixed vocabulary with growing analyses; execution wants a fixed
scheduler with a growing vocabulary. Each layer picks the axis that keeps *its* extension
cheap — Strategy-per-node behind the protocol on the execution side, Visitor-style external
operations on the AST side.

## 4. Parse layer

### 4.1 Envelope decoding (`parser.py`)

Before the grammar sees anything, `decode_envelope` peels the **surface envelope** the source
grammar sits under, as raw text, in one fixed order: the outermost `!`/`!*` intent split
(`split_intent`), the trailing `;key[=val]` per-expression params (`split_expr_params`,
including `iteration.*` directives and the `;broadcast` flag), and the `src*(body)`
iteration shape (`split_collection_iteration`), including the reduce-over-iteration nesting
`(src*(body)!peri)!reducer`. This ordering is the **single source of truth**: both the eager
parse tree (`build`) and the lazy DAG (`compiler._compile_text`) consume the *same*
`decode_envelope`, so the two paths cannot drift in surface semantics (result parity is pinned
by `test_bare_relexpr_text_path_matches_ast_path`).

### 4.2 The recursive-descent grammar (`grammar.py`)

`parse(text) -> Node` decodes one *source expression* into the AST. Design note (from the
module): the spec's rules are **procedural and committing**, so a recursive-descent parser is
used rather than a PEG — ordered-choice PEG backtracking cannot express *commitment*. The
canonical example is the §4.1.1.4 structured-value classifier: `_commits_to_struct` decides on
the first entry whether a `(` opens a structured annotation or an expression source list, and
once committed a later malformed entry is a `malformed_source` **error**, not a
reclassification. All scanning sits on the depth/quote-aware primitives in `_scan.py`
(`iter_top_level`, `balanced_body`, `split_top_level`, `skip_quoted`) so "only separators at
depth 0 outside quotes are structural" (§8 rule 8) has exactly one implementation.

### 4.3 The AST (`nodes.py`)

A closed union of 13 frozen dataclasses (`Text`, `Url`, `RelUrl`, `Binding`, `RelExpr`,
`RemoteExpr`, `SelfRef`, `IdentityRef`, `VarRef`, `StructObject`, `Source`, `Iteration`,
`Expression`). Nodes carry no behavior; `children`/`walk` traverse them externally. Two
deliberate distinctions:

- **`Binding` vs `Source`.** A *name-only* descriptor (`a=v`) stays a `Binding` — an eager
  bind excluded from the packed sources. Any descriptor carrying weight, budgets, execution
  annotations, or the expansion mark becomes a `Source` — a weighted contributor that stays in
  the packed sources and is referenceable by name.
- **Standalone vs embedded references.** Only a *standalone* `$name` in a value position
  parses structurally (`VarRef`); an embedded `$name` inside text is left for string
  interpolation at resolve time (§8.2). `nodes.py` imports nothing internal, so a consumer that
  only needs the type names never pulls in the parser or executor.

## 5. Compilation layer (`dag/compiler.py`)

### 5.1 Lowering & the registry

`compile_expression(target)` accepts **either** surface text (lazy path) **or** a parse-tree
node (eager path) and returns a `Graph(sink)`. A `LoweringRegistry` maps each AST type to a
lowering function (Registry / Abstract Factory); `default_registry()` wires the 13 built-ins.
`registry.copy()` + `register(AstType, lowerer)` overrides how any surface form lowers —
**without editing the compiler** (Open/Closed).

### 5.2 Reference edges → acyclic by construction

The compiler derives `$name`/`$N` dependency edges per segment, mirroring the reference
engine's two-phase list resolution (`_build_slots`):

- a **named slot** (binding or named source) sees only named slots declared **earlier**
  (left-to-right);
- an **unnamed** source sees **every** sibling named slot;
- `$N` resolves from a source only when slot *N* is named;
- the **intent** depends on **all** slots (it resolves after the full gather);
- an unknown reference gets no edge and stays verbatim.

Because named slots never depend on unnamed sources and named→named edges are strictly
left-to-right, **compiled graphs are cycle-free by construction**. (`check_acyclic` still
guards *hand-built* graphs of custom nodes.)

### 5.3 Hybrid laziness ("the whole expression is not parsed upfront")

Only the *top-level* structure is decoded eagerly. A group-shaped segment defers its inner
text into a `LazyExprNode` thunk compiled only when executed; a `MapNode` recompiles its row
body per collection row; a `ReduceNode` parses its reducer only once rows exist. This is what
lets an expression fan out to sub-expressions that are themselves only parsed on demand.

### 5.4 The executable node vocabulary

| Node | Role |
|---|---|
| `TextNode` | inline text / prompt template — `$` substitution |
| `WebFetchNode` | absolute-URI fetch (scheme-classified: `http`/`url4`/`other`) |
| `RelUrlNode` | `/path` data read, or `/path(ctx)!intent` relative-expression sub-request |
| `RemoteFetchNode` | `url4://authority/path…` remote expression |
| `HoldingsNode` | `@` / `@identity[/coll]` via the holdings port |
| `StructNode` | inline `{k: v}` → canonical JSON after substitution |
| `BindingNode` | named passthrough that other nodes edge to |
| `LazyExprNode` | Virtual Proxy over an unparsed fragment (compiled on resolve) |
| `GuardNode` | per-source disposition: `;optional`/`;t=`/`;retry=` (isolation boundary) |
| `ExpandNode` | `*source`/`;expand` → `list[str]` spliced into sibling positions |
| `BarrierNode` | make a fetch-intent structurally depend on all sources (url4 2.0: a URI intent is a `CodePointerNode` instead; see `docs/spec/2026-10-09-url4-rds-code-pointer/`) |
| `GatherNode` | internal gather-join of an intent-less group (AST-only carrier — no surface form, `OME-508`) |
| `InlineCollectionNode` | `(e1,e2,…)` as a real ordered element list for `*` |
| `ProcessNode` | `(sources)!intent` base merge via the `process` hook |
| `MergeNode` | one broadcast application (`$current` bound) |
| `BroadcastCollectNode` | assemble broadcast results into the §6.1.4 JSON array |
| `FanoutReduceNode` | label N parallel responses, reduce via `ctx.processor` (url4 2.0: only for a quoted-text or computed intent; a URI intent is a `CodePointerNode`) |
| `MapNode` | `src*(body)` per-row evaluation (concurrency/on_error/slice) |
| `CollectNode` / `ReduceNode` | serialize rows to JSON array / reduce the array |
| `JoinNode` | join ordered parts, flattening `list[str]` |

Nodes are `@dataclass(eq=False)` so **node identity is object identity** — which is exactly
what lets the executor memoize shared (diamond) nodes by construction.

## 6. Execution layer (`dag/executor.py`, `dag/node.py`)

> **Diagram — the runtime DAG & ensemble model:** `docs/diagrams/url4-dag-execution-model.svg`
> traces a concrete fan-out+reduce expression into its node graph (sink `FanoutReduceNode`, the
> `RelUrlNode` calls, the sub-request codec, the `IOLayer` port and adapter), with the
> `ExecutionContext` capabilities, the iteration path, and the payload-shape legend.

### 6.1 The dataflow executor

`Executor.execute(sink)` schedules the graph as a **demand-driven, memoized, structurally
concurrent** dataflow:

- **One `asyncio.Task` per node per run, keyed by `id(node)`** (`_memo`). Diamond dependencies
  resolve exactly once; independent nodes run in parallel simply because their tasks coexist.
  The check-then-store around `_memo` is a deliberate *await-free* critical section — on the
  single-threaded loop `create_task` schedules without yielding, so two parents of a shared
  child can never both create a task for it.
- **Pull-based from the sink** — only reachable nodes are ever scheduled.
- **One `asyncio.TaskGroup`** — the first failure cancels every in-flight sibling (an
  intentional improvement over the reference engine's bare `gather`). The resulting
  `ExceptionGroup` is unwrapped (`first_error`) back to the first real error, so callers keep
  catching plain `Url4Error` subclasses.
- **Deterministic dispatch order** (deps insertion order) — but *not* completion order; an
  order-sensitive `IOLayer` must not assume FIFO arrival.

### 6.2 `ExecutionContext` — per-run capabilities

Every `resolve(inputs, ctx)` receives the run's capabilities: the `io` port; the reducer
`processor` path (`DEFAULT_PROCESSOR = "/claude"`); the overridable `process` merge hook; the
lexical `scope`; `strict_fields` (the §5.3.4.1 field-path error mode); a shared error tally
(`collected_errors`); and two executor-injected escape hatches nodes call but never
implement — `spawn` (compile+run a *text fragment* on a fresh executor: `MapNode` rows,
`LazyExprNode`) and `execute_node` (run a *prebuilt subtree* on a fresh executor: `GuardNode`'s
isolation boundary). `ctx.child(scope)` makes a new scope frame sharing everything else, so a
supplied `ctx` is never mutated and is safe across overlapping concurrent `run()` calls.

### 6.3 Concurrency & admission control

`run(concurrency=N)` (default `DEFAULT_RUN_CONCURRENCY = 32`) installs a `BoundedIOLayer` — a
semaphore-bounded wrapper acquired **only around the inner `fetch`** — so the whole run's I/O
(a bare fan-out, a fan-out+reduce, and the aggregate of all map rows) never exceeds the bound,
*underneath* any node-local cap such as `MapNode`'s `;iteration.concurrency`
(`DEFAULT_MAP_CONCURRENCY = 8`). The wrapper forwards the optional capability ports only when
the inner adapter provides them, so a `runtime_checkable` isinstance test against the wrapper
reports exactly the wrapped adapter's capabilities. `concurrency` is validated *before* any
semaphore is built — `Semaphore(0)` would hang every fetch forever.

## 7. Execution & iteration semantics

### 7.1 Strategy selection

`_compile_group` picks the resolution strategy from the shape:

- **code pointer** (`CodePointerNode`, url4 2.0) — checked first: a relative-URI or `url4://`
  intent calls that code once with the sources as a JSON input document, and the strategies
  below do not apply (`docs/spec/2026-10-09-url4-rds-code-pointer/`).
- **base** (`ProcessNode`) — sources gather, then the intent merges via `ctx.process`. A
  *text* intent substitutes **post-gather** (so `$N` positions renumbered by expansion are
  correct, §5.3.12.4); a *fetch* intent sits behind a `BarrierNode` to preserve
  sources-then-intent order.
- **fan-out + reduce** (`FanoutReduceNode`) — only when the group is *all* relative-expression
  calls **and** carries a top-level intent (mirroring the reference engine's fan-out gate). The
  N calls run in parallel; responses are labeled by `(name, weight)`, formatted
  (`build_reducer_input`), and the reduce step is itself a fetch of `ctx.processor?q=()!<input>`.
  A *single* bare relative expression with a top-level intent folds the intent into that one
  call instead of spawning a spurious reducer.
- **broadcast** (`!*`) — each source resolves under the outer scope; a `MergeNode` applies the
  intent per source with `$current` bound (text intent substitutes per source; fetch intent is
  one shared node); `BroadcastCollectNode` assembles the §6.1.4 JSON array of
  `{source_position, source_name, result}`.

### 7.2 Iteration (`src*(body)`)

`MapNode` resolves the collection once, parses it into rows (`parse_collection`), and evaluates
`({body})!{intent}` **per row as an independent sub-graph** via `ctx.spawn`. The row value is
**bound into the spawned scope** under a reserved NUL-prefixed key — never substituted into the
expression text — so a row containing `(` or `!` cannot corrupt the re-parse. Directives:
`;iteration.slice` selects a half-open range before evaluation; `;iteration.concurrency` caps
per-map fan-out; `;iteration.on_error` picks the per-row policy — `collect` (default, embeds
error objects and increments the tally), `skip` (omit failed rows), `fail` (abort the whole map
on first error, via a TaskGroup). Rows return as `list[str]` (the internal Map→Collect/Reduce
contract) so row boundaries survive embedded newlines; `CollectNode` serializes them to the
protocol-default JSON array (§5.3.8), or `ReduceNode` reduces the array.

### 7.3 Terminal state & tolerated failure

`GuardNode` implements the per-source disposition (§10.1): a *permanent* error
(`Url4Error.permanent`) never retries; a transient one retries up to `retries` times; `;t=` is a
transient timeout. A source that still fails is terminal — `required` (default) raises,
`optional` returns a **`SourceFailure` value** (not an exception). Group nodes treat
`SourceFailure` as a third payload shape: they *skip* it in the packed sources and in
`$name`/`$N` population, so it flows through the gather instead of cancelling the TaskGroup. The
guarded subtree runs on its **own executor/TaskGroup** (`ctx.execute_node`) precisely so a
tolerated failure surfaces as a value rather than cancelling siblings in the outer run.

### 7.4 Collection parsing (`io_layer.parse_collection`, §5.3.7)

With a declared media type the matching strategy is applied strictly (`application/json`,
`application/x-ndjson`, `text/csv`, `text/tab-separated-values`, `text/plain`); without one the
type is **conservatively sniffed** — HTML (a soft-404 signature) and JSON objects fail fast; a
single-line non-array body is a *scalar*, not a collection, and is refused (§5.3.9); prose that
merely contains commas is rejected by a header heuristic rather than mangled as CSV. An empty
body is an empty collection (zero rows, success).

## 8. Hexagonal I/O (`io_layer.py`, `io_static.py`, `io_http.py`, `subrequest.py`)

> **Diagram — core, ports & adapters:** `docs/diagrams/url4-hexagonal-ports-adapters.svg`
> shows the framework-free core, the driving API port, the driven `IOLayer` port with its
> optional capability ports and the `process`/`LoweringRegistry` extension ports, and the
> `StaticIOLayer` / `HttpIOLayer` / custom adapters that implement them.

### 8.1 The port and its optional capabilities

Nodes never perform I/O; they depend on the **`IOLayer` port** — a `Protocol` with one
operation:

```python
class IOLayer(Protocol):
    async def fetch(self, target: str, *, relative: bool) -> str: ...
```

Everything is a fetch: a bare `/api/x` is a data read; a relative *expression* `/claude(ctx)!i`
is fetched as the encoded sub-request `/claude?q=(ctx)!i` — there is **no separate "call"
primitive**, so dispatching a model backend is a localhost fetch like any other. Two optional
capability protocols widen the port without breaking old adapters (both `runtime_checkable`):

- **`SupportsFetchEx`** — `fetch_ex(FetchRequest) -> FetchResult` (body **+** media type), so
  collection parsing can be Content-Type-driven. `fetch_result()` bridges: a bare-`fetch`
  adapter is wrapped body-only (`media_type=None` → sniffing).
- **`SupportsHoldings`** — `fetch_holdings(identity, collection)` for `@`/`@identity` (§5.6). An
  adapter lacking it makes `@` a permanent `self_ref_on_non_url4` error (§5.6.6).

### 8.2 Adapters

- **`StaticIOLayer`** — in-memory, deterministic, no network (the test default). `fetch_map`
  for static reads, `routes` mapping a localhost path to a `(context, intent) -> str` handler
  (sync or async), optional `holdings` and `media_types`. Depends only on the sub-request codec
  and errors.
- **`HttpIOLayer`** — the `run()` default: httpx `GET`, the **only** module importing httpx
  (imported lazily by `run`). One lazily created `AsyncClient` is reused for the adapter's
  lifetime so a fan-out's N fetches share a connection pool; `follow_redirects=True`; a
  `url4://` target is translated to `https://` on the wire (§3.5); any HTTP failure surfaces as
  `ResolutionError`. `run()` closes the client it owns; an injected client is left alone.

### 8.3 The sub-request wire codec (`subrequest.py`)

The single owner of the `/path?[params&]q=(context)!intent` encoding. `encode_subrequest`
**wire-escapes** only the characters that would corrupt the format — `()`, `'`, `%`, `&`, `#`,
space, control chars — leaving `$` and ordinary punctuation verbatim so URLs stay
human-readable; `q` is always the last parameter. `decode_subrequest` inverts it by locating the
structural `(context)` and first `!` on the *still-escaped* text (content parens/quotes are
`%28`/`%29`/`%27` and cannot interfere). `extract_expression_params` is the depth-aware
query splitter a receiving node runs first: `&` separates params only at depth 0 outside quotes,
so a nested `q=(…?x=1&y=2)!…` keeps its inner `&`, and the expression-bearing values
(`q`, `processor`) are returned **raw** for the expression decoder to percent-decode.

## 9. Variable & reference model (`context.py`, `ensemble.py`)

- **Scope** is an immutable **parent-pointer chain** (`Context`): every `child()` stacks a new
  frame, so concurrent iterations never corrupt one another and nested bindings never leak
  outward. Read-heavy/write-light, shallow (outer / iteration / fan-out / reducer).
- **Substitution** (`ensemble.py`) — `$name`/`$N` from scope, `$item` per row, `$current` per
  broadcast source; `$$` → literal `$`; unknown names stay verbatim so the model sees them as
  text. **Field paths** (`.field`, `[N]`) traverse the JSON-decoded referenced value
  (`$item.answers[0].text`). The error mode is `strict_fields`: lenient/LLM default substitutes
  `""` for a missing field/bad index; strict/RDS raises `ScopeError(malformed_source)`. Values
  landing inside a `{…}` JSON blob are JSON-escaped so they can't break a downstream
  `json.loads`.

## 10. Error model (`errors.py`)

A single hierarchy mirrors the evaluation phases; every error also carries the spec's wire
vocabulary — a `code` string and a `permanent` flag (permanent errors MUST NOT be retried):

| Exception | Default `code` | `permanent` | Raised when |
|---|---|---|---|
| `Url4Error` (base) | `internal_error` | `True` | catch-all base |
| `ParseError` (+`position`) | `malformed_source` | `True` | text isn't valid url4 |
| `ScopeError` | `unbound_reference` | `True` | `$name`/`$N` unbound (or strict field-path fail) |
| `ResolutionError` | `resolution_failed` | **`False`** | a source (URL/path/sub-request) failed |
| `CollectionError` | `malformed_source` | `True` | a `*` source isn't iterable |
| `CycleError` | `cycle_detected` | `True` | a hand-built graph has a cycle |

`ResolutionError` is transient by default (retryable); permanent outcomes (`unknown_identity`,
`identity_access_denied`, …) are raised with an explicit `code=…, permanent=True`. Distinct
from all of these is **`SourceFailure`** (§7.3) — a *value*, not an exception: the terminal
state of a tolerated `;optional` source. `errors.py` imports nothing internal (dependency sink).

## 11. Extensibility points

1. **New surface forms / lowerings** — `LoweringRegistry.copy().register(AstType, lowerer)`;
   pass the registry to `compile_expression`/`run`. The registry is threaded through `spawn`
   and `validate` so spawned fragments and pre-flight linting use the same custom lowerings.
2. **New backends / transports** — implement `IOLayer.fetch` (optionally `SupportsFetchEx` /
   `SupportsHoldings`); inject via `run(io=…)`. This is the seam for a real model gateway.
3. **The merge/reduce hook** — override `process(sources, intent, scope) -> str` (default
   `default_process`) and/or the `processor` route to change how sources+intent combine.
4. **Custom `DagNode`s** — any object with `deps` + `resolve` executes; identity-based
   memoization and acyclicity checks apply automatically.
5. **Run-state inspection** — pass an explicit `ExecutionContext` to read `collected_errors`
   after the run; tune `concurrency` and `strict_fields` per run.

## 12. Notable design decisions & trade-offs

| Decision | Rationale | Trade-off |
|---|---|---|
| Expression-problem flip (closed AST / open DAG) | each layer keeps *its* extension cheap | two node vocabularies to learn |
| Recursive descent, not PEG | the spec's rules *commit*; PEG backtracking can't express commitment | hand-written per-rule functions |
| One `decode_envelope`, two consumers (eager `build` + lazy DAG) | surface semantics **cannot drift** between paths | the two build different *graph shapes* (result-parity, not shape-parity) |
| Identity-based memoization (`eq=False`) | diamond deps resolve exactly once, for free | nodes aren't value-comparable/hashable |
| One TaskGroup, first-failure cancels siblings | no orphaned in-flight work; errors surface promptly | a tolerated failure needs an *isolated* sub-executor (`GuardNode`) |
| Run-wide `BoundedIOLayer` under per-map caps | a fan-out/among-rows aggregate can't stampede a backend | a second semaphore layer to reason about |
| Everything is a `fetch` (no "call" primitive) | model dispatch, data reads, holdings, reduce all share one port | the adapter carries all backend semantics |
| `SourceFailure` as a value, not an exception | an `;optional` failure flows through the gather without cancelling | group nodes must handle a third payload shape |
| Lazy, distributed parsing | nested/iterated fragments compile only on demand | parse errors in a dead branch surface late (mitigated by `Graph.validate()`) |

## 13. The SDK product surface (`render`, `builders`, `client`, `server`)

Sections 2–12 describe the engine: its only entry is `run(text, io) -> str`. The SDK layer
turns that engine into a product surface — an AST→text inverse, Python constructors, a client
façade, and a node/server side — without widening the core's import graph (the four modules
below import the engine; the engine imports none of them). Six design principles, forced by the
language spec and the codebase, govern all four:

1. **Strings stay first-class.** Every facade accepts a raw expression string wherever it
   accepts a `Node`; every builder output renders to canonical text.
2. **Renderer output is certified.** `render()` re-parses its own output and compares ASTs —
   no silently-wrong wire text can escape.
3. **Mode is inferred, never declared** — LLM vs RDS falls out of intent shape (§6), so no
   facade takes a "mode" flag.
4. **Two-axis annotations stay visibly separate** in `src()`: attribution
   (`name`/`weight`/`budgets`) vs execution (a closed set of typed kwargs).
5. **A node IS an `IOLayer`.** `Url4Node` implements `fetch`/`fetch_ex`/`fetch_holdings`;
   `node.evaluate(expr)` ≡ `run(expr, io=node)`; the ASGI shim reuses the same dispatch. GET is
   the only verb (url4-engine doctrine N1).
6. **The core stays framework-free** (repo hexagonal mandate): the ASGI app is a plain async
   callable; uvicorn is imported only inside `serve()`, behind the `server` extra.

### 13.1 Renderer (`render.py`)

`render(node: Node, *, check: bool = True) -> str` is the inverse of `build()`/`parse()`:
`build(render(x)) == x` for every parser-producible AST `x` (wrapped in
`Expression(sources=(x,))` when `x` is not itself an `Expression`/`Iteration`, mirroring
`build()`'s envelope). `check=True` enforces that equality per call; a mismatch or an
unrepresentable input raises **`RenderError`** (a new `Url4Error` subclass, code `unrenderable`)
naming the offending node. Normalization is deliberate and documented: a descriptor-empty
`Source` renders as the canonical `Binding` form; `Text` always renders quoted; `RelExpr`/
`RemoteExpr` use sugar form when `params == ()` and the canonical `?k=v&q=` form otherwise;
top-level `Expression`/`Iteration` and leaf values render bare while composite source nodes
render parenthesized (to defeat `build()`'s top-level intent-hoisting — see the engine findings
in the work ledger); `Source.expand` renders as the `*` prefix; numbers use decimal-only
formatting (negative/nonfinite/sub-1e-12 → `RenderError`). Unrepresentable inputs (→ `RenderError`) include URLs carrying unbalanced
parens/quotes/depth-0 `,;!`, struct nesting > 2, an `Iteration.reducer` in value position, and
a `Source` wrapping an expression-valued node whose first execution annotation is a dual-scope
key (the §8.1.2 boundary would reclassify it on reparse). A supporting addition,
`grammar.parse_value(text)`, exposes the value-detection path so builders classify strings
exactly as the grammar does.

### 13.2 Builders (`builders.py`)

Python constructors that lower to the existing frozen AST (no parallel representation):
`text`, `ref`, `self_`, `identity`, `struct`, `expand`, `src` (the two-axis descriptor:
attribution kwargs `name`/`weight`/`budgets`; execution kwargs `mode`/`t`/`retry`/`accept`/
`required`/`optional`/`expand`/`annotations`), `expr`, `broadcast`, `iterate`, and `reduce`.
Coercions match the grammar: a `str` source → `grammar.parse(str)` (full descriptor grammar); a
`str` value → `grammar.parse_value(str)` (a plain word is a *bare token*, not text — inline
prose needs `text(...)`); a `Mapping` → `struct()`; a `list`/`tuple` collection in `iterate` →
an inline parenthesized collection. `intent` accepts only `str | Text | Url | RelUrl` (what the
engine's `intent_atom` can produce); anything else raises `TypeError` with guidance.
`iterate(reduce=…)` embedded as a source is auto-rewritten by `expr()` into the
value-position-valid `Expression(sources=(iteration-sans-reducer,), intent=reducer)`. Every
builder result satisfies `render(node, check=True)` by construction.

### 13.3 Client (`client.py`)

`Client` is the caller-side façade; `Url4Result` (frozen) is its envelope — `.text` (the body),
`.request` (the canonical expression that ran, the audit artifact), `.data` (`json.loads(text)`,
raising `ValueError` for non-JSON), and `.elements` (`.data` as a list, raising `ValueError`
otherwise). The async helpers `query`/`broadcast`/`iterate`/`reduce`/`evaluate` share **one**
execution path: build the AST via the §13.2 builders, wrap in `RemoteExpr` when a node target is
set, render to canonical text (that text *is* `Url4Result.request`), and execute via `run()`.
Local vs remote differ only in which DAG node does the wire hop. `io=None` lazily owns an
`HttpIOLayer` closed by `aclose()`; an injected `io` is never closed. Protocol params
(quorum/triggers/fmt/…) ride on the expression — the executor already enforces `quorum`
(`dag/compiler._quorum_of`); triggers/fmt are carried-but-unenforced Part C follow-ups. There is
deliberately **no** module-level `url4.query()` (a module-global async client would bind an event
loop); the `screamingface` app layer may add that sugar with its own lifecycle.

### 13.4 Node / server (`server.py`)

`Url4Node` implements the `IOLayer` + `SupportsFetchEx` + `SupportsHoldings` ports — a node *is*
an io layer. Decorators register the surface: `@node.endpoint("/claude")` (intent processors —
a `Request(path, context, intent, params)` handler whose `context` is *opaque, already-resolved*
data, never an unresolved expression), `@node.holdings(collection=None)` and
`@node.identity("emily")` (the `@`/`@name[/coll]` holdings ports), and `node.data_route(...)`
(static-or-callable data reads). `node.evaluate(expr)` runs `run(expr, io=self)` in-process;
`asgi()` returns a plain async **GET-only** callable (405 otherwise) whose eval path
`GET /v1?…&q=<expr>` reconstructs and evaluates the expression — the surface a remote `Client`
query targets, closing the loop end-to-end. Relative fetches route inbound; absolute
`http(s)://`/`url4://` delegate to the (lazily-owned or injected) outbound layer. ASGI errors map
by code: `ParseError`→400, unknown identity/path→404, `identity_access_denied`/`consent_*`→403,
transient `ResolutionError`→502, other `Url4Error`→500; the body is the result string (200,
`text/plain`) or `{"error": {code, message}}`. `serve(host, port, …)` imports uvicorn lazily
behind the `server` extra. No response-envelope JSON is invented — Parts C+ define it; v1 returns
the raw body and reserves the shape.

### 13.5 SDK boundary (out of scope, reserved for Part C+)

Quorum/trigger *enforcement* beyond what the executor already does, streaming delivery, the
response envelope (§18 of the language spec), settlement/attribution reporting, policy
registries, auth/consent transport (needs the URL4-Auth-Token / Part C transport spec),
telemetry planes (url4-engine doctrine T/O/F), module-level query sugar, and the `screamingface`
branding layer are all deliberately deferred.

## 14. Public API surface

Top-level (`import url4`) — **engine:** `run`, `compile_expression`, `Parser`/`build`/`walk`;
the I/O port + adapters (`IOLayer`, `StaticIOLayer`, `HttpIOLayer`, `FetchRequest`,
`FetchResult`, `SupportsFetchEx`, `SupportsHoldings`, `fetch_result`, `parse_collection`); the
AST node types and `Context`; the sub-request codec (`encode_subrequest`, `decode_subrequest`,
`extract_expression_params`); and the full error hierarchy (incl. `RenderError`). **SDK
surface** (§13): `render`; the builder functions (`text`, `ref`, `self_`, `identity`, `struct`,
`expand`, `src`, `expr`, `broadcast`, `iterate`, `reduce`); `Client` + `Url4Result`; and
`Url4Node`. The DAG internals (`Executor`, `ExecutionContext`, `Graph`, `LoweringRegistry`,
`DagNode`, `Payload`, `SourceFailure`, `DEFAULT_PROCESSOR`, the concrete node classes) are
exported under `url4.dag` for advanced/extension use.

## 15. Package integration — CI, coverage & release

url4 is a first-class monorepo component, wired into the same machinery as `apps/aigateway`/
`apps/scoreboard` (mirroring their structure, not inventing new conventions):

- **CI** — `.github/workflows/url4-tests.yml`, path-filtered to `packages/url4/**` (self-
  triggering on its own YAML), single Python 3.12 (matching `requires-python >= 3.12` and
  scoreboard's single-version lane): `uv sync` → `ruff check` → `ruff format --check` →
  `pyright` → `pytest … --cov=url4 --cov-fail-under=95`, with the `dorny/test-reporter` and
  PR-only `orgoro/coverage` steps copied from `scoreboard-tests.yml`.
- **Coverage gate — 95%, deliberately above the repo's usual 80%.** The two apps stay at 80%;
  url4 is held higher by explicit decision. This is a real bar met by real tests (`tests/unit/`
  + `tests/spec/`), not a copy of the app threshold — a future reader should not "correct" it
  back down to 80%.
- **SDLC stack** — a `url4` entry in `.claude/sdlc.local.md` (root `packages/url4`, skill
  `sdlc-python`, gates including `pytest --cov=url4 --cov-fail-under=95 -q`), so the standard
  gate loop exercises the package automatically instead of by hand.
- **Release lane** — a `packages/url4` entry in `release-please-config.json`
  (`release-type: python`, `version-file: packages/url4/pyproject.toml`) for version-bump /
  CHANGELOG automation on merge to `main`.

Deliberately **out of scope** (documented so they are not re-litigated): a **CODEOWNERS entry**
and a **`dependabot.yml`** `uv` ecosystem — neither exists anywhere in the repo yet, so minting
them for url4 alone would set unreviewed repo-wide convention; and an actual **package-publish
target** (PyPI or a private index) — neither app's release lane publishes a Python package (both
build only Docker images + Helm charts, which don't apply to a library), so `release-please`
registration buys version automation without inventing a publish target. Both are separate,
repo-wide decisions.

## 16. Conformance

`tests/spec/` is an executable conformance suite, one file per language area — value detection,
descriptors, references, structured values, expansion, iteration, canonical form, holdings, and
the HTTP wire format — alongside the module unit/characterization tests under `tests/unit/`
(renderer round-trip corpus + random-AST property, builder golden strings, client envelope, node
dispatch + ASGI status mapping). The full suite is **697 tests** at **97.86%** line coverage,
green under ruff + pyright + pytest and gated at ≥95% in CI — the practical oracle for the
surface-semantics `§` claims in this document.
