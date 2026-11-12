# Installation

Source: https://docs.screamingface.ai/sf-client/installation

Install the Client and point it at an engine, hosted or one you run yourself.

The **Client** is a Python library. It never calls a model provider itself, so it always needs an [engine](learn-engine.md) to talk to. Use a hosted one if your account has access, or run your own on your machine. The code you write is the same either way.

## 1 · Install the Client

You need Python **3.12 or newer**. In a notebook, install the Client with one cell:

```python
!pip install "screamingface[notebook]"
```

From a terminal, run:

```bash
uv pip install "screamingface[notebook]"
```

The `[notebook]` extra pulls in ipywidgets, so `sf.connect()` renders a live panel in whatever Jupyter frontend you already use; drop it for scripts. Everything else, including [`url4`](learn-url4.md), resolves automatically. A quick check that it worked:

```python
import screamingface as sf

len(sf.__all__)   # 105
```

## 2 · Point at an engine

**Hosted engine**

The fastest start, once your account has access. Name the hosted engine once, log in through your browser, and you are running on compute we provide. There is no local setup, and no provider key of your own: the hosted engine does not take one (bring-your-own-key is the local path). To get access, reach out to the OpenMined team. Until your account has access, use the local engine tab: after login every provider shows as unavailable and an evaluation is refused.

```python
import screamingface as sf

sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)
```

A hosted engine sits behind Cloudflare Access. There is no token to paste: `login()` collects it through your browser. In a script it opens the browser for you; in a notebook it prints a link to open.

```python
client = sf.Client(engine_url="https://fusion.screamingface.ai")
client.login()          # a script opens Cloudflare Access in your browser; a notebook prints a link to open
client.authenticated    # True once the token arrives
```

That is the whole hosted path. The [Quickstart](sf-client-first-fusion.md) takes it from here, and the [Connections](sf-client-guides-connections.md) guide covers provider access.

**Your own engine**

Everything runs on your machine, on your own keys, with no account and no login. The engine ships in the same package behind the `[runtime]` extra, so it is one more install and three commands, not a separate deployment:

```bash
pip install "screamingface[runtime,notebook]"
```

