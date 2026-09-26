# Kind environment (uniform executor test-plan §5)

A local single-node-per-role kind cluster that runs the whole `screamingface-engine` chart —
queue runner, warm child pool, the shared events stream, and one mount of each kind (a model
endpoint and a data route) — against a stub aigateway. It exists so the uniform executor's e2e
cases (`tests/kind/`, marker `kind`) and the phase-0/5 measurement harness
(`scripts/bench/sync_latency.py`) have something real to run against.

## Layout

| Path | What |
|---|---|
| `kind-config.yaml` | one control-plane node, one worker node; cluster name `sf-uniform` |
| `aigw-stub/` | a FastAPI stand-in for aigateway: `POST /v1/chat/completions`, `GET /v1/models`, `GET /healthz`, fault injection (`X-Stub-Fail`), an oversized reply (`X-Stub-Bytes`) |
| `url4-kind.toml` | the declared world this environment ships: the shipped `[aigateway]` defaults plus one `[data]` route (`/corpus/papers`) |
| `engine-kind.Dockerfile` | layers `url4-kind.toml` onto the engine image at `/etc/url4/url4.toml` — the shared `apps/screamingface-engine/url4.toml` is untouched |
| `values-kind.yaml` | the chart values table from test-plan §5 |
| `values-kind-node.yaml` | layers `node.enabled: true` back on, for the phase-0 B1 baseline only |
| `up.sh` / `down.sh` | bring the cluster up / tear it down |

## Why a Dockerfile overlay for the world config

The declared world (`url4.toml`) is baked into the image at `/etc/url4/url4.toml`
(`Dockerfile`) — the chart ships no ConfigMap for it (`configmap.yaml`'s comment: "the App reads
that file at boot too"). The kind environment needs one extra `[data]` route the shared
`url4.toml` does not declare, so `engine-kind.Dockerfile` builds a second, tiny image FROM the
already-built base that only overlays that one file. `Dockerfile.benchmark`'s runtime stage is
`FROM ${BASE}` again, so building it FROM the overlay (not the base) carries the same world into
the benchmark image `up.sh` loads for the runner pool.

The model world needs no override at all: `BUILTIN_MODEL_WORLD`
(`world/models/builtins.py`) already declares every model id aigateway's compiled provider
plugins know, `anthropic/claude-haiku-4-5` included, so the shipped `url4.toml`'s
`default_route` already resolves — pointing `config.aigatewayBaseUrl` at the stub is enough to
route it there.

## Bringing it up

```sh
cd apps/screamingface-engine
deploy/kind/up.sh
```

Idempotent — re-running rebuilds the images, reloads them, and `helm upgrade`s the existing
release. Pass extra `helm` arguments straight through, e.g. for the phase-0 B1 baseline:

```sh
deploy/kind/up.sh -f deploy/kind/values-kind-node.yaml
```

Tear down:

```sh
deploy/kind/down.sh
```

`down.sh` only deletes the `sf-uniform` kind cluster. It never touches the standalone `nats-js`
Docker container other test suites use on `localhost:4222` — that container is not part of this
cluster; the cluster runs its own NATS from the chart's bundled subchart.

## Rollout order (implementation-notes.md D7)

The App and the worker pool both refuse to start while a legacy `url4-cloud_<topic>` stream
still exists in NATS (JetStream error 10065: a new `url4-cloud.*` stream cannot overlap an old
per-topic one). On a **fresh** cluster — which is all `up.sh` ever creates — no such stream
exists, so this never fires and nothing here has to run `admin purge-legacy-streams`.

It only matters when upgrading an existing deployment that predates the shared events stream
(uniform executor PRD 01). That order is:

1. **Drain** the running deployment (stop new runs; let in-flight ones finish).
2. Run `admin purge-legacy-streams` **with the new image** (it also refuses to start while an
   old-shape stream exists, by the same guard — run it as a one-off, not as the long-running
   App).
3. **Deploy** the new chart version.

Reversing steps 2 and 3 — deploying first — is the failure this order exists to avoid: the new
App/worker would refuse to start at all, and the previous release could not even accept a
`helm rollback` back onto a bus that already carries fresh, unpurged streams from the failed
upgrade.

## Running the test suite

```sh
uv run pytest tests/kind -m kind -q
```

Kind tests are excluded from the default `pytest` run (`addopts = "-m 'not kind'"` in
`pyproject.toml`) and skip cleanly — a bare `pytest` collects them but a run with no `-m kind`
never executes them; passing `-m kind` and running with no reachable `kind-sf-uniform` context
skips each test individually rather than erroring, exactly like the repo's existing
NATS-reachability skip in `tests/integration/`.
