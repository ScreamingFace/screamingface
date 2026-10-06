# Changelog

## Unreleased

### Features

* **screamingface:** carry each Benchmark's provenance and saturation verdict from the Engine catalogue. `Benchmark.provenance` is a `BenchmarkProvenance` (paper, authors, citation, inspect porters as GitHub handles, website, harness pinned to a commit or tag, licence with any note, content warning, a `PublishedScore` human baseline and frontier score, the SDK notebook that runs it) and `Benchmark.saturation` is the Engine's derived verdict (`saturated` / `open` / `unknown`). An Engine that predates them serves neither: `provenance` reads `None` and `saturation` reads `unknown`. The local Scoreboard seed emits the same keys, so a local board shows what a deployed one shows.

* **screamingface:** publish a cached run's full cost when every cache hit is priced (`OME-1463`, decision D7 on `OME-1251`). `CandidateResult.cache_saved_cost_archive_usd` carries what the hits served from archive-matched cache entries would have cost, and `CandidateResult.cache_unpriced_hits` the Engine's count of hits with no price at all (`None` when the Engine sent no run summary). Both serialize into report.json. A leaderboard submission now sends the archive saving as `cache_saved_cost_archive_usd`, beside `run_cost_usd` and `cache_saved_cost_usd` and never added to either; the Scoreboard sums the three. **Behavior change:** a run with cache hits is sent as `complete`, with its spend as `run_cost_usd`, when the Engine's summary shows no unpriced hit and the spend is priced. Any unpriced hit, a missing summary, or an unpriced spend still sends `partial` with no amount. **Requires a Scoreboard that accepts the field** (`OME-1382`); against an older one, an archive-priced run's submission rejects with HTTP 422.

* **screamingface:** render completed per-operation accounting and per-Case details across benchmarks. `CandidateResult.accounting` derives immutable stage, operation, member, model and Case summaries from retained records, preserving unknown values and authoritative root totals. Direct model members receive usage only when every Case has a unique observation. Includes an offline Jupyter review notebook (`14_report_accounting.ipynb`).

* **screamingface:** mark Benchmarks scored by refusal rate. `BenchmarkInfo.inverted_grade` is `True` when every Case score is **already** 1 − the eval's grade (a should-refuse safety Benchmark such as `xstest_unsafe`), and report.json states it in the `benchmark` block — `false` for every other Benchmark. It is read from the Benchmark resource on a normal run (cross-checked against the run result) and from the run result on a replay. It is a mark, not an instruction: never flip a score with it. An Engine that predates the mark omits it, which reads as `false` — so deploy the Engine that ships `xstest_unsafe` and the Engine that sends the mark together.

  **Engines that send the mark need this release first.** An older SDK refuses the run result of a flipped Benchmark ("unsupported field `inverted_grade`"); every other Benchmark is unaffected.
* **screamingface:** show the refusal-rate mark where researchers look. `Benchmark.inverted_grade` carries it from the catalogue (absent means `false`); a flipped Benchmark gets an "inverted grade" chip in `sf.benchmarks` listings, a "grading" line on its card, and one line under the notebook report view's header — all saying "each Case scores 1 − the eval's grade, so higher is still better". Every other Benchmark renders exactly as before.

* **screamingface:** preserve Engine-observed caller version as `CandidateResult.client_version` and in report JSON; unavailable provenance remains null.

