# 😱 ScreamingFace

> **Build model fusions, measure them honestly, and reproduce any run from a single line of text.**

ScreamingFace is a toolkit for composing **fusions**, several models answering the same question and
reduced to a single answer, and scoring them against real benchmarks. Concretely, it is three pieces:

- **An open protocol, `url4`.** Every fusion and its benchmark run compile to one short,
  human-readable line. Sharing a result is sharing that string: `sf.evaluate(url4_string)` replays
  the exact run, and `sf.Url4(url4_string).to_python()` hands you the same recipe as Python source
  you can edit. **A result is only worth as much as your ability to rerun it.**
- **A shared cache.** Every model call is cached and shared across the community, so reproducing a
  run is both **faithful and nearly free**. Verifying someone's work costs minutes, not budgets, and
  the more people run, the cheaper it gets for everyone.
- **A small toolkit.** A Python library where composing a fusion, evaluating it, and reading the
  scores takes **a few lines, not an infrastructure project** to stand up first.

We built this because the same pattern kept showing up: a fusion beat the best single model inside
it, and the result was nearly impossible to reproduce or check. Two datapoints: reproducing DRACO,
our best fusion scored **68.6%** vs **60.2%** for the top single model (**+8.4**,
[write-up](https://andrewtrask.substack.com/p/6-weeks-ago-frontier-ai-labs-lost)); and small-model
ensembles beat their best member in _Beyond Leaderboards_ (Skurikhin et al., Los Alamos).

It is early, and rough in places. If you find something wrong, good: every result here is meant to
be rerun and picked apart.

📚 [docs.screamingface.ai](https://docs.screamingface.ai) ·
🏆 [leaderboard.screamingface.ai](https://leaderboard.screamingface.ai) ·
⚖️ [Apache-2.0](LICENSE)

## What it gives you

- **One interface, every provider.** Bring your own keys and compose across open and closed models,
  API and local. The client never calls a provider directly; your keys go to an engine that holds
  them.
- **Evaluation you can defend.** A benchmark is pinned and lives engine-side: the cases, the judge,
  the rubric, the answer keys. Your candidate only ever sees the prompt. That separation is the
  whole reason a "verified gain" means anything.
- **Start from the frontier.** Pull a published run's `url4`, change one thing, and measure the
  difference, so the next person starts where the last one finished.
- **Shared cache, and subsidized compute.** Model calls are cached and shared across the
  community, and we sponsor compute for researchers on a discretionary basis. A BYOK path is also
  available, and we are happy to extend the providers we support — just [open an issue](https://github.com/ScreamingFace/screamingface/issues).

And it only really works as a community: no one team can measure every model, on every benchmark,
across every domain. **We are looking for talented people to join this early community and help
demonstrate it at a bigger scale.**

Right now this is single-turn evaluation. No multi-turn or tool-using agent loops yet.

## Quickstart

```bash
pip install "screamingface[notebook]"
```

> To run your own engine locally, add the `[runtime]` extra:
> `pip install "screamingface[runtime]"`

```python
import screamingface as sf

sf.configure(engine_url="http://127.0.0.1:9108")   # your own engine, or a hosted one

gpt = sf.Model("openrouter/openai/gpt-5.5")
flash = sf.Model("openrouter/google/gemini-3-flash-preview")
fusion = sf.Fusion([gpt, flash], synthesizer="openrouter/openai/gpt-5.5")

# score the solo model beside the fusion, on the same cases
report = sf.evaluate([gpt, fusion], benchmark="ifeval", limit=3)
{c.name: c.score for c in report.candidates}
```

Full walkthrough in the [Quickstart](https://docs.screamingface.ai/sf-client/quickstartPage).

## Prerequisites

You need the **client** (a Python library) and an **engine** (the runtime that actually does the
work). Two ways to get an engine:

- **Run your own:** your machine, your keys, nothing in the middle on the local path.
- **Use a hosted one:** an engine we operate, with the shared cache and, for some cohorts, subsidized
  compute.

Same client code either way; only the engine URL changes. The
[Installation guide](https://docs.screamingface.ai) has both.

| Tool   | Version | Notes                                                                        |
| ------ | ------- | ---------------------------------------------------------------------------- |
| Python | ≥ 3.12  | for the client                                                               |
| uv     | latest  | for working in this repo: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

## Monorepo layout

```
apps/
  aigateway/      AI gateway: holds provider keys (encrypted), one endpoint to every provider
  screamingface-engine/     the Engine: turns a url4 expression into a graded result
  scoreboard/     the public Leaderboard service
packages/
  screamingface/  the Client: `pip install screamingface` (Python SDK)
  url4/           the url4 protocol: grammar, parser, AST, DAG executor
public-docs/      the documentation site (docs.screamingface.ai)
docs/             SDLC artifacts: spec/ plan/ tasks/ work/ diagrams/ (see docs/README.md)
```

> Legacy code (the old desktop app, plugin server, and url4 engine) is preserved read-only at the
> git tag **`legacy-monorepo-2026-07-08`**.

## Working in this repo

```bash
git clone https://github.com/ScreamingFace/screamingface.git
cd screamingface
git config core.hooksPath .githooks     # pre-commit guard (blocks commits to main)
```

Run a service:

```bash
# AI gateway (port 9105)
cd apps/aigateway && uv sync && uv run uvicorn aigateway.main:app --port 9105 --reload

# Scoreboard (port 9106)
cd apps/scoreboard && uv sync && uv run scoreboard
```

Run the docs site:

```bash
cd public-docs && npm install && npm run dev
```

Check a stack (lint, format, typecheck, tests, and coverage) in one command:

```bash
uv run .claude/scripts/run_gates.py <stack>   # aigateway | scoreboard | url4
```

## More

- **Docs** (quickstart, guides, concepts) → [docs.screamingface.ai](https://docs.screamingface.ai)
- **Developing / git workflow** → [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **AI gateway internals** → [`apps/aigateway/README.md`](apps/aigateway/README.md)
- **Scoreboard internals** → [`apps/scoreboard/README.md`](apps/scoreboard/README.md)
- **url4 protocol** → [`packages/url4/README.md`](packages/url4/README.md)
- **Repo guide** (skills, agents, cards, process) → [`.claude/README.md`](.claude/README.md)
- **Legacy code** → `git checkout legacy-monorepo-2026-07-08`

## License

[Apache-2.0](LICENSE). Open to whoever shows up to measure the next slice.
