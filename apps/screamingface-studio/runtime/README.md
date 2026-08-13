# ScreamingFace Studio runtime

This package provides the local backend for the ScreamingFace Studio desktop app. It runs the AI
Gateway and ScreamingFace Engine together as one supervised process, without Docker, Kubernetes,
NATS, or Postgres.

The same package can run from Python during development or be built as a standalone PyInstaller
sidecar for Tauri.

## Architecture

| Service | Address | Responsibility |
| --- | --- | --- |
| AI Gateway | `http://127.0.0.1:9105` | Provider credentials, model discovery, and inference routing |
| ScreamingFace Engine | `http://127.0.0.1:9108` | REST/WebSocket API and URL4 execution |

The Engine runs URL4 jobs in-process and uses an in-memory event stream. AI Gateway stores its
database, encryption key, and JWT secret below the runtime data directory. The ScreamingFace SDK
is a client for the Engine; it is not another service or executable.

Both HTTP services bind to loopback. AI Gateway authentication is disabled for this local-only
deployment, so the runtime must not be exposed directly to a network.

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- macOS arm64 for the currently verified frozen build

Use the committed `uv.lock`. In particular, the runtime pins `litellm==1.87.0` because newer
resolutions may require a Rust toolchain when a compatible macOS wheel is unavailable.

## Run from source

```sh
cd apps/screamingface-studio/runtime
uv sync --frozen
.venv/bin/screamingface-runtime \
  --data-dir ~/.screamingface-studio
```

The default data directory is `~/.screamingface-studio`. It can also be set with
`SCREAMINGFACE_RUNTIME_DATA_DIR`.

The packaged URL4 configuration is used automatically. To test a different configuration:

```sh
.venv/bin/screamingface-runtime \
  --data-dir /tmp/screamingface-runtime \
  --runner-config /path/to/url4.toml
```

On startup, the launcher:

1. creates the writable data directory;
2. applies AI Gateway migrations in-process;
3. starts both ASGI application lifespans;
4. announces readiness after both ports are listening;
5. supervises both services until `SIGINT` or `SIGTERM`.

If either service exits unexpectedly, the launcher stops its peer and exits non-zero.

## Process contract

Tauri and other process supervisors should consume the launcher's machine-readable output.

Successful startup writes one line to stdout:

```text
SCREAMINGFACE_RUNTIME_READY {"services":{"aigateway":"http://127.0.0.1:9105","engine":"http://127.0.0.1:9108"}}
```

Startup is limited to 30 seconds. Migration, configuration, lifespan, and port-binding failures
exit non-zero and write a concise line to stderr:

```text
SCREAMINGFACE_RUNTIME_ERROR <cause>
```

One `SIGINT` or `SIGTERM` shuts down both ASGI lifespans and the parent process.

## Verify a running runtime

Basic HTTP checks:

```sh
curl -fsS http://127.0.0.1:9105/healthz
curl -fsS http://127.0.0.1:9108/healthz
curl -fsS http://127.0.0.1:9108/v1/models
curl -fsS http://127.0.0.1:9108/v1/connections
```

Run the credential-free execution smoke test in another terminal:

```sh
cd apps/screamingface-studio/runtime
.venv/bin/screamingface-runtime-smoke
```

Expected output:

```text
SCREAMINGFACE_RUNTIME_SMOKE_OK screamingface-runtime-ok
```

This diagnostic mints a capability, attaches the production WebSocket protocol, schedules an
in-process URL4 run, and verifies its terminal result. It evaluates a deterministic literal URL4
expression and does not call or charge a model provider. The smoke command is development tooling,
not a second shipped sidecar.

Run the unit tests with:

```sh
uv run --frozen pytest
```

## Build the sidecar

```sh
cd apps/screamingface-studio/runtime
./build-sidecar.sh
```

The build produces a PyInstaller `onedir` bundle:

```text
dist/screamingface-runtime/
├── screamingface-runtime
└── _internal/
```

Run the frozen executable from any working directory:

```sh
apps/screamingface-studio/runtime/dist/screamingface-runtime/screamingface-runtime \
  --data-dir ~/.screamingface-studio
```

`onedir` avoids extracting a one-file archive on every app launch and allows release tooling to
sign nested native libraries before signing the main executable. The current macOS arm64 bundle
is approximately 198 MB and is ad-hoc signed by PyInstaller for local development.

The PyInstaller spec explicitly collects dependencies that static analysis cannot fully discover:

- AI Gateway provider plugins and migrations;
- LiteLLM, Tiktoken, Tortoise, URL4, and URL4 Cloud lazy imports;
- the runner configuration, Engine diagrams, and LiteLLM model data;
- distribution metadata used by plugin registries;
- native libraries used by cryptography and Uvicorn's accelerated stack.

## Tauri lifecycle

The desktop process starts the runtime before creating its main window. It waits for the readiness
record, forwards runtime output into the application log, records unexpected exits, and sends a
graceful termination signal when Tauri exits. Runtime state is stored below Tauri's application
data directory.

Development builds look for the frozen executable first and fall back to the runtime virtual
environment. Set `SCREAMINGFACE_RUNTIME_EXECUTABLE` to test a specific build explicitly.

For application bundles, `src-tauri/before_build.sh` builds the PyInstaller `onedir` artifact and
copies it into `src-tauri/resources/screamingface-runtime`. Tauri packages that directory as an
application resource; the generated contents are ignored by Git.

## Runtime resources

The desktop runtime embeds its configuration at
`src/screamingface_runtime/resources/url4.toml`. The container deployment uses
`apps/url4-cloud/url4.toml`. A unit test requires their meaningful contents to match so the desktop
and container model worlds cannot drift silently.

AI Gateway migrations are Python modules and are bundled through PyInstaller's hidden imports.
The SQLite database and generated secrets remain outside the application bundle in the writable
data directory.

## Debug the services separately

Running the services independently can help isolate Gateway or Engine problems.

Terminal 1:

```sh
cd apps/aigateway
uv sync --frozen
.venv/bin/aigateway migrate
AIGW_AUTH_MODE=disabled .venv/bin/aigateway serve
```

Terminal 2:

```sh
cd apps/url4-cloud
uv sync --frozen
.venv/bin/url4-cloud serve --local
```

This split setup is for debugging only. The desktop app should use the combined runtime process.

## Known limitations

- Ports `9105` and `9108` are currently fixed. Starting a second local runtime reports an
  occupied-port startup error.
- Benchmark evaluation requires prepared benchmark assets configured through
  `URL4_BENCHMARK_ASSETS`. Catalog, connection, and smoke APIs work without them.
- The frozen bundle currently includes broad LiteLLM module and data collection. It favors
  correctness over minimum bundle size.
- Release code signing, notarization, target-triple naming, and builds for platforms other than
  macOS arm64 are not yet configured here.
