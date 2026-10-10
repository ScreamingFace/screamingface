# url4 architecture — the three layers

url4 is one package with three layers. An expression is **the language**. The
DAG is **the engine**. The node is **the network**. Every module belongs to one
layer. A layer imports only the layers below it.

```
        text  "(a=https://x, tone='formal')!'Summarize $a in a $tone tone'"
          |
  +-------v--------+   LANGUAGE   url4.core    text <-> AST   (pure, sync)
  | grammar parser |              grammar/parser -> nodes -> render
  | nodes  render  |              builders, scope, scanning, errors
  +-------+--------+
          |  AST
  +-------v--------+   ENGINE     url4.dag     AST -> executable DAG
  | lower -> wire  |              _lowering + _wiring -> compile_expression
  | executor/nodes |              executor + node vocabulary + semantics
  +---+---------+--+
      |         |
      |         +------+  WIRE   url4.wire    the "?q=" sub-request codec (shared)
      |  IOLayer port   |
  +---v----------------v--+
  |  IO PORT               |   url4.io   layer (port) + static/http (adapters)
  +-----------+------------+
              |
  +-----------v------------+   NODE   url4.peer   server + client + dispatch
  |  node / CLI            |          url4.cli    `url4 serve` / `url4 eval`
  +------------------------+

  url4.observe    leaf: the observation seam. The engine and the node import it.
  url4.streaming  separate axis: the CloudEvents / OTel wire contract.
```

## The layer map

| Layer | Package | Role | May import |
|---|---|---|---|
| language | `url4.core` | url4 text ↔ AST. Pure, synchronous. | standard library |
| wire | `url4.wire` | The `?q=(context)!intent` codec. One owner, shared below both consumers. | `core` |
| engine | `url4.dag` | AST → typed DAG → concurrent execution. | `core`, `wire`, `io.layer`, `io.idempotency`, `observe` |
| io port | `url4.io` | The `IOLayer` port and its adapters — the seam. | `core`, `wire` |
| leaf | `url4.observe` | Observation events and context-local sinks. | standard library only (plus `url4._log_attributes`, a stdlib-only leaf) |
| node | `url4.peer` | `Url4Node` (server), `Client` (requestor), dispatch. | `core`, `wire`, `dag`, `io`, `observe`. Not `cli`, not `streaming` |
| node | `url4.cli` | `url4 serve` / `url4 eval`. The composition root. | `core`, `wire`, `dag`, `io`, `observe`, `peer`. Not `streaming` |
| axis | `url4.streaming` | The wire contract between a client and a runner. | standard library + pydantic. No other url4 layer |

## The direction rule

> A layer imports only the layers below it.

- `url4.core` imports the standard library only. It is a leaf of leaves.
- `url4.wire` imports `core` only.
- `url4.dag` may import `core`, `wire`, `observe`, `io.layer`, and `io.idempotency`. It must not
  import `peer`, `cli`, or `streaming`.
- `url4.io` may import `core` and `wire` only. It must not import `dag`,
  `observe`, `peer`, `cli`, or `streaming`. The engine depends on the port, never
  the reverse. `io.layer` and `io.idempotency` are standard-library only, so the engine can
  name the port without dragging in a transport.
- `url4.observe` is a leaf. It imports the standard library only (and
  `url4._log_attributes`, a stdlib-only leaf outside the layer matrix).
- `url4.peer` must not import `cli` or `streaming`. The CLI composes the node,
  not the reverse.
- `url4.cli` must not import `streaming`.
- `url4.streaming` imports no other url4 layer.

`tests/unit/test_layering.py` enforces this over the source AST. It is the
source of truth: when this document and the test disagree, the test is right.
It sees function-local and `TYPE_CHECKING` imports too. A crossing import fails
the test with the file and the module name.

`url4.dag` reaches `url4.io` only through the port modules, `url4.io.layer` and
`url4.io.idempotency`. One exception is documented: `dag/_run.py` lazily imports `url4.io.http` for the default IO layer
when the caller passes no `io`. The test allows that import from that file and
no other.

`io/layer.py` is the port, and `io/idempotency.py` is the key a retrying guard
offers through it (a context variable, so adapters opt in). `io/static.py` and
`io/http.py` are adapters. The engine may name the port at module scope. The
default `HttpIOLayer` in `dag/_run.py` is imported lazily, so `import url4.dag`
names no transport.

