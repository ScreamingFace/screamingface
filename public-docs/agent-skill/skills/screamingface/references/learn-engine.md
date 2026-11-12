# ScreamingFace Engine

Source: https://docs.screamingface.ai/learn/engine

The runtime that turns a url4 expression into a result, and the trust boundary that holds the keys.

The engine is the runtime that runs [url4](learn-url4.md) expressions. The [Client](sf-client.md) hands a url4 expression to an engine. The engine does the work: schedules the graph, reaches the providers, and streams back usage and the result. Because it sits between you and the providers, it is also the system's **trust boundary**, the one place that holds your credentials and does the grading.

You mostly will not touch it directly. The [Client](sf-client.md) talks to it for you, and the only decision that usually matters is which engine to point at.

## How it executes

At its core is a **demand-driven, memoized DAG executor**. Demand-driven means it works backwards from the result, so it only runs the nodes that result actually needs. Memoized means a value shared by several branches is computed once, not repeated: model calls are matched by a fingerprint of the route, prompt and parameters, and with the cache on a call that was made before is served from it. Independent nodes run at the same time. The first failure cancels the others rather than letting a broken run drift on. The number of calls running at once is capped so a wide fan-out can't overwhelm the providers.

The executor lives in [`packages/url4/…/dag`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4/src/url4/dag); the cloud service that wraps it, control plane, one-shot runner, and the streaming wire protocol, is [`apps/screamingface-engine`](https://github.com/ScreamingFace/screamingface/tree/main/apps/screamingface-engine).

## The trust boundary

The engine holds what must not leak. Provider credentials are handed to it once and stored encrypted at rest (AES-256-GCM) by the AI gateway's credential store, and are never returned to the Client. Benchmark cases and grading stay engine-side. The run report does return each graded case's rubric criteria and the judge that scored it, so you can see how a score was reached, but nothing about the grading can be changed from the Client. That separation is what makes a score mean something: the code being graded cannot alter the grader, and neither can the person who wrote it.

Be clear about the direction this runs, though. The boundary protects the grading and your credentials, not the content of your prompts. Whatever you put into a prompt is sent to the model provider you chose, exactly as any other API call would send it. If you are evaluating against sensitive material, that material reaches the provider.

-   **Credentials**: encrypted `credential_blobs` in the [AI gateway](https://github.com/ScreamingFace/screamingface/tree/main/apps/aigateway); the master key `AIGATEWAY_SECRET_KEY` is never stored with the data or logged.
-   **One endpoint, every provider**: the engine fans out to open and closed providers alike through the LiteLLM-based gateway, so a fusion can mix models from different vendors behind a single connection.
-   **Full usage accounting**: it streams an event for each node as the graph runs, reporting tokens, cost, and latency, so you can watch a run as it happens.

## Running one

Your own engine ships in the client package, behind the `runtime` extra. Three commands install it, fetch the benchmark data it reads from disk, and start it:

```bash
pip install "screamingface[runtime]"
screamingface prepare medxpert  # benchmark data, once
screamingface up              # engine, gateway, scoreboard on loopback
```

That serves the engine on `127.0.0.1:9108`, alongside the gateway that holds your provider keys and a local scoreboard. `screamingface status` reports each of the three, and `screamingface down` stops them. The [Installation](sf-client-installation.md) guide covers the rest, including when a local engine needs its own web-search key.

```bash
screamingface status
```

A local engine starts with the request cache on, and cache entries do not expire. `use_cache=False` on `sf.evaluate` opts one evaluation out, and [`sf.cache.pull_from_remote()`](sf-client-api-cache.md) loads the hosted community cache into it. A local engine started with `screamingface up` comes with `medxpert` ready to run, and other benchmarks can run locally too. The hosted engine serves the full set, DRACO included, with no setup. To run more benchmarks on a local engine from a repository checkout, run `just local-stack-notebooks` from `packages/screamingface/`.

Point the Client at an engine with one call. Its default is a hosted engine, so a local one is always named explicitly:

```python
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",      # the Client talks only to an Engine...
    scoreboard_url="http://127.0.0.1:9106",  # ...and the leaderboard it publishes to
)
```

The same engine runs three ways: **bundled** invisibly inside the Client and [SDK](learn-url4-sdk.md), **self-hosted** for a team that wants the whole system inside its own walls, or **hosted** for shared, subsidized capacity that we run. The cloud deployment (Kubernetes Jobs, a streaming event bus, a Helm chart) lives in [`apps/screamingface-engine`](https://github.com/ScreamingFace/screamingface/tree/main/apps/screamingface-engine). A local run needs none of it.

> The engine is not a router. A router picks one model per call. The engine composes many into a graph. It is not open compute either: hosted capacity is subsidized for chosen cohorts, and self-hosting is on your own hardware.

## Where the code lives

-   [`apps/screamingface-engine`](https://github.com/ScreamingFace/screamingface/tree/main/apps/screamingface-engine): the engine service (backend, runner, shared wire protocol).
-   [`packages/url4/…/dag`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4/src/url4/dag): the DAG executor it drives.
-   [`apps/aigateway`](https://github.com/ScreamingFace/screamingface/tree/main/apps/aigateway): the credential store and provider gateway.
