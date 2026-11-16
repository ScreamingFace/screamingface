---
name: screamingface
description: Use when writing, running or debugging Python code that imports `screamingface` (`import screamingface as sf`). Covers composing fusions with `sf.Fanout`, `sf.Synthesize` and the reducers, evaluating them on a benchmark, connecting providers, reading reports and costs, and sharing a run as a url4. Generated from the ScreamingFace Client docs, version 0.1.12.
---

# ScreamingFace Client

`screamingface` is the Python library of the ScreamingFace Client. You compose models into a fusion, evaluate it on a benchmark, and read the score and the cost.

Docs version: 0.1.12. This skill is generated from https://docs.screamingface.ai. The index below links to each docs page and to its sections. Every page is also served as Markdown: add `.md` to its address.

## Before you write code

- Python 3.12 or newer. In a notebook, `!pip install "screamingface[notebook]"`. From a terminal, `uv pip install "screamingface[notebook]"`. The `[runtime]` extra adds the local engine. See [Installation](https://docs.screamingface.ai/sf-client/installation).
- The Client never calls a model provider itself. It needs an engine: a hosted one (access is granted by the OpenMined team) or one on your own machine, started with `screamingface up`, which uses your own provider keys.
- A local engine started with `screamingface up` serves one benchmark, `medxpert`. The hosted engine serves the others.
- On a hosted engine, log in with `client.login()` on a `sf.Client(engine_url=...)`. See [Installation](https://docs.screamingface.ai/sf-client/installation) and [Connections](https://docs.screamingface.ai/sf-client/guides/connections).

## Rules

1. Build a fusion as a chain: `sf.Fanout([model_a, model_b]) >> sf.Synthesize("provider/model")`. A reducer such as `sf.Vote()` can end the block in place of `sf.Synthesize`. See [Fusions](https://docs.screamingface.ai/sf-client/guides/fusions) and [Reducers](https://docs.screamingface.ai/sf-client/api/reducers).
2. Pass `benchmark=` to every `sf.evaluate` call. It has no default. Use `limit=` while you iterate: it caps the case count and is the main cost control. See [Running an evaluation](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation).
3. A run is paid on your own provider keys when you use a local engine. Read the cost from `report.usage.cost_usd`. See [Usage](https://docs.screamingface.ai/sf-client/api/usage).
4. Use only names in `sf.__all__`. [The sf namespace](https://docs.screamingface.ai/sf-client/api/modules) lists the modules, and the API reference pages in the index list every public name.
5. Read an error by its code. [Errors](https://docs.screamingface.ai/sf-client/api/errors) lists the classes and the codes.

## Index

### Overview

- [Overview](https://docs.screamingface.ai/sf-client): Open infrastructure for composing, measuring and sharing model fusions.
  - [What the Client and Leaderboard provide](https://docs.screamingface.ai/sf-client#what-the-client-and-leaderboard-provide)
  - [How it works](https://docs.screamingface.ai/sf-client#how-it-works)
  - [Two ways to run](https://docs.screamingface.ai/sf-client#two-ways-to-run)
  - [The smallest example](https://docs.screamingface.ai/sf-client#the-smallest-example)

### Tutorials

- [Installation](https://docs.screamingface.ai/sf-client/installation): Install the Client and point it at an engine, hosted or one you run yourself.
  - [1 · Install the Client](https://docs.screamingface.ai/sf-client/installation#1-install-the-client)
  - [2 · Point at an engine](https://docs.screamingface.ai/sf-client/installation#2-point-at-an-engine)
  - [Frequently asked questions](https://docs.screamingface.ai/sf-client/installation#frequently-asked-questions)
- [Your first fusion](https://docs.screamingface.ai/sf-client/first-fusion): Combine two models into one, run it on a benchmark, and read the score.
  - [1 · Import the library](https://docs.screamingface.ai/sf-client/first-fusion#1-import-the-library)
  - [2 · Connect to an engine](https://docs.screamingface.ai/sf-client/first-fusion#2-connect-to-an-engine)
  - [3 · Build the fusion](https://docs.screamingface.ai/sf-client/first-fusion#3-build-the-fusion)
  - [4 · Run it](https://docs.screamingface.ai/sf-client/first-fusion#4-run-it)
  - [5 · Read the score](https://docs.screamingface.ai/sf-client/first-fusion#5-read-the-score)
  - [How far this goes](https://docs.screamingface.ai/sf-client/first-fusion#how-far-this-goes)
  - [Where to go next](https://docs.screamingface.ai/sf-client/first-fusion#where-to-go-next)
- [Reproduce OpenRouter's DRACO results](https://docs.screamingface.ai/sf-client/reproduce-draco): Run a DRACO subset end to end to compare fusions with its solo models.
  - [1 · Configure the engine](https://docs.screamingface.ai/sf-client/reproduce-draco#1-configure-the-engine)
  - [2 · Connect a provider](https://docs.screamingface.ai/sf-client/reproduce-draco#2-connect-a-provider)
  - [1 · Configure the engine](https://docs.screamingface.ai/sf-client/reproduce-draco#1-configure-the-engine-2)
  - [2 · Connect a provider](https://docs.screamingface.ai/sf-client/reproduce-draco#2-connect-a-provider-2)
  - [Reading the panel](https://docs.screamingface.ai/sf-client/reproduce-draco#reading-the-panel)
  - [Configure OpenRouter via script](https://docs.screamingface.ai/sf-client/reproduce-draco#configure-openrouter-via-script)
  - [3 · Compose the candidates](https://docs.screamingface.ai/sf-client/reproduce-draco#3-compose-the-candidates)
  - [The request cache](https://docs.screamingface.ai/sf-client/reproduce-draco#the-request-cache)
  - [4 · Look up the benchmark](https://docs.screamingface.ai/sf-client/reproduce-draco#4-look-up-the-benchmark)
  - [5 · Evaluate](https://docs.screamingface.ai/sf-client/reproduce-draco#5-evaluate)
  - [6 · Read the study](https://docs.screamingface.ai/sf-client/reproduce-draco#6-read-the-study)
  - [What the columns mean](https://docs.screamingface.ai/sf-client/reproduce-draco#what-the-columns-mean)
  - [Reading it in code](https://docs.screamingface.ai/sf-client/reproduce-draco#reading-it-in-code)
  - [What the full benchmark shows](https://docs.screamingface.ai/sf-client/reproduce-draco#what-the-full-benchmark-shows)

### How-to guides

- [Connections](https://docs.screamingface.ai/sf-client/guides/connections): Connect a model provider through the engine, and log in to a hosted one.
  - [What you can do with it](https://docs.screamingface.ai/sf-client/guides/connections#what-you-can-do-with-it)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/connections#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/connections#how-to)
  - [1 · Configure engine](https://docs.screamingface.ai/sf-client/guides/connections#1-configure-engine)
  - [2 · Connect from a notebook](https://docs.screamingface.ai/sf-client/guides/connections#2-connect-from-a-notebook)
  - [3 · Connect from a script](https://docs.screamingface.ai/sf-client/guides/connections#3-connect-from-a-script)
  - [4 · Read the current state](https://docs.screamingface.ai/sf-client/guides/connections#4-read-the-current-state)
  - [5 · Disconnect](https://docs.screamingface.ai/sf-client/guides/connections#5-disconnect)
  - [What a connection carries](https://docs.screamingface.ai/sf-client/guides/connections#what-a-connection-carries)
  - [When it fails](https://docs.screamingface.ai/sf-client/guides/connections#when-it-fails)
  - [Links](https://docs.screamingface.ai/sf-client/guides/connections#links)
- [Models](https://docs.screamingface.ai/sf-client/guides/models): Select a model route and set the answer policy a candidate owns.
  - [What you can do with it](https://docs.screamingface.ai/sf-client/guides/models#what-you-can-do-with-it)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/models#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/models#how-to)
  - [1 · Select a route](https://docs.screamingface.ai/sf-client/guides/models#1-select-a-route)
  - [2 · Name an independent sample](https://docs.screamingface.ai/sf-client/guides/models#2-name-an-independent-sample)
  - [3 · Override the answer policy](https://docs.screamingface.ai/sf-client/guides/models#3-override-the-answer-policy)
  - [4 · See what the engine can reach](https://docs.screamingface.ai/sf-client/guides/models#4-see-what-the-engine-can-reach)
  - [5 · Check that a route accepts your policy](https://docs.screamingface.ai/sf-client/guides/models#5-check-that-a-route-accepts-your-policy)
  - [6 · Discover a route's parameters](https://docs.screamingface.ai/sf-client/guides/models#6-discover-a-routes-parameters)
  - [Links](https://docs.screamingface.ai/sf-client/guides/models#links)
- [Map-reduce for fusions](https://docs.screamingface.ai/sf-client/guides/map-reduce): A fusion can dispatch a question to its member models, then map, filter and reduce what comes back into the one answer a benchmark grades. This page covers each stage and the signals that pass between them.
  - [The four stages at a glance](https://docs.screamingface.ai/sf-client/guides/map-reduce#the-four-stages-at-a-glance)
  - [Dispatch: fan out to a panel](https://docs.screamingface.ai/sf-client/guides/map-reduce#dispatch)
  - [Reduce: collapse to one answer](https://docs.screamingface.ai/sf-client/guides/map-reduce#reduce)
  - [Choosing a reducer](https://docs.screamingface.ai/sf-client/guides/map-reduce#choosing-a-reducer)
  - [Map: score each answer](https://docs.screamingface.ai/sf-client/guides/map-reduce#map)
  - [Available signals](https://docs.screamingface.ai/sf-client/guides/map-reduce#available-signals)
  - [Reading a signal](https://docs.screamingface.ai/sf-client/guides/map-reduce#reading-a-signal)
  - [Signals in practice](https://docs.screamingface.ai/sf-client/guides/map-reduce#signals-in-practice)
  - [Putting it together: a judged fusion](https://docs.screamingface.ai/sf-client/guides/map-reduce#putting-it-together-a-judged-fusion)
  - [Filter: drop answers before reducing](https://docs.screamingface.ai/sf-client/guides/map-reduce#filter)
  - [Other ways to dispatch](https://docs.screamingface.ai/sf-client/guides/map-reduce#other-ways-to-dispatch)
  - [See also](https://docs.screamingface.ai/sf-client/guides/map-reduce#see-also)
- [Fanout fusion](https://docs.screamingface.ai/sf-client/guides/fusions): Combine members into one answer through a synthesizer.
  - [What you can do](https://docs.screamingface.ai/sf-client/guides/fusions#what-you-can-do)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/fusions#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/fusions#how-to)
  - [1 · Combine two models](https://docs.screamingface.ai/sf-client/guides/fusions#1-combine-two-models)
  - [2 · Read the resolved name](https://docs.screamingface.ai/sf-client/guides/fusions#2-read-the-resolved-name)
  - [3 · Choose the synthesizer](https://docs.screamingface.ai/sf-client/guides/fusions#3-choose-the-synthesizer)
  - [4 · Nest a fusion](https://docs.screamingface.ai/sf-client/guides/fusions#4-nest-a-fusion)
  - [5 · Handle partial grading failures](https://docs.screamingface.ai/sf-client/guides/fusions#5-handle-partial-grading-failures)
  - [6 · Use the sf.Fusion shortcut](https://docs.screamingface.ai/sf-client/guides/fusions#6-use-the-sffusion-shortcut)
  - [The building blocks](https://docs.screamingface.ai/sf-client/guides/fusions#the-building-blocks)
  - [sf.Fanout](https://docs.screamingface.ai/sf-client/guides/fusions#sffanout)
  - [sf.Synthesize](https://docs.screamingface.ai/sf-client/guides/fusions#sfsynthesize)
  - [Attributes](https://docs.screamingface.ai/sf-client/guides/fusions#attributes)
  - [Raises](https://docs.screamingface.ai/sf-client/guides/fusions#raises)
  - [Links](https://docs.screamingface.ai/sf-client/guides/fusions#links)
- [Pipelines](https://docs.screamingface.ai/sf-client/guides/pipelines): Chain recipes in series, so each stage refines the previous stage's answer.
  - [What you can do](https://docs.screamingface.ai/sf-client/guides/pipelines#what-you-can-do)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/pipelines#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/pipelines#how-to)
  - [1 · Chain two recipes](https://docs.screamingface.ai/sf-client/guides/pipelines#1-chain-two-recipes)
  - [2 · Build the same chain with >>](https://docs.screamingface.ai/sf-client/guides/pipelines#2-build-the-same-chain-with-)
  - [3 · Flatten vs. nest](https://docs.screamingface.ai/sf-client/guides/pipelines#3-flatten-vs-nest)
  - [4 · Compose recursively](https://docs.screamingface.ai/sf-client/guides/pipelines#4-compose-recursively)
  - [5 · Mix recipe types as stages](https://docs.screamingface.ai/sf-client/guides/pipelines#5-mix-recipe-types-as-stages)
  - [The Pipeline class](https://docs.screamingface.ai/sf-client/guides/pipelines#the-pipeline-class)
  - [Parameters](https://docs.screamingface.ai/sf-client/guides/pipelines#parameters)
  - [Attributes](https://docs.screamingface.ai/sf-client/guides/pipelines#attributes)
  - [Raises](https://docs.screamingface.ai/sf-client/guides/pipelines#raises)
  - [Links](https://docs.screamingface.ai/sf-client/guides/pipelines#links)
- [Benchmarks](https://docs.screamingface.ai/sf-client/guides/benchmarks): Discover the benchmarks an engine publishes and pick the protocol you want to run.
  - [What you can do with it](https://docs.screamingface.ai/sf-client/guides/benchmarks#what-you-can-do-with-it)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/benchmarks#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/benchmarks#how-to)
  - [1 · See what this engine publishes](https://docs.screamingface.ai/sf-client/guides/benchmarks#1-see-what-this-engine-publishes)
  - [2 · Read the identity card](https://docs.screamingface.ai/sf-client/guides/benchmarks#2-read-the-identity-card)
  - [3 · Know what discovery will not tell you](https://docs.screamingface.ai/sf-client/guides/benchmarks#3-know-what-discovery-will-not-tell-you)
  - [Links](https://docs.screamingface.ai/sf-client/guides/benchmarks#links)
- [Running an evaluation](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation): Evaluate one or many candidates against a benchmark and get one Report.
  - [What you can do](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#what-you-can-do)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#how-to)
  - [1 · Evaluate one candidate](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#1-evaluate-one-candidate)
  - [2 · Read the score](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#2-read-the-score)
  - [3 · Evaluate several at once](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#3-evaluate-several-at-once)
  - [4 · Read what it cost](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#4-read-what-it-cost)
  - [5 · Watch a run](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#5-watch-a-run)
  - [6 · Point at the engine](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#6-point-at-the-engine)
  - [7 · Reopen a saved report](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#7-reopen-a-saved-report)
  - [8 · Run chosen cases](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#8-run-chosen-cases)
  - [When it fails](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#when-it-fails)
  - [Links](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation#links)
- [Using the community's cache](https://docs.screamingface.ai/sf-client/guides/community-cache): Pull the hosted community cache into a local engine, so your local runs answer calls the community has already made, for free.
  - [Before you start](https://docs.screamingface.ai/sf-client/guides/community-cache#before-you-start)
  - [1 · Start the local engine](https://docs.screamingface.ai/sf-client/guides/community-cache#1-start-the-local-engine)
  - [2 · Pull the cache for your models](https://docs.screamingface.ai/sf-client/guides/community-cache#2-pull-the-cache-for-your-models)
  - [3 · Check the result](https://docs.screamingface.ai/sf-client/guides/community-cache#3-check-the-result)
  - [4 · Run your evaluation](https://docs.screamingface.ai/sf-client/guides/community-cache#4-run-your-evaluation)
  - [If the pull stops](https://docs.screamingface.ai/sf-client/guides/community-cache#if-the-pull-stops)
  - [Keep the cache current](https://docs.screamingface.ai/sf-client/guides/community-cache#keep-the-cache-current)
  - [See also](https://docs.screamingface.ai/sf-client/guides/community-cache#see-also)
- [Leaderboards](https://docs.screamingface.ai/sf-client/guides/leaderboards): Browse ranked results, publish a CandidateResult, and pull the url4 back out.
  - [What you can do with it](https://docs.screamingface.ai/sf-client/guides/leaderboards#what-you-can-do-with-it)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/leaderboards#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/leaderboards#how-to)
  - [1 · See which boards exist](https://docs.screamingface.ai/sf-client/guides/leaderboards#1-see-which-boards-exist)
  - [2 · Read one board](https://docs.screamingface.ai/sf-client/guides/leaderboards#2-read-one-board)
  - [3 · Point the Client at a leaderboard](https://docs.screamingface.ai/sf-client/guides/leaderboards#3-point-the-client-at-a-leaderboard)
  - [4 · Publish a result](https://docs.screamingface.ai/sf-client/guides/leaderboards#4-publish-a-result)
  - [5 · Fetch a published score](https://docs.screamingface.ai/sf-client/guides/leaderboards#5-fetch-a-published-score)
  - [6 · Edit what you submitted](https://docs.screamingface.ai/sf-client/guides/leaderboards#6-edit-what-you-submitted)
  - [7 · Remix a score](https://docs.screamingface.ai/sf-client/guides/leaderboards#7-remix-a-score)
  - [8 · Reproduce a published run](https://docs.screamingface.ai/sf-client/guides/leaderboards#8-reproduce-a-published-run)
  - [What "verified" means here](https://docs.screamingface.ai/sf-client/guides/leaderboards#what-verified-means-here)
  - [Links](https://docs.screamingface.ai/sf-client/guides/leaderboards#links)
- [Reproduce & share (url4)](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share): Read the exact plan a run executed, and hand it to someone else.
  - [What you can do](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#what-you-can-do)
  - [Main APIs](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#main-apis)
  - [How to](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#how-to)
  - [1 · Read a url4](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#1-read-a-url4)
  - [2 · Turn a url4 back into code](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#2-turn-a-url4-back-into-code)
  - [3 · Inspect the operation graph](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#3-inspect-the-operation-graph)
  - [4 · Identify the run](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#4-identify-the-run)
  - [5 · Share the whole report](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#5-share-the-whole-report)
  - [What "reproduce" means here](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#what-reproduce-means-here)
  - [Links](https://docs.screamingface.ai/sf-client/guides/reproduce-and-share#links)
- [Clients](https://docs.screamingface.ai/sf-client/guides/clients): The default Client behind sf.*, and when to build your own.
  - [What you can do with it](https://docs.screamingface.ai/sf-client/guides/clients#what-you-can-do-with-it)
  - [The two forms, side by side](https://docs.screamingface.ai/sf-client/guides/clients#the-two-forms-side-by-side)
  - [The default Client](https://docs.screamingface.ai/sf-client/guides/clients#the-default-client)
  - [Build your own Client](https://docs.screamingface.ai/sf-client/guides/clients#build-your-own-client)
  - [Async](https://docs.screamingface.ai/sf-client/guides/clients#async)
  - [Custom transports](https://docs.screamingface.ai/sf-client/guides/clients#custom-transports)
  - [One process, one shared Client](https://docs.screamingface.ai/sf-client/guides/clients#one-process-one-shared-client)
  - [When to use each](https://docs.screamingface.ai/sf-client/guides/clients#when-to-use-each)
  - [See also](https://docs.screamingface.ai/sf-client/guides/clients#see-also)
- [Install the agent skill](https://docs.screamingface.ai/sf-client/agent-skill): Give a coding agent the ScreamingFace Client docs as a skill.
  - [Copy to your agent](https://docs.screamingface.ai/sf-client/agent-skill#copy-to-your-agent)
  - [Install the skill](https://docs.screamingface.ai/sf-client/agent-skill#install-the-skill)
  - [Update the skill](https://docs.screamingface.ai/sf-client/agent-skill#update-the-skill)
  - [Read the docs as Markdown](https://docs.screamingface.ai/sf-client/agent-skill#read-the-docs-as-markdown)
  - [How it is built](https://docs.screamingface.ai/sf-client/agent-skill#how-it-is-built)
  - [Troubleshooting](https://docs.screamingface.ai/sf-client/agent-skill#troubleshooting)

### Overview

- [Modules](https://docs.screamingface.ai/sf-client/api/modules): The modules and functions you can call on sf directly.
  - [sf.benchmarks](https://docs.screamingface.ai/sf-client/api/modules#sfbenchmarks)
  - [sf.models](https://docs.screamingface.ai/sf-client/api/modules#sfmodels)
  - [sf.connections](https://docs.screamingface.ai/sf-client/api/modules#sfconnections)
  - [sf.leaderboards](https://docs.screamingface.ai/sf-client/api/modules#sfleaderboards)
  - [sf.events](https://docs.screamingface.ai/sf-client/api/modules#sfevents)
  - [sf.reports](https://docs.screamingface.ai/sf-client/api/modules#sfreports)
  - [sf.cache](https://docs.screamingface.ai/sf-client/api/modules#sfcache)
  - [sf.analytics](https://docs.screamingface.ai/sf-client/api/modules#sfanalytics)
  - [Top-level functions](https://docs.screamingface.ai/sf-client/api/modules#top-level-functions)
  - [evaluate()](https://docs.screamingface.ai/sf-client/api/modules#evaluate)
  - [configure()](https://docs.screamingface.ai/sf-client/api/modules#configure)
  - [connect() and disconnect()](https://docs.screamingface.ai/sf-client/api/modules#connect-and-disconnect)
  - [classify()](https://docs.screamingface.ai/sf-client/api/modules#classify)
  - [fetch_media()](https://docs.screamingface.ai/sf-client/api/modules#fetch_media)
  - [close()](https://docs.screamingface.ai/sf-client/api/modules#close)

### Classes

- [Clients](https://docs.screamingface.ai/sf-client/api/clients): Client and AsyncClient: how you reach an engine.
  - [Client](https://docs.screamingface.ai/sf-client/api/clients#client)
  - [Constructor arguments](https://docs.screamingface.ai/sf-client/api/clients#constructor-arguments)
  - [Properties](https://docs.screamingface.ai/sf-client/api/clients#properties)
  - [evaluate()](https://docs.screamingface.ai/sf-client/api/clients#evaluate)
  - [Replay a captured run with evaluate()](https://docs.screamingface.ai/sf-client/api/clients#replay-a-captured-run-with-evaluate)
  - [connect() and disconnect()](https://docs.screamingface.ai/sf-client/api/clients#connect-and-disconnect)
  - [Lifecycle](https://docs.screamingface.ai/sf-client/api/clients#lifecycle)
  - [AsyncClient](https://docs.screamingface.ai/sf-client/api/clients#asyncclient)
- [Recipes](https://docs.screamingface.ai/sf-client/api/recipes): The abstract Recipe base every candidate shares, where each concrete type is documented, and the corrective loops that draft under a benchmark's check.
  - [Recipe](https://docs.screamingface.ai/sf-client/api/recipes#recipe)
  - [Where each type is documented](https://docs.screamingface.ai/sf-client/api/recipes#where-each-type-is-documented)
  - [Corrective loops](https://docs.screamingface.ai/sf-client/api/recipes#corrective-loops)
  - [CorrectiveLoop](https://docs.screamingface.ai/sf-client/api/recipes#correctiveloop)
  - [SelfCorrective](https://docs.screamingface.ai/sf-client/api/recipes#selfcorrective)
- [Models](https://docs.screamingface.ai/sf-client/api/models): The Model recipe class you build, and the discovery types routes come back as: ModelInfo, ModelDetails, and their fields.
  - [Model](https://docs.screamingface.ai/sf-client/api/models#model)
  - [Parameters](https://docs.screamingface.ai/sf-client/api/models#parameters)
  - [Attributes](https://docs.screamingface.ai/sf-client/api/models#attributes)
  - [Raises](https://docs.screamingface.ai/sf-client/api/models#raises)
  - [Discovery types](https://docs.screamingface.ai/sf-client/api/models#discovery-types)
  - [ModelInfo](https://docs.screamingface.ai/sf-client/api/models#modelinfo)
  - [ModelDetails](https://docs.screamingface.ai/sf-client/api/models#modeldetails)
  - [ModelParameter](https://docs.screamingface.ai/sf-client/api/models#modelparameter)
  - [ModelParameterSchema](https://docs.screamingface.ai/sf-client/api/models#modelparameterschema)
  - [ModelCapability](https://docs.screamingface.ai/sf-client/api/models#modelcapability)
- [Fusion](https://docs.screamingface.ai/sf-client/api/fusions): Combine parallel members into one answer through a synthesizer.
- [Reducers](https://docs.screamingface.ai/sf-client/api/reducers): The steps of a fan-out block: reducers, judges, narrow steps, a gate and declared signals.
  - [The steps of a block](https://docs.screamingface.ai/sf-client/api/reducers#the-steps-of-a-block)
  - [Reducers that end a block](https://docs.screamingface.ai/sf-client/api/reducers#reducers-that-end-a-block)
  - [Judges](https://docs.screamingface.ai/sf-client/api/reducers#judges)
  - [Narrow steps](https://docs.screamingface.ai/sf-client/api/reducers#narrow-steps)
  - [Gate](https://docs.screamingface.ai/sf-client/api/reducers#gate)
  - [Declared signals](https://docs.screamingface.ai/sf-client/api/reducers#declared-signals)
  - [Extractors and predicates](https://docs.screamingface.ai/sf-client/api/reducers#extractors-and-predicates)
  - [Reading what a reducer decided](https://docs.screamingface.ai/sf-client/api/reducers#reading-what-a-reducer-decided)
- [Pipeline](https://docs.screamingface.ai/sf-client/api/pipelines): Chain recipes in series, each stage refining the last.
- [Url4](https://docs.screamingface.ai/sf-client/api/url4): The string value a run carries, and the editable Python it forks to.
- [Benchmarks](https://docs.screamingface.ai/sf-client/api/benchmarks): Benchmark and the read-only values discovery returns.
  - [Benchmark](https://docs.screamingface.ai/sf-client/api/benchmarks#benchmark)
  - [Attributes](https://docs.screamingface.ai/sf-client/api/benchmarks#attributes)
  - [BenchmarkInfo](https://docs.screamingface.ai/sf-client/api/benchmarks#benchmarkinfo)
  - [Validation](https://docs.screamingface.ai/sf-client/api/benchmarks#validation)
- [Connections](https://docs.screamingface.ai/sf-client/api/connections): The provider-connection values: Connection, the OAuth flows, and the interactive panel.
  - [Connection](https://docs.screamingface.ai/sf-client/api/connections#connection)
  - [OAuthFlow](https://docs.screamingface.ai/sf-client/api/connections#oauthflow)
  - [AsyncOAuthFlow](https://docs.screamingface.ai/sf-client/api/connections#asyncoauthflow)
  - [ConnectionPanel](https://docs.screamingface.ai/sf-client/api/connections#connectionpanel)
- [Reports](https://docs.screamingface.ai/sf-client/api/reports): Report and everything it carries.
  - [Report](https://docs.screamingface.ai/sf-client/api/reports#report)
  - [Attributes](https://docs.screamingface.ai/sf-client/api/reports#attributes)
  - [candidates](https://docs.screamingface.ai/sf-client/api/reports#candidates)
  - [Serialisation](https://docs.screamingface.ai/sf-client/api/reports#serialisation)
  - [Saved reports](https://docs.screamingface.ai/sf-client/api/reports#saved-reports)
  - [Beyond the report](https://docs.screamingface.ai/sf-client/api/reports#beyond-the-report)
- [CandidateResult](https://docs.screamingface.ai/sf-client/api/candidate-result): One candidate's outcome and the values it carries (MemberResult, OperationInfo, CaseResult), and the CaseGrade tree behind each case score.
  - [CandidateResult](https://docs.screamingface.ai/sf-client/api/candidate-result#candidateresult)
  - [cases](https://docs.screamingface.ai/sf-client/api/candidate-result#cases)
  - [CaseResult](https://docs.screamingface.ai/sf-client/api/candidate-result#caseresult)
  - [CaseOperation](https://docs.screamingface.ai/sf-client/api/candidate-result#case-operation)
  - [Case media](https://docs.screamingface.ai/sf-client/api/candidate-result#case-media)
  - [Accounting, answers and trace](https://docs.screamingface.ai/sf-client/api/candidate-result#accounting-answers-and-trace)
  - [Combine evidence](https://docs.screamingface.ai/sf-client/api/candidate-result#combine-evidence)
  - [How a case is graded](https://docs.screamingface.ai/sf-client/api/candidate-result#how-a-case-is-graded)
  - [CaseGrade](https://docs.screamingface.ai/sf-client/api/candidate-result#casegrade)
  - [Check](https://docs.screamingface.ai/sf-client/api/candidate-result#check)
  - [Evidence](https://docs.screamingface.ai/sf-client/api/candidate-result#evidence)
  - [EvidenceProducer](https://docs.screamingface.ai/sf-client/api/candidate-result#evidenceproducer)
  - [MemberResult](https://docs.screamingface.ai/sf-client/api/candidate-result#memberresult)
  - [OperationInfo](https://docs.screamingface.ai/sf-client/api/candidate-result#operationinfo)
- [Usage](https://docs.screamingface.ai/sf-client/api/usage): Usage for token and cost accounting, and Failure for anything that went wrong.
  - [Usage](https://docs.screamingface.ai/sf-client/api/usage#usage)
  - [Failure](https://docs.screamingface.ai/sf-client/api/usage#failure)
- [Leaderboards](https://docs.screamingface.ai/sf-client/api/leaderboards): The public board: what it holds, and what a submission records.
  - [Leaderboard](https://docs.screamingface.ai/sf-client/api/leaderboards#leaderboard)
  - [LeaderboardInfo](https://docs.screamingface.ai/sf-client/api/leaderboards#leaderboardinfo)
  - [LeaderboardEntry](https://docs.screamingface.ai/sf-client/api/leaderboards#leaderboardentry)
  - [LeaderboardBaseline](https://docs.screamingface.ai/sf-client/api/leaderboards#leaderboardbaseline)
  - [LeaderboardScore](https://docs.screamingface.ai/sf-client/api/leaderboards#leaderboardscore)
  - [LeaderboardRankingNotice](https://docs.screamingface.ai/sf-client/api/leaderboards#leaderboardrankingnotice)
  - [ScoreMetadataEvent](https://docs.screamingface.ai/sf-client/api/leaderboards#scoremetadataevent)
  - [Reproduction](https://docs.screamingface.ai/sf-client/api/leaderboards#reproduction)
- [Events](https://docs.screamingface.ai/sf-client/api/events): What a run reports through on_event while it is still running.
  - [Event](https://docs.screamingface.ai/sf-client/api/events#event)
  - [Started](https://docs.screamingface.ai/sf-client/api/events#started)
  - [Span](https://docs.screamingface.ai/sf-client/api/events#span)
  - [Log](https://docs.screamingface.ai/sf-client/api/events#log)
  - [Usage](https://docs.screamingface.ai/sf-client/api/events#usage)
  - [Terminated](https://docs.screamingface.ai/sf-client/api/events#terminated)
  - [TerminationError](https://docs.screamingface.ai/sf-client/api/events#terminationerror)
- [Errors](https://docs.screamingface.ai/sf-client/api/errors): What the Client raises, and the warnings it emits when a run or a submission carries a caveat.
  - [The hierarchy](https://docs.screamingface.ai/sf-client/api/errors#the-hierarchy)
  - [Errors](https://docs.screamingface.ai/sf-client/api/errors#errors)
  - [What an error carries](https://docs.screamingface.ai/sf-client/api/errors#what-an-error-carries)
  - [Replay errors and verdicts](https://docs.screamingface.ai/sf-client/api/errors#replay-errors-and-verdicts)
  - [Warnings](https://docs.screamingface.ai/sf-client/api/errors#warnings)

### Modules & types

- [Shared cache](https://docs.screamingface.ai/sf-client/api/cache): Use the shared cache from the hosted engine when running locally.
  - [The local request cache](https://docs.screamingface.ai/sf-client/api/cache#the-local-request-cache)
  - [sf.cache.pull_from_remote](https://docs.screamingface.ai/sf-client/api/cache#sfcachepull_from_remote)
  - [PullResult](https://docs.screamingface.ai/sf-client/api/cache#pullresult)
  - [CachePullError](https://docs.screamingface.ai/sf-client/api/cache#cachepullerror)
  - [screamingface cache pull](https://docs.screamingface.ai/sf-client/api/cache#screamingface-cache-pull)
- [Classify](https://docs.screamingface.ai/sf-client/api/classify): Send one text to a text classifier and read its label scores.
  - [The call](https://docs.screamingface.ai/sf-client/api/classify#the-call)
  - [What the classifier endpoint receives](https://docs.screamingface.ai/sf-client/api/classify#what-the-classifier-endpoint-receives)
  - [What it returns](https://docs.screamingface.ai/sf-client/api/classify#what-it-returns)
  - [Limits and timing](https://docs.screamingface.ai/sf-client/api/classify#limits-and-timing)
  - [Errors](https://docs.screamingface.ai/sf-client/api/classify#errors)
- [Analytics](https://docs.screamingface.ai/sf-client/api/analytics): Analytics controls for opting in and out, and what it collects.
  - [The first import](https://docs.screamingface.ai/sf-client/api/analytics#the-first-import)
  - [Functions](https://docs.screamingface.ai/sf-client/api/analytics#functions)
  - [Status](https://docs.screamingface.ai/sf-client/api/analytics#status)
  - [Where the choice is saved](https://docs.screamingface.ai/sf-client/api/analytics#where-the-choice-is-saved)
  - [screamingface analytics](https://docs.screamingface.ai/sf-client/api/analytics#screamingface-analytics)
  - [DO_NOT_TRACK](https://docs.screamingface.ai/sf-client/api/analytics#do_not_track)
  - [Colab](https://docs.screamingface.ai/sf-client/api/analytics#colab)

### Overview

- [Architecture](https://docs.screamingface.ai/learn): How the pieces fit (url4 the protocol, the engine that runs it, and the surfaces you compose from) and where each one lives in the codebase.
  - [The layers](https://docs.screamingface.ai/learn#the-layers)
  - [How a request flows](https://docs.screamingface.ai/learn#how-a-request-flows)
  - [The trust boundary](https://docs.screamingface.ai/learn#the-trust-boundary)
  - [Where the code lives](https://docs.screamingface.ai/learn#where-the-code-lives)

### Explanation

- [url4](https://docs.screamingface.ai/learn/url4): The grammar and protocol that packages sources and an intent into one line, so a fusion runs, reproduces, and can be reused like a model call.
  - [Two layers](https://docs.screamingface.ai/learn/url4#two-layers)
  - [The shape](https://docs.screamingface.ai/learn/url4#the-shape)
  - [Two ways to run it](https://docs.screamingface.ai/learn/url4#two-ways-to-run-it)
  - [How it runs](https://docs.screamingface.ai/learn/url4#how-it-runs)
  - [An address, not just a string](https://docs.screamingface.ai/learn/url4#an-address-not-just-a-string)
  - [Why it exists](https://docs.screamingface.ai/learn/url4#why-it-exists)
  - [In code](https://docs.screamingface.ai/learn/url4#in-code)
- [url4 SDK](https://docs.screamingface.ai/learn/url4-sdk): The Python library for building, reading, and running url4 expressions.
  - [Parse and render](https://docs.screamingface.ai/learn/url4-sdk#parse-and-render)
  - [Build in Python](https://docs.screamingface.ai/learn/url4-sdk#build-in-python)
  - [Execute](https://docs.screamingface.ai/learn/url4-sdk#execute)
  - [From the command line](https://docs.screamingface.ai/learn/url4-sdk#from-the-command-line)
  - [Where the code lives](https://docs.screamingface.ai/learn/url4-sdk#where-the-code-lives)
- [Files in url4](https://docs.screamingface.ai/learn/url4-files): Images and PDFs as url4 sources: file URLs, sha256 blob refs, what v1 refuses, and the limits.
  - [A file URL as a source](https://docs.screamingface.ai/learn/url4-files#a-file-url-as-a-source)
  - [The transport guard](https://docs.screamingface.ai/learn/url4-files#the-transport-guard)
  - [Blob refs](https://docs.screamingface.ai/learn/url4-files#blob-refs)
  - [Not in v1](https://docs.screamingface.ai/learn/url4-files#not-in-v1)
  - [Benchmark Cases](https://docs.screamingface.ai/learn/url4-files#cases)
  - [Limits](https://docs.screamingface.ai/learn/url4-files#limits)
  - [Which models take files](https://docs.screamingface.ai/learn/url4-files#which-models-take-files)
  - [Errors](https://docs.screamingface.ai/learn/url4-files#errors)
  - [Where the code lives](https://docs.screamingface.ai/learn/url4-files#where-the-code-lives)
- [ScreamingFace Engine](https://docs.screamingface.ai/learn/engine): The runtime that turns a url4 expression into a result, and the trust boundary that holds the keys.
  - [How it executes](https://docs.screamingface.ai/learn/engine#how-it-executes)
  - [The trust boundary](https://docs.screamingface.ai/learn/engine#the-trust-boundary)
  - [Running one](https://docs.screamingface.ai/learn/engine#running-one)
  - [Where the code lives](https://docs.screamingface.ai/learn/engine#where-the-code-lives)
- [Caching and compute](https://docs.screamingface.ai/learn/caching): What a run bills: call-level caching, a shared community cache, and where the compute comes from.
  - [How caching works](https://docs.screamingface.ai/learn/caching#how-caching-works)
  - [The shared community cache](https://docs.screamingface.ai/learn/caching#the-shared-community-cache)
  - [Pull the community cache into a local engine](https://docs.screamingface.ai/learn/caching#pull-the-community-cache-into-a-local-engine)
  - [Reproducing a submission](https://docs.screamingface.ai/learn/caching#reproducing-a-submission)
  - [Make a pinned cache](https://docs.screamingface.ai/learn/caching#make-a-pinned-cache)
  - [Local runs](https://docs.screamingface.ai/learn/caching#local-runs)
  - [Complete and partial](https://docs.screamingface.ai/learn/caching#complete-and-partial)
  - [Replay from the copy](https://docs.screamingface.ai/learn/caching#replay-from-the-copy)
  - [When a replay fails](https://docs.screamingface.ai/learn/caching#when-a-replay-fails)
  - [Where the compute comes from](https://docs.screamingface.ai/learn/caching#where-the-compute-comes-from)
  - [Providers](https://docs.screamingface.ai/learn/caching#providers)
- [AI gateway](https://docs.screamingface.ai/learn/ai-gateway): Where your provider keys live, encrypted, and the one endpoint the engine calls to reach every model provider.
  - [One endpoint, every provider](https://docs.screamingface.ai/learn/ai-gateway#one-endpoint-every-provider)
  - [Where your keys live](https://docs.screamingface.ai/learn/ai-gateway#where-your-keys-live)
  - [Providers are plugins](https://docs.screamingface.ai/learn/ai-gateway#providers-are-plugins)
  - [The request cache](https://docs.screamingface.ai/learn/ai-gateway#the-request-cache)
  - [Running it](https://docs.screamingface.ai/learn/ai-gateway#running-it)
- [Leaderboard](https://docs.screamingface.ai/learn/leaderboard): The public board where ensemble results are ranked, and where every entry carries the recipe that produced it and whether the hosted engine ran it.
  - [How a rank happens](https://docs.screamingface.ai/learn/leaderboard#how-a-rank-happens)
  - [The line to beat](https://docs.screamingface.ai/learn/leaderboard#the-line-to-beat)
  - [The paper link](https://docs.screamingface.ai/learn/leaderboard#the-paper-link)
  - [The recipe is the reward](https://docs.screamingface.ai/learn/leaderboard#the-recipe-is-the-reward)
  - [From the Client](https://docs.screamingface.ai/learn/leaderboard#from-the-client)
  - [Known limits](https://docs.screamingface.ai/learn/leaderboard#known-limits)
  - [Where the code lives](https://docs.screamingface.ai/learn/leaderboard#where-the-code-lives)

### Other pages

- [Compose model fusions. Reproduce every run from one line.](https://docs.screamingface.ai/)
