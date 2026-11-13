# Caching and compute

Source: https://docs.screamingface.ai/learn/caching

What a run bills: call-level caching, a shared community cache, and where the compute comes from.

Evaluating a fusion means many model calls, and calls cost money and time. ScreamingFace addresses that in two ways: it caches calls to the providers that support it, and it gives you a choice of where the compute comes from.

## How caching works

When the [engine](learn-engine.md) calls a model on a provider that supports caching, it stores the response keyed by the exact request. Reuse the same model in another candidate, or run the same evaluation again, and the stored response is served instead of paying for it twice. Only some providers support it; the Providers table below shows which. A local engine starts with the request cache on: `screamingface up` sets `AIGW_REQUEST_CACHE_ENABLED=true` unless the variable is already exported, so `export AIGW_REQUEST_CACHE_ENABLED=false` before `screamingface up` turns it off. Cache entries do not expire. `use_cache=False` on `sf.evaluate`, `Client.evaluate` and `AsyncClient.evaluate` opts one evaluation out: every model call is made fresh, and the report shows those calls as cache `bypass` with the reason `opted_out`.

-   **Within a run:** with the cache on, an identical call from another candidate is served from the cache. Calls are matched by a fingerprint of the route, prompt and parameters, not by model object, so two identical model objects share one cached response. The first candidate to run stores the response and the next one reuses it.
-   **Across runs:** with the cache on, a call that repeats exactly is served from the cache. A call whose input changed, such as the second turn of a case whose first answer differs, is paid again. A run that failed partway can be restarted: the calls that already completed and repeat exactly come back from the cache.

## The shared community cache

A hosted engine's cache is shared across the community. If anyone has already run the same model configuration against a benchmark, that call is a cache hit for you as well, at no cost. This sharing covers model calls. The gateway also caches web-search and web-fetch results, but only for each account: a result that one account stored is never given to another account.

A published result carries its [url4](learn-url4.md). A call from that url4 that is already in the shared cache is served from it.

The shared cache belongs to the hosted engine. A local engine has its own cache, on by default, which bills a rerun only for the calls not made before, but starts empty and stays yours. Running everything yourself means giving up the community's hits unless you pull them, as the next section shows.

### Pull the community cache into a local engine

`sf.cache.pull_from_remote()` copies the shareable rows of the hosted community cache into the local gateway database. A local run then answers from those rows, for free, the calls the community has already made. `screamingface cache pull` does the same from a shell. The pull opens a hosted sign-in in a browser, so it needs hosted access. The [Cache reference](sf-client-api-cache.md) has the signatures, the result type and the errors.

## Reproducing a submission

A cache saves money, but it is not a record. Its rules can change between releases, and a model can be retired. So a run can make a **pinned cache** of itself. A pinned cache keeps every model answer and every web-tool result of the run. It is separate from the request cache. It does not use the cache's keys or rules, and it is kept forever.

A run makes a pinned cache of itself when you pass `capture=True`. Capture is off by default. A leaderboard submission keeps the pinned cache id and the capture status. `sf.evaluate(pinned_cache="…")` reads the published score's [url4](learn-url4.md) and answer seed from the board and replays the captured answers. A replay never captures; explicit `capture=True` is an error. The [Leaderboards guide](sf-client-guides-leaderboards.md) shows the calls and the outcomes.

An optional `url4=` must be the same parsed recipe as the published one. An explicit `answer_seed=` must match the stored seed; `0` is a seed, and a seedless capture replays without one. Use `score_id=` to replay a private score you submitted, logging in when asked. A capture with no public score needs its original `url4` and seed, and returns no verdict.

To inspect the first few cases, pass `limit=n` with a published score, where `0 < n < published case count`. A partial replay is never judged or recorded: `reproduction` is `None`. The Engine must still be able to rebuild the published recipe and a compatible subset; otherwise the Client raises `PlanningError` with code `partial_replay_unavailable`. This is different from a partial capture, which cannot be reproduced.

### Make a pinned cache

When capture is on (`capture=True`), the Engine opens a pinned cache in the [AI gateway](learn-ai-gateway.md) when the run starts. The gateway stores each model answer. It stores the answer that the caller got, whether the answer came from the cache or from a live call. Model calls of the benchmark's judges are stored too. The Engine stores each web-search and web-fetch result as the tool returned it, before the Engine cuts it to length. When the run ends, the Engine seals the copy. A sealed copy cannot change.