* **screamingface:** carry the catalogue's two grouping axes on `Benchmark` — `interaction` and the new hand-assigned `difficulty` tier (`easy`/`medium`/`hard`; served values verbatim, any non-blank string; `None` when an older Engine omits the key)
* **screamingface:** render `sf.benchmarks.list()` as a faceted map — clickable chip rows (Difficulty: All/Easy/Medium/Hard · Interaction: All/Single-shot/Multi-turn/Agentic · Origin: All plus the origins present) over a listing grouped easy→hard with interaction lanes; chips and search compose, and a tier-less catalogue from an older Engine keeps the flat list
* **screamingface:** show each benchmark's provenance in the listing and on its card, linked to its source collection (`Benchmark.origin` — any non-blank string, `"screamingface"` when an older Engine omits it; rendered as a per-row chip)
* **screamingface:** report what a submitted run cost is worth. `CandidateResult.run_cost_status` is `complete`, `partial`, or `unavailable`, and rides on the leaderboard submission beside `run_cost_usd`. It is optional on construction and inferred from the cost when omitted, so no existing caller has to supply it; only `partial` must be named explicitly, because it needs cache evidence an amount alone cannot carry. It also serializes into report.json, so an exported report keeps the distinction between `partial` and `unavailable` — both carry a null cost, and a reader rebuilding the status from the amount alone would collapse them.
* **screamingface:** send what the cache saved on a leaderboard submission. `CandidateResult.cache_saved_cost_usd` holds the provider-reported saving summed across the run's spans (a `Decimal`, or `None` when nothing priceable was observed, which is not zero). It is sent as a decimal string beside `run_cost_usd`, never added to it: the Scoreboard sums the two where it needs a total. The key is **omitted** when there is no saving, so an uncached run's submission is unchanged. The archive-matched figure is never carried or sent. It also serializes into report.json, null when absent. On construction, a saving with no cost now infers `run_cost_status="partial"`, and `unavailable` beside a saving is refused, because the Scoreboard refuses that pair.

  **Requires a Scoreboard that accepts the field** (`OME-1325`). A cached run's submission rejects with HTTP 422 against an older Scoreboard; uncached runs are unaffected.
* **screamingface:** `Span` carries `cache_saved_cost_usd` and `cache_saved_cost_archive_usd` — what that span's cache hits would have cost had they not been served from cache. **Never add the two together.** The first is money the provider itself priced for the call that filled the entry; the second is a real measured amount from a *different* call of the same model and kind, so it says nothing provable about this span. They are two fields rather than one amount plus a label precisely so the difference cannot be collapsed. `None` means nothing priceable was observed, which is not zero.
* **screamingface:** declare an answer seed per evaluation and name the sitting in the report (`evaluate(answer_seed=…)` sends `X-Answer-Seed`; `CandidateResult.answer_seed` serializes into report.json, null when unseeded)
* **screamingface:** expose `ModelDetails.execution_access` (`configured`, `missing`, or `None` for older Gateways).

* **screamingface:** expose and render why a published score will not rank
* **screamingface:** send the candidate's declared model routes on a leaderboard submission.
  The payload gains a `models` array carrying `CandidateResult.models` verbatim, alongside the
  existing `ran_with_providers`, which is unchanged. Previously each route was truncated to its
  provider prefix, so a fusion of open-weight models submitted as `["openrouter"]` and was
  published as closed.

  **Requires a Scoreboard that accepts the field.** Submissions reject with HTTP 422 against a
  Scoreboard deployed before `OME-1181`.

### Bug Fixes

