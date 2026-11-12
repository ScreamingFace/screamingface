# url4 SDK

Source: https://docs.screamingface.ai/learn/url4-sdk

The Python library for building, reading, and running url4 expressions.

The url4 SDK is the Python library for the [url4](learn-url4.md) protocol: parse an expression, build one in code, walk the tree, or execute it. It ships as the `url4` package.

```bash
pip install url4
```

## Parse and render

`build` parses a url4 string into a frozen syntax tree; `render` turns a tree back into canonical text. The two are exact inverses, so an expression survives a round-trip unchanged. That guarantee is what makes url4 a reliable audit trail. `walk` traverses the tree.

```python
import url4

# Parse a url4 string into a syntax tree, and render it back, losslessly.
node = url4.build("(https://a, https://b)!'summarize both'")
assert url4.render(node) == "(https://a, https://b)!'summarize both'"

for child in url4.walk(node):   # preorder traversal of the tree
    ...
```

## Build in Python

When you would rather not assemble strings, the builder API constructs the same tree directly. `src` makes a source (with optional name, weight, budgets), `expr` groups sources under an intent, and `iterate` / `reduce` express map-and-reduce. `ref` and `text` build references and literals.

```python
import url4

# Build the same expression with the Python DSL instead of a string.
expr = url4.expr(
    url4.src("https://a"),
    url4.src("https://b"),
    intent=url4.text("summarize both"),
)
print(url4.render(expr))   # a canonical url4 string
```

## Execute

Execution needs an **I/O layer**: the piece that resolves a source to content. `StaticIOLayer` returns fixed values (ideal for tests); `HttpIOLayer` fetches over the network. `evaluate_sync` runs an expression in one call and returns a result carrying both the answer and the canonical request that produced it. For async use, `url4.Client` runs expressions inside an event loop.

```python
import url4

# A StaticIOLayer returns fixed content per source, ideal for tests.
io = url4.StaticIOLayer({"https://a": "alpha", "https://b": "beta"})

result = url4.evaluate_sync("(https://a, https://b)!'summarize both'", io=io)
print(result.text)      # the reduced answer
print(result.request)   # the canonical url4 that actually ran
```

A url4 node can also be served over HTTP, so other expressions can call it as a source. This is the same shape the [engine](learn-engine.md) exposes. Serving needs uvicorn, which comes with the `url4[server]` extra rather than the base install:

```python
# Serving needs the server extra: pip install "url4[server]"
from url4 import Url4Node

node = Url4Node("demo")
node.serve()   # 127.0.0.1:4404 by default, an HTTP node other expressions can call
```

Parsing and execution raise typed errors: `ParseError` for malformed text, `ScopeError` for an unresolved reference, `CycleError` for a circular dependency, and `RenderError` when a tree cannot round-trip, all subclasses of `Url4Error`.

## From the command line

```bash
url4 eval "(https://a, https://b)!'summarize both'"
url4 serve
```

> **url4 SDK vs the ScreamingFace Client.** This library is the low-level protocol: parse, build, and run url4. The [ScreamingFace Client](sf-client.md) (`screamingface`) is the research-facing layer on top: it composes fusions and benchmarks, drives an engine, and reads back scored reports. Reach for the SDK when you are working with url4 itself; reach for the Client when you are running evaluations.

## Where the code lives

-   [`packages/url4`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4): the package, with its [README](https://github.com/ScreamingFace/screamingface/blob/main/packages/url4/README.md).
-   [`src/url4/core/builders.py`](https://github.com/ScreamingFace/screamingface/blob/main/packages/url4/src/url4/core/builders.py): the Python builder API.
-   [`packages/url4/examples`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4/examples): runnable examples.
