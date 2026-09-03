# screamingface

Evaluate composable Candidate Recipes against URL4-native research Benchmarks.

> **Development status:** immutable Model/Fusion/Pipeline authoring, Engine-backed discovery, the direct
> evaluation API, and the confirmed `url4-cloud` lifecycle are implemented. The current MVP
> Engine publishes canonical `draco`, canonical `ifeval`, and the separately named
> `healthbench-worst30` challenge as complete URL4 Benchmark resources. There is no fixture,
> embedded benchmark runtime, or Client-side execution fallback.

## Local notebook runtime

Install the SDK, notebook tools, and local services together:

```bash
pip install "screamingface[runtime,notebook]"
screamingface prepare draco  # first run only
screamingface up
```

`screamingface up` starts AI Gateway, Scoreboard, and the Engine in the background. Use
`screamingface status`, `screamingface doctor`, `screamingface logs`, `screamingface restart`, and
`screamingface down` to manage them. Runtime state is stored under `~/.screamingface` by default;
set `SCREAMINGFACE_DATA_DIR` or pass `--data-dir` to override it.

The default service ports are Gateway `9105`, Scoreboard `9106`, and Engine `9108`. Override them
with `--gateway-port`, `--scoreboard-port`, and `--engine-port`, or the corresponding
`SCREAMINGFACE_GATEWAY_PORT`, `SCREAMINGFACE_SCOREBOARD_PORT`, and `SCREAMINGFACE_ENGINE_PORT`
environment variables. `screamingface up` prints the resolved SDK environment variables; the SDK
does not switch away from its hosted defaults automatically.

For scripts and troubleshooting:

```bash
screamingface status --json
screamingface doctor
screamingface logs --service engine --tail 100 --no-follow
screamingface prepare --list
```

Logs are timestamped, tagged by service, rotated at 10 MiB, and retain five backups. Benchmark
preparation records a versioned manifest, skips current assets, and supports `--force` when a
fresh download is required.

## Target v1 workflow

The approved Python workflow is:

```python
import screamingface as sf

sf.connect()  # notebook panel; connect any providers enabled by this Engine

opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
gpt = sf.Model("openrouter/openai/gpt-5.5")

frontier_pair = sf.Fusion(
    [opus, gpt],
    name="frontier-pair",
    synthesizer="openrouter/anthropic/claude-opus-4.8",
)

report = sf.evaluate(
    [opus, gpt, frontier_pair],
    benchmark="draco",
    limit=1,
)
```

`evaluate(...)` requires an explicit Benchmark id, fetches its Candidate-independent URL4
expression once, compiles and structurally links every Candidate, executes those complete URL4s
concurrently, and returns one immutable `Report` in declared order. There is no implicit default
Benchmark selection. All no-spend validation finishes before the first paid Run starts. Execution
requires a Benchmark Runner image containing the expression's referenced data, grading, and
Aggregation routes.

A complete evaluation URL4 is already linked to its Benchmark and can be evaluated directly. The
Client validates the embedded Candidate projection, executes that exact expression, and recovers
the pinned Benchmark identity from the Engine result:

```python
score = sf.leaderboards.get_score(score_id)
editable_python = score.url4.to_python()
replayed_report = sf.evaluate(score.url4)
```

`Url4.to_python()` is local and no-spend: it returns a `str` of Python source, not live objects —
the `sf.Model`, `sf.Fusion`, `sf.Pipeline`, `sf.CorrectiveLoop`, or `sf.SelfCorrective` written
back out as editable code, plus the recovered Benchmark call. Raw URL4 evaluation does not accept
`benchmark=` or `limit=` because either would imply recompiling an already-complete expression.
Replay starts a new, potentially paid Run; identical URL4 does not guarantee identical model
output.

Every Client-compiled Candidate URL4 contains exactly one inert `_sf_recipe` source with the
versioned `screamingface.recipe.v1` descriptor. It preserves the public Recipe structure and names
for exact replay reporting and `to_python()` reconstruction. These operations require that
descriptor; the Client does not guess authoring structure from an executable call graph.

