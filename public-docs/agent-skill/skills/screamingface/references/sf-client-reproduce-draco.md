# Reproduce OpenRouter's DRACO results

Source: https://docs.screamingface.ai/sf-client/reproduce-draco

Run a DRACO subset end to end to compare fusions with its solo models.

By the end, you'll have a scored comparison of **four recipes**: three solo models and one fusion built from them, all on one case (`limit=1`). On the hosted engine the case comes from [DRACO](https://arxiv.org/abs/2602.11685) and each answer is judged three times. On a local engine the case comes from `medxpert`, graded by exact match with no judge.

> You'll need the [ScreamingFace Engine](learn-engine.md) running and an OpenRouter connection first. See [Installation](sf-client-installation.md). Every model below is an OpenRouter route, so one connection covers everything. DRACO runs on the hosted engine, which needs an account with access. On a local engine, `medxpert` is ready by default, so with a local engine run the same steps on `medxpert`.

## 1 · Configure the engine

The [**ScreamingFace Engine**](learn-engine.md) is a separate process that grades the benchmarks and calls the models on your behalf. On a local engine it holds your provider credentials; on the hosted engine the operator manages them. The Client hands all of that work to the engine, so this first step tells the Client where to find it.

```python
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
```

`sf.configure()` validates and stores the URLs without making a network request. The example above points at a **local engine** on `http://127.0.0.1:9108` and its leaderboard on `http://127.0.0.1:9106`, so local scores stay local. A non-default `engine_url` requires `scoreboard_url`; `configure` raises `ValueError` without it. To run one yourself, install the `[runtime]` extra and start the stack with `screamingface up`. The [Installation](sf-client-installation.md) guide walks through that end to end.

To use the **hosted ScreamingFace engine** instead, name it: the Client's default engine is the hosted one, `https://fusion.screamingface.ai`, and its leaderboard is `https://leaderboard.screamingface.ai`. With no `configure` call and a local stack running, the Client uses the local stack instead and prints `connected to the local stack at http://127.0.0.1:9108`. Hosted access is granted by the OpenMined team, so reach out to them before it will run evaluations for your account.

**If the engine isn't reachable**, the first call that needs it will raise `EngineUnavailableError`. You can check a local one beforehand with `curl http://127.0.0.1:9108/healthz`. Provider connection calls require HTTPS outside loopback.

## 2 · Connect a provider

**On the hosted engine** there is nothing to connect: `sf.connect()` shows a panel with a Log in button, and after login every provider the OpenMined team has enabled for your account shows as connected. A provider that is not enabled shows as unavailable. **On a local engine** the engine holds your credentials, and you need at least one provider connected before you can call a model. `sf.connect()` with no arguments shows a panel of every provider the engine supports. The example below connects **OpenRouter** with an API key on a local engine, walking through all six states of the auth flow.

```python
sf.connect()
```

Connecting a provider

1 / 6

### Provider connections

Engine · http://127.0.0.1:9108

-   Anthropic
    
    NOT CONNECTED
-   Antigravity
    
    NOT CONNECTED
-   Codex
    
    NOT CONNECTED
-   Gemini CLI
    
    NOT CONNECTED
-   Hugging Face
    
    NOT CONNECTED
-   OpenAI
    
    NOT CONNECTED
-   OpenRouter
    
    NOT CONNECTED

Every provider the engine advertises, with its live status. Nothing is connected yet.

> You'll need the [ScreamingFace Engine](learn-engine.md) running and an OpenRouter connection first. See [Installation](sf-client-installation.md). Every model below is an OpenRouter route, so one connection covers everything. DRACO runs on the hosted engine, which needs an account with access. On a local engine, `medxpert` is ready by default, so with a local engine run the same steps on `medxpert`.

## 1 · Configure the engine

The [**ScreamingFace Engine**](learn-engine.md) is a separate process that grades the benchmarks and calls the models on your behalf. On a local engine it holds your provider credentials; on the hosted engine the operator manages them. The Client hands all of that work to the engine, so this first step tells the Client where to find it.

