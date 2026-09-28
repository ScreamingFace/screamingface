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

  url4.observe    leaf: the observation seam. Only the engine imports it.
  url4.streaming  separate axis: the CloudEvents / OTel wire contract.
```

## The layer map

| Layer | Package | Role | May import |
|---|---|---|---|
| language | `url4.core` | url4 text ↔ AST. Pure, synchronous. | standard library |
| wire | `url4.wire` | The `?q=(context)!intent` codec. One owner, shared below both consumers. | `core` |
| engine | `url4.dag` | AST → typed DAG → concurrent execution. | `core`, `wire`, `io.layer`, `observe` |
| io port | `url4.io` | The `IOLayer` port and its adapters — the seam. | `core`, `wire` |
| leaf | `url4.observe` | Observation events and context-local sinks. | standard library |
| node | `url4.peer` | `Url4Node` (server), `Client` (requestor), dispatch. | `core`, `wire`, `dag`, `io`, `observe` |
| node | `url4.cli` | `url4 serve` / `url4 eval`. The composition root. | all of the above |
| axis | `url4.streaming` | The wire contract between a client and a runner. | standard library + pydantic |

## The direction rule

> A layer imports only the layers below it.

- `url4.core` imports the standard library only. It is a leaf of leaves.
- `url4.wire` imports `core` only.
- `url4.dag` may import `core`, `wire`, `io.layer`, and `observe`. It must not
  import `peer`, `cli`, or `streaming`.
- `url4.io` must not import `dag`. The engine depends on the port, never the
  reverse. `io.layer` is standard-library only, so the engine can name the port
  without dragging in a transport.
- `url4.observe` is a leaf. It imports no engine module and no transport.
- `url4.peer` must not import `cli`. The CLI composes the node, not the reverse.
- `url4.streaming` imports no url4 module.

`tests/unit/test_layering.py` enforces this over the source AST. It sees
function-local and `TYPE_CHECKING` imports too. A crossing import fails the test
with the file and the module name.

`io/layer.py` is the port. `io/static.py` and `io/http.py` are adapters. The
engine may name the port at module scope; a concrete adapter is imported lazily
(the default `HttpIOLayer` in `dag/_run.py`), so `import url4.dag` names no
transport.

## Where do I start? — a task index

| I want to change… | Start here | Layer |
|---|---|---|
| the grammar or a parse error | `core/grammar.py` | language |
| the AST node shape | `core/nodes.py` | language |
| canonical rendering / the round-trip check | `core/render.py` | language |
| the Python builders (`src`, `expr`, `iterate`) | `core/builders.py` | language |
| the lexical scope (`$name` resolution) | `core/context.py` | language |
| the `?q=` escaping or decoding | `wire/subrequest.py` | wire |
| how text lowers to a DAG node | `dag/_lowering.py`, `dag/_wiring.py` | engine |
| the public `run()` entry | `dag/_run.py` | engine |
| the scheduler or the exactly-once memo | `dag/executor.py` | engine |
| the `DagNode` protocol or `ExecutionContext` | `dag/node.py`, `dag/_context.py` | engine |
| one executable node (fetch, group, guard, iteration) | `dag/nodes/*.py` | engine |
| collection parsing (JSON / CSV / JSONL) | `dag/semantics/collection.py` | engine |
| `$name` / `$item` substitution | `dag/semantics/ensemble.py` | engine |
| the port or a capability protocol | `io/layer.py` | io |
| the in-memory test adapter | `io/static.py` | io |
| the httpx adapter | `io/http.py` | io |
| the node's registration or dispatch order | `peer/server.py`, `peer/_dispatch.py` | node |
| the requestor `Client` | `peer/client.py` | node |
| `url4.toml` or the `serve` flags | `cli/_config.py`, `cli/_serve.py` | node |
| observation events or sinks | `observe.py` | leaf |
| the CloudEvents wire contract | `streaming/protocol/` | streaming |

Note: `dag/compiler.py` is the public facade only. The implementation is
`dag/_lowering.py` (the `LoweringRegistry` and the per-node lowerers) plus
`dag/_wiring.py` (the group-wiring strategy).

## The two side axes

`url4.observe` is a leaf at the package root. The engine imports it; it imports
nothing above it. It is documented public API (`from url4.observe import
current_log_sink`), so it stays at the root.

`url4.streaming` is a separate axis, not a layer. It is the wire contract
between a client and a runner. It imports no url4 module. It is an optional
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
  lazily.

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
