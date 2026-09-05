"""Build the public v1 notebooks deterministically."""

from __future__ import annotations

import json
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
    }


def _notebook(*cells: NotebookNode) -> NotebookNode:
    for index, cell in enumerate(cells, 1):
        cell["id"] = f"cell-{index:02d}"
    return nbformat.v4.new_notebook(
        cells=list(cells),
        metadata={
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

From a terminal:

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

From a terminal:

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

From a terminal:

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

From a terminal:

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

From a terminal:

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

From a terminal:

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
## 0. Before running

From a terminal:

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
PARAMS = {"max_tokens": 8192, "temperature": 0.0}

gemini = sf.Model(model="openrouter/google/gemini-3.1-pro-preview", params=PARAMS)
report = sf.evaluate(gemini, benchmark="medxpert", limit=5)
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
qwen = sf.Model(model="openrouter/qwen/qwen3.8-2.4t-a95b", params=PARAMS)
deepseek = sf.Model(model="openrouter/deepseek/deepseek-v4-pro", params=PARAMS)

SYNTHESIS_PROMPT = (
    "You are given several experts' step-by-step analyses of a multiple-choice medical "
    "question. Weigh their reasoning and the evidence they cite — not merely how many chose "
    "each option — and determine the single best choice."
)
kimi = sf.Model(model="openrouter/moonshotai/kimi-k3", params=PARAMS, prompt=SYNTHESIS_PROMPT)

panel = sf.Fusion(members=[gemini, qwen, deepseek], name="medical_panel", synthesizer=kimi)"""),
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

From a terminal:

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
