# screamingface

Evaluate composable Candidate Recipes against URL4-native research Benchmarks.

> **Development status:** immutable Model/Fusion/Pipeline authoring, Engine-backed discovery, the direct
> evaluation API, and the confirmed `url4-cloud` lifecycle are implemented. The current MVP
> Engine publishes canonical `draco`, canonical `ifeval`, and the separately named
> `healthbench-worst30` challenge as complete URL4 Benchmark resources. There is no fixture,
> embedded benchmark runtime, or Client-side execution fallback.

## Local notebook runtime

Local Engine result artifacts live in the private `<data_dir>/artifacts` directory
rather than temporary storage. Set `URL4_CLOUD_ARTIFACTS_DIR` to override it;
`screamingface status` shows the absolute serving directory and its current size.
The Engine's retention policy still applies. This configuration is independent of SDK
report rendering, export and recovery APIs.

Install the SDK, notebook tools, and local services together:

```bash
pip install "screamingface[runtime,notebook]"
screamingface prepare --all  # first run only
screamingface up
```

`draco`, the Benchmark the examples below use, is a local inspect Task, and so is `ifeval`: the plain
`screamingface up` Engine lists neither. From a checkout, `just local-stack-notebooks` serves an
Engine with the `inspect` extra beside the stack; otherwise point `SCREAMINGFACE_ENGINE_URL` at such
an Engine and `SCREAMINGFACE_SCOREBOARD_URL` at its Scoreboard (a non-default Engine without a
Scoreboard is refused).

`screamingface up` starts AI Gateway, Scoreboard, and the Engine in the background. Use
`screamingface status`, `screamingface doctor`, `screamingface logs`, `screamingface restart`, and
`screamingface down` to manage them. Runtime state is stored under `~/.screamingface` by default;
set `SCREAMINGFACE_DATA_DIR` or pass `--data-dir` to override it.

The default service ports are Gateway `9105`, Scoreboard `9106`, and Engine `9108`. Override them
with `--gateway-port`, `--scoreboard-port`, and `--engine-port`, or the corresponding
`SCREAMINGFACE_GATEWAY_PORT`, `SCREAMINGFACE_SCOREBOARD_PORT`, and `SCREAMINGFACE_ENGINE_PORT`
environment variables. `screamingface up` prints the resolved SDK environment variables; the SDK
does not switch away from its hosted defaults automatically.

Benchmark datasets live in `<data-dir>/benchmark-assets`, where `screamingface prepare` writes
them. To read them from another folder instead — for example a read-only copy bundled with an
app — start the runtime with `screamingface --data-dir <dir> up --benchmark-assets-dir <folder>`.
The folder must exist, or `up` fails before any service starts. The Engine reads datasets from it,
`status --json` and `doctor` report bundle status from it (and name it), and `restart` keeps it.
`prepare` still writes only to the data directory and refuses `--benchmark-assets-dir`.

The local gateway caches model responses by default (`AIGW_REQUEST_CACHE_ENABLED=false` before
`screamingface up` turns it off). To start from the community cache instead of an empty one, pull
it into the local gateway — from a notebook or a shell:

```python
import screamingface as sf

sf.cache.pull_from_remote()  # everything
sf.cache.pull_from_remote(["openrouter/anthropic/claude-opus-5.5"])  # only these models
```

```bash
screamingface cache pull --model openrouter/anthropic/claude-opus-5.5
```

The pull signs in to the hosted Engine (a browser opens once per process), shows its progress, and
keeps rows you already have. Models are named exactly as the hosted cache names them, and a run
can only hit rows of the models its candidates and judge use, so a filtered pull loses no hits.
If it stops, calling it again in the same process continues where it left off; a new process
starts over, re-reading but not re-adding what is already local. One evaluation opts out of the
cache with `evaluate(..., use_cache=False)`.

A pulled row answers only the exact request it was stored for: the same model, prompt and
parameters, the same Benchmark revision, and the same `answer_seed` if the run used one. Change
any of them (even `temperature`) and every call misses and is paid. The rows hold a one-way hash
of the request, not the request, so a pull cannot tell you which configurations it covers. Two
ways to land on one that does:

- Run a standard Benchmark with a bare `sf.Model("…")`: the Benchmark fixes the prompts and
  parameters, so this is the most common configuration.
- Re-run a published leaderboard entry with `sf.evaluate(entry.url4)`. Only runs made on the
  hosted Engine are in the hosted cache, so an entry that was run locally and submitted gives no
  hits; and a leaderboard entry does not carry its `answer_seed`, so a seeded run re-run from its
  `url4` alone misses.

A filtered pull that matches no rows says so (a model name with a typo matches nothing).

For scripts and troubleshooting:

```bash
screamingface status --json
screamingface doctor
screamingface logs --service engine --tail 100 --no-follow
screamingface prepare --list
```

Logs are timestamped, tagged by service, rotated at 10 MiB, and retain five backups. The log and
its backups are readable only by you. Versions before `OME-990` wrote prompts into this log;
`screamingface logs --purge` deletes the backups and empties the live log (it does not securely
erase the disk blocks). Three structural prompt carriers are redacted before anything is
written: url4 `q=` query values, litellm's `Messages:` exception suffix, and litellm's debug curl
`-d` body. The runtime also forces `LITELLM_LOG=WARNING`. Prompt text that appears without one
of those markers is not detected, so review a log before sharing it. Benchmark
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

### Fusion quorum and failed members

A Fusion requires every member by default (`quorum="all"`). Mark individual members
with `optional=True` to tolerate their failures:

```python
resilient = sf.Fusion(
    [
        sf.Model("provider/a", optional=True),
        sf.Model("provider/b", optional=True),
        "provider/c",  # required
    ],
    synthesizer="provider/synth",
    quorum=2,
)
```

The compiler wraps optional members with URL4's `;optional` and gates the member-only
expression with `;quorum=2`, before running the synthesizer. Required members always
have to succeed, even if other successes already meet the quorum. Strings and Recipes
without `optional=True` remain required. `Pipeline(..., optional=True)` and
`Fusion(..., optional=True)` guard a complete composite when used as a member of another
Fusion; their intermediate answers do not count toward the containing Fusion's quorum.
Optional Recipes are only valid as Fusion members, not standalone Candidates, pipeline
stages, or synthesizers.

The synthesizer receives JSON containing the original `input` and an `outputs` string
with ordered `member_N: answer` sections for successful members only. Fusions using the
default quorum and only required members retain their existing outputs object.

Quorum is a success floor checked after members finish, not an early response race.
`quorum="all"` still requires every member to succeed, including optional members;
`quorum=0` permits synthesis with no successful members when every member is optional.
`None`, booleans, negative numbers, and numbers above the member count are rejected.
Quorum and per-member optional settings survive `Url4.to_python()` and replay.
A reducer synthesizer (`sf.Vote`, `sf.Reduce`, `sf.Judge` and the other combine blocks) takes
quorum and optional members too. It reads only the members that answered, and the evidence lists
each failed optional member with the reason `missing`; a judge scores only the members that
answered. `sf.Concat` joins only the members that answered, so set `label=True` when the next
stage must know which member wrote each part. With `quorum=0` and no member answering, the
reducer abstains and the Case scores 0.0.

**Deployment requirement:** before using composed quorum Recipes (such as a Pipeline
feeding a quorum Fusion or a quorum Fusion used as a synthesizer), deploy an Engine
containing the URL4 nested-expression scope fix shipped with this change. Older runtimes
can pass literal binding references instead of resolved upstream answers. Deploy the
Engine operation-reporting update as well to retain member outputs and accounting.
URL4 already supports quorum and optional sources; the runtime change fixes scope
propagation for these compositions.

### Independent samples of one model

`sf.samples(model, n)` builds `n` Models of one route that differ only in an integer `seed`, so a
vote over them counts `n` real answers and not one cached answer `n` times:

```python
candidate = sf.Fusion(
    sf.samples("openrouter/openai/gpt-5.5", 5, temperature=0.7),
    synthesizer=sf.Vote(extract="last_number", normalize="numeric"),
)
```

The block form is the same Candidate, byte for byte:
`synthesizer=sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric"))`.

Seeds default to `0` through `n - 1`; pass `seeds=[...]` (unique ints) to choose them. `prompts=[...]`
gives member `i` its own prompt (for example one per language), `temperature=` and `params=` apply
to every member, and a `sf.Model` as the first argument is the base whose prompt and params the
samples inherit. A model whose provider does not accept `seed` fails with `sf.PlanningError` (code
`unsupported_model_parameter`) before the run starts and before any model is called. The SDK emits
`sf.DuplicateMembersWarning` when a reducer Fusion has two members that send the same request,
because the gateway may serve them from one cached answer. `sf.DuplicateMembersWarning` fires for
any reducer synthesizer, a named reducer or an `sf.Reduce` block.

A call that sets its own `seed` keeps it, and a run seed (`answer_seed=`, one "sitting" of an
evaluation) only applies to calls without one. So `sf.samples()` members, and any
`sf.Model(params={"seed": ...})`, send the same requests in every sitting, and a mean and
confidence interval across sittings would look tighter than the model really is. When a run seed is
set and a Recipe or a replayed URL4 has such calls, the SDK emits `sf.FixedSeedSittingWarning`
before the run starts, naming the calls, and then runs as usual. If you already pass different `seeds=` to `sf.samples()` in
each sitting, the warning is expected, and you can silence it:

```python
import warnings

warnings.filterwarnings("ignore", category=sf.FixedSeedSittingWarning)
```

Otherwise drop the explicit seed. The check covers Recipes and raw URL4 replays
(`client.evaluate("<url4>", answer_seed=...)`), with the same text.

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
stage's answer. No original input or accumulated history is injected implicitly. The one exception
is the stage after a `sf.Rank` or a `sf.Filter`: its selection JSON also holds the input of that
Fusion (see "Rank and Concat selections"). Pipelines and complete Fusions compose recursively,
including in the synthesis role:

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

### Deterministic synthesizers

A Fusion can combine its members with a rule instead of a model:

```python
routes = [
    "openrouter/openai/gpt-5.5",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/google/gemini-3.1-pro-preview",
]

by_vote = sf.Fusion(routes, synthesizer=sf.Vote(extract="last_number", normalize="numeric"))
by_median = sf.Fusion(routes, synthesizer=sf.Median(extract="last_number", select="value"))
```

The combine step makes no model call. The answer is one member's text byte for byte, or the median
number itself for `select="value"`. A tie goes to the first member in author order and sets `tie`.
A member with no usable value does not vote. When no member votes, the Case abstains: its output is
`""`, its score is 0.0 and `case.abstained` is true. It does not fail.
On HealthBench a harmful answer can score below 0, so an abstain can rank above a bad answer; this
is intended. Only the final step of a Candidate can mark a Case as abstained: a combine step that
feeds another stage (a Rank or a Filter) never does.

**Weighted median.** `sf.Median(weights=(1, 1, 3))` takes one positive number per member, or
`sf.signal(key)`, as `sf.Vote` does. The members with a usable weight are sorted by value. The
answer is the first value where the running weight reaches half the total weight. At exactly
half, the answer is the mean of that value and the next one, so equal weights give the plain
median. A member with a missing or non-positive weight is dropped. It is never the nearest pick.
The evidence shows that member with the status `"excluded"` and the reason `no_weight`.
When no member is left, the Case abstains. For a number in a JSON reply, use the block form
`sf.Reduce("median", extract=sf.Extract("field", path="answer"),
weights=sf.signal("field:confidence"), select="value")`. The block form takes `select=` as
`sf.Median` does: `select="value"` returns the median number, and the default
`select="nearest"` returns the text of the nearest member. A `sf.signal("score:judge")` weight
raises `ValueError`: a Median has no judge.

`sf.Mean` returns the mean of the members' numbers (`select="value"`, the default) or the text of
the member nearest the mean (`select="nearest"`). Give it weights to make some members count more:

```python
by_mean = sf.Fusion(routes, synthesizer=sf.Mean(weights=[1, 1, 2]))
```

The sums are exact, and the division is rounded to 34 significant digits. A member with no usable
weight is dropped: it is not in the mean and it is never the nearest member. For a number in a
JSON reply, use the block form `sf.Reduce("mean", extract=sf.Extract("field", path="answer"),
weights=sf.signal("field:confidence"))` (see "Combine recipes"). The block form also takes
`select="nearest"`.
The evidence shows a member with no usable weight with the status `"excluded"` and the reason
`no_weight`.

To group answers the way the benchmark grades them, let the benchmark choose the extract rule. The
SDK reads the rule from the benchmark before any spend:

```python
by_grader = sf.Fusion(routes, synthesizer=sf.Vote(extract="benchmark"))
report = client.evaluate(by_grader, benchmark="inspect-gsm8k")
```

A benchmark with no answer rule raises `ValueError` before any spend. For a rule with arguments, use
`sf.Reduce("plurality", extract=sf.Extract("regex", pattern=...))`.

**Regex patterns.** `sf.Extract("regex", pattern=...)` and `sf.matches(pattern)` run on RE2 in the
Engine. RE2 has no lookarounds and no backreferences. `\d` and `\w` match ASCII only: use `\p{L}` and
`\p{N}` for Unicode letters and digits. `$` is the end of the text, so write `\s*$` to allow a
trailing newline. The repeat limit is 1000. The Engine refuses a compiled program over 5000
instructions. The SDK checks the pattern before any spend, and it is a little stricter than RE2 for
`\Q...\E`, `\C`, `\x{...}` and POSIX `[[:class:]]`. The Engine compile is authoritative: a pattern
that the SDK accepts and RE2 refuses fails the Case with `combine_spec_invalid`.

The evidence (the Answer row per member, the tally, the result, the agreement and the chosen member)
is in the `combine` field of each case's `operations` entry (`op_synthesis_1` for a single reducer).
`case.answers()` joins each member's text to its Answer. `case.trace()` and `report.trace_dict()`
show what each block did, in order. `report.trace_dict()` is `screamingface.report-trace.v1`, and
`report.to_dict()` and `report.export()` stay `report.v1`. This needs an Engine that serves
`GET /v1/operators`.

Give a vote weights to make some members count more. A list gives each member a fixed weight, one
positive number per member in author order. A `sf.signal` weighs each member by a number on its own
Answer:

```python
fixed = sf.Fusion(routes, synthesizer=sf.Vote(weights=[2, 1, 1]))

# Each member replies with JSON such as {"answer": "B", "confidence": 0.4}.
by_confidence = sf.Fusion(
    routes,
    synthesizer=sf.Reduce(
        "weighted",
        extract=sf.Extract("field", path="answer", normalize="text"),
        weights=sf.signal("field:confidence"),
    ),
)

# The same rule in the named form, with the cost of each member's own model calls as the weight.
by_cost = sf.Fusion(routes, synthesizer=sf.Vote(weights=sf.signal("cost_usd")))
by_cost_block = sf.Fusion(
    routes,
    synthesizer=sf.Reduce(
        "weighted",
        extract=sf.Extract("last_line", normalize="text"),
        weights=sf.signal("cost_usd"),
    ),
)
```

Each answer scores the sum of the weights of the members who gave it. The answer is the text of the
heaviest member who gave the winning answer (the first in author order on equal weights). A member
with no weight does not vote, and when no member is left the Case abstains. The report shows each
member's `weight` and each answer's summed `score`.
A member whose signal weight is not usable has the status `"excluded"` and the reason `no_weight`
in the evidence.

A weight that is zero, negative, not finite or above `sys.float_info.max / 256` raises `ValueError`
at `sf.Vote(...)`, and a weight that is not a number raises `TypeError`. A wrong number of weights
raises `ValueError` when the Fusion is built. All of these raise before any call. Weights apply to
`sf.Vote`, `sf.Mean` and `sf.Median` (see "Weighted median" above). `sf.signal("score:judge")`
needs a judge on the same vote (see "Judge synthesizer" below).

The accounting keys are `cost_usd`, `latency_ms`, `tokens_in` and `tokens_out`. For a member they
are the sum over the model calls that member made, which the Engine finds by each call's route and
params. When two members send the same route and params (for example a repeated model, or a model
that a later stage or another Fusion also calls), the Engine cannot tell the calls apart, so those
members have no accounting value and do not vote. This also holds in a corrective loop with
`max_rounds` of 2 or more, where every round sends the member's calls again. To give each member
its own calls, use `sf.samples()` (a different `seed` for each member).

A cached replay reads each call's original cost, latency and tokens, so it gives the same signals
and the same tally. A fresh live rerun can give a different `latency_ms` (and a different cost, if
prices changed). Only `cost_usd` is proven end to end by the paid replay lane. `latency_ms`,
`tokens_in` and `tokens_out` are carried by the cache metadata and covered by unit tests only.

**Members left out.** A step that reads a signal or a signal weight leaves out a member that has
no value for it. The evidence row of that member has `status: "excluded"` and the reason
`no_signal` (no value for the signal that the step reads: `sf.Rank(by_signal=...)`,
`sf.Pick(by_signal=...)` or `sf.Filter(where=sf.signal(...) ...)`) or `no_weight` (no usable
signal weight in a weighted `sf.Vote`, `sf.Median` or `sf.Mean`: missing, zero, negative or too
large). `case.answers()` gives that member `sf.Answer(status="excluded", reason="no_signal")` (or
`reason="no_weight"`), with the value it read, and the trace `extract` entry shows the same status
and reason. The row is written also when the step abstains because no member is left. A member
that failed keeps `status: "fail"` and its own reason, also when its signal is missing. Fixed
weights (a list) never leave a member out. An excluded member is not a failure: `dropped` and the
quorum count only failed members. The answer of the Case does not change. Only the evidence says
more. So `sf.Answer.status` can now also be `"excluded"`. This needs an Engine and an SDK from the
same release: an older SDK cannot read evidence with an excluded member.

### Judge synthesizer

A judge is a model that reads the members and picks one. The answer of the Fusion is the text of the
member that the judge picked. The judge does not write the answer.