**Prepare the benchmark you will run:** The engine reads datasets from disk rather than downloading them mid-run, so a run cannot silently use a different revision. A local engine started with `screamingface up` comes with `medxpert` (2,450 questions) ready to run, a fine default to start with. The hosted engine serves the full set (DRACO, IFEval and the other leaderboard benchmarks) with no setup, and those benchmarks can run on a local engine from a repository checkout: run `just local-stack-notebooks` from `packages/screamingface/` ([just](https://github.com/casey/just) is the command runner). The pip package does not install `inspect-ai`, which those benchmarks need, so a local engine ships with `medxpert` ready out of the box.

```bash
$ screamingface prepare medxpert
Benchmark assets ready at /Users/you/.screamingface/benchmark-assets
```

**Start the stack:** One command brings up three loopback services: the engine executes runs, the gateway holds your provider keys and calls the models, and the scoreboard serves your local leaderboard.

```bash
$ screamingface up
ScreamingFace is ready.
  gateway db=sqlite:///Users/you/.screamingface/aigateway.sqlite3 · request_cache=on
  Gateway    http://127.0.0.1:9105
  Scoreboard http://127.0.0.1:9106
  Engine     http://127.0.0.1:9108
  Logs       /Users/you/.screamingface/runtime.log
  export SCREAMINGFACE_ENGINE_URL=http://127.0.0.1:9108
  export SCREAMINGFACE_SCOREBOARD_URL=http://127.0.0.1:9106
```

**Point the Client at it:** No login step: a local engine advertises none. A non-default `engine_url` requires `scoreboard_url` in the same call. With no `configure` call and no `SCREAMINGFACE_ENGINE_URL`, the Client uses a running local stack and prints `connected to the local stack at http://127.0.0.1:9108`.

```python
sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
```

From there `screamingface status` checks it, `screamingface logs` follows it, and `screamingface down` stops it. Enabling providers, web search, port conflicts, the local leaderboard, the cache and analytics are in the FAQ below.

## Frequently asked questions

The Client is installed but the engine is not. The `screamingface` command and the server stack both come from the `[runtime]` extra:

```bash
pip install "screamingface[runtime,notebook]"
```

Reopen your shell afterwards if the command still is not found.

`screamingface up` enables the OpenRouter provider for you. If you set `AIGW_OPENROUTER_ENABLED=false`, OpenRouter no longer appears in `sf.connections.list()`, `sf.connect("openrouter", ...)` raises `unknown_provider` ("The provider is not available on this SF Engine"), and an evaluation of an OpenRouter route raises `model_not_found`. Unset the variable, or set it to `true`, in the shell you start the runtime from, then run `screamingface down && screamingface up`. The gateway reads the setting at startup.

The stack defaults to 9105, 9106 and 9108, and it names the occupied ones rather than starting halfway. Run `screamingface status`: `foreign processes occupy runtime ports` means something unrelated holds them; if a previous stack is still up, `screamingface down` is enough.

If the occupant is something you would rather not kill, you do not have to free the port. Move the stack instead. Every port is overridable, either as a flag on `up` and `restart`, or as an environment variable:

```bash
# either as flags, on up and restart...
screamingface up --gateway-port 9205 --scoreboard-port 9206 --engine-port 9208

# ...or as environment variables
export SCREAMINGFACE_GATEWAY_PORT=9205
export SCREAMINGFACE_SCOREBOARD_PORT=9206
export SCREAMINGFACE_ENGINE_PORT=9208
screamingface up
```

If you move the *engine* port, point the client at the new one, next to its scoreboard (a non-default engine always needs both): `sf.configure(engine_url="http://127.0.0.1:9208", scoreboard_url=…)`.

One caveat worth knowing: the environment variables are read by `up`, `restart`, `status` and `doctor` only; `down` and `logs` ignore them. That is harmless in practice, because those two work from the runtime state recorded in your data directory rather than from a port, so they stop and tail whatever `up` started, on whichever ports it used.

Only when you run your own engine *and* a route you evaluate cannot search the web itself. Benchmarks like DRACO ask candidates to research an answer; most providers search natively and the engine just asks them to. The exception is providers with no search of their own (**Hugging Face** routes in particular), where the engine falls back to a bounded tool loop it runs against Tavily. A hosted engine supplies its own key; benchmarks that never search, such as `medxpert`, need none.

Export it before `up`, in the shell you start the runtime from:

```bash
export TAVILY_API_KEY="tvly-..."
screamingface up
```

Without the key, web tools stay off by default: a candidate whose route depends on the Tavily loop fails before its first paid request rather than quietly answering a research question with no research behind it.

`sf.configure(engine_url=...)` with a non-default engine raises `ValueError` unless `scoreboard_url` is passed too, and `SCREAMINGFACE_ENGINE_URL` requires `SCREAMINGFACE_SCOREBOARD_URL`. The pair decides where `sf.leaderboards.submit` publishes. Pass the local scoreboard to keep scores local:

```python
sf.configure(engine_url="http://127.0.0.1:9108", scoreboard_url="http://127.0.0.1:9106")
```

Pass `scoreboard_url="https://leaderboard.screamingface.ai"` to publish to the hosted leaderboard from a local engine. Submitting there needs a Cloudflare Access login, and access is granted by the OpenMined team.

`screamingface up` starts the gateway with `request_cache=on`: a model call that was made before with the same route, prompt and parameters is answered from the local cache. Pass `use_cache=False` to `sf.evaluate` to opt one run out, or export `AIGW_REQUEST_CACHE_ENABLED=false` before `screamingface up` to turn the cache off. The cache starts empty. To start from the community cache, pull it into the local gateway; the pull signs in to the hosted engine, which needs an account with access:

```bash
$ screamingface cache pull --model openrouter/anthropic/claude-opus-4.8
```

`sf.cache.pull_from_remote()` does the same from Python and returns a `PullResult`. `--model` repeats to limit the pull to those models.

Analytics are on by default. The first `import screamingface` prints a notice and saves the choice `accepted`. `screamingface analytics status` and `sf.analytics.status()` report the choice; `enable`, `disable` and `reset_identifier` change it, and `sf.analytics.disable()` turns analytics off. A non-empty `DO_NOT_TRACK` value other than `0`, `false`, `no` or `off` disables analytics for the process, and the first import then prints no notice and saves nothing.

```bash
$ screamingface analytics status
{"choice": "accepted", "enabled": true, "scope": "installation", "installation_id": "e368e2f6-68a0-4824-9c92-79388a95398f"}
```

```python
sf.analytics.status()
# {'choice': 'accepted', 'enabled': True, 'scope': 'installation', 'installation_id': 'cfcae993-e908-4513-8e01-7d1f3822031c'}
```

A macOS Python without a CA bundle, so the dataset download cannot verify TLS. Point that one command at certifi's bundle:

```bash
SSL_CERT_FILE=$(python -c "import certifi;print(certifi.where())") \
  screamingface prepare medxpert
```

Not if your account has hosted access: the hosted engine skips the local setup entirely. Without access, run your own. A local engine puts the whole stack on your own machine, on your own keys.