The installed `draco` definition always refers to the complete official 100-task Benchmark;
`limit=1` merely runs one Case. Grading uses five independent Judge passes per criterion. The
current executable Judge is `openrouter/google/gemini-3.1-pro-preview`, Google's official
replacement for the paper's retired `Gemini-3-Pro Preview`. Reports should disclose that Judge
version difference when comparing scores with the paper.

Benchmark IDs are flat, complete identities. Bounded development runs use `limit` without changing
the named protocol: `benchmark="draco", limit=1` still uses canonical DRACO's full rubric and five
Judge passes. The non-canonical HealthBench challenge is therefore named independently as
`healthbench-worst30`, rather than presented as a canonical HealthBench variant.

### Candidate policy

Models work without prompt configuration. For a Fusion that produces a final answer, name its
synthesizer explicitly; neither the Engine catalogue nor a Benchmark silently chooses one. The SDK
supplies general answer and constraint-aware synthesis prompts, then embeds the explicit Model
routes and resolved prompt defaults in the final URL4:

```python
plain = sf.Model("openrouter/openai/gpt-5.5")
pair = sf.Fusion(
    [opus, gpt],
    synthesizer="openrouter/anthropic/claude-opus-4.8",
)
```

Researchers can override only Candidate-owned policy when an experiment needs it:

```python
careful = sf.Model(
    "openrouter/openai/gpt-5.5",
    prompt="Answer from primary evidence and follow every requested output constraint.",
    params={"reasoning_effort": "high"},
)

constraint_aware = sf.Fusion(
    [opus, gpt],
    synthesizer=sf.Model(
        "openrouter/openai/gpt-5.5",
        prompt="Produce one final answer that preserves every constraint in the original request.",
        params={"reasoning_effort": "high"},
    ),
)
```

These overrides never alter Benchmark-owned Cases, fixed Judge models or prompts, Grading, or
Aggregation. Prompt defaults and explicit overrides are embedded in each final URL4. Every Fusion
requires an explicit `synthesizer=` and always produces one answer. Model-call parameters are never
invented by the SDK: a parameter-free Model emits no sampling or retrieval parameters and therefore
uses the Engine's configured defaults. Benchmarks may still impose explicit execution policy in
their own URL4 protocol. Transport, routing, tool, and Benchmark-policy fields remain unavailable
through Candidate `params`.

### Serial and recursive composition

Every complete `Recipe` accepts one input and returns one final answer. `Model` is atomic,
`Fusion` runs members in parallel and passes their answers to a synthesizer, and `Pipeline` passes
one answer through ordered serial stages:

```python
draft = sf.Model("openrouter/openai/gpt-5.5")
review = sf.Model(
    "openrouter/anthropic/claude-opus-4.8",
    prompt="Review the previous answer and return a corrected answer.",
)
final = sf.Model(
    "openrouter/openai/gpt-5.5",
    prompt="Polish the previous answer without adding unsupported claims.",
)

review_chain = sf.Pipeline([draft, review, final], name="review-chain")
same_chain = draft.then(review).then(final)
```

The first Pipeline stage receives the Candidate input; each later stage receives only the previous
stage's answer. No original input or accumulated history is injected implicitly. Pipelines and
complete Fusions compose recursively, including in the synthesis role:

```python
judge = sf.Model("openrouter/anthropic/claude-opus-4.8")
writer = sf.Model("openrouter/openai/gpt-5.5")

candidate = sf.Fusion(
    [
        review_chain,
        sf.Model("openrouter/google/gemini-3.1-pro-preview"),
    ],
    synthesizer=sf.Pipeline([judge, writer]),
)
```

`Pipeline([...])` is the canonical serial representation; `.then(...)` is immutable shorthand and
never executes work. Every Recipe-valued position also accepts a model-route string as shorthand
for `sf.Model(...)`. Shape mismatches, cycles, invalid models, and invalid parameters fail before
spend.