```python
by_label = sf.Fusion(
    routes,
    synthesizer=sf.Judge(
        "anthropic/claude-opus-5", returns="label", rubric="Pick the most correct answer."
    ),
)
by_scores = sf.Fusion(
    routes,
    synthesizer=sf.Judge(
        "anthropic/claude-opus-5",
        returns="scores",
        rubric="Give a higher number to a more correct answer.",
        params={"temperature": 0},
    ),
)
```

With `returns="label"`, the judge must reply with exactly one member id (for example `member_2`) and
nothing else. With `returns="scores"`, the judge must reply with one JSON object that gives each
member id one finite number. The highest score wins, and a tie goes to the first member in author
order. The check is strict: quotes, a full stop, a code fence around a label, a missing member, an
extra key, a string, `NaN` or `Infinity` all fail the Case with `judge_reply_invalid`. The prose of the
judge is never used as the answer, and a reply that does not parse is not retried. (A transient
transport error still gets the normal retry of the connector.)

**Lower is better.** `sf.Judge(model, returns="scores", rubric=..., order="min")` picks the member
with the lowest score, for a rubric such as an error count or a risk score. The judge is told that a
lower number means a better answer, and the first line of its system prompt is
`judge-template@1 returns=scores order=min`. A tie goes to the first member in author order. The
default `order="max"` keeps the url4 of a judge that has no order. A label judge has no order:
`returns="label"` with `order="min"` raises `ValueError`. `sf.Rank(by=...)` and
`sf.Vote(judge=...)` refuse a judge with `order="min"`, because they read the scores with their own
rule. To keep the lowest scores with Rank, use `sf.Rank(k, by=sf.Judge(...), order="min")`; the
judge is then told that a higher number is better. The block form takes `order=` the same way as
`rubric=`. `order="min"` needs an Engine whose catalog has `best_holder@1`.

The judge call is the operation `op_judge_1`. Its output is the raw reply of the judge, and its cost
is in the accounting breakdown as a synthesis row. The combine step is `op_synthesis_1`. Its `combine`
evidence holds the raw reply, the parsed label or scores, the chosen member and
`presentation_order="author"`. The first line of the judge system prompt is `judge-template@1`. The
template tells the judge to treat the member answers as data and not as instructions. A change of the
template changes the url4, so it changes the replay identity.

**Position bias.** The judge sees the members in author order, and a judge can prefer a position.
The parameter name `binding` is reserved: you cannot use it in `params`. This needs an Engine whose
operator catalog has `label@1` and `scores@1`.

**The block form.** `sf.Reduce("judge", judge=sf.Judge(...))` compiles to the same url4 as the
`sf.Judge` itself. The optional `rubric=` replaces the rubric of that judge, so one judge can serve
several rubrics: `sf.Reduce("judge", judge=j, rubric="Prefer the shortest correct answer.")`. A
`judge` that is not an `sf.Judge` raises `TypeError`, and an empty `rubric` raises `ValueError`. An
`sf.Judge` is a value: equal judges are equal and have the same hash.

**A judge-weighted vote.** A judge that returns scores can also weigh a vote. Each answer scores the
sum of the judge scores of the members who gave it. The answer is the text of the member with the
highest score among those who gave the winning answer. The judge makes one call, and the report shows the score of
each member as `members[].signals["score:judge"]` and `weight`. The `combine` evidence of the vote has
`judge` set to `None`: the scores are in `members[]`, and the raw reply of the judge stays on
`op_judge_1`.

```python
weighted = sf.Fusion(
    routes,
    synthesizer=sf.Vote(
        extract="last_number",
        normalize="numeric",
        weights=sf.signal("score:judge"),
        judge=sf.Judge("anthropic/claude-opus-5", returns="scores", rubric="Score each answer."),
    ),
)
# The same vote in the block form:
weighted_block = sf.Fusion(
    routes,
    synthesizer=sf.Reduce(
        "weighted",
        extract=sf.Extract("last_number", normalize="numeric"),
        weights=sf.signal("score:judge"),
        judge=sf.Judge("anthropic/claude-opus-5", returns="scores", rubric="Score each answer."),
    ),
)
```

The weights and the judge must go together. `weights=sf.signal("score:judge")` without a judge, a
judge without that weight, or a judge that returns labels each raise `ValueError` when the vote is
built, before any call is paid (the Engine reads `score:judge` strictly, so a lone half would fail
after the member calls). A judge that is not an `sf.Judge` raises `TypeError`. The same strict read
applies to the reply: a malformed or too large reply, a `NaN` or an infinite score fails the Case
with `judge_reply_invalid`. It never counts as "no weight", which would hide the defect behind an
abstain.