```python
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
```

`sf.configure()` validates and stores the URLs without making a network request. The example above points at a **local engine** on `http://127.0.0.1:9108` and its leaderboard on `http://127.0.0.1:9106`, so local scores stay local. A non-default `engine_url` requires `scoreboard_url`; `configure` raises `ValueError` without it. To run one yourself, install the `[runtime]` extra and start the stack with `screamingface up`. The [Installation](sf-client-installation.md) guide walks through that end to end.

To use the **hosted ScreamingFace engine** instead, name it: the Client's default engine is the hosted one, `https://fusion.screamingface.ai`, and its leaderboard is `https://leaderboard.screamingface.ai`. With no `configure` call and a local stack running, the Client uses the local stack instead and prints `connected to the local stack at http://127.0.0.1:9108`. Hosted access is granted by the OpenMined team, so reach out to them before it will run evaluations for your account.

**If the engine isn't reachable**, the first call that needs it will raise `EngineUnavailableError`. You can check a local one beforehand with `curl http://127.0.0.1:9108/healthz`. Provider connection calls require HTTPS outside loopback.

## 2 · Connect a provider

**On the hosted engine** there is nothing to connect: `sf.connect()` shows a panel with a Log in button, and after login every provider the OpenMined team has enabled for your account shows as connected. A provider that is not enabled shows as unavailable. **On a local engine** the engine holds your credentials, and you need at least one provider connected before you can call a model. `sf.connect()` with no arguments shows a panel of every provider the engine supports. The example below connects **OpenRouter** with an API key on a local engine, walking through all six states of the auth flow.

```python
sf.connect()
```

Connecting a provider

1 / 6

### Provider connections

Engine · http://127.0.0.1:9108

-   Anthropic
    
    NOT CONNECTED
-   Antigravity
    
    NOT CONNECTED
-   Codex
    
    NOT CONNECTED
-   Gemini CLI
    
    NOT CONNECTED
-   Hugging Face
    
    NOT CONNECTED
-   OpenAI
    
    NOT CONNECTED
-   OpenRouter
    
    NOT CONNECTED

Every provider the engine advertises, with its live status. Nothing is connected yet.

### Reading the panel

Each row shows one provider: its display name, **live status**, and what you can do. On a local engine the status is one of `not connected`, `pending`, `connected`, `needs reauth` or `error`. On the hosted engine it is `Connected` or `Unavailable`, with no buttons, because a hosted engine takes no keys of its own. The header shows which engine you're talking to, so you won't accidentally send a key to the wrong one.

> We're using OpenRouter here for simplicity, but you can build fusions with models from any of the providers listed above. One caveat: **caching covers OpenRouter, Anthropic, OpenAI and Hugging Face routes**, so runs on Codex, Gemini CLI and Antigravity aren't reused.

### Configure OpenRouter via script

Scripts skip the panel by naming the provider and passing the key directly. Pull the key from the environment instead of hardcoding it.

```python
import os

sf.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])
sf.connections.list()        # the same status the panel shows
sf.disconnect("openrouter")  # remove it again
```

`sf.connect(...)` returns a `Connection` with validated status, so a bad key fails right here, not later during evaluation. `sf.connections.list()` gives you one per provider (same data the panel shows), and on a local engine `sf.disconnect(...)` is safe to call even if you've never connected. A hosted engine refuses both `connect` with a key and `disconnect`.

The panel states, the OAuth flow for Codex, Antigravity, Anthropic and Gemini CLI, and the hosted engine's read-only connections are in the [Connections guide](sf-client-guides-connections.md) and the [Connections reference](sf-client-api-connections.md).

## 3 · Compose the candidates

A **candidate** is anything you are submitting to be scored, whether that is a single model or a fusion.

