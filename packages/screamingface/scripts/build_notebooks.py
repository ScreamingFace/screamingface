"""Build the public v1 notebooks deterministically."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import nbformat
from nbformat import NotebookNode

_DRACO_ANSWER_PROMPT_PARTS = (
    "You are answering a research-quality prompt. Provide a thorough, ",
    "well-reasoned answer in prose. Address every aspect the prompt raises. ",
    "Use clear structure (headings, bullet lists where appropriate) and cite ",
    "specific facts, methodologies, or sources where relevant.\n\n",
    "Do not refuse, abstain, or claim uncertainty unless the question is ",
    "genuinely ambiguous — the goal is to demonstrate depth of understanding. ",
    "Length: aim for the level of detail the question warrants; brevity that ",
    "skips key points will be penalised by the rubric.",
)
_DRACO_ANSWER_PROMPT = "".join(_DRACO_ANSWER_PROMPT_PARTS)

_DRACO_SYNTHESIS_PROMPT_PARTS = (
    "You are synthesising a single, comprehensive answer to a research-quality ",
    "prompt by combining N independent answers from a panel of models. The ",
    "downstream grader will score your output against a STRUCTURED RUBRIC of ",
    "weighted criteria — your goal is to maximise rubric coverage.\n\n",
    "Procedure:\n",
    "1. Read every panel answer carefully.\n",
    "2. Identify which claims, facts, citations, or arguments each panel member ",
    "contributes that the others miss.\n",
    "3. Produce ONE unified prose response that:\n",
    "   - Combines the strongest reasoning from every panel member\n",
    "   - Preserves specific named entities, dates, methodologies, and citations\n",
    "   - Resolves disagreements by favouring the more specific / better-cited claim\n",
    "   - Uses clear structure (headings, lists) where it aids the reader\n",
    "4. Do not introduce new facts that no panel member provided.\n",
    "5. Do not hedge or refuse — the panel collectively has enough material.\n\n",
    "Output: the unified prose answer, no preamble, no JSON wrapper.",
)
_DRACO_SYNTHESIS_PROMPT = "".join(_DRACO_SYNTHESIS_PROMPT_PARTS)


def notebooks() -> dict[str, NotebookNode]:
    return {
        "00_quickstart.ipynb": _quickstart(),
        "01_client_tour.ipynb": _client_tour(),
        "02_connection.ipynb": _connection(),
        "06_draco.ipynb": _draco_full_e2e(),
        "07_ifeval.ipynb": _ifeval_e2e(),
        "08_healthbench.ipynb": _healthbench_e2e(),
        "09_corrective_loops.ipynb": _corrective_loops(),
        "10_gdpval.ipynb": _gdpval_e2e(),
        "11_medxpert.ipynb": _medxpert_e2e(),
        "12_inspect_evals_benchmarks.ipynb": _inspect_evals_boards(),
        "13_contracteval.ipynb": _contracteval_e2e(),
    }


def _notebook(*cells: NotebookNode) -> NotebookNode:
    # WHY: record the generating checkout, not an unrelated package installed in the builder.
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    for index, cell in enumerate(cells, 1):
        cell["id"] = f"cell-{index:02d}"
    return nbformat.v4.new_notebook(
        cells=list(cells),
        metadata={
            "screamingface": {"generated_by_version": project["project"]["version"]},
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
    )


def _draco_candidate_policy_cell(*, synthesis: bool = False) -> NotebookNode:
    source = _string_assignment("DRACO_ANSWER_PROMPT", _DRACO_ANSWER_PROMPT_PARTS)
    if synthesis:
        source += "\n\n" + _string_assignment(
            "DRACO_SYNTHESIS_PROMPT",
            _DRACO_SYNTHESIS_PROMPT_PARTS,
        )
    return nbformat.v4.new_code_cell(source)


def _string_assignment(name: str, parts: tuple[str, ...]) -> str:
    literals = "\n".join(f"    {json.dumps(part, ensure_ascii=False)}" for part in parts)
    return f"{name} = (\n{literals}\n)"


def _quickstart() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# ScreamingFace quickstart

Six steps: inspect the public Leaderboards, connect a provider, run a Benchmark, read the
Report, publish its Candidate Result, and replay its URL4. The wider interface is covered in
`01_client_tour.ipynb`."""),
        nbformat.v4.new_markdown_cell("""\
## Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare draco  # first run only: download pinned Benchmark assets
screamingface up             # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished. Stack
management stays outside the notebook so **Run All** never starts or stops local services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)

BENCHMARK_ID = "draco\""""),
        nbformat.v4.new_markdown_cell("""\
## 1 · Leaderboards

Leaderboard discovery reads from the independently seeded Scoreboard and does not require a
provider connection. Its registered boards may differ from the Engine's Benchmark catalogue.
Both values render as interactive, brand-system notebook widgets."""),
        nbformat.v4.new_code_cell("""\
leaderboards = sf.leaderboards.list()
leaderboards"""),
        nbformat.v4.new_code_cell("""\
leaderboard = sf.leaderboards.get(BENCHMARK_ID, top=10)
leaderboard"""),
        nbformat.v4.new_markdown_cell("""\
## 2 · Connect

`sf.connect()` renders the Engine-backed provider panel. A key entered here goes to the SF
Engine for AI Gateway validation and encrypted storage; the notebook never retains it. On a
hosted Engine the panel asks for Cloudflare Access login first."""),
        nbformat.v4.new_code_cell("""\
sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 3 · Evaluate

`limit=1` selects one Case from canonical DRACO. The Benchmark still applies every rubric
criterion and all five canonical Judge passes, so this is an authentic one-Case rehearsal—not a
weakened smoke protocol. It is **not** comparable with a complete 100-Case DRACO result. Grading
can still make many paid calls; run it deliberately. While it runs, the live panel shows
progress,
model calls, tokens and cost."""),
        nbformat.v4.new_code_cell("""\
candidate = sf.Model("openrouter/google/gemini-3-flash-preview")

report = sf.evaluate(candidate, benchmark=BENCHMARK_ID, limit=1)"""),
        nbformat.v4.new_markdown_cell("""\
## 4 · Report

The Report renders score, pass rate, coverage, cost and tokens, with every Case and the
Judge's per-criterion reasoning underneath. **&darr; report.json** downloads the portable
artifact — the same complete JSON document `report.export()` writes to the notebook's working
directory."""),
        nbformat.v4.new_code_cell("""\
report"""),
        nbformat.v4.new_code_cell("""\
artifact_path = report.export()
artifact_path"""),
        nbformat.v4.new_markdown_cell("""\
## 5 · Publish and retrieve

Publication accepts the evaluated `CandidateResult` directly. It derives the Benchmark id,
compiled URL4, models, the Benchmark-native score, timestamps, and idempotency key from that
immutable result — the score is submitted exactly as the Engine reported it, and the
Scoreboard ranks it without recalculating. Publication is independently opt-in so
**Run All** never changes the Scoreboard.

The local Scoreboard accepts writes without login. Hosted deployments may require an
edge-verified identity or keep score submission closed."""),
        nbformat.v4.new_code_cell("""\
PUBLISH_RESULT = False

submission = sf.leaderboards.submit(report.candidates.only) if PUBLISH_RESULT else None
submission if submission is not None else ("Set PUBLISH_RESULT = True to publish this result.")"""),
        nbformat.v4.new_code_cell("""\
published_score = sf.leaderboards.get_score(submission.id) if submission is not None else None
published_score"""),
        nbformat.v4.new_code_cell("""\
updated_leaderboard = (
    sf.leaderboards.get(BENCHMARK_ID, top=10) if submission is not None else leaderboard
)
updated_leaderboard"""),
        nbformat.v4.new_markdown_cell("""\
## 6 · Fork or replay the submitted URL4

`published_score.url4` is the raw evaluation expression stored by the Scoreboard. Its
`.to_python()` method returns an editable Model/Fusion and evaluation cell without spending.
Passing the URL4 itself to `sf.evaluate(...)` instead executes that exact, already
Benchmark-linked expression and returns a normal `Report`; do not pass `benchmark=` or `limit=`
again.

Replay is a fresh paid Evaluation and model output may differ, so it has its own opt-in guard.
"""),
        nbformat.v4.new_code_cell("""\
fork_python = published_score.url4.to_python() if published_score is not None else None
print(fork_python if fork_python is not None else "Publish a score to generate a fork.")"""),
        nbformat.v4.new_code_cell("""\
REPLAY_RESULT = False

replayed_report = (
    sf.evaluate(published_score.url4) if REPLAY_RESULT and published_score is not None else None
)
replayed_report if replayed_report is not None else (
    "Set REPLAY_RESULT = True after publishing to run the stored URL4 again."
)"""),
    )


def _client_tour() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# ScreamingFace client tour

Explore the full public Client surface without making a paid model call. This complements the
short quickstart: it covers explicit Client lifecycle, Engine discovery, provider connections,
Model and Fusion authoring, hosted authentication, asynchronous use, progress Events, typed
errors, and Report anatomy.

Every state-changing or paid example is either descriptive or guarded off by default."""),
        nbformat.v4.new_markdown_cell("""\
## Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare draco  # first run only: download pinned Benchmark assets
screamingface up             # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished. Stack
management stays outside the notebook so **Run All** never starts or stops local services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Choose a Client lifecycle

