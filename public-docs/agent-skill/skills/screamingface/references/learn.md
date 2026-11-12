# Architecture

Source: https://docs.screamingface.ai/learn

How the pieces fit (url4 the protocol, the engine that runs it, and the surfaces you compose from) and where each one lives in the codebase.

ScreamingFace is a small stack built around one idea: describe an entire AI system as a single [**url4**](learn-url4.md) expression, run it behind a trust boundary, and hand anyone that same expression to run it again. This page shows how the pieces fit and where each lives in the [codebase](https://github.com/ScreamingFace/screamingface/tree/main).

## The layers

-   [**url4:**](learn-url4.md) The protocol is one line naming some sources and an intent, which compiles to a typed graph of operations. It can fetch data, call models, run code, fan those out, and reduce the results to one answer. A source can itself be another url4, so expressions nest into arbitrarily large systems. This is the artifact everything else passes around.
-   [**The engine:**](learn-engine.md) It is the runtime and trust boundary, and it runs a url4 expression: it schedules the graph, sends each model call out to a provider, and streams back tokens, cost, and the result. It holds the provider credentials, so the Client never sees them.
-   [**The AI gateway:**](learn-ai-gateway.md) It is a LiteLLM-based gateway the engine calls to reach every provider through one OpenAI-shaped endpoint. It stores provider credentials encrypted at rest.
-   [**The Client:**](sf-client.md) It is the Python library researchers use. It composes fusions and benchmarks and talks only to an engine, never to a provider directly.
-   [**The Leaderboard:**](learn-leaderboard.md) It is where results go public. Each entry says whether the hosted engine ran it, and keeps the url4 that produced it, so a rank can always be checked. The board itself is at [leaderboard.screamingface.ai](https://leaderboard.screamingface.ai).

## How a request flows

A run always follows the same path. The Client compiles what you built into a url4 expression and sends it to an engine. The engine runs the expression as a graph, with independent nodes running in parallel, and sends each model call out through the AI gateway to the provider. Usage and results stream back as the graph runs. Replay the same expression and the whole system runs again.

There are two ways to run, and only the engine URL changes. A **local** engine runs on your own machine, on your own keys, with its own cache (on by default).

[Diagram: Local request flow: the Client drives an engine on your own machine, which fans model calls out through the gateway to the providers you hold keys for; its cache accumulates and can pull from the shared community cache, and the engine submits a verifiable result to the public leaderboard.]

**Local.** The Client drives an engine on your own machine; model calls fan out through the gateway to the providers you hold keys for. Its cache accumulates across runs and can pull from the shared community cache, and the engine submits a verifiable result to the public leaderboard.

A **hosted** engine, one we operate, runs the identical protocol but adds the [shared community cache](learn-caching.md) and subsidized compute for chosen cohorts, so a call already in the shared cache is a cache hit rather than a new provider call.

[Diagram: Hosted request flow: the Client on your machine reaches a ScreamingFace-run engine and gateway in the cloud that call providers on subsidised tokens; the shared community cache grows with every run, and the engine submits a verifiable result to the public leaderboard.]

**Cloud.** The Client reaches a ScreamingFace-run engine and gateway in the cloud that call providers on subsidised tokens, so you need no keys of your own. The cache is shared across the community and grows with every run.

## The trust boundary

Provider credentials live behind the engine and gateway, never in the Client. A key is handed to the engine once, stored encrypted (AES-256-GCM), and used to reach providers on your behalf. The Client keeps none. In an evaluation, the benchmark prompts go out to the models, and the grading stays engine-side: the report returns each graded case's rubric criteria and judge, but nothing about the grading can be changed from the Client. That is what makes a verified result mean something. The credential store is the [AI gateway](https://github.com/ScreamingFace/screamingface/tree/main/apps/aigateway)'s encrypted `credential_blobs`; the master key (`AIGATEWAY_SECRET_KEY`) is never stored with the data or logged.

## Where the code lives

| Component | Path |
| --- | --- |
| url4: the protocol | [`packages/url4`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4) |
| engine: the cloud service | [`apps/screamingface-engine`](https://github.com/ScreamingFace/screamingface/tree/main/apps/screamingface-engine) |
| engine: the DAG executor | [`packages/url4/src/url4/dag`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4/src/url4/dag) |
| AI gateway | [`apps/aigateway`](https://github.com/ScreamingFace/screamingface/tree/main/apps/aigateway) |
| Client: the Python library | [`packages/screamingface`](https://github.com/ScreamingFace/screamingface/tree/main/packages/screamingface) |
| Leaderboard | [`apps/scoreboard`](https://github.com/ScreamingFace/screamingface/tree/main/apps/scoreboard) |