-   `sf.Model`: one configured call (route, prompt, parameters). On its own, it's a solo candidate.
-   `sf.Fanout(...) >> sf.Synthesize(...)`: a fusion. `sf.Fanout` sends the question to several members. `sf.Synthesize` adds an explicit **synthesizer**. Here, the synthesizer is another model that combines the members' answers into one.

```python
ANSWER = "Answer this research prompt thoroughly, in prose, with specific evidence."
SYNTHESIS = "Combine the panel's answers into one unified prose answer. Add no new facts."

opus = sf.Model("openrouter/anthropic/claude-opus-4.8", prompt=ANSWER)
gpt = sf.Model("openrouter/openai/gpt-5.5", prompt=ANSWER)
gemini = sf.Model("openrouter/google/gemini-3.1-pro-preview", prompt=ANSWER, params={"max_tokens": 8192})

frontier_trio = sf.Fanout([opus, gpt, gemini], name="frontier-trio") >> sf.Synthesize(
    sf.Model(
        "openrouter/anthropic/claude-opus-4.8",
        prompt=SYNTHESIS,
        params={"max_tokens": 8192},
    )
)

candidates = [opus, gpt, gemini, frontier_trio]   # 3 solo models and 1 fusion
```

`frontier_trio` fuses the three frontier models. Its score next to each solo model shows whether adding models helps on this case.

### The request cache

With the cache on, a model call that was made before is served from the cache instead of being paid for again. Calls are matched by route, prompt and parameters, not by model object, so **an identical call is served from the cache**. Cache entries do not expire.

A local engine starts with the cache on and empty. `evaluate(..., use_cache=False)` opts one run out, and `export AIGW_REQUEST_CACHE_ENABLED=false` before `screamingface up` turns it off. `sf.cache.pull_from_remote()` copies the community cache into a local engine. On the hosted engine the cache is shared across the community: if anyone has already run that model config against a benchmark, you get a cache hit at no cost.

## 4 · Look up the benchmark

Benchmarks live on the engine, not in the Client. Fetching one returns its identity and the protocol revision it is pinned to, so you can see what you are about to be graded against before spending anything. This call is free. It needs an engine that serves the benchmark: the hosted engine serves `draco-3pass`, and a local engine started with `screamingface up` comes with `medxpert` ready to run. To run more benchmarks on a local engine from a repository checkout, run `just local-stack-notebooks` from `packages/screamingface/`.

```python
draco = sf.benchmarks.get("draco-3pass")
draco.title, draco.revision, draco.case_count
```

On a local engine, look up `medxpert`:

```python
medxpert = sf.benchmarks.get("medxpert")
medxpert.title, medxpert.revision, medxpert.case_count
```

```
('MedXpertQA', '1e5a3b8a461a52f7', 2450)
```

It does **not** download the actual questions. Cases are loaded engine-side at eval time.

`sf.benchmarks.list()` shows what this engine has. The hosted engine lists `draco` and `draco-3pass` among its benchmarks. On a local engine, `medxpert` is ready by default, so on a local engine run this tutorial on `medxpert`.

`draco-3pass` runs the same 100-case dataset and rubric as the canonical `draco` board, judging each answer three times instead of five. Passing `limit=1` pins this tutorial to a single case. The `medxpert` run below cost $0.717229 for the four candidates.

## 5 · Evaluate

One call sends all four candidates as a **single request**. The benchmark id is passed here rather than to the lookup above, because the lookup was only for reading the protocol.

```python
report = sf.evaluate(candidates, benchmark="draco-3pass", limit=1)
```

On a local engine started with `screamingface up`, use `medxpert`, which is ready by default:

```python
report = sf.evaluate(candidates, benchmark="medxpert", limit=1)
```

Before the first model call, the Client checks the whole plan: that the benchmark agrees with what the engine has, that every model route exists in the catalog, and that each candidate compiles. Anything wrong with the plan raises `PlanningError`, which names the specific problem in its message; a provider that is not connected raises `ProviderConnectionError` instead. All of this happens before anything is spent.