Module functions such as `sf.models.list()` use one lazy default Client. `sf.configure()`
replaces
that default when an application needs another Engine origin, and `sf.close()` closes it.

Long-running applications can instead own an explicit Client and close it deterministically.
This
tour uses that form so its lifecycle is visible."""),
        nbformat.v4.new_code_cell("""\
client = sf.Client(engine_url="http://127.0.0.1:9108")
{
    "engine_url": client.engine_url,
    "closed": client.closed,
    "authenticated": client.authenticated,
    "authenticating": client.authenticating,
}"""),
        nbformat.v4.new_markdown_cell("""\
For a hosted Engine protected by Cloudflare Access, caller login is separate from
provider credentials. Protected requests can start login automatically, or an application can be
explicit:

```python
with sf.Client(engine_url="https://your-engine.example") as hosted:
    hosted.login(timeout=300)
    print(hosted.authenticated)
    hosted.logout()
```

Local loopback development does not require that browser flow."""),
        nbformat.v4.new_markdown_cell("""\
## 2. Discover Models and their exact contracts"""),
        nbformat.v4.new_code_cell("""\
models = client.models.list()
models"""),
        nbformat.v4.new_code_cell("""\
MODEL_ID = "openrouter/google/gemini-3-flash-preview"
model = client.models.get(MODEL_ID)
{
    "id": model.id,
    "provider": model.provider,
    "auth_mode": model.auth_mode,
    "enabled_parameters": [
        name for name, parameter in model.parameters.items() if parameter.enabled
    ],
    "enabled_tools": [
        name for name, capability in model.tools.items() if capability.gateway_status == "enabled"
    ],
    "stale": model.stale,
    "degraded": model.degraded,
}"""),
        nbformat.v4.new_markdown_cell("""\
Parameter schemas are executable contracts. Candidate construction is local;
evaluation preflight validates the selected values against this live Engine contract before any
model request is launched."""),
        nbformat.v4.new_code_cell("""\
max_tokens = model.parameters["max_tokens"]
{
    "request_path": max_tokens.request_path,
    "schema": max_tokens.schema,
    "provider_support": max_tokens.provider_support,
    "gateway_projection": max_tokens.gateway_projection,
    "cache_behavior": max_tokens.cache_behavior,
}"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Discover Benchmarks"""),
        nbformat.v4.new_code_cell("""\
benchmarks = client.benchmarks.list()
benchmarks"""),
        nbformat.v4.new_code_cell("""\
draco = client.benchmarks.get("draco")
{
    "id": draco.id,
    "title": draco.title,
    "description": draco.description,
    "revision": draco.revision,
    "case_count": draco.case_count,
}"""),
        nbformat.v4.new_markdown_cell("""\
### Module-level shorthand

Every discovery call above has a module-level form backed by the one lazy default Client.
Use the explicit Client when you need lifecycle control; use these in a notebook."""),
        nbformat.v4.new_code_cell("""\
sf.benchmarks.list()
sf.benchmarks.get("draco")
sf.models.get("openrouter/google/gemini-3-flash-preview")"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Inspect and manage provider connections

`client.connect()` displays the Engine-backed notebook panel. Applications can also use
`client.connect("openrouter", api_key=...)`, OAuth, `client.connections.get(...)`, and
`client.disconnect(...)`. Provider secrets go to the Engine for validation and encrypted
storage;
they are never returned by discovery."""),
        nbformat.v4.new_code_cell("""\
client.connections.list()"""),
        nbformat.v4.new_code_cell("""\
MUTATE_CONNECTIONS = False

if MUTATE_CONNECTIONS:
    from getpass import getpass

    connection = client.connect("openrouter", api_key=getpass("OpenRouter API key: "))
else:
    connection = "Connection mutation disabled. Use client.connect() for the notebook panel."
connection"""),
        nbformat.v4.new_markdown_cell("""\
OAuth providers return a bounded flow rather than a secret:

```python
flow = client.connect("provider-id", method="oauth")
print(flow.authorize_url)
connection = flow.wait(timeout=300)  # or flow.cancel()
client.disconnect("provider-id")
```"""),
        nbformat.v4.new_markdown_cell("""\
## 5. Author Models and Fusions locally"""),
        nbformat.v4.new_code_cell("""\
writer = sf.Model(
    MODEL_ID,
    name="writer",
    prompt="Answer accurately and explain the important trade-offs.",
    params={"max_tokens": 4096, "temperature": 0.0},
)
reviewer = sf.Model(
    "openrouter/anthropic/claude-haiku-4.5",
    name="reviewer",
    params={"max_tokens": 4096, "temperature": 0.0},
)
panel = sf.Fusion(
    [writer, reviewer],
    name="reviewed-answer",
    synthesizer=sf.Model(
        MODEL_ID,
        prompt="Produce one accurate final answer from the panel responses.",
        params={"max_tokens": 4096, "temperature": 0.0},
    ),
)
[writer, panel]"""),
        nbformat.v4.new_markdown_cell("""\
Recipes contain no Benchmark logic. At evaluation time the Client compiles each
Recipe into URL4 and links it to the selected Engine-owned Benchmark protocol."""),
        nbformat.v4.new_markdown_cell("""\
## 6. Evaluate with progress and typed Events

`progress=True` prints the built-in readable lifecycle. `on_event` receives immutable Events for
custom UI, telemetry, finish-reason/refusal inspection, or logging. `limit` selects a bounded
prefix only when the Benchmark permits it. The run below remains disabled by default."""),
        nbformat.v4.new_code_cell("""\
RUN_EVALUATION = False
events = []

report = (
    client.evaluate(
        [writer, panel],
        benchmark="draco",
        limit=1,
        on_event=events.append,
        progress=True,
    )
    if RUN_EVALUATION
    else None
)
[event.kind for event in events]"""),
        nbformat.v4.new_markdown_cell("""\
## 7. Read the Report as values or a portable artifact

`Report.ok` means the Evaluation produced scored Candidate results without recorded failures.
Results retain the compiled URL4 graph, model operations, aggregate and per-Case usage, finish
reasons, Benchmark grades, Checks, accepted or rejected raw Evidence, failures, and timing.
"""),
        nbformat.v4.new_code_cell("""\
if report is not None:
    result = report.candidates["writer"]
    case = result.cases[0]
    report_view = {
        "ok": report.ok,
        "benchmark": report.benchmark,
        "candidate_names": [item.name for item in report.candidates],
        "score": result.score,
        "metrics": dict(result.metrics),
        "url4": result.url4,
        "operations": result.operations,
        "finish_reason": case.finish_reason,
        "grade": case.grade,
        "checks": () if case.grade is None else case.grade.checks,
        "evidence": ()
        if case.grade is None or not case.grade.checks
        else case.grade.checks[0].evidence,
        "failures": report.failures,
        "usage": report.usage,
        "duration_ms": report.duration_ms,
    }
else:
    report_view = "Evaluation disabled — no result to inspect."
report_view"""),
        nbformat.v4.new_code_cell("""\
report.to_json() if report is not None else None"""),
        nbformat.v4.new_markdown_cell("""\
## 8. Handle the public error family

Catch `sf.ScreamingFaceError` for Engine, authentication, planning, connection, and execution
failures. More specific subclasses remain available when recovery differs:

```python
try:
    report = client.evaluate(writer, benchmark="draco", limit=1)
except sf.ProviderConnectionError:
    client.connect()
except sf.PlanningError as exc:
    print(f"Fix the Candidate or Benchmark selection: {exc}")
except sf.ExecutionError as exc:
    print(f"The launched run failed: {exc}")
except sf.ScreamingFaceError as exc:
    print(f"ScreamingFace could not complete the request: {exc}")
```"""),
        nbformat.v4.new_markdown_cell("""\
## 9. Use the asynchronous Client

The asynchronous API mirrors discovery, connections, authentication, and evaluation. Top-level
`await` works in Jupyter, so this metadata-only example is safe to run."""),
        nbformat.v4.new_code_cell("""\
async with sf.AsyncClient(engine_url="http://127.0.0.1:9108") as async_client:
    async_models = await async_client.models.list()
    async_draco = await async_client.benchmarks.get("draco")

{"model_count": len(async_models), "benchmark": async_draco.id}"""),
        nbformat.v4.new_markdown_cell("""\
## 10. Close the explicit Client"""),
        nbformat.v4.new_code_cell("""\
client.close()
client.closed"""),
    )


