# AI gateway

Source: https://docs.screamingface.ai/learn/ai-gateway

Where your provider keys live, encrypted, and the one endpoint the engine calls to reach every model provider.

The **AI gateway** is the component that actually reaches model providers, and the place your provider credentials are stored. The [engine](learn-engine.md) never calls a provider directly and never holds a raw key: it calls the gateway, and the gateway reaches OpenRouter, Anthropic, and the rest.

## One endpoint, every provider

It is a LiteLLM-based gateway that exposes a single, OpenAI-shaped endpoint. The engine sends one request shape and the gateway routes it to the right provider, so adding a provider does not change how the engine calls out.

## Where your keys live

A key you connect is handed to the gateway once, validated, and stored **encrypted at rest** (AES-256-GCM) as credential blobs. It is never returned to the engine or the Client, and never written into your notebook. The master key that unlocks them, `AIGATEWAY_SECRET_KEY`, is never stored alongside the data and never logged, and no OS keychain is involved.

This is why the gateway is the system's credential boundary: everything above it reasons about a [connection](sf-client-guides-connections.md), its provider and status, without ever seeing the secret behind it.

## Providers are plugins

Every provider the gateway can reach is a **plugin**. Each one adapts a provider, OpenRouter, Anthropic, OpenAI, the Codex and Gemini CLIs, Hugging Face, and so on, to the gateway's single OpenAI-shaped interface, so supporting a new provider means adding a plugin, not changing the engine or the Client.

Plugins are enabled per deployment, and the set that is turned on is exactly what the engine advertises: it is the list you see when you call `sf.connect()` or [read your connections](sf-client-guides-connections.md). A route whose plugin is off never appears, so a missing provider is usually a disabled plugin rather than a bad key.

A provider's plugin can be switched off. `screamingface up` enables the OpenRouter plugin for you. If you set `AIGW_OPENROUTER_ENABLED=false`, OpenRouter no longer appears among the providers a local engine advertises, `sf.connect("openrouter", …)` raises `unknown_provider`, and an evaluation of an OpenRouter route raises `model_not_found`.

## The request cache

The gateway stores model responses keyed by the exact request and serves a repeat of that request from the store. [Caching and compute](learn-caching.md) covers what a hit saves. A local gateway has the cache on by default (`AIGW_REQUEST_CACHE_ENABLED=true`, set by `screamingface up` unless you export another value), and `use_cache=False` on an evaluation opts that run out. The gateway also stores the pinned cache of a run that captures. Rows of the hosted community cache load into the local gateway database with [`sf.cache.pull_from_remote()`](sf-client-api-cache.md).

## Running it

On a hosted engine the gateway runs for you. If you run the engine yourself, `screamingface up` starts the gateway too, with its own SQLite database in the data directory, and needs no migration step. The [Installation](sf-client-installation.md) guide has the commands.