> **This step costs money.** Each candidate answers the case once. On DRACO a judge model then grades each answer three or five times; `medxpert` has no judge. Read `report.usage.cost_usd` after a run before you scale it up. `draco-3pass` at all 100 cases, or the five-pass `draco`, costs far more than one case.

If a model fails, only the candidates using it are affected, and the rest still score. A failure lowers that candidate's coverage instead of counting as zero, so a partial result looks partial. `evaluate` still returns a report, so check it before you read the scores:

```python
report.ok          # False if any candidate or member failed
report.failures    # what failed, and why
```

With the cache on, a repeated call that already succeeded is served from the cache. A call whose input changed, such as the second turn of a `medxpert` case, is paid again.

## 6 · Read the study

The report lists each candidate in the order you declared them, with its score and coverage.

On the local run above, each candidate's score:

```python
{c.name: c.score for c in report.candidates}
```

```
{'claude-opus-4.8': 0.0, 'gpt-5.5': 1.0, 'gemini-3.1-pro-preview': 1.0, 'frontier-trio': 1.0}
```

### What the columns mean

-   **Score**: The candidate's benchmark score. On DRACO a case is judged against a fixed set of criteria, so values land on a coarse grid instead of anywhere in 0 to 100%. On `medxpert` the score is the fraction of cases answered correctly.
-   **Coverage**: How much of the case set produced a grade. Below 100% means something failed, and the score then covers only what completed.

### Reading it in code

-   `report.candidates["frontier-trio"].score`: one candidate's score.
-   `max(report.candidates, key=lambda c: c.score or 0)`: the top scorer. Check `report.ok` first, because a failed candidate has a score of `None` and counts as 0 here. There is no `best` field, because picking a winner is a judgement about your own experiment rather than something the report should decide.
-   `len(report.candidates["frontier-trio"].cases)` against `report.case_count`: how many cases produced a result, next to how many ran.
-   `report.candidates["frontier-trio"].url4`: that candidate's expression. The url4 belongs to a candidate, not to the report, since each one compiled separately.
-   `report.to_dict()`: everything above as plain JSON-compatible values.

> **Don't over-read a single run.** One case is an integration check, not a measurement. Run it twice and the winner may change. Treat the result as a shape worth exploring rather than a finding.

## What the full benchmark shows

The real claim is demonstrated on all 100 DRACO tasks, not this one-case sample. These are published figures rather than output from the code above, so your own numbers will differ. The live `draco-3pass` board lists 15 entries, and its top score is 68.69%. Live scores are on the [leaderboard](https://leaderboard.screamingface.ai/benchmark.html?id=draco-3pass).

### Published DRACO result

draco · 100 tasks

COMPLETE·13/16 CANDIDATES SCORED

Score by candidate+8 MORE

-   Fable 5 + GPT-5.5100/100 cases
    
    100%coverage
    
    68.6%BEST
    
-   Opus + GPT-5.5 + DeepSeek100/100 cases
    
    100%coverage
    
    67.0%
    
-   Opus 4.8 + GPT-5.5 + Gemini 3.1 Pro100/100 cases
    
    100%coverage
    
    65.7%
    
-   Opus 4.8 + GPT-5.5100/100 cases
    
    100%coverage
    
    64.2%
    
-   DeepSeek + Kimi + GPT-5.5100/100 cases
    
    100%coverage
    
    61.9%
    
-   GPT-5.5 (solo)100/100 cases
    
    100%coverage
    
    60.2%
    
-   Opus 4.8 + Opus 4.8100/100 cases
    
    100%coverage
    
    58.5%
    
-   Gemini 3 Flash + Kimi + DeepSeek100/100 cases
    
    100%coverage
    
    58.5%
    

The best fusion beat the best solo model by **8.4 points**, and five different fusions beat every individual model. Three solo models didn't finish every task (Gemini 3.1 Pro only completed 47 of 100), so their scores are averages over completed tasks and aren't directly comparable. Full chart and method: [published results](https://andrewtrask.substack.com/p/6-weeks-ago-frontier-ai-labs-lost).