def _connection() -> NotebookNode:
    """Point the Client at an Engine, then choose a credential mode — no paid call."""

    return _notebook(
        nbformat.v4.new_markdown_cell(
            """# Configure the connection

The ScreamingFace Python Client talks to two services: the **Engine** (fusion + execution) and
the **Scoreboard** (public Leaderboards). Getting from `import screamingface as sf` to a working
evaluation is two decisions — **where** the Client points, and **how** it is allowed to spend on
model providers.

Nothing here makes a paid model call; every runnable cell is safe. The full Client surface is in
`01_client_tour.ipynb`; an end-to-end run is in `00_quickstart.ipynb`."""
        ),
        nbformat.v4.new_code_cell("import screamingface as sf"),
        nbformat.v4.new_markdown_cell(
            """## 1 · The two endpoints

`engine_url` is the SF Engine that plans and runs evaluations; `scoreboard_url` is the Scoreboard
that serves Leaderboards. With no arguments the Client targets the hosted development deployment.
A Client renders as a connection card showing exactly where it points and its status —
construction opens no network, so this is safe to display."""
        ),
        nbformat.v4.new_code_cell("sf.Client()"),
        nbformat.v4.new_markdown_cell(
            """## 2 · Point the Client at an Engine

Three ways, from most implicit to most explicit.

**Environment** — set before the first call; the lazy default Client reads them once. Best for CI
and deployments:

```bash
export SCREAMINGFACE_ENGINE_URL="http://127.0.0.1:9108"
export SCREAMINGFACE_SCOREBOARD_URL="http://127.0.0.1:9106"
```

**`sf.configure(...)`** — replace the process-wide default so every module-level call
(`sf.leaderboards`, `sf.evaluate`, `sf.connect`) follows it. It returns that Client, which renders
as the card below."""
        ),
        nbformat.v4.new_code_cell(
            """client = sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
client"""
        ),
        nbformat.v4.new_markdown_cell(
            """**An explicit `sf.Client(...)`** — own the instance when you need a second origin or
deterministic lifecycle. Module-level `sf.*` keeps using the default; this one is independent, and
closing it shows on the card."""
        ),
        nbformat.v4.new_code_cell(
            """hosted = sf.Client(
    engine_url="https://fusion.dev.screamingface.ai",
    scoreboard_url="https://leaderboard.dev.screamingface.ai",
)
hosted"""
        ),
        nbformat.v4.new_code_cell("hosted.close()\nhosted"),
        nbformat.v4.new_markdown_cell(
            """## 3 · Provide credentials

The Engine needs provider credentials to make model calls. There are two modes, and a deployment
uses **exactly one**.

### Option 1 · Bring your own key (BYOK)

Pass a provider key straight to the Engine — no hosted login. Best for a local or self-hosted
Engine. `sf.connect()` with no arguments opens the same panel interactively. The key goes to the
Engine for validation and encrypted storage; the notebook never keeps it."""
        ),
        nbformat.v4.new_code_cell(
            """BYOK_API_KEY = None  # e.g. "sk-or-..."; leave None to skip

byok = (
    sf.connect("openrouter", api_key=BYOK_API_KEY)
    if BYOK_API_KEY
    else "Set BYOK_API_KEY to connect a provider with your own key."
)
byok"""
        ),
        nbformat.v4.new_markdown_cell(
            """### Option 2 · Hosted credits

On a hosted Engine, `sf.connect()` handles login for you: the panel shows a **Log in** step
(Cloudflare Access opens in your browser), then reveals the providers your hosted account can
use — you spend shared credits instead of your own keys.

```python
sf.configure(engine_url="https://your-engine.example")
sf.connect()   # log in via the panel, then pick a provider
```

Prefer to script the login? Own a Client and call `login()` yourself; the connection card then
reads **signed in**:

```python
with sf.Client(engine_url="https://your-engine.example") as session:
    session.login(timeout=300)      # browser login
    print(session.authenticated)    # True
    session.connect()
```

Local loopback development never needs this flow.

### Not supported: BYOK + hosted credits

> **One mode per deployment.** A Client uses BYOK **or** hosted credits, never both at once.
> Local / self-hosted Engine → BYOK; a hosted ScreamingFace Engine → hosted credits after login."""
        ),
        nbformat.v4.new_markdown_cell(
            """## Recap

- **Where:** environment variables → `sf.configure(...)` (the module default) → an explicit
  `sf.Client(...)` you own.
- **How:** BYOK (`api_key=`) or hosted credits (`login()`) — one mode per deployment.
- `sf.close()` closes the module default; `client.close()` closes an instance you own."""
        ),
        nbformat.v4.new_code_cell("sf.close()"),
    )


def _ifeval_e2e() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# IFEval: the protocol grid — solo and panel, with and without correction