Each flat Benchmark resource uses `screamingface.benchmark.v1` and carries one canonical `url4`
plus an opaque immutable `revision`. The SDK fetches the requested id, compiles a Recipe
into an expression accepting `$input`, and links it through the single universal `$candidate`
binding. A Benchmark invokes that bound expression through `/candidate`; that route evaluates it
inside the same Engine job, not through an additional Client or control-plane request. Old
structural member/synthesizer bindings fail with a typed planning error rather than invoking a
second Client compilation path.

The Candidate input is normally plain text. Engine-owned Benchmarks that require native chat
history wrap structured turns in the versioned Candidate-input envelope; the Runner preserves
their roles while the SDK continues to treat `$input` as opaque. This supports multi-turn and
stateful protocols without a Client-interpreted workflow language.

## Install

```bash
pip install screamingface
```

Python 3.12 or newer is required. This command installs the hosted client. The local stack
(`screamingface up`) also needs the runtime services and notebook tools:

```bash
pip install "screamingface[runtime,notebook]"
```

### Troubleshooting

`SCREAMINGFACE_RUNTIME_ERROR No module named 'X'` from `screamingface up` — common on
Colab, which preinstalls some of the runtime dependencies: the `[runtime]` extra is not
installed. Run `pip install "screamingface[runtime,notebook]"` and start again with
`screamingface up`. `screamingface doctor` names the missing modules.

## Client configuration

The module-level interface constructs one process-wide Client lazily against the hosted development
Engine and public Scoreboard. Configure either origin explicitly when selecting local or alternate
deployments:

```python
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
report = sf.evaluate(candidates, benchmark="draco", limit=1)
sf.close()
```

`sf.configure(...)` replaces and closes any existing default Client. `sf.close()` releases the
default Client and clears it so the next module-level operation can construct a fresh one. Setting
`SCREAMINGFACE_ENGINE_URL` and `SCREAMINGFACE_SCOREBOARD_URL` may be set before the first operation
for environment-driven configuration. The hosted development Scoreboard defaults to
`https://leaderboard.dev.screamingface.ai`.

The Client hides Benchmark fetching, URL4 compilation, REST/WebSocket transport, Event replay,
and Report decoding behind `sf.evaluate(...)`.

### Hosted caller authentication

Hosted Engines may be protected by Cloudflare Access. No authentication selector,
Cloudflare service token, or provider key is passed to the Client:

```python
client = sf.Client(engine_url="https://fusion.dev.screamingface.ai")
client.login()  # optional: the first protected request also starts login
```

The Client discovers the Access application audience from the Engine redirect, creates an
ephemeral encryption keypair, and opens Cloudflare Access login in the user's browser. It polls
Cloudflare's encrypted transfer service and decrypts the returned application token locally. The
token is held only in process memory and sent as `Cf-Access-Token` on REST requests and WebSocket
handshakes. `client.logout()` forgets it and opens the Engine's Cloudflare Access logout endpoint
in the browser. Concurrent callers share one browser login, a server-rejected token starts one fresh
login even before its local expiry, and an Access-specific WebSocket rejection is retried once after
reauthentication.

The login URL is always printed. Desktop Python also attempts to open it automatically; in Jupyter
or Colab, click the displayed URL and complete the configured Access login. This flow does not use
a localhost callback and does not require dynamic client registration or **Allow loopback
clients**. The user's email or identity must be allowed by the Cloudflare Access policy for the
hosted Engine. The Client prints a confirmation after it receives and validates the transferred
token; `client.authenticated` then returns `True`. Local Engines that do not advertise Access
continue to work without authentication.

The public authentication boundary is the URL4 Cloud origin, not AI Gateway. After Cloudflare
Access authenticates the caller, the deployment passes the verified identity to URL4 Cloud as
`X-User-Email`. URL4 Cloud forwards that identity—not the Access token—to the internal AI Gateway.
Consequently, the Python Client never calls AI Gateway or a model provider directly:

```text
Python Client -- Cf-Access-Token --> Cloudflare Access --> URL4 Cloud
                                                          -- X-User-Email --> AI Gateway
                                                                             -- provider key --> Provider
```

These credentials have deliberately different lifetimes and owners:

- The Cloudflare Access token exists only in Client memory and authenticates calls to URL4 Cloud.
- `X-User-Email` is derived from the edge-verified identity and selects the AI Gateway account.
- A provider key entered through `sf.connect()` travels through URL4 Cloud once for AI Gateway to
  validate and store; URL4 Cloud does not retain it.
- No shared Cloudflare key, provider key, or administrator key is configured on the Client.

If the hosted application later adopts Cloudflare Managed OAuth, the Client can migrate to OAuth
discovery and authorization code + PKCE. That is a possible future protocol, not an additional
authentication mode implemented by this package today.

In a notebook, `sf.connect()` displays the connection panel bound to the lazy default Client. For a
remote Engine, the panel first checks noninteractively whether Cloudflare Access is present. An
unprotected remote Engine loads its providers normally; a protected Engine shows the Engine login
row and loads provider rows only after login succeeds. Login waits in the background, so the
notebook remains usable and the row becomes
**Cancel** while the encrypted transfer is pending. Opening `sf.connect()` again reflects that same
in-progress login, and all open panels follow its eventual login/logout state. Cancel stops only the
pending transfer without opening another browser page;
Log out clears the completed token and opens Cloudflare Access logout. An explicit Access rejection
is shown in the panel, while an abandoned browser flow remains cancelable until its timeout. Local
Engines omit this row. This one-time transfer polling is separate from the authenticated WebSocket
used for model execution.
The Engine derives its connection catalogue from AI Gateway's enabled provider plugins. API keys
are supported for any provider that advertises `api_key`, and the panel can start OAuth for any
provider that advertises `oauth`. A key is sent only to the SF Engine,
which asks AI Gateway to validate and store it; the Python Client does not persist it and never
calls AI Gateway or a provider directly. One OpenRouter key covers every enabled `openrouter/...`
route, but does not authorize direct routes owned by other providers.

```python
sf.connect()
flow = sf.connect("codex", method="oauth")
flow.authorize_url
connection = flow.wait()  # or flow.cancel()
sf.connections.list()
sf.connections.get("openrouter")
sf.disconnect("openrouter")
```

The same panel retains OAuth, pending, authorization, cancellation, and reauthentication states.
The Engine catalogue remains authoritative about which methods each provider supports.

Local and hosted Engines use the same Client contract. Local mode may run the URL4 executor
in-process with an in-memory event bus; hosted mode may use the REST/WebSocket control plane with
NATS and scheduled workers. Engine execution is selected through `engine_url`; public Leaderboard
discovery is configured independently through `scoreboard_url`. Generic URL4 execution remains
benchmark-agnostic; installed Engine definitions own Benchmark semantics.

## Progress and Reports

`evaluate` consumes the Engine's REST and WebSocket lifecycle internally. An optional callback
receives typed CloudEvents views in sequence:

```python
def observe(event: sf.Event) -> None:
    print(event.kind)


report = sf.evaluate(
    candidates,
    benchmark="draco",
    limit=1,
    on_event=observe,
)
```

If a callback raises, the Client attempts to cancel all active Candidate Runs and re-raises the
original exception.

One `Report` shape covers one or many Candidates:

```python
report.ok
report.benchmark
report.case_count
report.candidates[0]
report.candidates["frontier-pair"]
report.candidates["frontier-pair"].run_id
report.candidates["frontier-pair"].url4
report.candidates["frontier-pair"].operations
report.candidates.only
report.failures
report.usage
report.started_at
report.completed_at
report.to_dict()
report.to_json()
artifact_path = report.export()  # Path("report.json")
report.export("runs/draco.json")
```