An `exact` replay shows that the copy is internally consistent: its stored answers give the stored score. The copy keeps each web-tool result as the run reported it. An `exact` replay does not prove that those results are the true web results.

Capture adds no call to a provider. It is best effort. If the gateway cannot store something, the run still goes on and still returns its result. The copy is then `partial`.

Keep one thing in mind. The pinned cache id is part of a published score. Any authenticated gateway account that has the id and sends the exact request can read the stored answer. On a private board, only the submitter of a score can read it, so no one else gets its pinned cache id. Capture is off by default. Pass `capture=True` only to a run whose answers you want to share.

### Local runs

The local runtime starts a real AI gateway with its own SQLite database. A capture on the local runtime is always `partial`, with the reason `local` (`capture_partial_reasons == ('local',)`). Its pinned cache lives only in that local gateway. A local capture is never reproducible on a board.

### Complete and partial

[Diagram: State diagram: a pinned cache is opened, filled, sealed and confirmed by the gateway, and the capture status is complete only when every call is stored and the run did not use the local runtime; a failure to open, a failed, refused, missing, error or ambiguous call, an unconfirmed seal or a local run gives the status partial.]

The states of a pinned cache and the reasons a capture is partial.

A captured run has a `capture_status` and, when the copy opened, a `pinned_cache`. The status is `complete` only when the copy opened, the copy sealed, every model call and every web-tool result is stored, and the run did not use the local runtime. In all other cases it is `partial`. A partial score is not replayed: the Client raises `ReproductionError` with code `not_reproducible` and starts no run. Its `.reproduction.reason` is `partial`.

| Why it is partial | What happened |
| --- | --- |
| Open | The Engine could not open the copy when the run started. The run went on without capture and has no pinned cache id. |
| Seal | The gateway did not confirm the seal at the end of the run. A run that is cancelled is never sealed. A copy that is not sealed cannot be replayed. |
| Failed | The gateway could not store a model answer or a web-tool result. For example, one entry was larger than the gateway's limit for one entry. |
| Refused | The gateway did not take a call into the copy. It never stores a streaming call. It also refuses a call when the copy is unknown, is not open, or belongs to another account. |
| Missing | The gateway did not say whether it stored a call. An older gateway, from before pinned caches, does this. So does a gateway that refused the call before it checked the copy, for example because the request body was not valid. |
| Error | A model call or a web tool ended with no answer to store, for example after a time-out or a cancel, and no later call with the same request was stored. A later call with the same request that was stored removes this reason. |
| Ambiguous | The copy can hold an answer that the model did not use. This is the case when the Engine sent a call again because of a `max-age` bound, or when it retried a call after a transport error. The Engine cannot tell which answer is the right one. |
| Local | The run used the local runtime. Its copy lives only in the local gateway, so a board cannot replay it. |

A model call that ends with an error from the provider is stored with that error. It does not make the run partial. A replay gives the same error, so the case fails in the same way as in the original run.

A run that is not captured has no `capture_status` (`None`), and no pinned cache id. A run is not captured when you do not pass `capture=True`, or when the Engine did not capture it. `None` means unknown, not partial. If capture is on and the Engine did not capture the run (an older Engine), the Client emits an `EvaluationWarning`, and the result keeps `None`. A score from a leaderboard that predates pinned caches has no status too. The Client raises `ReproductionError` with code `not_reproducible` and `.reproduction.reason == "unknown"`. It does the same for a score with no pinned cache id or no benchmark revision.

### Replay from the copy

`sf.evaluate(pinned_cache="…")` asks the Engine to run the score's url4 and answer seed against the pinned cache. The Engine must confirm that it runs in replay mode. In a confirmed replay, every model call goes to the copy, and so does every web-tool read. The copy answers each call with the answer that it stored for the same call. A call matches a stored answer when it has the same case, the same Attempt of that case, the same request, and the same position among identical calls in that case. In each case and Attempt, the first identical call gets the first stored answer, the second gets the second, and so on.

A replay does not depend on the cache or on the models of today. It works after a model is retired, after a provider plugin is removed, and after the cache rules change. A request that the copy cannot answer fails its case.