* **screamingface:** remediate runtime logs already on disk (`OME-1048`). Every `screamingface up` now tightens the rotated backups `runtime.log.1`…`.5` to `0600`, as `OME-990` already did for the live log; before this, a backup written `0644` by an earlier version kept that mode until five more rotations pushed it out. The backups' content is left alone. Versions before `OME-990` also wrote prompts into these files, so the new `screamingface logs --purge` deletes every rotated backup and empties the live log (a running stack keeps logging into it). It runs only when you invoke it: nothing is purged automatically.
* **screamingface:** stop publishing a cache replay's $0 as an exact run cost. A response the Gateway served from its cache spends nothing upstream, so a cached run's spend understates its cost, yet the leaderboard showed and ranked it as `complete`. `CandidateResult.cache_hits` now counts the run's cache-served round trips (the Engine's run summary, falling back to hit spans; `0` when none), and serializes into report.json. A leaderboard submission from a run with **any** hit is sent as `run_cost_status="partial"` with no `run_cost_usd`, whether or not its spend was priced. `cache_saved_cost_usd` is still sent when present. **Behavior change:** such a row shows no cost on the board. The local result is unchanged: `usage.cost_usd` and `run_cost_status` still report what the run spent. Uncached runs submit exactly as before. To publish a real cost, rerun with the cache bypassed.
* **screamingface:** redact prompt carriers at the runtime log sink (`OME-1050`).
  `runtime.log` captures the stack's entire stdout and stderr: `print`, warnings,
  unconfigured loggers and tracebacks.
  * Three structural carriers are now redacted, both on every log record and on every
    line written to the file: url4 `q=` query values, litellm's `Messages:` exception
    suffix, and litellm's debug curl `-d` request body.
  * The runtime also pins `litellm.redact_messages_in_exceptions = True`.
  * It forces `LITELLM_LOG=WARNING`. **Behavior change:** `LITELLM_LOG=DEBUG` no longer
    turns the log into a prompt transcript.
  * An already-installed log record factory is wrapped, never replaced.
  * Prompt text with none of those markers is out of scope and is not detected.
* **screamingface:** one failed Candidate no longer stops its healthy siblings (`OME-1071`, `OME-1067`). In a multi-Candidate `evaluate(...)`, a Candidate whose stream is lost, whose start the Engine never admits, or that fails in any other ordinary way no longer stops every Run of the Client: the other Candidates run to their end, and the progress output marks the failed row at once. When one or more Candidates failed, `evaluate` then raises `ExecutionError(code="candidates_failed")` from the first failure. `details["failed"]` maps each failed Candidate's name to its code (`unexpected_error` for an exception without one), and the new `ExecutionError.partial_report` holds a `Report` of the Candidates that succeeded (`None` when none did). **Behavior change:** in a multi-Candidate Evaluation, errors such as `EngineUnavailableError` or `AuthenticationError` from a Candidate now arrive as the `__cause__` of `candidates_failed`, not directly. A one-Candidate Evaluation raises the failure itself, as before. Ctrl-C, task cancellation and an exception from your own `on_event` callback still stop every Run and re-raise that exception unchanged; the Runs the SDK stopped then read `stopped` (panel row and terminal `run stopped`), not `run failed`. The error's hint points to `error.partial_report`, because IPython shows only the message, hint and code.
* **screamingface:** refuse a seeded evaluation before any spend when a Candidate Model's provider does not accept `seed`. The parameter preflight read the gateway's policy (`gateway_status`) and never the provider's evidence (`provider_support`) on the same contract row, so a fusion containing such a model passed the check, went to the wire, and died mid-run with `provider_error` — score `null`, coverage `0.0`, after the members that worked were already billed. It now raises `PlanningError` naming the Model and the parameter and saying the run cannot be reproducible, and likewise for **any** declared parameter the provider denies — `temperature`, `top_k` or anything else — not just `seed`. Only an explicit `unsupported` refuses: `conditional` and `unknown` pass through unchanged, and an unseeded run is unaffected. Declaring a seed per-Model only on the Models that accept it remains allowed, which is how a deliberately partial sitting is expressed.
* **screamingface:** accept `answer_seed` on the module-level `evaluate(...)`, not only on `Client.evaluate`. The one-line call every example notebook uses raised `TypeError: evaluate() got an unexpected keyword argument 'answer_seed'`, so seeded runs were unreachable for notebook users even though the feature above had shipped. Both branches forward it now — Recipes and a complete URL4 — and omitting it still declares no seed.
* **screamingface:** check every required Candidate Model before evaluation dispatch and raise `ProviderConnectionError` for Gateway-reported missing access. Sync and async Clients reuse model admission details; older Gateways preserve existing behavior.

## 0.1.1 (2026-08-13)