`Report.export(...)` writes the exact complete JSON document returned by `to_json()`, creates
parent directories, replaces an existing selected file for deterministic reruns, and returns its
`Path`. A Report remains one JSON document even when it contains multiple Candidates; JSONL is
reserved for a future collection of independent Reports.

Each entry in `CandidateResult.operations` is a public immutable `sf.OperationInfo` value.

Authentication, validation, transport, execution, protocol, and invalid-result failures raise
typed exceptions. Partial-result reporting remains a later Engine/Report contract.

Expected SDK failures inherit from `ScreamingFaceError` and always carry a stable error code, plus
an optional HTTP status, structured details, remediation hint, and `permanent`/`retryable`
classification. The public classes reflect distinct recovery actions:

- `EngineUnavailableError`: start, reconfigure, or retry the Engine.
- `AuthenticationError`: authenticate the caller again.
- `PlanningError`: change the Candidate, Benchmark, Model, or evaluation configuration.
- `ExecutionError`: inspect or retry a Run that failed after reaching the Engine.
- `ProviderConnectionError`: change a provider credential or provider connection.

IPython and Jupyter render these failures as a concise message, hint, and code instead of exposing
dependency tracebacks. Notebook panels render the same safe text inline. Programmatic callers can
catch a specific recovery class or catch `ScreamingFaceError` for every expected SDK failure;
translated low-level failures remain attached through `error.__cause__` for debugging. Programmer
errors such as invalid Python argument types retain their normal tracebacks.

Every `CandidateResult` exposes the Engine-owned top-level `coverage` ratio. A partial score remains
available alongside the Cases that could not be graded, and the notebook Report panel labels the
result as partial rather than silently presenting it as a complete evaluation.

## Ownership boundary

```text
Researcher or SF App
        ↓
ScreamingFace Python Client
  Recipe authoring · URL4 compilation · Events · Reports · Leaderboard reads
        ├─ REST + WebSocket → SF Engine → AI Gateway
        └─ public HTTPS GET → Scoreboard
```

Evaluation, discovery, and provider-connection operations call the configured SF Engine.
Leaderboard discovery calls the configured public Scoreboard. The Client never calls AI Gateway,
model providers, Tavily, or Benchmark datasets directly. Local and hosted Engines expose the same
Client-visible contract; in-memory channels, NATS, workers, and deployment topology are Engine
details.

Models, Fusions, and Pipelines are immutable, structurally comparable, Client-independent, and
network-free. Models select routes and optional answer policy; Fusions declare parallel topology
and an explicit synthesizer; Pipelines declare serial topology. Every placement compiles to a
distinct logical invocation, even when two Recipe values are equal or reused. The SDK compiles the
complete Recipe into one Candidate expression. Benchmarks are immutable Engine protocols
that own Cases, Candidate Invocation order, fixed Judge configuration, Grading, Aggregation,
and execution policy. Reports record the exact Engine-pinned Benchmark revision.

Durable reuse across graph positions, Candidates, retries, and resumed Evaluations belongs to the
Engine's provenance-aware response cache; Client compilation never merges authored positions.

## Discovery

An Engine implementing the provisional catalogue contract exposes typed discovery:

```python
models = sf.models.list()
gpt_details = sf.models.get("openrouter/openai/gpt-5.5")
benchmarks = sf.benchmarks.list()
boards = sf.leaderboards.list()
draco_board = sf.leaderboards.get("draco", top=50)

# After evaluating a Benchmark whose Scoreboard accepts submissions:
submission = sf.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
)
same_submission = sf.leaderboards.get_score(submission.id)
editable_python = same_submission.url4.to_python()
replayed_report = sf.evaluate(same_submission.url4)
```