## Where do I start? — a task index

| I want to change… | Start here | Layer |
|---|---|---|
| the grammar or a parse error | `core/grammar.py` | language |
| character classes or quoted-text decoding | `core/_lexical.py` | language |
| structured weights and budgets (`(k:v)`) | `core/_struct_values.py` | language |
| what is a call head (`/p(`, `/p?…q=(`, `url4://`) | `core/_call_head.py` | language |
| the envelope split (`!intent`, `;params`, `src*(body)`) | `core/parser.py`, `core/_splitters.py`, `core/_iteration_envelope.py` | language |
| the AST node shape | `core/nodes.py` | language |
| canonical rendering / the round-trip check | `core/render.py` | language |
| the Python builders (`src`, `expr`, `iterate`) | `core/builders.py` | language |
| the lexical scope (`$name` resolution) | `core/context.py` | language |
| the `?q=` escaping or decoding | `wire/subrequest.py` | wire |
| how text lowers to a DAG node | `dag/_lowering.py`, `dag/_wiring.py` | engine |
| how a source descriptor lowers (label, expand, guard) | `dag/_descriptor.py` | engine |
| the public `run()` entry | `dag/_run.py` | engine |
| the scheduler or the exactly-once memo | `dag/executor.py` | engine |
| the `DagNode` protocol or `ExecutionContext` | `dag/node.py`, `dag/_context.py` | engine |
| one executable node (fetch, group, guard, iteration) | `dag/nodes/*.py` | engine |
| collection parsing (JSON / CSV / JSONL) | `dag/semantics/collection.py` | engine |
| `$name` / `$item` substitution | `dag/semantics/ensemble.py` | engine |
| the port or a capability protocol | `io/layer.py` | io |
| the guard's idempotency key ("reuse until answered") | `io/idempotency.py` | io |
| the in-memory test adapter | `io/static.py` | io |
| the httpx adapter | `io/http.py` | io |
| the node's registration or dispatch order | `peer/server.py`, `peer/_dispatch.py` | node |
| the requestor `Client` | `peer/client.py` | node |
| `url4.toml` or the `serve` flags | `cli/_config.py`, `cli/_serve.py` | node |
| observation events or sinks | `observe.py` | leaf |
| the CloudEvents wire contract | `streaming/protocol/` | streaming |

Note: `dag/compiler.py` is the public facade only. The implementation is
`dag/_lowering.py` (the `LoweringRegistry` and the per-node lowerers),
`dag/_descriptor.py` (the source-descriptor lowering) and `dag/_wiring.py`
(the group-wiring strategy).

## The two side axes

`url4.observe` is a leaf at the package root. The engine and the node import it;
it imports nothing above it. It is documented public API (`from url4.observe import
current_log_sink`), so it stays at the root.

`url4.streaming` is a separate axis, not a layer. It is the wire contract
between a client and a runner. It imports no other url4 layer. It is an optional
extra (`url4[streaming]`) because it is pydantic models.

## The invariants the layers rest on

- **Parse and render are inverses.** `build(render(node)) == node`, or `render`
  raises `RenderError`. See `core/render.py`.
- **The intent is mandatory.** A parenthesized group needs `!intent` (`OME-508`).
  The parser and the DAG read one envelope decode, `core/parser.py`.
- **The engine resolves each node exactly once.** `dag/executor.py` memoizes by
  `id` with no `await` between the check and the store. Do not insert one.
- **HTTP and in-process dispatch cannot diverge.** `peer/_http.py` reuses
  `peer/_dispatch.py`.
- **The engine names no transport at module scope.** `HttpIOLayer` is imported
  lazily in `dag/_run.py`.

## Gates

| Gate | Command | What it protects |
|---|---|---|
| layer direction | `pytest tests/unit/test_layering.py` | this document |
| import isolation | `pytest tests/unit/test_import_isolation.py` | no framework or pydantic in the core |
| module size | `python scripts/check_module_size.py` | the reviewed hotspot splits |
| suppressions | `python scripts/check_suppressions.py` | the `# type: ignore` / `# noqa` ratchet |

The module-size ratchet is keyed by path. When a module moves, update its
`BASELINE` entry in `scripts/check_module_size.py`. Do not raise a cap to make
CI pass.