Baseline-only release. `0.1.0` and `0.1.1` were both uploaded to PyPI by hand rather than by
`release-screamingface.yml`, so this repository never recorded `0.1.1`. This entry realigns the
recorded version with what PyPI already serves; there is no code change between `0.1.0` and
`0.1.1` in this repository. The next release cut by release-please (`0.1.2`) is the first
published through the Trusted Publishing pipeline.

## 0.1.0 (2026-08-13)


### Features

* **screamingface:** add leaderboard workflows ([f757921](https://github.com/ScreamingFace/screamingface/commit/f757921c729f1a06ccf891295d0351c3f6f89212))
* **screamingface:** add pipeline recipes ([362faf0](https://github.com/ScreamingFace/screamingface/commit/362faf08804ccbc57d290bf0dfda04d83d6865fc))
* **screamingface:** add Python evaluation client ([9bc3069](https://github.com/ScreamingFace/screamingface/commit/9bc3069ecdcf83af47f2f554fa92c379a07f30c3))
* **screamingface:** add Python evaluation client ([4ddcf4a](https://github.com/ScreamingFace/screamingface/commit/4ddcf4afe08174ba9f2eea947e17e6d42c870b4d))
* **screamingface:** add recursive pipeline recipes ([617441d](https://github.com/ScreamingFace/screamingface/commit/617441dae8d577ee1407d4da5f2359cadb0b15dd))
* **screamingface:** complete case outcome consumption ([e225dd6](https://github.com/ScreamingFace/screamingface/commit/e225dd6b6ca42393530167b9a257c900f3069188))
* **screamingface:** consume normalized benchmark case outcomes (OME-803) ([49d8d3d](https://github.com/ScreamingFace/screamingface/commit/49d8d3d71911cbf71d000c6de0a9a43043316d0b))
* **screamingface:** decode Case status and refusal from candidate-result.v1 ([0b015f6](https://github.com/ScreamingFace/screamingface/commit/0b015f60359823d810505b177c51c38da4af5544))
* **screamingface:** export report artifacts ([cfb43eb](https://github.com/ScreamingFace/screamingface/commit/cfb43ebb192040d748d818a089c8a209c009678d))
* **url4-cloud:** add HealthBench challenge protocols ([3c0bef1](https://github.com/ScreamingFace/screamingface/commit/3c0bef18422b8bb4db7aaf2acff5b8facfcff193))
* **url4-cloud:** add IFEval benchmark protocols ([c3043c8](https://github.com/ScreamingFace/screamingface/commit/c3043c873aa0b71a1a50bb6ec6aeae9b55ec465e))


### Bug Fixes

* attribute and remove websocket_disconnected drops ([151d257](https://github.com/ScreamingFace/screamingface/commit/151d2575d7777c2b19a560816ff91244bcb96011))
* **screamingface:** decode candidate-input envelopes for case display ([43b8d99](https://github.com/ScreamingFace/screamingface/commit/43b8d99041c65c60d1db85c4c18bd4733173874f))
* **screamingface:** default just jupyter to the local engine ([66a993f](https://github.com/ScreamingFace/screamingface/commit/66a993f156bbeb10dee546ac11c63a03a72edc0a))
* **screamingface:** deliver capped Reports and survive an Access challenge ([722ab50](https://github.com/ScreamingFace/screamingface/commit/722ab500062444ca56876b9fe0ce7c0975072233))
* **screamingface:** enforce one local stack at a time in the justfile ([29462f4](https://github.com/ScreamingFace/screamingface/commit/29462f40321bcc2326e4f26b3a848cc63209fe3c))
* **screamingface:** improve evaluation progress recovery ([082c728](https://github.com/ScreamingFace/screamingface/commit/082c72829117c251aee9e1d96af6398fe8315a19))
* **screamingface:** keep an out-of-band notice from killing a paid Run ([86c8427](https://github.com/ScreamingFace/screamingface/commit/86c84276a1a0b174d41650179be350a706242bae))
* **screamingface:** never replay a paid Run start after an Access login ([bfed68b](https://github.com/ScreamingFace/screamingface/commit/bfed68bef4a85aff51e2e8966347fcf81d94ee87))
* **screamingface:** port demo notebook to current API ([65b0da7](https://github.com/ScreamingFace/screamingface/commit/65b0da78a8a2f89f60ec079359d7cf39a8e0003b))
* **screamingface:** reject refused Case shapes the engine contract forbids ([f3c5227](https://github.com/ScreamingFace/screamingface/commit/f3c522795b53a619cc820845de061d7570a4f515))
* **screamingface:** say checkout, not worktree, in stack messages ([d2729d2](https://github.com/ScreamingFace/screamingface/commit/d2729d265be37b116285ed44233ab6eb6b73ed64))
* **screamingface:** see Candidate references in URL4 source position ([0cbdae9](https://github.com/ScreamingFace/screamingface/commit/0cbdae9fde3157f10dadfceac806e0d8e6ec8a38))
* **screamingface:** stop paid Runs when an async Evaluation is cancelled ([04f86de](https://github.com/ScreamingFace/screamingface/commit/04f86de43290187caada2c6f04562facf7d662fc))
* **screamingface:** surface event stream failures ([5c33a67](https://github.com/ScreamingFace/screamingface/commit/5c33a675c75111fe285e9d6bed5a28ed5a6aa48c))
* **screamingface:** surface failure identity and failed-state semantics in the report view ([65de0d7](https://github.com/ScreamingFace/screamingface/commit/65de0d7d968a6594b6f3063943a9bf35cbb412e9))
* **screamingface:** verify the WebSocket against the same roots as HTTP ([4c7e0f0](https://github.com/ScreamingFace/screamingface/commit/4c7e0f00e8fd846836292047a10a52439c9cd4e7))
* **screamingface:** verify the WebSocket against the same roots as HTTP ([40cb232](https://github.com/ScreamingFace/screamingface/commit/40cb23238f21341c87be5e248302bbc44e5ae4f0))


### Refactors

* **screamingface:** model fusion synthesizers ([1699e12](https://github.com/ScreamingFace/screamingface/commit/1699e1221974c6a933563c8baf95f916b570e359))
* **url4-cloud:** drop the healthbench/smoke exam in favor of limit=1 rehearsals ([197e5a2](https://github.com/ScreamingFace/screamingface/commit/197e5a2030ce536d7ab627bdbc7b87fcede1258f))


### Documentation

* **public-docs:** ScreamingFace Client documentation — layout, Overview, Quickstart, and six user guides ([f292d19](https://github.com/ScreamingFace/screamingface/commit/f292d19a8cb70d3e5574dcb50592dbd2d107e583))
* record evaluation client decisions ([5d33e4f](https://github.com/ScreamingFace/screamingface/commit/5d33e4fe99f76d7aa76af4dc6e2bc8317d9500bb))
* **screamingface:** add HealthBench challenge notebook ([24fd8d1](https://github.com/ScreamingFace/screamingface/commit/24fd8d1e94269656fc4c211941c7f123794e4d5c))
* **screamingface:** add IFEval research notebook ([8472d99](https://github.com/ScreamingFace/screamingface/commit/8472d998cc7fd3f6ebd5642bb8aa1304815e857e))
* **screamingface:** explain the stack recipes via the fixed-port mental model ([081f77b](https://github.com/ScreamingFace/screamingface/commit/081f77bf08dfb4b58433f209d6c70feb2602d81c))
* **screamingface:** keep the earlier demo notebook draft as 09_demo_v2 ([3ecb81d](https://github.com/ScreamingFace/screamingface/commit/3ecb81d3f96bdfe82f07913dfeaa2ab48e862a5c))
* **screamingface:** teach _resolve_case_status with a staged Feynman docstring ([54a386d](https://github.com/ScreamingFace/screamingface/commit/54a386d2cec4c1988a5dca2ae297281400b8c9ee))