A replay is `exact` when it gives the stored score and case count on the same benchmark revision. When the score has a case digest, the replay must also give the same digest. The digest covers each case of the run: its id, its status and its score. A case with no grade has no score.

If the Engine does not confirm replay mode when the run starts, it may run the url4 as a normal, paid run. So the Client stops the run and raises `ReproductionError` with code `replay_unsupported`. If that stop fails, an `EvaluationWarning` says that the run may still be running and spending. An Engine can also confirm the start and then finish a run whose summary does not name the copy. That run is already over, and it may have paid providers. The Client reports it with the same exception too, rather than returning a replay report.

### When a replay fails

A full published replay returns a `Report`. Its single `CandidateResult.reproduction` holds the verdict: read `.outcome` for `exact` or `failed`, and `.reason` for a failure. A replay can fail even when its aggregate score matches:

-   **An older engine** may not know replay. The Client raises `ReproductionError` with code `replay_unsupported`; `exc.reproduction` carries the failure.
-   **A copy that is not available.** The copy is unknown, or it is not sealed (for example, the Engine stopped during the original run), or the gateway is older and has no pinned caches. A web-tool lookup or a model call that the gateway does not answer, because of a transport failure or an error other than not found, is the same. Cases fail, and the replay is reported as `frozen_copy_unavailable`.
-   **A changed engine or SDK** may build a request in another way. The copy has no answer for that request, and the case fails with `frozen_copy_miss`. `missed_cases` lists these cases.
-   **Different web tools.** A run that had no web tools (it had no web-search connection) can differ from a replay on an Engine that offers them. The requests then differ, and the case misses the copy.
-   **Same request, different answers.** With sampling, or with the cache off, the same request can get different answers. Each case and Attempt keeps its own answers, in the order that the calls were created. One limit remains: the judge calls for different Attempts of one case share their answers. A replay can swap two identical judge calls that run at the same time, and then the score can differ (`score_differs`).
-   **Different case results.** The score and the case count match, but the case digest does not. The Client reports `cases_differ`.
-   **A changed benchmark** grades a different exam, so the numbers cannot be compared. The Client reports `benchmark_revision_changed`.

A replay call can fail before the copy answers it, for example when every transport attempt fails. That call fails its case with `frozen_copy_unavailable`. The Engine does not send it again as a new call, because a new call would read the next stored answer, which belongs to another call. A `frozen_copy_miss` is not sent again either.

A failed replay is not recorded. It is not proof against the score, because of the known limits above. It is not a confirmation either.

## Where the compute comes from

There are two ways to run. They differ in who supplies the compute and which cache you draw from.

-   **Local:** Run the engine on your own machine with your own provider keys. You pay your providers directly.
-   **Hosted:** Use an engine we operate. It carries the shared cache, and we subsidize compute for chosen cohorts.

[Diagram: The client points at one engine. A local engine runs on your machine with its own cache; a hosted engine we operate carries the shared community cache.]

Same protocol, two engines. A local engine keeps its own cache; the hosted engine carries the shared community cache.

The client code is identical either way; only the engine URL changes. The [Installation](sf-client-installation.md) guide walks through both.

## Providers

A local engine advertises these seven providers. Caching is opt-in per provider: `openrouter`, `anthropic`, `openai` and `huggingface` are served from the cache; the CLI plugins bypass it and dispatch every time. How you connect each one varies (a pasted key or a login through a CLI tool); the [Connect a provider](sf-client-guides-connections.md) guide has the specifics.

| Provider | Reached via | Cached? | What it is |
| --- | --- | --- | --- |
| `openrouter` | API key | Yes | A router over many hosted models (OpenAI, Anthropic, Google, DeepSeek, Qwen and more) behind one key. |
| `anthropic` | API key | Yes | Claude models, direct. |
| `openai` | API key | Yes | OpenAI models, direct. |
| `huggingface` | API key | Yes | Hugging Face inference endpoints. |
| `gemini-cli` | CLI plugin | No | Google Gemini through the gemini CLI. |
| `codex` | CLI plugin | No | OpenAI models through the Codex CLI. |
| `antigravity` | CLI plugin | No | Gemini through the Antigravity CLI. |
