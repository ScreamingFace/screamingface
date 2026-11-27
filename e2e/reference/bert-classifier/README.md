# Fixed-label classifier reference

This isolated Python 3.12 project implements the Unit 8A `POST /classify` boundary. The validated
request reaches a tokenizer and head supplied by a local loader. The response contains the full
sentiment score vector in `NEGATIVE`, `POSITIVE` order. The target is Linux x86_64 CPU.

`bert_reference.server.loopback_server(environment, loader, port=...)` verifies the artifact
snapshot before calling the loader and composes a Uvicorn server for `127.0.0.1`. Pass the absolute
artifact directory in `SF_BERT_REFERENCE_ARTIFACT_ROOT` and the independently approved digest of
its `manifest.json` in `SF_BERT_REFERENCE_MANIFEST_SHA256`. The loader receives a read-only map of
verified filename to bytes; it must consume those bytes directly and work offline. Run the server
with its own listener rather than supplying a socket. Use `target.toml` as the Gateway target stanza
after configuring a test origin. The standard scalar readiness request is `{"inputs":"ping"}`.

The normative manifest format is defined in the Unit 8A C7 fragment. The unit suite uses the exact
documented manifest with synthetic file bytes, a fake tokenizer and a fake head. A backend for the
real pinned checkpoint and its provisioned files are needed for real inference.

After populating the Python wheel cache, run the package gates from this directory:

```sh
uv lock --check --offline
uv run --frozen --offline pytest -q
uv run --frozen --offline ruff check .
uv run --frozen --offline ruff format --check
PYRIGHT_PYTHON_GLOBAL_NODE=on uv run --frozen --offline pyright
uv build --offline --no-build-isolation
```

Pyright uses an already installed Node executable. Use an isolated network with loopback available
for deterministic HTTP tests.

For the scalar composition check, use three separate Python environments installed from the
same checkout's frozen Gateway, Engine and SDK locks:

```sh
uv run --frozen --offline python tests/compose_scalar.py "$GATEWAY_PYTHON" "$ENGINE_PYTHON" "$SDK_PYTHON"
```

The harness substitutes account and credential storage, while the real Gateway checks peer
identity, endpoint grants, request limits and upstream replies. The SDK and Engine run their
normal scalar path. The harness asserts the fixture inputs and Gateway send counts.