[IFEval](https://arxiv.org/abs/2311.07911) contains 541 instruction-following prompts with
deterministic checks for requirements such
as word counts, required sections, and forbidden punctuation. Grading uses the vendored official
verifier and makes no grading-model calls.

This notebook runs the SAME benchmark (`ifeval`) across a 2x2 protocol grid, varying exactly one
dimension at a time:

|                | solo                    | panel                                     |
|----------------|-------------------------|-------------------------------------------|
| **no loop**    | plain `sf.Model`        | `sf.Fusion` (drafts blended once)         |
| **corrective** | `sf.SelfCorrective`     | `sf.CorrectiveLoop` (drafts checked, best |
|                | (self-coached retries)  | passing draft submitted verbatim)         |

where `sf.CorrectiveLoop` is the protocol from
[this paper](https://openreview.net/pdf?id=XSIYfTm2h7) """),
        nbformat.v4.new_markdown_cell("""\
<img src="assets/ifeval-benchmark.svg" width="900"
  alt="IFEval at a glance: 541 prompts with machine-checkable constraints, one invocation
  per prompt, free deterministic verification, score = all-strict prompts / 541"/>"""),
        nbformat.v4.new_markdown_cell("""\
![The IFEval protocol grid: solo vs panel, no loop vs corrective](assets/ifeval-protocol-grid.png)
"""),
        nbformat.v4.new_markdown_cell("""\
## Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare ifeval  # first run only: download pinned Benchmark assets
screamingface up             # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished. Stack
management stays outside the notebook so **Run All** never starts or stops local services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## Define models and fusion"""),
        nbformat.v4.new_code_cell("""\
ANSWER_PROMPT = (
    "Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request."
)

PARAMS = {"max_tokens": 8192, "temperature": 0.0}

ministral = sf.Model(
    model="openrouter/mistralai/ministral-3b-2512",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)
phi = sf.Model(
    model="openrouter/microsoft/phi-4",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)"""),
        nbformat.v4.new_code_cell("""\
SYNTHESIS_PROMPT = (
    "Produce one final answer to the original request from the panel drafts. "
    "Preserve every instruction and formatting constraint."
)

deepseek = sf.Model(
    model="openrouter/deepseek/deepseek-v4-flash",
    prompt=SYNTHESIS_PROMPT,
    params=PARAMS,
)

light_open_source = sf.Fusion(
    members=[ministral, phi], name="light_open_source", synthesizer=deepseek
)"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Solo, no loop — canonical baseline"""),
        nbformat.v4.new_code_cell("""\
canonical_solo = sf.evaluate(phi, benchmark="ifeval", limit=1)
canonical_solo"""),
        nbformat.v4.new_markdown_cell("""\
## 2. Panel, no loop — whole-Fusion synthesis"""),
        nbformat.v4.new_code_cell("""\
canonical_fusion = sf.evaluate(light_open_source, benchmark="ifeval", limit=1)
canonical_fusion"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Solo, corrective — `sf.SelfCorrective`

The same model re-sits the exam up to three times, authoring its own study notes from the
check surface's sanitized feedback between sittings. A first-round pass costs one draft and
one free check — nothing else."""),
        nbformat.v4.new_code_cell("""\
self_corrective = sf.evaluate(
    sf.SelfCorrective(phi, max_rounds=3),
    benchmark="ifeval",
    limit=1,
)
self_corrective"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Panel, corrective — `sf.CorrectiveLoop`"""),
        nbformat.v4.new_code_cell("""\
corrective_loop = sf.CorrectiveLoop(members=[ministral, phi], judge=deepseek, max_rounds=3)
corrective_loop"""),
        nbformat.v4.new_code_cell("""\
corrective_loop_report = sf.evaluate(
    corrective_loop,
    benchmark="ifeval",
    limit=2,
)
corrective_loop_report"""),
        nbformat.v4.new_markdown_cell("""\
## 5. Send the score to the Scoreboard

Publication takes the evaluated `CandidateResult` and submits the Benchmark's **native
score** exactly as the Engine graded it — fractional or negative values included — and the
Scoreboard stores and ranks it without recalculating. Opt-in so **Run All** never changes
the public Leaderboard."""),
        nbformat.v4.new_code_cell("""\
PUBLISH_RESULT = False

submission = (
    sf.leaderboards.submit(corrective_loop_report.candidates.only) if PUBLISH_RESULT else None
)
submission"""),
    )


def _draco_full_e2e() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# DRACO Benchmark with ScreamingFace 😱


Deep Research Accuracy, Completeness, and Objectivity (DRACO) Benchmark is an open benchmark for
evaluating deep research agents grounded in how users actually use AI for complex research tasks
published by Perplexity
([blog post](https://research.perplexity.ai/articles/evaluating-deep-research-performance-in-the-wild-with-the-draco-benchmark),
[paper](https://arxiv.org/pdf/2602.11685).
DRACO consists of 100 research tasks, each paired with expert crafted rubrics
averaging ~40 evaluation criteria.

This notebook evaluates DRACO using new models (August 2026) and fusions of these models on
[screamingface](https://github.com/ScreamingFace/screamingface)."""),
        nbformat.v4.new_markdown_cell("""\
<img src="assets/draco-benchmark.svg" width="900"
  alt="DRACO at a glance: 100 research tasks, ~40 weighted rubric criteria each, judge
  answers MET/UNMET per criterion, score = mean of weighted case scores in 0..1"/>"""),
        nbformat.v4.new_markdown_cell("""\
## Running things locally

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare draco  # first run only: download pinned Benchmark assets
screamingface up             # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished. Stack
management stays outside the notebook so **Run All** never starts or stops local services."""),
        nbformat.v4.new_markdown_cell("""\
Export `TAVILY_API_KEY` before `screamingface up`: the Gemini, Kimi, DeepSeek, and
Qwen answer routes use its guarded tool loop, and the Engine fails before model spend when that
required retrieval mechanism is unavailable."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Connect OpenRouter"""),
        nbformat.v4.new_code_cell("""\
sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 2. Define the models"""),
        nbformat.v4.new_code_cell("""\
ANSWER_PROMPT = (
    "You are answering a research-quality prompt. Provide a thorough, "
    "well-reasoned answer in prose. Address every aspect the prompt raises. "
    "Use clear structure (headings, bullet lists where appropriate) and cite "
    "specific facts, methodologies, or sources where relevant.\\n\\n"
    "Do not refuse, abstain, or claim uncertainty unless the question is "
    "genuinely ambiguous — the goal is to demonstrate depth of understanding. "
    "Length: aim for the level of detail the question warrants; brevity that "
    "skips key points will be penalised by the rubric."
)"""),
        nbformat.v4.new_code_cell("""\
PARAMS = {"max_tokens": 32768, "temperature": 0.0}

deepseek = sf.Model(
    model="openrouter/deepseek/deepseek-v4-pro",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)
qwen = sf.Model(
    model="openrouter/qwen/qwen3-coder",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)
glm = sf.Model(
    model="openrouter/z-ai/glm-5.2",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Define the synthesize model and the fusion"""),
        nbformat.v4.new_code_cell("""\
SYNTHESIS_PROMPT = (
    "You are synthesising a single, comprehensive answer to a research-quality "
    "prompt by combining N independent answers from a panel of models. The "
    "downstream grader will score your output against a STRUCTURED RUBRIC of "
    "weighted criteria — your goal is to maximise rubric coverage.\\n\\n"
    "Procedure:\\n"
    "1. Read every panel answer carefully.\\n"
    "2. Identify which claims, facts, citations, or arguments each panel member "
    "contributes that the others miss.\\n"
    "3. Produce ONE unified prose response that:\\n"
    "   - Combines the strongest reasoning from every panel member\\n"
    "   - Preserves specific named entities, dates, methodologies, and citations\\n"
    "   - Resolves disagreements by favouring the more specific / better-cited claim\\n"
    "   - Uses clear structure (headings, lists) where it aids the reader\\n"
    "4. Do not introduce new facts that no panel member provided.\\n"
    "5. Do not hedge or refuse — the panel collectively has enough material.\\n\\n"
    "Output: the unified prose answer, no preamble, no JSON wrapper."
)

kimi = sf.Model(
    model="openrouter/moonshotai/kimi-k3",
    prompt=SYNTHESIS_PROMPT,
    params=PARAMS,
)

best_open_source = sf.Fusion(
    members=[deepseek, glm, qwen], name="best_open_source", synthesizer=kimi
)"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Run DRACO with the fusion"""),
        nbformat.v4.new_code_cell("""\
report = sf.evaluate(best_open_source, benchmark="draco", limit=1)
report"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Send the score to the Scoreboard

Publication takes the evaluated `CandidateResult` and submits the Benchmark's **native
score** exactly as the Engine graded it — fractional or negative values included — and the
Scoreboard stores and ranks it without recalculating. Opt-in so **Run All** never changes
the public Leaderboard."""),
        nbformat.v4.new_code_cell("""\
PUBLISH_RESULT = False

submission = sf.leaderboards.submit(report.candidates.only) if PUBLISH_RESULT else None
submission"""),
    )


_HEALTH_SYNTHESIS_PROMPT_PARTS = (
    "You are synthesising the single best response to a health-related ",
    "conversation by combining independent responses from a panel of models. ",
    "A physician-authored rubric will grade your output per criterion — ",
    "accuracy, completeness, safety, and appropriate hedging all matter; so ",
    "does avoiding harmful or false content.\n\n",
    "Procedure:\n",
    "1. Read every panel response carefully.\n",
    "2. Identify what each contributes that the others miss (facts, safety ",
    "caveats, follow-up questions, care-seeking guidance).\n",
    "3. Produce ONE unified response to the final user turn that:\n",
    "   - Keeps every clinically correct, relevant point\n",
    "   - Drops anything inaccurate, unsafe, or speculative\n",
    "   - Resolves disagreements by favouring the safer, better-supported claim\n",
    "   - Stays concise — verbosity is not rewarded\n",
    "4. Do not introduce claims no panel member made.\n\n",
    "Output: the unified response only, no preamble, no JSON wrapper.",
)


def _healthbench_e2e() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# HealthBench — two boards over one exam

Can a fusion of open-weights models improve on a strong single model across
[HealthBench](https://openai.com/index/healthbench/) Professional conversations?

The Engine serves this exam as **two** boards. Same conversations pool, same
physician-written rubrics, same pinned Judge — they differ in exactly two places:

| | `healthbench-worst30` | `healthbench-professional` |
|---|---|---|
| Conversations asked | the 157 hardest (the 30% top models score worst on) | all 525 |
| Final score | plain average, **negatives kept** | the **official** average, floored at 0 |
| Answers | "how does this do on the hard tail?" | "how does this compare to published numbers?" |

Per-case scoring is identical on both: satisfying a rubric item adds its points, tripping a
safety item subtracts them, so one case can score below zero. The boards only disagree on
what to do with that at the end. On the hardest 157, flooring at 0 would flatten every
entrant to 0.00 — so worst30 keeps the negative. The full board floors it, because that is
what published HealthBench figures do."""),
        nbformat.v4.new_markdown_cell("""\
<img src="assets/healthbench-worst30-benchmark.svg" width="900"
  alt="HealthBench worst-30 at a glance: 157 hardest conversations, physician-written
  rubrics where penalties subtract, unclamped case scores, raw mean keeps negatives"/>"""),
        nbformat.v4.new_markdown_cell("""\
## 0. Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare healthbench  # first run only: download pinned Benchmark assets
screamingface up             # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished. Stack
management stays outside the notebook so **Run All** never starts or stops local services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Run the hard board with 1 model

`limit=1` runs a single Case — a cheap rehearsal that exercises the whole pipeline. Drop
the argument to sit the whole exam."""),
        nbformat.v4.new_code_cell("""\
PARAMS = {"max_tokens": 32768, "temperature": 0.0}

deepseek = sf.Model(
    model="openrouter/deepseek/deepseek-v4-pro",
    params=PARAMS,
)"""),
        nbformat.v4.new_code_cell("""\
deepseek_report = sf.evaluate(deepseek, benchmark="healthbench-worst30", limit=1)
deepseek_report"""),
        nbformat.v4.new_markdown_cell("""\
## 2. Define the Fusion with open source models and evaluate it"""),
        nbformat.v4.new_code_cell("""\
qwen = sf.Model(
    model="openrouter/qwen/qwen3.8-2.4t-a95b",
    params=PARAMS,
)
glm = sf.Model(
    model="openrouter/z-ai/glm-5.2",
    params=PARAMS,
)"""),
        nbformat.v4.new_code_cell("""\
SYNTHESIS_PROMPT = (
    "You are synthesising the single best response to a health-related "
    "conversation by combining independent responses from a panel of models. "
    "A physician-authored rubric will grade your output per criterion — "
    "accuracy, completeness, safety, and appropriate hedging all matter; so "
    "does avoiding harmful or false content.\\n\\n"
    "Procedure:\\n"
    "1. Read every panel response carefully.\\n"
    "2. Identify what each contributes that the others miss (facts, safety "
    "caveats, follow-up questions, care-seeking guidance).\\n"
    "3. Produce ONE unified response to the final user turn that:\\n"
    "   - Keeps every clinically correct, relevant point\\n"
    "   - Drops anything inaccurate, unsafe, or speculative\\n"
    "   - Resolves disagreements by favouring the safer, better-supported claim\\n"
    "   - Stays concise — verbosity is not rewarded\\n"
    "4. Do not introduce claims no panel member made.\\n\\n"
    "Output: the unified response only, no preamble, no JSON wrapper."
)

kimi = sf.Model(
    model="openrouter/moonshotai/kimi-k3",
    params=PARAMS,
    prompt=SYNTHESIS_PROMPT,
)

best_open_source = sf.Fusion(
    members=[deepseek, qwen, glm], name="best_open_source", synthesizer=kimi
)"""),
        nbformat.v4.new_code_cell("""\
worst30_report = sf.evaluate(best_open_source, benchmark="healthbench-worst30", limit=1)
worst30_report"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Run the same Fusion on the full exam

Nothing about the Candidate changes — only the board it sits. This one asks all 525
conversations and reports the official HealthBench score, so its number is the one to put
beside a published figure.

Two things worth knowing before dropping `limit`:

- A full run costs roughly **3.3x** a full worst-30% run per candidate (525 conversations
  instead of 157, each with one Judge call per rubric item).
- The score is floored at 0. A candidate that trips enough safety items lands at 0.00
  here while still ranking above another entrant on the worst-30% board — that is the
  clip doing its job, not a bug."""),
        nbformat.v4.new_code_cell("""\
professional_report = sf.evaluate(best_open_source, benchmark="healthbench-professional", limit=1)
professional_report"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Send the scores to the Scoreboard

Each board has its own Leaderboard, so a Candidate is submitted to each separately.
Publication takes the evaluated `CandidateResult` and submits the Benchmark's **native
score** exactly as the Engine graded it — fractional or negative values included — and the
Scoreboard stores and ranks it without recalculating. Opt-in so **Run All** never changes
the public Leaderboard."""),
        nbformat.v4.new_code_cell("""\
PUBLISH_RESULT = False

submissions = (
    [
        sf.leaderboards.submit(report.candidates.only)
        for report in (worst30_report, professional_report)
    ]
    if PUBLISH_RESULT
    else None
)
submissions"""),
    )


def _gdpval_e2e() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# GDPval — real professional work

Can a fusion of open-weights models beat a strong single model on work that professionals
actually do? [GDPval](https://arxiv.org/abs/2510.04374) is OpenAI's real-work benchmark: tasks
written by practitioners averaging 14 years of experience, across 44 occupations in the nine
largest sectors of US GDP.

The Engine serves `gdpval-text`, the prose-only slice of the 220-task open gold set — 102 tasks
whose reference material and expected deliverable are documents rather than spreadsheets or
slide decks.

**Read this before quoting a number.** This board is deliberately not GDPval's published metric,
in two ways:

- **Grading.** GDPval is scored by blinded expert *pairwise* comparison against a human
  professional's deliverable. This board uses an AI judge against the task's own rubric,
  one criterion at a time.
- **Submission.** GDPval expects the finished document. This board submits plain text —
  83 of these 102 tasks expected a formatted file.

Criteria that check the delivered *file* rather than the answer's content are excluded from
scoring, because a text submission can never satisfy them. So a `gdpval-text` score answers
"does the fusion beat the solo model here?" — never "how do we compare to the GDPval
leaderboard?"."""),
        nbformat.v4.new_markdown_cell("""\
<img src="assets/gdpval-benchmark.svg" width="1200"
  alt="GDPval-text at a glance: 220 open gold tasks filtered to 102 prose cases, reference
  documents parsed once at build time, one judge call per rubric criterion (median 44 per
  task, roughly 4,500 per full run), case score = earned points over positive points with
  negatives subtracting and no clamp, board score = plain mean over 102 cases — deliberately
  not the official pairwise-vs-human GDPval metric"/>"""),
        nbformat.v4.new_markdown_cell("""\
## 0. Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare gdpval  # first run only: download pinned Benchmark assets
screamingface up              # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished.
Stack management stays outside the notebook so **Run All** never starts or stops local
services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Run one case with a single model

`limit=1` runs a single Case — a cheap rehearsal that exercises the whole pipeline. Drop the
argument to sit the whole exam.

Worth knowing before you do: grading fans out **one judge call per rubric criterion**, and these
rubrics carry a median of 44 after filtering. A full 102-task run is roughly 4,500 judge calls
per candidate, so rehearse with `limit` before committing to a full sweep."""),
        nbformat.v4.new_code_cell("""\
gem_flash = sf.Model(
    model="openrouter/google/gemini-3-flash-preview",  # fast, cheap model
    params={"max_tokens": 8192, "temperature": 0.0},
)
report = sf.evaluate(gem_flash, benchmark="gdpval-text", limit=3)
report"""),
        nbformat.v4.new_markdown_cell("""\
## 2. Define a Fusion of open-source models and evaluate it

GDPval rubrics reward breadth, structure and completeness — a median of 44 separately scored
criteria per task. That is union-of-coverage territory: each member contributes partial credit
the others miss, and the synthesiser's job is to keep all of it."""),
        nbformat.v4.new_code_cell("""\
PARAMS = {"max_tokens": 32768, "temperature": 0.0}

deepseek = sf.Model(
    model="openrouter/deepseek/deepseek-v4-pro",
    params=PARAMS,
)
deepseek

qwen = sf.Model(
    model="openrouter/qwen/qwen3.8-2.4t-a95b",
    params=PARAMS,
)
glm = sf.Model(
    model="openrouter/z-ai/glm-5.2",
    params=PARAMS,
)"""),
        nbformat.v4.new_code_cell("""\
SYNTHESIS_PROMPT = (
    "You are producing the single best deliverable for a professional work request by "
    "combining independent drafts from a panel of models. An expert-written rubric will "
    "grade your output criterion by criterion — accuracy, completeness, structure, and "
    "following the request's explicit instructions all matter.\\n\\n"
    "Procedure:\\n"
    "1. Read the request and every panel draft carefully.\\n"
    "2. Identify what each draft contributes that the others miss — figures, sections, "
    "caveats, required fields, recommended next steps.\\n"
    "3. Produce ONE unified deliverable that:\\n"
    "   - Keeps every correct, relevant point from any draft\\n"
    "   - Drops anything inaccurate or unsupported by the reference material\\n"
    "   - Follows every explicit instruction in the request, including structure and "
    "section names\\n"
    "   - Resolves disagreements by favouring the better-supported claim\\n"
    "4. Do not invent figures or facts no draft and no reference material supplied.\\n\\n"
    "Output: the finished deliverable only, no preamble and no commentary about the panel."
)

kimi = sf.Model(
    model="openrouter/moonshotai/kimi-k3",
    params=PARAMS,
    prompt=SYNTHESIS_PROMPT,
)

open_panel = sf.Fusion(members=[deepseek, qwen, glm], name="open_panel", synthesizer=kimi)"""),
        nbformat.v4.new_code_cell("""\
fusion_report = sf.evaluate(open_panel, benchmark="gdpval-text", limit=2)
fusion_report"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Read the per-case scores

A case score is points earned over points winnable. Penalties subtract without widening the
denominator, so a case can score **below zero** — that is intended, not a bug: a harmful answer
should rank below one that said nothing.

A case the judge could not fully grade reports `None` rather than `0.0`. The two are different
facts, and collapsing them would make a judge outage look like model weakness."""),
        nbformat.v4.new_code_cell("""\
for case in fusion_report.candidates.only.cases:
    print(case.case_id, case.status, case.grade.score if case.grade else None)"""),
    )


def _medxpert_e2e() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# MedXpertQA — expert medical multiple choice

[MedXpertQA](https://arxiv.org/abs/2501.18362) is 2,450 expert-written medical questions, each
with ten lettered choices and one correct answer. The model reasons step by step, then commits to
a letter; grading is an exact string match against the published key.

That makes it the cheapest board here to grade — **no judge, no grading tokens at all**. Cost is
entirely answer generation.

**Two things to know before reading a score.**

- The exchange is **two turns**: the model reasons freely, then commits against a bare trigger
  sent as its own turn. That layout is what makes the committed letter come first, which the
  official parser depends on. It also means the board calls your candidate **twice per case**.
- For a **fusion**, those two turns wrap the whole ensemble rather than each member. The Engine
  invokes a candidate as an opaque recipe and cannot reach inside it, so these numbers are not
  comparable to an implementation that runs two-turn per member and shows the synthesiser each
  member's reasoning."""),
        nbformat.v4.new_markdown_cell("""\
<img src="assets/medxpert-benchmark.svg" width="1200"
  alt="MedXpertQA at a glance: 2,450 expert medical MCQs with ten choices, a two-turn
  reason-then-commit exchange, free exact-match grading, score = matching cases / cases run
  with answered_rate reported beside it"/>"""),
        nbformat.v4.new_markdown_cell("""\
## 0. Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare medxpert  # first run only: download pinned Benchmark assets
screamingface up                # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished.
Stack management stays outside the notebook so **Run All** never starts or stops local
services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Run a few cases with one model

`limit` keeps the rehearsal cheap. Grading is free, so what you pay for is two candidate calls
per case — reason, then commit."""),
        nbformat.v4.new_code_cell("""\
PARAMS = {"max_tokens": 32768, "temperature": 0.0}

# gemini = sf.Model(model="openrouter/google/gemini-3.1-pro-preview", params=PARAMS)
# solo = sf.Model(model="openrouter/deepseek/deepseek-v4-flash-0731", params=PARAMS)

member1 = sf.Model(model="openrouter/qwen/qwen3.7-flash", params=PARAMS)
report = sf.evaluate(member1, benchmark="medxpert", limit=2)
report"""),
        nbformat.v4.new_markdown_cell("""\
### Why `max_tokens` is 8192 and not lower

Reasoning models exhaust a smaller budget before they commit and return nothing. That does not
lower their score — it removes them from the comparison, because a model answering 77% of rows is
being measured on a smaller, easier exam than one answering all of them. This board scores an
unanswered case as **wrong** rather than skipping it, which is the official harness's verdict and
keeps two systems on the same denominator."""),
        nbformat.v4.new_code_cell("""\
candidate = report.candidates.only
print("score    :", candidate.score)
print("metrics  :", candidate.metrics)"""),
        nbformat.v4.new_markdown_cell("""\
`answered_rate` is worth reading beside the score. A 40% built from 40% correct is a knowledge
result; a 40% built from 90% correct on the half it answered is a formatting failure, and only
the second is fixed by raising `max_tokens`."""),
        nbformat.v4.new_markdown_cell("""\
## 2. Compare a Fusion against the same model

A fusion is welcome here and the board takes no view on whether it should win. Worth knowing what
the mechanism can and cannot do: an MCQ answer is a single discrete choice, so a synthesiser has
nothing to *merge* — it can only pick among the panel's votes. That is a different situation from
a rubric benchmark, where each member contributes partial credit the others miss."""),
        nbformat.v4.new_code_cell("""\
# The members below are reasoning models: thinking burns output tokens, so give them room.
PANEL_PARAMS = {"max_tokens": 32768, "temperature": 0.0}
SYNTHESIS_PROMPT = (
    "You are given several experts' step-by-step analyses of a multiple-choice medical "
    "question. Weigh their reasoning and the evidence they cite — not merely how many chose "
    "each option — and determine the single best choice."
)

member1 = sf.Model(model="openrouter/qwen/qwen3.7-flash", params=PANEL_PARAMS)
member2 = sf.Model(model="openrouter/google/gemini-3.8-flash", params=PANEL_PARAMS)
synth = sf.Model(
    model="openrouter/anthropic/claude-haiku-4.5", params=PANEL_PARAMS, prompt=SYNTHESIS_PROMPT
)
panel = sf.Fusion(name="medical_panel", members=[member1, member2], synthesizer=synth)

panel"""),
        nbformat.v4.new_code_cell("""\
fusion_report = sf.evaluate(panel, benchmark="medxpert", limit=5)
fusion_report"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Read the per-case outcomes

Each case is one bit: the committed letter matched the key or it did not. The check row carries
what the model committed and what was expected, so a wrong answer can be inspected rather than
just counted."""),
        nbformat.v4.new_code_cell("""\
for case in fusion_report.candidates.only.cases:
    grade = case.grade
    print(case.case_id, case.status, grade.score if grade else None)"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Before you scale up

A `limit=N` run is a smoke test, not a ranking. On the full set, temperature-0 sampling does not
make the leaderboard stable — small subsamples reshuffle it — so a difference of a point or two
between two systems on a handful of cases is noise, not a result. Run the whole set before
quoting a comparison."""),
    )


def _inspect_evals_boards() -> NotebookNode:
    # FEATURE: OME-1202 — the front door to the imported catalogue: list the two origin
    # groups, pick an imported board, run a fusion against it. STORY: as a researcher who
    # heard "we import inspect_evals benchmarks now", I see what's on the shelf and run
    # one, without reverse-engineering SDK calls from tickets or source.
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# The benchmark catalogue — ours and imported

The catalogue no longer holds only ScreamingFace-authored boards. Benchmarks imported from
[inspect_evals](https://ukgovernmentbeis.github.io/inspect_evals/) — GSM8K, MMLU, ARC, BoolQ and
friends — sit beside them as first-class boards: same listing, same `sf.evaluate(...)` call, same
report.

Every benchmark carries an **origin**, and the listing renders one group per origin, so you can
always tell what we built from what we brought in. An imported board keeps its source eval's own
scorer — the upstream grading logic is called, never reimplemented — and its dataset is snapshotted
and pinned at import time, so a published board never drifts under you.

This notebook walks the whole path: list the catalogue → read an imported board's card → run a
fusion against it."""),
        nbformat.v4.new_markdown_cell("""\
## 0. Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface up      # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished.
Stack management stays outside the notebook so **Run All** never starts or stops local services.

**Where the imported boards live.** An Engine serves imported boards only when it runs with its
`inspect` extra (the upstream scorers come from `inspect-ai`, which cannot co-install with the
local runtime's dependencies — a declared conflict, not an accident). The local
`screamingface up` stack therefore lists the ScreamingFace group only. **An inspect-capable
Engine is a prerequisite for everything past section 1**: the listing works against any Engine,
and the first cell of section 2 checks for the imported shelf and stops with guidance rather
than failing partway through. To browse and run the imported catalogue, point the SDK at an
inspect-capable Engine before starting the kernel:

```bash
export SCREAMINGFACE_ENGINE_URL="https://<an-engine-with-the-inspect-extra>"
```

Leaving it unset falls back to a running local stack, then to the hosted default.

**Running one yourself, from a checkout.** The `just local-stack-notebooks` recipe above does
exactly this: it bakes the imported snapshots, serves an inspect-capable Engine beside the
`screamingface up` stack on a free port — reaching the same Gateway on `:9105`, so only the
Engine URL changes — and exports `SCREAMINGFACE_ENGINE_URL` for the kernel it opens."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 1. List the catalogue — one group per origin

The listing groups by each benchmark's `origin`: a **ScreamingFace** tab for our boards, first,
and an **inspect_evals** tab linking to the source collection. Without `ipywidgets` the same
grouping renders as titled sections. The search box filters rows inside every group."""),
        nbformat.v4.new_code_cell("""\
benchmarks = sf.benchmarks.list()
benchmarks"""),
        nbformat.v4.new_markdown_cell("""\
## 2. Read an imported board's card

Imported boards are named `inspect-<key>` after their upstream eval. We'll use **GSM8K** —
grade-school math word problems, graded by the eval's own numeric match against the published
answer. That grading is free: no judge, no grading tokens, so cost is answer generation only.

The card carries the provenance: `origin` names the source collection, and `revision` pins the
imported dataset snapshot — two catalogues showing the same revision asked the exact same
questions.

The first lines below are the gate from section 0: if this Engine serves no imported boards,
the notebook stops here with directions instead of failing on the lookup."""),
        nbformat.v4.new_code_cell("""\
if not any(benchmark.origin == "inspect_evals" for benchmark in benchmarks):
    raise RuntimeError(
        "this Engine serves no imported boards — the rest of this notebook needs an "
        "Engine running with its inspect extra; see section 0 for how to point "
        "SCREAMINGFACE_ENGINE_URL at one"
    )

gsm8k = sf.benchmarks.get("inspect-gsm8k")
{
    "id": gsm8k.id,
    "title": gsm8k.title,
    "origin": gsm8k.origin,
    "revision": gsm8k.revision,
    "case_count": gsm8k.case_count,
}"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Run a fusion against it

An imported board takes a fusion exactly like a home-grown one — the Engine invokes the candidate
as an opaque recipe, so nothing about the import changes how ensembles run. `limit` keeps the
rehearsal cheap; the calls below are paid model calls, so run this cell deliberately and rehearse
small before any full sweep."""),
        # WHY an all-OpenRouter panel rather than the Anthropic synthesiser used elsewhere in
        # these examples: the seeded cells below are the point of this section, and the SDK's
        # free preflight REFUSES a seeded run whose catalogue marks `seed` unsupported
        # (OME-1231). An Anthropic synthesiser would make the seeded cells raise.
        nbformat.v4.new_code_cell("""\
PANEL_PARAMS = {"max_tokens": 8192, "temperature": 0.0}
SYNTHESIS_PROMPT = (
    "You are given several models' step-by-step solutions to a grade-school math word "
    "problem. Check each chain of arithmetic, resolve any disagreement by re-deriving the "
    "disputed step, and answer with the single final number."
)

member1 = sf.Model(model="openrouter/qwen/qwen3.7-flash", params=PANEL_PARAMS)
member2 = sf.Model(model="openrouter/google/gemini-3.8-flash", params=PANEL_PARAMS)
synth = sf.Model(
    model="openrouter/qwen/qwen3.8-flash", params=PANEL_PARAMS, prompt=SYNTHESIS_PROMPT
)
math_panel = sf.Fusion(name="math_panel", members=[member1, member2], synthesizer=synth)

math_panel"""),
        nbformat.v4.new_code_cell("""\
report = sf.evaluate(math_panel, benchmark="inspect-gsm8k", limit=2)
report"""),
        nbformat.v4.new_markdown_cell("""\
### Asking for a reproducible run

`answer_seed` pins the sampler for every model in the fusion — members and synthesiser
alike — so the same seed asks each provider for the same draw twice.

A seed only means something if every model honours it, so the SDK checks the whole panel
before spending anything: if a provider's catalogue says outright that the model does not
support `seed`, the run is refused up front rather than sampled unseeded and reported as
though it were reproducible. That is why this panel is all-OpenRouter — an Anthropic
synthesiser would be refused here, since the Messages API has no seed field at all.

Changing the seed is the cheapest way to separate the panel from the draw: what stays the
same across the two runs below is the panel, what moves is the sampling."""),
        nbformat.v4.new_code_cell("""\
report1 = sf.evaluate(math_panel, benchmark="inspect-gsm8k", limit=2, answer_seed=42)
report1"""),
        nbformat.v4.new_code_cell("""\
report2 = sf.evaluate(math_panel, benchmark="inspect-gsm8k", limit=2, answer_seed=7)
report2"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Read the per-case outcomes

Each case is one bit — the committed number matched the key or it did not — and the check row
carries what the candidate answered against what was expected, so a miss can be inspected rather
than just counted."""),
        nbformat.v4.new_code_cell("""\
for case in report.candidates.only.cases:
    grade = case.grade
    print(case.case_id, case.status, grade.score if grade else None)"""),
        nbformat.v4.new_markdown_cell("""\
## 5. A multiple-choice board — same calls, one thing to change

`inspect-mmlu` is 57 subjects of four-option questions, graded by the eval's `choice`
scorer against the published letter. The SDK calls are identical to section 3; what has to
change is the **synthesiser's prompt**, because the answer format did. Asking for "the
single final number" on a board that wants `A`/`B`/`C`/`D` is how a panel scores zero
while answering correctly.

Worth knowing about MCQ boards: a fusion has less to do here than on free text. A choice is
one discrete token, so the synthesiser cannot *merge* partial credit the way it can on a
rubric board — it can only weigh votes and pick. The two families are not comparable in
what they ask of an ensemble."""),
        nbformat.v4.new_code_cell("""\
MCQ_SYNTHESIS_PROMPT = (
    "You are given several experts' analyses of one multiple-choice question. Weigh their "
    "reasoning and the evidence they cite — not merely how many chose each option — and "
    "answer with the single best choice."
)

mcq_synth = sf.Model(
    model="openrouter/anthropic/claude-haiku-4.5",
    params=PANEL_PARAMS,
    prompt=MCQ_SYNTHESIS_PROMPT,
)
mcq_panel = sf.Fusion(name="mcq_panel", members=[member1, member2], synthesizer=mcq_synth)

mmlu_report = sf.evaluate(mcq_panel, benchmark="inspect-mmlu", limit=2)
mmlu_report"""),
        nbformat.v4.new_markdown_cell("""\
## 6. A yes/no board

`inspect-boolq` asks a reading-comprehension question whose answer is `Yes` or `No`, graded
by the eval's `pattern` scorer against a regex anchored at the end of the reply. That anchor
is the whole trick: a model that reasons for a paragraph and finishes with "Yes" scores,
while one that opens with "Yes, because…" does not. Say so in the prompt.

This board is free text rather than a fixed set of options, so unlike the MCQ boards it
carries a **check surface** — the mid-run pass/fail signal a `corrective_loop` reads (see
`09_corrective_loops.ipynb`). MCQ boards are refused one deliberately: pass/fail feedback
over four options is an elimination attack, not a hint."""),
        nbformat.v4.new_code_cell("""\
BOOLQ_SYNTHESIS_PROMPT = (
    "You are given several experts' readings of one passage and a yes/no question about it. "
    "Weigh their reasoning, then end your reply with exactly one word — Yes or No — as the "
    "final word, with nothing after it."
)

boolq_synth = sf.Model(
    model="openrouter/anthropic/claude-haiku-4.5",
    params=PANEL_PARAMS,
    prompt=BOOLQ_SYNTHESIS_PROMPT,
)
boolq_panel = sf.Fusion(name="boolq_panel", members=[member1, member2], synthesizer=boolq_synth)

boolq_report = sf.evaluate(boolq_panel, benchmark="inspect-boolq", limit=2)
boolq_report"""),
        nbformat.v4.new_code_cell("""\
for case in boolq_report.candidates.only.cases:
    grade = case.grade
    print(case.case_id, case.status, grade.score if grade else None)"""),
        nbformat.v4.new_markdown_cell("""\
## 7. An LLM-judged board — grading is a model call too

`inspect-frontierscience` is 160 frontier-level physics, chemistry and biology problems
([FrontierScience](https://openai.com/index/frontierscience/), by OpenAI) in two formats:
olympiad-style short answers and open research questions. There is no answer key to
string-match — grading is the eval's own **LLM judge**, reading each reply against the
official grading prompt (olympiad) or a per-case rubric (research).

Three things change when the judge is a model:

- **Grading costs tokens.** Every judge call is routed and metered through the same
  gateway as the panel's own calls, so the report's cost covers answering *and* grading —
  a judged score that omitted judge cost would be wrong by construction.
- **The judge is exam identity.** The judge model, its pinned params, and its grading
  prompt are hashed into the board's `revision` — swap any of them and it is a different
  exam, published under a different revision. (This board pins the same house judge our
  own judged boards use; its scores are therefore **not comparable** to the paper's
  published numbers, which were graded by a different judge.)
- **Partial credit exists.** Research answers earn rubric points (normalised to 0–1), so
  a fusion can genuinely merge partial solutions here — the opposite of the MCQ family.

Judged boards carry **no check surface**: a mid-run check would spend judge tokens on
every attempt. And `limit` matters twice now — each case below pays for the panel's
answers *and* one judge call."""),
        nbformat.v4.new_code_cell("""\
PANEL_PARAMS = {"max_tokens": 32768, "temperature": 0.0}  # increase max tokens for frontierscience

# Rebuild the members too: they captured the 8192 cap when they were created above, and
# reasoning models spend most of it thinking, so a research derivation stops mid-answer.
member1 = sf.Model(model="openrouter/qwen/qwen3.7-flash", params=PANEL_PARAMS)
member2 = sf.Model(model="openrouter/google/gemini-3.8-flash", params=PANEL_PARAMS)

SCIENCE_SYNTHESIS_PROMPT = (
    "You are given several models' step-by-step solutions to a frontier-level science "
    "problem. Check each derivation, resolve any disagreement by re-deriving the disputed "
    "step, and commit to one final answer, stated precisely. Every explicit constraint in "
    "the problem is a hard requirement: check your final answer against each one, and never "
    "trade a stated constraint for an answer that seems better."
)

science_synth = sf.Model(
    model="openrouter/anthropic/claude-haiku-4.5",
    params=PANEL_PARAMS,
    prompt=SCIENCE_SYNTHESIS_PROMPT,
)
science_panel = sf.Fusion(
    name="science_panel", members=[member1, member2], synthesizer=science_synth
)

science_panel"""),
        nbformat.v4.new_code_cell("""\
frontierscience_report = sf.evaluate(science_panel, benchmark="inspect-frontierscience", limit=2)
frontierscience_report"""),
        nbformat.v4.new_markdown_cell("""\
### The judge's reasoning rides the report

A judged grade is not a bare number: each case's check evidence carries the judge's own
explanation verbatim, so a surprising score can be read, not just counted — which judge
prompt the case got, what the judge said, and what grade it committed."""),
        nbformat.v4.new_code_cell("""\
for case in frontierscience_report.candidates.only.cases:
    grade = case.grade
    print(case.case_id, case.status, grade.score if grade else None)

first = frontierscience_report.candidates.only.cases[0].grade
() if first is None or not first.checks else first.checks[0].evidence"""),
        nbformat.v4.new_markdown_cell("""\
## 8. The rest of the shelf

Four sections, four grading families, one set of calls — that is the whole point of the
import. The rest of the shelf works the same way; pick an id from the inspect_evals group
in section 1 and match the synthesiser's prompt to how that board is graded:

- **A final number**, graded by numeric match — `inspect-gsm8k`, `inspect-aime24`,
  `inspect-aime25`.
- **A letter**, graded by the `choice` scorer — `inspect-mmlu`, `inspect-mmlu_pro`,
  `inspect-arc_easy`, `inspect-arc_challenge`, `inspect-commonsense_qa`,
  `inspect-winogrande`, `inspect-race_h`, `inspect-musr`, `inspect-hellaswag`,
  `inspect-wmdp_bio`, `inspect-wmdp_chem`, `inspect-wmdp_cyber`.
- **Yes / No as the last word**, graded by an anchored pattern — `inspect-boolq`.
- **yes / no anywhere in the reply**, graded by `includes` — `inspect-paws`.
- **An open science answer**, graded by the eval's own LLM judge through our gateway —
  `inspect-frontierscience` (section 7).

A `limit=N` run is a smoke test, not a ranking: on small subsamples a point or two between
two systems is noise. Run the whole set before quoting a comparison, and read `coverage`
beside the score — these boards score the gradeable subset and publish how much of the run
that was, so a good score over thin coverage is a formatting failure wearing a knowledge
result's clothes."""),
    )


def _contracteval_e2e() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# ContractEval — find the clause, scored by pure string matching

[ContractEval](https://arxiv.org/abs/2508.03080) gives a model a full commercial contract and one
of 41 clause categories, and asks it to quote the answering sentences **verbatim** — or to reply
`"No related clause."` if the contract has none. 4,182 questions over 102 real contracts, from
the [CUAD](https://huggingface.co/datasets/theatticusproject/cuad-qa) test split.

Grading is string containment: every gold sentence must appear in the reply, with **no partial
credit**. No judge, no grading tokens — like MedXpertQA, what you pay for is answer generation.

**Two things to know before reading a score.**

- **70.3% of rows have no clause.** A model that always says "No related clause." is right on
  every one of them and scores ~70% *accuracy* while answering nothing. That is why the headline
  score here is **F1**, not accuracy — F1 scores that model 0.
- **The score is not a mean of case scores.** F1 comes from a confusion matrix built across the
  whole run, so a 5-case rehearsal produces a number that is real but extremely coarse."""),
        nbformat.v4.new_markdown_cell("""\
## 0. Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare contracteval  # first run only: download pinned Benchmark assets
screamingface up                    # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished.
Stack management stays outside the notebook so **Run All** never starts or stops local
services."""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## 1. Run a few cases with one model

Contracts are long — the median case is about 5,400 input tokens and the largest is ~63,000 — so
`limit` matters more here than on most boards. The answer itself is short: a few quoted
sentences, or the refusal string."""),
        nbformat.v4.new_code_cell("""\
# No `temperature` here on purpose: several current reasoning models reject the parameter
# outright — OpenRouter answers `openai/gpt-5.5` with a 404 for ANY temperature value, and
# `anthropic/claude-opus-4.8` with a 400 — while `gemini-3.1-pro-preview` and
# `qwen/qwen3.7-flash` accept it. The reference harness calls at temperature 0; omitting it
# leaves each provider on its own default, which is the only setting that works across a
# mixed panel. Add `"temperature": 0.0` back for a model you know accepts it.
PARAMS = {"max_tokens": 4096}

solo = sf.Model(model="openrouter/openai/gpt-5.5", params=PARAMS)
report = sf.evaluate(solo, benchmark="contracteval", limit=5)
report"""),
        nbformat.v4.new_markdown_cell("""\
### Reading the metrics

`score` is F1. Beside it the board reports the whole confusion matrix, so you can see *which*
mistake a model is making rather than only how often:

- **`false_no_related_clause_rate`** — the paper calls this *laziness*: how often the model
  claimed no clause exists when one did. This is the refusal lever, and it is the number that
  separates a cautious model from a knowledgeable one.
- **`recall`** vs **`precision`** — low recall means it misses real clauses; low precision means
  it answers when it should have abstained.
- **`jaccard_mean`** — token overlap on the rows that *do* have a clause, so a model that found
  roughly the right passage but not exactly scores above one that was nowhere near."""),
        nbformat.v4.new_code_cell("""\
candidate = report.candidates.only
print("score (F1):", candidate.score)
for key, value in candidate.metrics.items():
    print(f"  {key:32s} {value}")"""),
        nbformat.v4.new_markdown_cell("""\
## 2. Compare a Fusion against the same model

The board takes no view on whether a fusion should win. Worth knowing what the mechanism has to
work with: unlike an MCQ, the answer here is *text a member either quoted or did not*, so a
synthesiser has something real to reconcile. It also has a way to lose — a synthesiser that
paraphrases its members instead of copying their quotes scores zero on rows they got right."""),
        nbformat.v4.new_code_cell("""\
SYNTHESIS_PROMPT = (
    "You are given several assistants' attempts to extract the clause sentences answering a "
    "question about a contract. Choose the sentences best supported by the contract text. "
    "Reproduce them EXACTLY as they appear — never paraphrase, reword, or summarise. If none "
    'of the attempts identifies a genuinely relevant clause, reply "No related clause."'
)

member1 = sf.Model(model="openrouter/openai/gpt-5.5", params=PARAMS)
member2 = sf.Model(model="openrouter/google/gemini-3.1-pro-preview", params=PARAMS)
synth = sf.Model(
    model="openrouter/anthropic/claude-opus-4.8", params=PARAMS, prompt=SYNTHESIS_PROMPT
)
panel = sf.Fusion(name="contract_panel", members=[member1, member2], synthesizer=synth)

fusion_report = sf.evaluate(panel, benchmark="contracteval", limit=5)
fusion_report"""),
        nbformat.v4.new_markdown_cell("""\
## 3. Read the per-case outcomes

Each case is one bit: every gold sentence was quoted, or it was not. The check row records
whether the model abstained and how many gold sentences the case had, so a wrong answer can be
inspected rather than just counted."""),
        nbformat.v4.new_code_cell("""\
for case in fusion_report.candidates.only.cases:
    grade = case.grade
    metrics = grade.metrics if grade else {}
    print(
        case.case_id,
        case.status,
        grade.score if grade else None,
        "positive" if metrics.get("is_positive") else "negative",
        "abstained" if metrics.get("abstained") else "answered",
    )"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Before you scale up

A `limit=N` run is a smoke test, not a ranking — and on this board it is coarser than most,
because F1 over five cases is built from a handful of confusion-matrix cells. With 70% of rows
negative, a small sample can easily contain no positive case at all, which makes precision and
recall undefined and the score 0. Run the full set before quoting any comparison.

**Know what the full set costs before you start it.** Contracts are long: the median case is
about 5,400 input tokens, so one pass over all 4,182 rows is roughly **23M input tokens per
panel member** — multiply by your members, and again by the synthesiser if it sees their
answers. There is no spend cap in this stack, so `limit` is the only brake. Raise it in steps
and read the cost in `report.usage` as you go."""),
    )


def _corrective_loops() -> NotebookNode:
    return _notebook(
        nbformat.v4.new_markdown_cell("""\
# Corrective loops across the benchmark suite

`sf.CorrectiveLoop` (the protocol from [this paper](https://openreview.net/pdf?id=XSIYfTm2h7))
runs a
panel of members against each Case, checks every draft mid-run on the Benchmark's advertised
check surface, and — when a draft fails — feeds the sanitized verification feedback through a
judge-coached rewrite, up to `max_rounds`. The best passing draft is submitted verbatim.

Every installed Benchmark advertises whether its check surface is free or paid:

| Benchmark | Checked by | Mid-run check cost |
|---|---|---|
| `ifeval` | vendored official verifier (deterministic) | free |
| `healthbench-worst30` | pinned GPT-5.4 rubric Judge | **paid — every round spends judge tokens** |
| `healthbench-professional` | the same pinned Judge | **paid — and 525 Cases, not 157** |
| `draco` | pinned Gemini rubric Judge | **paid — every round spends judge tokens** |"""),
        nbformat.v4.new_markdown_cell("""\
## Before running

Working from a checkout? `just local-stack-notebooks` in `packages/screamingface/` does every step
below — assets, stack, and Jupyter — in one command. Otherwise, from a terminal:

```bash
screamingface prepare --all  # first run only: download all three Benchmark assets
screamingface up             # start Gateway :9105, Scoreboard :9106, and Engine :9108
screamingface status
```

Use `screamingface logs` to inspect startup failures and `screamingface down` when finished.

For DRACO, export `TAVILY_API_KEY` before `screamingface up`: the answer routes use its guarded
tool loop, and the Engine fails before model spend when that retrieval mechanism is missing.
"""),
        nbformat.v4.new_code_cell("""\
import screamingface as sf

sf.connect()"""),
        nbformat.v4.new_markdown_cell("""\
## Define the panel and the judge"""),
        nbformat.v4.new_code_cell("""\
ANSWER_PROMPT = (
    "Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request."
)

PARAMS = {"max_tokens": 16384, "temperature": 0.0}

deepseek = sf.Model(
    model="openrouter/deepseek/deepseek-v4-pro",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)
qwen = sf.Model(
    model="openrouter/qwen/qwen3.8-2.4t-a95b",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)
glm = sf.Model(
    model="openrouter/z-ai/glm-5.2",
    prompt=ANSWER_PROMPT,
    params=PARAMS,
)"""),
        nbformat.v4.new_code_cell("""\
SYNTHESIS_PROMPT = (
    "Produce one final answer to the original request from the panel drafts. "
    "Preserve every instruction and formatting constraint."
)

kimi = sf.Model(
    model="openrouter/moonshotai/kimi-k3",
    prompt=SYNTHESIS_PROMPT,
    params=PARAMS,
)

corrective_loop = sf.CorrectiveLoop(members=[deepseek, qwen, glm], judge=kimi, max_rounds=3)
corrective_loop"""),
        nbformat.v4.new_markdown_cell("""\
## 1. IFEval — free deterministic checks

A first-round pass costs the member drafts and nothing else; only correction rounds add spend.
"""),
        nbformat.v4.new_code_cell("""\
ifeval_report = sf.evaluate(corrective_loop, benchmark="ifeval", limit=1)
ifeval_report"""),
        nbformat.v4.new_markdown_cell("""\
## 2. HealthBench worst-30% — paid rubric checks

The physician-authored rubric is graded by the pinned Judge, so every round — including a
first-round pass — makes one judge call per draft."""),
        nbformat.v4.new_code_cell("""\
healthbench_report = sf.evaluate(corrective_loop, benchmark="healthbench-worst30", limit=1)
healthbench_report"""),
        nbformat.v4.new_markdown_cell("""\
## 3. DRACO — paid rubric checks

Research-quality prompts with weighted rubrics; the longest and most expensive of the three.
"""),
        nbformat.v4.new_code_cell("""\
draco_report = sf.evaluate(corrective_loop, benchmark="draco", limit=1)
draco_report"""),
        nbformat.v4.new_markdown_cell("""\
## 4. Send the scores to the Scoreboard

Publication takes the evaluated `CandidateResult` and submits the Benchmark's **native
score** exactly as the Engine graded it — fractional or negative values included — and the
Scoreboard stores and ranks it without recalculating. Opt-in so **Run All** never changes
the public Leaderboard."""),
        nbformat.v4.new_code_cell("""\
PUBLISH_RESULT = False

submissions = (
    [
        sf.leaderboards.submit(report.candidates.only)
        for report in (ifeval_report, healthbench_report, draco_report)
    ]
    if PUBLISH_RESULT
    else None
)
submissions"""),
    )


def main() -> None:
    examples = Path(__file__).parents[1] / "examples"
    for name, value in notebooks().items():
        nbformat.write(value, examples / name)


if __name__ == "__main__":
    main()