**The judge in the trace.** In `case.trace()` and `report.trace_dict()`, the `reduce` entry of a
step that reads a judge names the judge call: `judge_operation_id` is the operation of the judge
(for example `op_judge_1`), and `judge_model` is the `model` of that operation's `model_call`
entry. This holds for `sf.Judge`, for `sf.Rank(by=sf.Judge(...))` (see "Rank and Concat
selections"), and for a Vote or a Filter that reads `sf.signal("score:judge")`. For any other step,
both keys are `None`. The SDK reads the link from the operation graph of the Case and never
guesses: both keys are `None` for a Case result with no operation graph, and for a step with no
judge operation or with more than one. `judge_model` is `None` when the judge call has no
accounting. The url4 does not change, so a judge url4 compiled before this change rebuilds, and
its trace links the judge too. The `combine` evidence itself has no judge model.

**The judge and the writer.** The model that scores the members should not also write the
answer. When a stage that reads a judge is followed directly by a model stage (an `sf.Model` or a
route string) with the same model as the judge, the SDK emits `sf.JudgeWriterWarning` (an
`sf.EvaluationWarning`) when it compiles the Pipeline, before any call. The warning names the
Pipeline, the two stage positions and the route. It does not stop the run and does not change the
url4. Two spellings of one route (with and without the provider prefix that the SDK adds) are one
model, as for `sf.DuplicateMembersWarning`. The SDK sends the warning once per Pipeline object,
and not again when it rebuilds a url4. Only the next stage is checked: a writer that is a Fusion
or a nested Pipeline is not. If one model in both roles is what you want, silence the warning:

```python
import warnings

warnings.filterwarnings("ignore", category=sf.JudgeWriterWarning)
```

### Pick and merge JSON fields

If the members reply with JSON, a rule can choose or build the answer. No model writes it.

```python
by_confidence = sf.Fusion(routes, synthesizer=sf.Pick("confidence", order="max"))
by_answer = sf.Fusion(routes, synthesizer=sf.Pick("answer", equals="yes", normalize="text"))
# the answer is only the "answer" field of the most confident member's JSON reply
answer_only = sf.Fusion(routes, synthesizer=sf.Pick("confidence", order="max", output="answer"))

# argmax: the member with the lowest value of a named signal (here, the cheapest member)
cheapest = sf.Fusion(routes, synthesizer=sf.Pick(by_signal=sf.signal("cost_usd"), order="min"))
# The same pick in the block form:
cheapest_block = sf.Fusion(
    routes, synthesizer=sf.Reduce("argmax", by_signal=sf.signal("cost_usd"), order="min")
)

merged = sf.Fusion(
    routes,
    synthesizer=sf.Merge(
        fields={
            "answer": sf.FieldRule.majority(normalize="text"),
            "score": sf.FieldRule.max(),
            "source": sf.FieldRule.from_member(2),
            "synonyms": sf.FieldRule.union(normalize="text"),
            "summary": sf.FieldRule.model("anthropic/claude-sonnet-5", prompt="Write one summary."),
        }
    ),
)
```

`sf.Pick(field, order="max"|"min")` reads one field from each member. It returns the text of the
member with the largest or smallest value, byte for byte. `sf.Pick(field, equals=value)` returns the
first member whose value is equal to `value`. `field` is a JSON path such as `confidence`, `a.b` or
`a[0].b`. With `normalize="text"` or `normalize="numeric"`, the value of each member and `value`
itself go through the same normalizer before the compare. A number or a boolean in `equals` is
compared in its JSON spelling (`1` is not `1.0`), unless you use `normalize="numeric"`.
Because `json_field@1` returns the contents of a string without its quotes, `equals=7` also matches
a member whose value is the string `"7"`. An empty `equals`, or `equals=True` with
`normalize="numeric"`, raises `ValueError` before any call. A tie goes to the first member in author
order and sets `tie`. A `field` that is longer than 256 characters raises `ValueError` before any
call.

`sf.Pick(by_signal=sf.signal(key), order="max"|"min")` (argmax) picks the member whose named signal is
the highest (`"max"`, the default) or the lowest (`"min"`). The signal can be an accounting key
(`cost_usd`, `latency_ms`, `tokens_in`, `tokens_out`) or `field:<path>`. The result is the text of
that member, byte for byte. A member with no value for the signal is skipped. When no member has a
value, the Case abstains. A tie goes to the first member in author order. For an accounting key, the
SDK adds `sources` to the combine context (the model calls of each member), as it does for a weighted
`sf.Vote`; a member with a call that appears twice in the Candidate gets no value. `score:judge` raises
`ValueError`: this reducer has no judge. Use `sf.Judge(..., returns="scores")`, which picks the member
with the highest judge score. A `Pick` takes a field or `by_signal=`, not both.
In the evidence, a member with no value for the signal has the status `"excluded"` and the reason
`no_signal`.

`output="answer"` (on a field Pick or on `by_signal=`) makes the answer one top-level field of the
winner's JSON reply, not its whole text. A string is returned without its quotes, and any other
value as compact JSON (`42`, `true`, `{"a":1}`). When the winner's field is missing, `null` or
blank, or its reply is not a JSON object, the Case abstains with the reason `output_missing`. The
next member is never used. `output` is a field name (a letter or `_`, then letters, digits or `_`,
at most 64 characters), not a path. A string that is not a field name raises `ValueError`, and a
value that is not a string raises `TypeError`, both before any call. The block forms take the same
`output=` option.

The block forms compile to the same url4 as the named classes, and `Url4(...).to_python()` writes the
named class back: `sf.Reduce("argmax", by_signal=..., order=...)` is `sf.Pick(by_signal=..., order=...)`,
`sf.Reduce("pick_field", field=..., order=...)` or `sf.Reduce("pick_field", field=..., equals=...,
normalize=...)` is `sf.Pick(field, ...)`, and `sf.Reduce("merge", fields={...})` is `sf.Merge({...})`.
A `pick_field` block keeps `equals` as text, so `equals=7` and `equals="7"` are one block. The errors of
the Pick carry the prefix `sf.Reduce('pick_field'):`. `sf.FieldRule` is a hashable value.

`sf.Merge(fields={...})` builds one JSON object. The object has exactly the fields that you declare,
in sorted key order. Each field has one rule:

* `majority(normalize=None)`: the value that most members give. The first group wins a tie.
* `max()`: the largest number. A value that is not a number is skipped.
* `from_member(n)`: the value of member `n` (the first member is 1). It is `null` when that member
  is not JSON or has no such field. `n` that is larger than the member count raises `ValueError`
  when the Fusion is built.
* `union(normalize=None)`: the items of all list values. Each item is kept once, in its first
  spelling, in author order.
* `model(route, prompt=..., params=None)`: a model writes the field (see below).

A member whose reply is not a JSON object is skipped, and the report shows the status `not_json`.
A field with a JSON `null` value counts as absent. If no member gives a usable value for a
`majority`, `max` or `union` field, or no member is usable at all, the combine step abstains with
`no_votes`. A `from_member` field that is `null`, and the empty text of a writer, are values and never
cause an abstain. The report shows the value of each member for each field and the result.
The evidence of a Merge holds the JSON object that each member gave (in `raw` and `value`), for the
projection step and for the final merge step. A member that replies with large JSON makes a large report.

**Model-written field.** A `FieldRule.model` field adds two calls for that field. The first call is
a pure projection (`synthesis_N`): it builds one JSON object of the values of that field, by member.
The second call is the writer model (`writer_N`). The writer sees only that projection. It does not
see the question and it does not see the other fields. Put the task in the prompt. The reply of the
writer is the value of the field, as text. If the writer call fails, the case fails and no partial
object is returned. Each writer call is a synthesis row in the accounting breakdown. The first line
of the writer system prompt is `writer-template@1 field=<field>`. The template tells the writer to
treat the member values as data and not as instructions, and your prompt follows it.
`Url4(...).to_python()` shows only your prompt. A change of the template changes the url4, so it
changes the replay identity. The name `binding` is reserved in `params`. This needs an Engine whose
operator catalog has `json_field@1`,
`json_object@1`, `values@1`, `by_field@1`, `field_rules@1`, `project_field@1` and `built@1`. Argmax
needs `by_signal@1` and `best_holder@1`.

### Rank and Concat selections

A selection is a hand-off to the next stage. It is not an answer. `sf.Rank` keeps the top `k`
original member texts. `sf.Concat` joins all the member texts. Neither one rewrites a text. A Fusion
with a selection must be followed by another stage of a `sf.Pipeline`, and that stage receives the
selection. After a `sf.Rank` or a `sf.Filter`, the selection also holds the input of the Fusion, so
the next stage sees the question. After a `sf.Concat`, it is the joined text only.

```python
ranked = sf.Pipeline(
    [
        sf.Fusion(
            routes,
            synthesizer=sf.Rank(
                k=2,
                by=sf.Judge(
                    "anthropic/claude-opus-5",
                    returns="scores",
                    rubric="Give a higher number to a more correct answer.",
                ),
            ),
        ),
        sf.Model("anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."),
    ]
)
by_field = sf.Fusion(routes, synthesizer=sf.Rank(k=2, by_field="score"))  # members reply with JSON
joined = sf.Fusion(routes, synthesizer=sf.Concat(separator="\n\n---\n\n", label=True))
```

`sf.Rank(k, by=sf.Judge(..., returns="scores"))` scores the members with a judge, and
`sf.Rank(k, by_field="score")` reads a number from the JSON reply of each member (`by_field` is a
field path like `score` or `result.score[0]`). The next stage receives this JSON, best member first:
`{"input":"...","selected":[{"id":"member_2","text":"..."},{"id":"member_4","text":"..."}]}`.
`input` is the input of this Fusion, character for character: the Case input when the Fusion is the
first stage, or the answer of the previous stage when it is not. A conversation input arrives as its
JSON text. The input is never cut: a selection of more than 8 MiB fails with
`combine_input_too_large`. The url4 of the candidate does not change. A tie at the cut
goes to the earlier member, and the evidence sets `tie`. `k` is from 1 to 256 and must not be more
than the number of members. If fewer than `k` members have a usable score, the combine step
abstains with `cut_not_met`, and the next stage gets the input and no member,
`{"input":"...","selected":[]}`. The judge call and the scores
of all the members stay in the report (`op_judge_1` and the `combine` evidence), also for the members that do not continue. A judge reply
that is not valid fails the Case with `judge_reply_invalid`, as for `sf.Judge`.

`sf.Concat(separator="\n\n---\n\n", label=True)` makes no model call. With `label=True`, each part
starts with `[member_1]` on its own line. The parts are in author order, and an empty member text
keeps its place. The separator is 1 to 1024 characters. If a member text contains the separator,
the text is joined unchanged and the evidence sets `separator_collision`, because then the
boundaries are not unique. A joined text of more than 8 MiB fails with `combine_input_too_large`.

`sf.Rank(k, by_signal=sf.signal(key), order="max")` ranks by a named number on the Answer of each
member: a field signal such as `field:score`, or an accounting key such as `cost_usd`. With
`order="max"` (the default) it keeps the members with the highest values. With `order="min"` it keeps
the members with the lowest values, for example the cheapest members. `order=` also works with `by=`
and `by_field=`. Give exactly one of `by`, `by_field` and `by_signal`; two, or none, raise
`ValueError`. A member with no value for the signal is not ranked. `sf.signal("score:judge")` is
refused, because a Rank with no judge has no judge score: use `by=sf.Judge(..., returns="scores")`.
In the evidence, a member with no value for the signal has the status `"excluded"` and the reason
`no_signal`.

```python
cheapest_two = sf.Pipeline(
    [
        sf.Fusion(routes, synthesizer=sf.Rank(k=2, by_signal=sf.signal("cost_usd"), order="min")),
        sf.Model("anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."),
    ]
)
```

**Rank and cut in the evidence.** The `combine` evidence of a Rank gives each member with a score
its `rank` (`CombineAnswerRow.rank`): 1 is the best, and equal scores take author order, so no two
members share a rank. A member with no score (it failed or was excluded) has no rank. The evidence
also has the `cut` (`CombineEvidence.cut`, a `sf.report.CombineCut`) with `k` and `order`. The
default order is written as `"max"`. The chosen members are exactly the members with a `rank` of
`cut.k` or less, best first. For `cheapest_two` with the costs member_1 0.03, member_2 0.01,
member_3 0.02 and member_4 0.01, the ranks are member_2 1, member_4 2, member_3 3 and member_1 4,
the chosen members are member_2 and member_4, and the cut is `{"k": 2, "order": "min"}`. When the
step abstains with `cut_not_met`, the ranks and the cut are still written. Only a Rank has a rank
and a cut. A Filter and a Pick have neither, and their evidence keeps its keys.

The block forms are `sf.Reduce("top_k", k=2, by_signal=..., order=...)` (also `by=` and `by_field=`)
and `sf.Reduce("concat", separator=..., label=...)`. Each compiles to the same url4 as `sf.Rank` and
`sf.Concat`, and a url4 is written back as `sf.Rank(...)` or `sf.Concat(...)`.

The compiler checks the place of a selection before any call. A Fusion with `Rank`, `Concat` or
`Filter` cannot be the last step of a candidate, cannot be a member of another Fusion (also not
through a `sf.Pipeline` that ends in one), and cannot be a member of a corrective loop. Each case
raises `ValueError`. After a Rank or a Filter, the next stage receives the input of the Fusion and
the kept member texts, never the texts that were cut. After a Concat, it receives only the joined
text, so put the task in the prompt of that stage. This needs an Engine whose operator catalog has
`scores@1` and `top_k@1` for `Rank` by a judge or by a field, `by_signal@1` and `top_k@1` for `Rank`
by a signal, or `join@1` and `all@1` for `Concat`.

### Filter selection

`sf.Filter` keeps the members that pass a test. The next stage gets the input of the Fusion and only
those members, as the same JSON that `sf.Rank` writes (`{"input":"...","selected":[...]}`), in
author order. `where=` is a regex or a signal comparison:

```python
confident = sf.Pipeline(
    [
        sf.Fusion(
            routes,
            # Each member replies with JSON such as {"answer": "B", "confidence": 0.4}.
            synthesizer=sf.Filter(where=sf.signal("field:confidence") >= 0.6),
        ),
        sf.Model("anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."),
    ]
)
formatted = sf.Filter(where=sf.matches(r"ANSWER: \d+", ignore_case=True))
checked = sf.Filter(where=sf.matches("yes"), extract=sf.Extract("field", path="verdict"))
```

`sf.signal(key)` compares with `>`, `>=`, `<`, `<=` and `==`. The number must be finite. There is
no `!=`, and no `and` or `or`: a Filter has one test. `sf.signal(key) == sf.signal(key)` stays a
plain `bool`, and a comparison is not a `bool` (`if sf.signal("cost_usd") < 1:` raises
`TypeError`). A threshold is stored as a float, so `1` and `1.0` are one test.
`sf.signal("field:x") == True` also passes a member whose number is `1.0`, because a signal holds a
float. A member with no value for the signal, or that failed to answer, is dropped.
An accounting key (`cost_usd`, `latency_ms`, `tokens_in`, `tokens_out`) reads the model calls of
each member, and `sf.signal("score:judge")` needs `judge=sf.Judge(..., returns="scores")` on the
same Filter. A regex reads the original text of the member, never the extracted answer.
`extract=` reads each answer first: a member whose answer cannot be read is dropped, and the
report shows the value it read.

A Filter can keep the members that a judge scores high enough. One judge call scores every
member, and the Filter keeps each member whose score passes the test:

```python
judged = sf.Filter(
    where=sf.signal("score:judge") >= 7,
    judge=sf.Judge("openai/gpt-5.5", returns="scores", rubric="Score each draft from 0 to 10."),
)
```

`where=sf.signal("score:judge")` and `judge=` go together: one without the other raises
`ValueError`. The judge must return scores, and it is always told that a higher number is
better (a judge with `order="min"` is refused). A judge reply that is not one finite score for
each member fails the Case with `judge_reply_invalid`.

A Filter that keeps no member abstains: its `combine` evidence has the result `abstain` with the
reason `no_votes`. The next stage still runs, and it gets the input and no member:
`{"input":"...","selected":[]}`. So a writer can say that no answer passed. (The Case is not marked
`abstained`, because a Filter is never the final step.) The report shows a pass mark in
`members[].score` of the `combine` evidence: `1.0` when the member is kept, `0.0` when it is
dropped, and `None` when the member failed to answer. The block form is `sf.Reduce("filter",
where=..., extract=..., judge=...)`. The place rules of "Rank and Concat selections" apply to a
Filter too. This needs an Engine whose operator catalog has `filter@1` and `kept@1`.

A member with no value for the signal of `where=` keeps the mark `0.0`. In the evidence, it has
the status `"excluded"` and the reason `no_signal`.

### Combine recipes

Each row is one combine scenario with a recipe that you can copy. Each recipe runs offline in the
Engine's tests, from the url4 that the SDK compiles. A scenario that needs two values from each
member (an answer and a confidence) asks each member for one JSON reply. Ask every member for the
same confidence scale, for example 0 to 1. The Engine cannot see that one member writes 80 and
another member writes 0.8.

| S | Scenario | Recipe |
|---|---|---|
| S1 | Read a number from each answer and return the median number | `s1_median_number` |
| S2 | Read a number from each answer and return the answer nearest the median | `s2_median_member` |
| S3 | Read a number from each answer and return the mean, with fixed weights | `s3_mean_static` |
| S4 | Read the answer and the confidence of each JSON reply and return the mean weighted by confidence | `s4_mean_by_confidence` |
| S4, median form | Read the answer and the confidence of each JSON reply and return the median weighted by confidence | `s4_median_by_confidence` or `sf.Reduce("median", extract=sf.Extract("field", path="answer"), weights=sf.signal("field:confidence"), select="value")` |
| S5 | Return the answer with the highest confidence | `s5_max_confidence` or `sf.Pick(..., output="answer")` |
| S7 | Keep the 2 answers with the highest confidence, then a writer combines them | `s7_top_confidence` |
| S8 | Return the answer with the highest confidence, read as a signal | `s8_argmax_confidence` or `sf.Pick(..., output="answer")` |
| S9 | Keep the answers with a confidence above 0.7, then a writer combines them | `s9_confident_only` |
| S10 | A judge scores each answer, keep the best 2, then a writer combines them | `s10_judge_top` |
| S10, threshold form | A judge scores each answer, keep the answers with a score of 7 or more (see "Filter selection") | `sf.Filter(where=sf.signal("score:judge") >= 7, judge=sf.Judge(m, returns="scores", rubric=R))` |
| S11 | A judge scores each answer and returns the best answer | `s11_judge_best` |
| S11, min form | A judge scores each answer with a lower number as better, and returns the answer with the lowest score | `sf.Judge(m, returns="scores", rubric=R, order="min")` |

```python
import screamingface as sf

routes = ["provider/alpha", "provider/beta", "provider/gamma"]
# Ask every member for the same JSON reply and the same confidence scale (0 to 1).
reply_json = (
    "Answer the request. Reply with only one JSON object: "
    '{"answer": "<your answer>", "confidence": <a number from 0 to 1>}.'
)
json_members = [sf.Model(route, prompt=reply_json) for route in routes]
writer = sf.Model(
    "provider/writer", prompt="Write the final answer to the input from the selected answers."
)
judge = sf.Judge(
    "provider/judge", returns="scores", rubric="Give a higher number to a more correct answer."
)

s1_median_number = sf.Fusion(routes, synthesizer=sf.Median(extract="last_number", select="value"))
s2_median_member = sf.Fusion(routes, synthesizer=sf.Median(extract="last_number"))
s3_mean_static = sf.Fusion(routes, synthesizer=sf.Mean(weights=(1, 1, 2)))
s4_mean_by_confidence = sf.Fusion(
    json_members,
    synthesizer=sf.Reduce(
        "mean", extract=sf.Extract("field", path="answer"), weights=sf.signal("field:confidence")
    ),
)
s4_median_by_confidence = sf.Fusion(
    json_members,
    synthesizer=sf.Reduce(
        "median",
        extract=sf.Extract("field", path="answer"),
        weights=sf.signal("field:confidence"),
        select="value",
    ),
)
s5_max_confidence = sf.Fusion(json_members, synthesizer=sf.Pick("confidence", order="max"))
s7_top_confidence = sf.Pipeline(
    [sf.Fusion(json_members, synthesizer=sf.Rank(k=2, by_field="confidence")), writer]
)
s8_argmax_confidence = sf.Fusion(
    json_members, synthesizer=sf.Pick(by_signal=sf.signal("field:confidence"), order="max")
)
s9_confident_only = sf.Pipeline(
    [
        sf.Fusion(json_members, synthesizer=sf.Filter(where=sf.signal("field:confidence") > 0.7)),
        writer,
    ]
)
s10_judge_top = sf.Pipeline([sf.Fusion(routes, synthesizer=sf.Rank(k=2, by=judge)), writer])
s11_judge_best = sf.Fusion(routes, synthesizer=judge)
```

The writer after a Rank or a Filter gets one JSON object: the Case input and the kept member
texts (see "Rank and Concat selections"). `sf.Rank` gives the kept members best first, and
`sf.Filter` gives them in author order. The `>` test of `sf.Filter` is strict: a confidence of
exactly 0.7 is not kept. When no member passes, the Filter abstains with `no_votes` and the writer
gets `{"input":"...","selected":[]}` (see "Filter selection"). A member whose reply is not JSON has
no confidence, so `sf.Pick` never returns it. When no member has a confidence, the Case abstains. A
judge reply that is not one JSON object with a finite score for each member fails the Case with
`judge_reply_invalid`.

### Signal sources

A Fusion can declare named signals: numbers that the run measures from each member answer. Give
`signals={name: source}` to `sf.Fusion`, and read a name in a rule with `sf.signal(name)`. The
combine evidence records the value of every declared name for every member, also when no rule
reads it. A rule that reads a name that the Fusion does not declare raises `ValueError` before any
call.

- `sf.Verbalized(pattern)` reads a number that the member writes in its text, for example
  `Confidence: 90`. The pattern is an RE2 pattern with exactly one group. The last match counts,
  and the number stays as the member wrote it. When nothing matches, or the group is not a decimal
  number, the member has no value.
- `sf.Logprob("mean" | "sum" | "prob")` reads the token log-probabilities of the reply, over all
  reply tokens. `mean` is the mean, `sum` is the sum, and `prob` is `exp(mean)`, a number above 0
  and at most 1.
- `sf.Entropy(top_logprobs=5)` is the mean token entropy of the reply, in nats, from the first
  `top_logprobs` alternatives of each token (1 to 20, default 5). A lower entropy means a more
  certain model.

Each row is one recipe that you can copy. Each recipe runs offline in the Engine's tests, from the
url4 that the SDK compiles.

| S | Scenario | Recipe |
|---|---|---|
| S12 | A vote weighted by the confidence that each member states | `s12_verbalized_vote` |
| S13 | A vote weighted by the token probability of each answer | `s13_logprob_vote` |
| S14 | Return the answer with the highest mean token log-probability | `s14_logprob_best` |
| S15 | Return the answer with the lowest mean token entropy | `s15_entropy_best` |
| S16 | Record a small model's mean log-probability against a threshold, then a larger writer | `s16_logprob_threshold` |

```python
import screamingface as sf

routes = [
    "openrouter/openai/gpt-4o-mini",
    "openrouter/openai/gpt-4.1-mini",
    "openrouter/openai/gpt-4.1-nano",
]
# Ask every member for the same confidence scale (0 to 100), and for the answer on the last line.
stated = (
    "Answer the request. On the first line write Confidence: and a whole number from 0 to 100. "
    "On the last line write only your final answer."
)

s12_verbalized_vote = sf.Fusion(
    [sf.Model(route, prompt=stated) for route in routes],
    signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")},
    synthesizer=sf.Vote(weights=sf.signal("conf")),
)
s13_logprob_vote = sf.Fusion(
    routes, signals={"p": sf.Logprob("prob")}, synthesizer=sf.Vote(weights=sf.signal("p"))
)
s14_logprob_best = sf.Fusion(
    routes,
    signals={"lp": sf.Logprob("mean")},
    synthesizer=sf.Pick(by_signal=sf.signal("lp"), order="max"),
)
s15_entropy_best = sf.Fusion(
    routes,
    signals={"ent": sf.Entropy()},
    synthesizer=sf.Pick(by_signal=sf.signal("ent"), order="min"),
)
s16_logprob_threshold = sf.Pipeline(
    [
        sf.Fusion(
            ["openrouter/openai/gpt-4o-mini"],
            signals={"lp": sf.Logprob("mean")},
            synthesizer=sf.Filter(where=sf.signal("lp") >= -0.3),
        ),
        sf.Model(
            "openrouter/openai/gpt-4.1",
            prompt="Write the final answer to the input from the selected answers.",
        ),
    ]
)
```

Ask every member for the same confidence scale. The Engine does not change the numbers: a member
that writes 90 and a member that writes 0.9 get very different weights. The Engine reads only the
last 64 KiB (65,536 characters) of each reply, so put the confidence line in that part. A line
before a longer text is not found, and that member has no value.

`sum` favors short replies: each token adds a number of 0 or less, so a longer reply has a lower
sum. `mean` and `prob` do not depend on the reply length, so use them to compare members.

A vote weight must be above 0. A `mean` or a `sum` is 0 or less, so `sf.Vote`, `sf.Median` and
`sf.Mean` refuse `sf.Logprob("mean")` and `sf.Logprob("sum")` as weights when you build the Fusion.
They also refuse `sf.Entropy`, because a higher entropy means less confidence: use `sf.Pick` or
`sf.Rank` with `order="min"` for entropy. Use `sf.Logprob("prob")` as a vote weight. The error
says so:

```python
try:
    sf.Fusion(
        routes,
        signals={"lp": sf.Logprob("mean")},
        synthesizer=sf.Vote(weights=sf.signal("lp")),
    )
except ValueError as error:
    print(error)  # names the fix: sf.Logprob("prob")
```

`sf.Logprob` and `sf.Entropy` work with OpenRouter models only, and each member must be one model
call (not a nested Fusion or Pipeline). The SDK asks each member call for `logprobs`, and also for
`top_logprobs` when the Fusion declares `sf.Entropy`. A model that the gateway parameter catalog
marks without logprobs is refused before any call. A model that cannot return logprobs at run time
fails with `logprobs_unsupported` and the Case fails; under a quorum, that member is left out and
shows as `missing`. A live test verifies one model: `openrouter/openai/gpt-4o-mini`.

Logprobs make each reply larger. The gateway cache does not keep a reply over 1,000,000 bytes, so a
rerun calls the model again, and the numbers can change. A frozen copy does not keep an entry over
2,000,000 bytes (request plus reply), and the capture reports `failed`. Keep `top_logprobs` small
when you need a replay that gives the same numbers.

S16 records the small model's value and whether it passed the Filter. The larger model still runs
on every Case: a cascade that skips it comes with E4c. When the small model does not pass, the
writer gets `{"input":"...","selected":[]}`.

### Fusion as a named recipe

`sf.Fusion(members, synthesizer=sf.Model(p))` is the named recipe Fan-out, then
`Reduce.compute(context)`, then Model. The block form says the same in blocks:

```python
block = sf.Pipeline(
    [
        sf.Fusion(routes, synthesizer=sf.Reduce("context")),
        sf.Model("openrouter/openai/gpt-5.5", prompt="Write the final answer from the drafts."),
    ]
)
same = sf.Fusion(
    routes,
    synthesizer=sf.Model(
        "openrouter/openai/gpt-5.5", prompt="Write the final answer from the drafts."
    ),
)
```

Before the compile, the SDK rewrites the block form to the Fusion. The two give the same url4, byte
for byte, and the same operation ids (`op_synthesis_N`). The rewrite keeps the stages after the
synthesizer (`Pipeline([Fusion(m, Reduce("context")), S, *rest])` is `Pipeline([Fusion(m, S), *rest])`),
and a named Pipeline keeps its name. A Fusion that was made with `sf.Fusion(...)` is not changed by
the rewrite. The candidate is named from the rewritten value, so both forms report `a+b`, and
`report.candidates[...]` uses that name (the block form's own `name` is `a+b->s`). Two block forms that
get the same name raise `ValueError`: give each one `name=`. The
`context` block makes no combine call: it needs no operator catalog (no `GET /v1/operators`) and it
has no member limit.

Use `sf.Reduce("context")` only as the synthesizer of a Fusion that is followed by the real
synthesizer in the same Pipeline. In every other place (the last stage, a Fusion member, a loop
member, or before another `context` Fusion) it raises `ValueError` before any call. To write a
multi-stage synthesizer in the block form, give it a name: `sf.Pipeline` makes an unnamed nested
Pipeline flat, so `sf.Pipeline([sf.Fusion(m, sf.Reduce("context")), sf.Pipeline([j, w])])` is read as
`[Fusion, j, w]`. Use `sf.Pipeline([j, w], name="judge-write")`, or a Fusion, as the synthesizer.

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

`sf.configure(...)` replaces and closes any existing default Client. A non-default `engine_url`
must come with its `scoreboard_url`; the call raises otherwise, so a local or preview Engine can
never publish to the hosted leaderboard by accident. The same holds for the environment:
`SCREAMINGFACE_ENGINE_URL` needs `SCREAMINGFACE_SCOREBOARD_URL`. `sf.close()` releases the
default Client so the next module-level operation constructs a fresh one.

The Client hides Benchmark fetching, URL4 compilation, REST/WebSocket transport, Event replay,
and Report decoding behind `sf.evaluate(...)`.

### Hosted caller authentication

Hosted Engines may be protected by Cloudflare Access. The Client logs in through the browser on
first use. For an unattended run that a person started (for example the e2e workbench), set
`SCREAMINGFACE_ACCESS_TOKEN` to an Access application token (`cloudflared access token -app=<engine
url>`); the Client uses it for every origin whose Access audience matches the token's `aud`, and
falls back to the browser login otherwise. The token acts as the person it was issued to.

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

JSON export serializes one Case at a time and replaces the destination only after the complete
file is flushed and fsynced. Existing output symlinks and ordinary file permissions are
preserved; new files honor the process umask. A failure before replacement keeps the previous
file. On POSIX, failure during the final directory fsync means replacement happened but its
durability is unconfirmed. `to_json()` uses the same serializer, but its returned string
still occupies memory; use `export()` for large reports.

`CandidateResult.client_version` records the caller-reported Client version retained by the
Engine for that run. It is also present in each candidate in `report.json`; missing or ambiguous
evidence is `null`. It is not the version of the Client later exporting the report, nor the
version that originally generated cached model answers.

Each entry in `CandidateResult.operations` is a public immutable `sf.OperationInfo` value.

Authentication, validation, transport, execution, protocol, and invalid-result failures raise
typed exceptions.

Expected SDK failures inherit from `ScreamingFaceError` and always carry a stable error code, plus
an optional HTTP status, structured details, remediation hint, and `permanent`/`retryable`
classification. The public classes reflect distinct recovery actions:

- `EngineUnavailableError`: start, reconfigure, or retry the Engine.
- `AuthenticationError`: authenticate the caller again.
- `PlanningError`: change the Candidate, Benchmark, Model, or evaluation configuration.
- `ExecutionError`: inspect or retry a Run that failed after reaching the Engine.
- `ProviderConnectionError`: change a provider credential or provider connection.

These classes arrive directly when the failure happens before any Candidate runs — for example
while the Client loads the Benchmark or the Model catalogue — and when an Evaluation has one
Candidate. A multi-Candidate Evaluation is different once its Candidates run: one failed
Candidate does not stop the others. They run to their end, the progress output marks the failed
row at once, and then the Evaluation raises `ExecutionError` with `code="candidates_failed"`:

- `error.details["failed"]` maps each failed Candidate's name to its error code, for example
  `websocket_disconnected`, `engine_at_capacity`, `authentication_failed` or
  `engine_unreachable` (`unexpected_error` when the failure had no SDK code);
- `error.__cause__` is the first failure itself, so an `AuthenticationError` or
  `EngineUnavailableError` from a running Candidate is found there, not raised directly;
- `error.partial_report` is a `Report` of the Candidates that succeeded, or `None` when none
  did. It holds nothing for a failed Candidate.

To keep the paid results, export the Partial Report; `details["failed"]` names the Candidates to run again:

```python
try:
    report = sf.evaluate(candidates, benchmark="draco")
except sf.ExecutionError as error:
    if error.code != "candidates_failed":
        raise
    if error.partial_report is not None:
        error.partial_report.export("partial-report.json")
    failed = error.details["failed"]  # {candidate name: code}
```

Ctrl-C, task cancellation, and an exception raised by your own `on_event` callback still stop
every Run of the Evaluation and re-raise that exception unchanged.

IPython and Jupyter render these failures as a concise message, hint, and code instead of exposing
dependency tracebacks. Notebook panels render the same safe text inline. Programmatic callers can
catch a specific recovery class or catch `ScreamingFaceError` for every expected SDK failure;
translated low-level failures remain attached through `error.__cause__` for debugging. Programmer
errors such as invalid Python argument types retain their normal tracebacks.

Every `CandidateResult` exposes the Engine-owned top-level `coverage` ratio. A partial score remains
available alongside the Cases that could not be graded, and the notebook Report panel labels the
result as partial rather than silently presenting it as a complete evaluation.

### Browse completed Case results

Install `screamingface[notebook]` and display a completed `report` in a live notebook to
browse 25 Case results per page. Use Previous/Next, enter an exact Case ID in Go to case
number, or filter by Candidate using the dropdown or a Candidate name. The answer/grading
and cost views remain available for every result. Numeric and string Case IDs retain their
original identity.

Download prepares the complete report JSON on disk, including every Candidate and Case,
then provides a Jupyter file link (or the saved path when no local server serves it).
In Colab it uses the native browser download API; the button can download the saved file
again without re-exporting it. Jupyter prepares exports and pages asynchronously. Colab
publishes bounded page changes and streaming exports inside the click callback, as its
widget transport requires. Failures leave the current page available and allow retry.
`report.export('report.json')` also writes the complete portable artifact directly.

Colab's custom widget manager is enabled automatically for this browser. The notebook extra
accepts ipywidgets 7.7.1 and 8, preserving Colab's compatible preinstalled version. If you
previously upgraded Colab to ipywidgets 8 and see a blank report, install
`ipywidgets==7.7.1` and restart the Colab session before displaying the report. Ordinary
Jupyter supports ipywidgets 8. Case clicks use Colab’s native callback API there and
ipywidgets DOM events in Jupyter. This compatibility verification covers completed reports;
older-widget live-progress accessibility has separate existing limitations.

Static HTML, including environments without the notebook extra, previews the first 25
results and shortens oversized Case panes. Small JSON downloads remain inline; larger
ones use explicit export. The complete retained data remains available through the Report
and JSON export.

### Completed accounting breakdown

Each Candidate exposes derived views of the Engine's retained operation and grading records:

```python
breakdown = report.candidates[0].accounting
breakdown.by_stage  # generation, synthesis, grading
breakdown.by_operation  # (stage, operation/check id)
breakdown.by_member  # direct model-member operation ids
breakdown.by_model  # request model or reliable declared identity; None when unknown
breakdown.by_case  # original Case ids
breakdown.unattributed_cost_usd
```

Each group has `usage`, `calls`, `cache`, `provider_latency_ms`, and `provider_attempts`.
These summarize retained observations; they do not replace the authoritative run total.
Missing observations remain unknown. A missing record stays in its declared model group
when that identity is unambiguous and agrees with retained requests. If any row's model
cannot be identified, all named `by_model` summaries are unknown: the unidentified work
could belong to any of them. The `None` bucket summarizes only its anonymous observations.
Calls count consumed responses, not provider retries.
Provider time sums attempt latencies and is not wall time. Unknown or unpriced costs prevent
an exact remainder; inconsistent records disable the breakdown (`consistent=False`).
Loop internals and composite-member ownership remain unattributed where the retained contract
cannot prove their scope. Derived group views are not added to Report JSON.

Each completed Report Case has **Answer & grading** and **Cost & usage** views.
The latter shows labelled activity blocks; whole-run totals remain above the Cases.
Try [the offline review notebook](examples/14_report_accounting.ipynb) without credentials or
paid calls. Its synthetic figures are explicitly labelled; actual evaluations use the same UI.

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

# After evaluating, with capture=True, a Benchmark whose Scoreboard accepts submissions:
submission = sf.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
)
same_submission = sf.leaderboards.get_score(submission.id)

# Add or fix the paper link and authors of a score you submitted, then read the edit log:
sf.leaderboards.edit(submission.id, paper_url="https://arxiv.org/abs/2610.01234")
edit_log = sf.leaderboards.metadata_events(submission.id)

# Attach open metadata about the authors (keyed by email) and the paper:
sf.leaderboards.edit(
    submission.id,
    authors_metadata={"alice@example.com": {"full_name": "Alice Smith", "institution": "Uni"}},
    paper_metadata={"title": "Our ensemble", "url": "https://arxiv.org/abs/2610.01234"},
)

# Replay the published run at $0 from its pinned cache (None unless it ran with capture=True):
replay = sf.evaluate(pinned_cache=same_submission.pinned_cache)
reproduction = replay.candidates.only.reproduction
if reproduction is not None:
    verdict = reproduction.outcome  # "exact" or "failed"; failures include .reason
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
`submit(..., paper_url=...)` links a paper you have already published (an `http` or `https` link
with a host and no user info or whitespace). Later, the submitter can call
`edit(score_id, authors=..., paper_url=...)`: an argument you leave out stays unchanged,
`paper_url=None` clears the link, and `authors=None` is refused (pass `[submitter]` to go back to
the default). `edit` returns the updated `LeaderboardScore`, which carries `paper_url` and
`metadata_updated_at`. `metadata_events(score_id)` returns the owner-only edit log as
`ScoreMetadataEvent` rows with the old and new values. The SDK does not check that the paper exists
or that the authors wrote it. A Scoreboard deployment may
keep writes closed, in which case `submit()` raises a typed `LeaderboardError`. Explicit Clients
expose the same interface at `client.leaderboards`; asynchronous Clients use `await`. The
Scoreboard is the deployed data system, while a Leaderboard is the ranked domain resource returned
to callers.

Provider access and explicit Candidate parameters are preflighted before execution. The SDK
fetches one detail document per distinct required Candidate Model, including parameter-free
Models, and reuses any document fetched during model admission. Authoritative missing provider
access raises `ProviderConnectionError` before any Candidate dispatch or progress events, with a
hint to configure BYOK via `sf.connect()` or enable the selected hosted provider profile.
`ModelDetails.execution_access` is `"configured"`, `"missing"`, or `None` when an older Gateway
omits the field. Unknown access preserves existing behavior; the early missing-access guarantee
requires a Gateway that publishes the field. Configured access is not credential validation.
Missing, disabled, wrong-type, or out-of-range parameters also fail before any paid Run begins.
Access and capability data come from Engine/AI Gateway discovery, with no provider-specific
credential or parameter rules in the SDK. Sync and async Clients use the same checks.

The returned catalogues are immutable ordered sequences: iteration, indexing, slicing, and
`len()` work normally in scripts and sidecars. Evaluating one in Jupyter automatically renders a
searchable catalogue when the `notebook` extra is installed, with escaped static HTML and compact
terminal representations as fallbacks. Notebook rendering does not change the underlying values
or introduce a separate discovery operation.

### Replay a published run

`evaluate(..., capture=True)` captures a **pinned cache**: every model and web-tool answer of the
run, stored with it (`CandidateResult.pinned_cache`). Capture is off by default. After the result is submitted,
`sf.evaluate(pinned_cache="<id>")` replays that run at $0: the recipe and answer seed come from the
public board, and every call is answered from the pinned cache. `CandidateResult.reproduction` then
says whether the replay gave the published score: `exact`, or `failed` with a `reason` and the
cases the pinned cache could not answer. An exact replay is recorded on the board (a leaderboard
login is asked for only then) unless `record_reproduction=False`.

- `score_id="<id>"` replays a score on a private board that you submitted.
- `url4=` is optional; when passed it must be the same parsed recipe as the published one. A passed
  `answer_seed` must equal the captured run's; a run captured without a seed replays without one.
- `limit=n` replays only the first n cases, for debugging. It is never judged or recorded.
- A capture that was never submitted replays with `url4=` (and `answer_seed=` if it had one) and
  has no verdict.
- A replay that cannot start (a partial capture, or an Engine that does not replay) raises
  `sf.ReproductionError`. Every other mismatch fails before any run.

## Examples

From a checkout, `just local-stack-notebooks` runs every notebook below: it bakes the frozen
benchmark assets, brings the local stack up, serves an Engine carrying the imported
inspect_evals boards alongside ours, and opens JupyterLab against it.

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
- [`examples/12_inspect_evals_benchmarks.ipynb`](examples/12_inspect_evals_benchmarks.ipynb): the
  catalogue as two origin groups — ours and the imported inspect_evals boards — then a
  Fusion against one of the imported boards.

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


## Reopen completed results

Public `Client` and `AsyncClient` instances save completed-run metadata before downloading
results. Artifact downloads are streamed and checked against the Engine ticket's size and
SHA-256. Cases are validated incrementally into a disk index and loaded on demand, preserving
prompts, answers, grading, operations, accounting, and the SDK's run provenance.

```python
import screamingface as sf

entries = sf.reports.list()
report = sf.reports.get(entries[0].id)
# In async code: report = await sf.reports.get_async(entries[0].id)
# Explicit removal: sf.reports.delete(entries[0].id)
```

The default location is `~/.screamingface/results`; `SCREAMINGFACE_RESULTS_DIR` overrides it,
or use `SCREAMINGFACE_DATA_DIR` to choose the containing data directory. `list()` reads
lightweight metadata and groups Candidates from the same Evaluation. `get()` and
`get_async()` use local copies when available and obtain fresh authentication when a missing
artifact needs downloading. They never start model runs. `destination='/another/disk'`
lets recovery copy retained results to another location. Incomplete recovery raises the
existing `candidates_failed` error with a `partial_report` and named Candidate failures.

New saved evaluations track whether evaluation, notebook display or JSON export is in progress.
When a POSIX notebook process exits unexpectedly, the next persisted Client for the same Engine
shows an informational notice with an explicit `sf.reports.get(...)` command for retained completed
results. It does not rerun models or recover automatically. Healthy, active and legacy results
stay quiet; headless Clients do not scan results at startup. Owners that cannot be verified dead
(including non-POSIX environments) are treated conservatively. Process-ID reuse can also suppress
a notice; saved results remain available through `sf.reports.list()`. On POSIX, overlapping
notebooks sharing the same directory preserve one another's unfinished work, including when
a saved Candidate is recovered, displayed or exported from another process.

Local copies remain until explicit deletion. Deleting a report also makes existing
Reports backed by its files unreadable. Recovery requires a saved completion record and
either a valid local raw result or an unexpired Engine artifact. An unavailable artifact
reports `result_expired` with its age. Death before completion is recorded cannot be recovered.
Disk failures report `result_storage_failed`; collection never silently falls back to RAM.
Only completion/result metadata is saved, never authentication credentials.

Set `Client(save_results=False)` or `AsyncClient(save_results=False)` for the previous
in-memory collection path. These options do not change a custom supplied `run_transport`.
Calling `to_dict()`, `to_json()`, converting Cases to a list, or requesting a Case slice
still materializes the requested data. `CandidateResult.accounting` also materializes its
full accounting breakdown. Notebook cost disclosures instead derive a compact context by
streaming Cases and cache that context beside a saved Case index on first use. Warm run-level
disclosures reuse the cache without decoding Cases; missing, stale or malformed caches
rebuild, and a read-only cache location still returns derived values. Per-Case HTML still
materializes its rendered output. Automatic lifecycle discovery remains a separate follow-up.

## Optional analytics (dev preview)

Analytics is off until you explicitly opt in. In local Python or Jupyter:

```python
import screamingface as sf

sf.analytics.enable()  # Remember consent for this OS user
sf.analytics.status()  # Inspect consent and effective state
sf.analytics.disable()  # Stop sending and remove the local identifier
sf.analytics.reset_identifier()  # Start a new identifier without linking it
```

The equivalent commands are `screamingface analytics status`, `enable`, `disable`
and `reset-id`. They do not start local runtime services. `sf.analytics.enable(persist=False)`
accepts for this process only when you do not want persistent preferences.
`sf.analytics.disable(process_only=True)` stops this process without changing the saved choice.
A truthy `DO_NOT_TRACK` overrides acceptance. Noninteractive use never prompts.

Explicit interactive `sf.connect()` setup shows a nonblocking notice if no choice
is saved. Continue without choosing to leave analytics off; the notice does not
wait for input or run during evaluation. Saved choices have no scheduled re-prompt.

Preferences live in `~/.screamingface/analytics.json`, or the explicit
`SCREAMINGFACE_ANALYTICS_CONFIG` path. This is independent of runtime `--data-dir`,
virtual environments and project directories. Writes are atomic and owner-only;
unreadable or malformed preferences disable collection. Failed preference writes
raise an error rather than claiming consent was saved.

The four events are `evaluation_started`, `evaluation_finished`,
`submission_started` and `submission_finished`. They contain random installation,
session and operation IDs, SDK version, Python/Jupyter origin, sync/async interface,
recipe/raw-URL4/submission workflow, outcome and coarse duration. For the current
release, local engines map to BYOK and remote engines to hosted. No prompts,
responses, scores, provider/model names, execution IDs, credentials or email are sent.

An installation ID is shared by processes using the same preference file; a session
ID is created lazily per process/kernel. Opt-out or identifier reset also invalidates
the active session so replacement identifiers cannot be joined through it. These
identifiers measure consenting installations/sessions, not verified people.

The SDK defaults to `https://analytics.screamingface.ai`. Set
`SCREAMINGFACE_ANALYTICS_ENDPOINT` to an HTTPS origin **before first analytics use**
to select another deployment, for example:

```bash
export SCREAMINGFACE_ANALYTICS_ENDPOINT=https://analytics.dev.screamingface.ai
# For staging: https://analytics.staging.screamingface.ai
```

Restart the process/kernel to change destinations. This setting is independent of
the engine URL; there is no automatic detection or fallback to another deployment.
The selected service owns the PostHog project configuration; the SDK needs no
PostHog token. Local consent remains installation-wide, so use a separate
`SCREAMINGFACE_ANALYTICS_CONFIG` file for isolated test consent/identifiers.
Native delivery posts to `/v1/events`, without product credentials or cookies. Delivery has a memory-only queue capped at 100 pending events, at most two
attempts per event and a two-second total delivery budget. It never waits for HTTP
in evaluation, never waits for delivery at shutdown, and may lose events. Consent
is rechecked before dispatch and retry; already dispatched requests can complete
after opt-out. There is no durable event spool.

In Colab, explicit `sf.connect()` setup starts a consent-only browser bridge in a
background worker. Unknown consent shows the same nonblocking disclosure. Use
`sf.analytics.enable()` to accept: it waits up to three seconds for confirmed browser
consent and a usable ID, then prints `Analytics enabled.` or
`Couldn't enable analytics; tracking remains off.` It returns `None`, so notebooks show only the confirmation message. Use
`sf.analytics.status()` for programmatic checks and detailed state. After successful return, the next evaluation
can be tracked without a separate polling cell. A timed-out acceptance is cancelled
locally so a late response cannot silently enable tracking.

Automatic setup and event delivery remain nonblocking. `sf.analytics.disable()`
stops local tracking immediately and returns `None`. It prints `Analytics disabled.`
and, while browser persistence is pending, `Saving your choice in the browser.`
Use `sf.analytics.status()` to inspect `pending` until acknowledged. Operations begun before consent is
confirmed are skipped, never replayed retroactively.

Colab uses the selected service's `/bridge/consent` iframe and cookie-checked
`/bridge/id/events` route. The runtime never receives the cookie itself or sends
events directly to `/v1/events`. The status has `scope="browser"` and an anonymous
`persistent_id`; `installation_id` is absent in meaning (`None`). No local consent
file is used. `persist=False` is unsupported in Colab because the server requires
browser consent for every batch. Process-only disable does not alter remembered
browser consent; normal disable requests a persisted decline. DNT suppresses all
requests, including decline persistence, so it cannot clear existing browser cookies.

The Colab queue holds at most 100 events, with one daemon worker and no retry.
Each initialization or control sequence shares a two-second Python budget, with
a shorter browser deadline for each command. Consent, DNT and cancellation are
rechecked before follow-on commands, including ID retrieval.
Blocked storage or browser errors fail closed; there is no runtime HTTP fallback.
Late replies cannot re-enable the kernel after opt-out. Already-dispatched requests
may complete; successful persisted decline prevents subsequent bridge delivery.
Cookie continuity is per browser profile/Colab partition, not cross-browser identity.
Safari may show a first-run Colab JavaScript-output warning, also reproduced without
this bridge. Real Colab background-worker verification remains a release gate.

There is no identity linking. Events follow PostHog-managed retention under the
selected plan; ScreamingFace does not promise a fixed raw-event deletion deadline.
A query retention window is not a guarantee of physical deletion, and session
recording retention does not control these events. Disabling or resetting an
identifier does not delete previously accepted events. Production rollout still
requires verified IP handling and a historical-deletion procedure.