Explicit Clients provide the same interface through `client.models.list()` and
`client.models.get(model_id)` alongside `client.benchmarks.list()`; asynchronous Clients use the
same names with `await`. `ModelInfo` rows are lightweight summaries containing the supported
parameter and tool names. `ModelDetails` is the profile-specific contract for one Model, including
typed parameter schemas, gateway policy, provider evidence, tools, transport, and freshness.

`sf.leaderboards` uses the separate public Scoreboard: `list()` returns its registered benchmark
summaries, while `get(benchmark_id, top=...)` returns one immutable `Leaderboard` containing ranked
best-per-spec entries and imported single-Model baselines. `submit(candidate_result)` publishes an
already-evaluated result — the Benchmark-native score exactly as the Engine graded it, fractional
or negative included — without asking the caller to repeat its Benchmark, URL4,
models, or run identity; `get_score(id)` retrieves the resulting immutable
`LeaderboardScore`. Omit `authors` to credit the authenticated submitter by default. When supplied,
the list is the exact credit line—the submitter is not added automatically—and the public
`LeaderboardScore.authors` and `LeaderboardEntry.authors` values contain the Scoreboard's
privacy-trimmed author identifiers. A score's `.url4` property is a string-compatible `Url4` value:
`.to_python()` produces an editable fork, while passing the value to `sf.evaluate(...)` replays it
through the configured Engine. Submitting a limited or incompletely graded Candidate surfaces a
`Partial submission` advisory because its score is not directly comparable with a full run. In a
notebook the Client displays a branded notice even when the score is assigned to a variable;
headless callers receive `sf.EvaluationWarning` attributed to their submission line. If that
warning category is configured as an error, submission stops before the Scoreboard is changed.
A Scoreboard deployment may
keep writes closed, in which case `submit()` raises a typed `LeaderboardError`. Explicit Clients
expose the same interface at `client.leaderboards`; asynchronous Clients use `await`. The
Scoreboard is the deployed data system, while a Leaderboard is the ranked domain resource returned
to callers.

Explicit Candidate parameters are preflighted against those details before execution. The SDK
fetches one detail document per distinct Model with explicit overrides on an operation the selected
Benchmark actually invokes; parameter-free Candidates and unused structural components perform no
detail lookup. Missing, disabled, wrong-type, or out-of-range values fail before any paid Run
begins. Model capability data always comes from the Engine/AI Gateway contract—there is no GPT- or
provider-specific parameter table in the SDK.

The returned catalogues are immutable ordered sequences: iteration, indexing, slicing, and
`len()` work normally in scripts and sidecars. Evaluating one in Jupyter automatically renders a
searchable catalogue when the `notebook` extra is installed, with escaped static HTML and compact
terminal representations as fallbacks. Notebook rendering does not change the underlying values
or introduce a separate discovery operation.

## Examples

- [`examples/00_quickstart.ipynb`](examples/00_quickstart.ipynb): one Candidate through the
  first canonical `draco` Case, from discovery through Report evidence.
- [`examples/01_client_tour.ipynb`](examples/01_client_tour.ipynb): a no-spend tour of Client
  lifecycle, hosted authentication, discovery, connections, authoring, events, errors, Reports,
  and the asynchronous API.
- [`examples/06_draco_full_e2e.ipynb`](examples/06_draco_full_e2e.ipynb): the complete seven-solo,
  nine-Fusion canonical DRACO experiment and audit workflow, with execution disabled by default.
- [`examples/07_ifeval_e2e.ipynb`](examples/07_ifeval_e2e.ipynb): canonical deterministic
  IFEval across the solo/panel × plain/corrective Recipe grid.
- [`examples/08_healthbench.ipynb`](examples/08_healthbench.ipynb): both HealthBench
  boards — the worst-30% open-Fusion challenge and the full 525-case exam with the
  official score — rehearsed cheaply with `limit=1` first.
All notebooks are deterministic outputs of `scripts/build_notebooks.py`.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov=screamingface --cov-fail-under=95 -q
uv run --extra notebook python scripts/check_notebooks.py
uv build
uv run python scripts/check_distribution.py
```
