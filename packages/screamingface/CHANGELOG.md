# Changelog

## Unreleased

### Features

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

## [0.2.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-v0.1.1...screamingface-v0.2.0) (2026-10-02)


### Features

* **aigateway:** log an unhandled exception once, by class name, with its call id ([db6757b](https://github.com/ScreamingFace/screamingface/commit/db6757bc56a7f6b49b38ae16e7059c06a55cda3f))
* **aigateway:** return full cache metadata on hits and pin the cross-stack hit contract ([#1100](https://github.com/ScreamingFace/screamingface/issues/1100)) ([16bb09a](https://github.com/ScreamingFace/screamingface/commit/16bb09ae38a73eed25576763ba5a73ed65729f0e))
* **client:** preserve run Client version in reports ([#1059](https://github.com/ScreamingFace/screamingface/issues/1059)) ([b39b9bc](https://github.com/ScreamingFace/screamingface/commit/b39b9bc284f7bca4729c42fb925cc7f4011e213b))
* **client:** show completed operation accounting ([#1097](https://github.com/ScreamingFace/screamingface/issues/1097)) ([2adc7a9](https://github.com/ScreamingFace/screamingface/commit/2adc7a9f1119e1eb54c0d0cec881b74a873da30d))
* **client:** show stages and dynamic activity in candidate rows ([#983](https://github.com/ScreamingFace/screamingface/issues/983)) ([a171901](https://github.com/ScreamingFace/screamingface/commit/a1719014f9a4e68b1ce924e9a5d02384ee013031))
* **engine:** attribute candidate model activity to benchmark cases ([#988](https://github.com/ScreamingFace/screamingface/issues/988)) ([36c9f36](https://github.com/ScreamingFace/screamingface/commit/36c9f366a70973507bac24f618abd62759da55fe))
* **engine:** declare gateway_internal_error in the failure vocabulary ([83b2c99](https://github.com/ScreamingFace/screamingface/commit/83b2c9901e2df5f66612185a78c7247f405b1122))
* **engine:** update live scores across shipped benchmarks ([#1096](https://github.com/ScreamingFace/screamingface/issues/1096)) ([e59f09b](https://github.com/ScreamingFace/screamingface/commit/e59f09b7d9f2dea43a149acc6eabfd90545211f5))
* **py-screamingface:** refuse undeclared failure codes and pin the list to the engine's ([38768bd](https://github.com/ScreamingFace/screamingface/commit/38768bd3111413ed3a2e613b528db3025998c8f3))
* **py-screamingface:** refuse undeclared failure codes and pin the list to the engine's ([685fdc6](https://github.com/ScreamingFace/screamingface/commit/685fdc67cb948af087dcf56ff2627b3355613a10))
* **screamingface-engine:** bake gated datasets with a CI token and import xstest_safe ([fdda6f9](https://github.com/ScreamingFace/screamingface/commit/fdda6f9638f44c6f26ca4eae96b4ec8a58d77f37))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([b6139b7](https://github.com/ScreamingFace/screamingface/commit/b6139b7ef6d880a9e8f29e2d11d8c9bef01ebdd0))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([382cce8](https://github.com/ScreamingFace/screamingface/commit/382cce8f67738145c64c1280d26fd5eca0ca80b1))
* **screamingface-engine:** reclassify the catch-all failure sites into named classes ([03da591](https://github.com/ScreamingFace/screamingface/commit/03da59170439cee88661ce8a8578c1277b1bcae9))
* **screamingface:** end the paid-smoke summary table with a total row ([ec64b16](https://github.com/ScreamingFace/screamingface/commit/ec64b164779350c5feced9c990e1f433dcc684fd))
* **screamingface:** give every paid-smoke press a per-board and whole-run overview ([1103223](https://github.com/ScreamingFace/screamingface/commit/1103223622493f71f6267bc99187a53dbd502d6c))
* **screamingface:** keep every paid-smoke press's full debug bundle ([9f0ab38](https://github.com/ScreamingFace/screamingface/commit/9f0ab38aeb3c6e187e692ad28cb752740f749527))
* **screamingface:** keep the paid smoke's stack logs when a CI run fails ([33e6c50](https://github.com/ScreamingFace/screamingface/commit/33e6c509beffa7af75de1702cb84dfc8dd1483af))
* **screamingface:** mark Benchmarks scored by refusal rate in report.json ([a89a190](https://github.com/ScreamingFace/screamingface/commit/a89a19004219ec7a84c3f54a8ff185c8889297ee))
* **screamingface:** mark Benchmarks scored by refusal rate in report.json ([bf256b4](https://github.com/ScreamingFace/screamingface/commit/bf256b43e9cd6d354f3a5b3ffec8cb4f9d37fefb))
* **screamingface:** print each paid-smoke board's verdict as it finishes ([8f2b62e](https://github.com/ScreamingFace/screamingface/commit/8f2b62e73291093ef81e96839ac0d3a916d1030c))
* **screamingface:** render the catalogue as a faceted map with chips ([a61549a](https://github.com/ScreamingFace/screamingface/commit/a61549a11b095013c027e454721dbb76b03b73af))
* **screamingface:** render the catalogue as a faceted map with chips ([a2af7bb](https://github.com/ScreamingFace/screamingface/commit/a2af7bbe196addc1a9b6e0b1724ee82c744c1138))
* **screamingface:** run paid-smoke boards four at a time with a 32k token budget ([0bab9dc](https://github.com/ScreamingFace/screamingface/commit/0bab9dcffd15ba748c29b441ecc6daf69e410b17))
* **screamingface:** scroll the listing body after roughly a screenful ([0bb7e86](https://github.com/ScreamingFace/screamingface/commit/0bb7e86bd890a1f1716daeac784a66b93c8c3643))
* **screamingface:** send run_cost_status beside the run cost ([#1017](https://github.com/ScreamingFace/screamingface/issues/1017)) ([b44fa78](https://github.com/ScreamingFace/screamingface/commit/b44fa781ff8c21cc47b36889817a8e573f8e76c9))
* **screamingface:** send the declared model routes on a submission ([#923](https://github.com/ScreamingFace/screamingface/issues/923)) ([72a8295](https://github.com/ScreamingFace/screamingface/commit/72a82950a8a321cf71cbecc2c01db5b0721cea73))
* **screamingface:** send what the cache saved on a leaderboard submission ([#1075](https://github.com/ScreamingFace/screamingface/issues/1075)) ([4168da1](https://github.com/ScreamingFace/screamingface/commit/4168da148ed2e5c38c7f4043a9dd85c427b72bd8))
* **screamingface:** show a judge's full reasoning behind a toggle in the report ([7bd90d0](https://github.com/ScreamingFace/screamingface/commit/7bd90d06978f32197fadf364b10b506a3f5d27ce))
* **screamingface:** show a judge's full reasoning behind a toggle in the report ([92551f9](https://github.com/ScreamingFace/screamingface/commit/92551f9dcd42891bc0b7d5be06622c8013ea026b))
* **screamingface:** show the refusal-rate mark in the catalogue and report view ([b4a0bc3](https://github.com/ScreamingFace/screamingface/commit/b4a0bc3c2117fb0a0f947c515ceecc605821c301))
* **screamingface:** show the refusal-rate mark in the catalogue and report view ([72c798d](https://github.com/ScreamingFace/screamingface/commit/72c798d1bdec0bab895002652bab28e1d105312e))
* **screamingface:** tighten rotated runtime logs and add logs --purge ([d26ef53](https://github.com/ScreamingFace/screamingface/commit/d26ef53eb362ec8f664493b95e3ad736051f6035))
* **screamingface:** tighten rotated runtime logs and add logs --purge ([4106fad](https://github.com/ScreamingFace/screamingface/commit/4106fad8b4e50d0efa960af68ab551f89a2fd127))
* **screamingface:** wait for Engine capacity when a run start gets the Engine's 503 ([#1115](https://github.com/ScreamingFace/screamingface/issues/1115)) ([a3f7769](https://github.com/ScreamingFace/screamingface/commit/a3f776956e9c1909f0237ebd9ea4147c0384fc1c))


### Bug Fixes

* attribute judge activity and simplify log display ([#1071](https://github.com/ScreamingFace/screamingface/issues/1071)) ([3293550](https://github.com/ScreamingFace/screamingface/commit/3293550b3d0dd8cc87798a70a4cffde9c42da2e0))
* **engine:** attribute failures at the candidate execution boundary ([#1060](https://github.com/ScreamingFace/screamingface/issues/1060)) ([a59d82e](https://github.com/ScreamingFace/screamingface/commit/a59d82e87c40cdc10a48c675e00f47964898f1ec))
* **engine:** report a missing row's real cause as its failure code ([f5a26db](https://github.com/ScreamingFace/screamingface/commit/f5a26db082e3cae3d70310da297cdc8c75608dd8))
* **engine:** report a missing row's real cause as its failure code ([3008da6](https://github.com/ScreamingFace/screamingface/commit/3008da684c6ef9f31d2a8c125fe62538d4537d51))
* **py-screamingface:** make the conformance bind fire on either side's drift ([b4c6521](https://github.com/ScreamingFace/screamingface/commit/b4c6521d0da1f9e45885b6483573cfbba7828642))
* **screamingface-engine:** close the xstest and CI-token gaps from review ([a11b685](https://github.com/ScreamingFace/screamingface/commit/a11b68512c1bcaa38676193cd548a1ccc1a7be59))
* **screamingface-engine:** declare contracteval's failure codes so a failed case reports instead of crashing ([fa8bbe8](https://github.com/ScreamingFace/screamingface/commit/fa8bbe859d8499c6a827e1f5f2a68a3c4cb6ab4c))
* **screamingface-engine:** declare contracteval's failure codes so failed cases report instead of crashing ([39cea39](https://github.com/ScreamingFace/screamingface/commit/39cea39fcc77ec08487b998429f86d3ab2cc7482))
* **screamingface-engine:** migrate the fourth DRACO-pinning test — the e2e failure tape ([1c5f93e](https://github.com/ScreamingFace/screamingface/commit/1c5f93ef359c00bcac0db493e420552f08177f62))
* **screamingface:** advise a paid-smoke rerun only when every failure was tolerated ([8fc76bd](https://github.com/ScreamingFace/screamingface/commit/8fc76bdf7050d320431a7dd090d9dcbe2073d712))
* **screamingface:** cap the full reasoning like every free text in the report ([f3f0d41](https://github.com/ScreamingFace/screamingface/commit/f3f0d41c9d90f5a7e480eb6101b1ad7ecd2df7db))
* **screamingface:** drop the stale kubernetes requirement from the runtime ([b0deaee](https://github.com/ScreamingFace/screamingface/commit/b0deaeef25af04225dfef84f6801e3704830b7da))
* **screamingface:** drop the stale kubernetes requirement from the runtime ([83f289b](https://github.com/ScreamingFace/screamingface/commit/83f289b3fdcc7e4c6bf5134d8cdb3edebab65dfc))
* **screamingface:** fail the paid button instead of green-skipping it ([9724506](https://github.com/ScreamingFace/screamingface/commit/97245069affe8792af81811d158a5c001777caee))
* **screamingface:** give the frontierscience panel room to finish and keep constraints ([8a80b51](https://github.com/ScreamingFace/screamingface/commit/8a80b5163ee76e3581f2dabce5a61ae7a2f1b170))
* **screamingface:** keep inverted_grade when the notebook helper reloads a report ([1cbd3af](https://github.com/ScreamingFace/screamingface/commit/1cbd3af41e77107651777568c02c60ef1e439f04))
* **screamingface:** keep the other candidates running when one fails; raise candidates_failed with a partial report ([#1121](https://github.com/ScreamingFace/screamingface/issues/1121)) ([762d928](https://github.com/ScreamingFace/screamingface/commit/762d928500970e5e9a54fe14f25f99fc44e3f84f))
* **screamingface:** keep the SDK's inspect-ai pin on the Engine's version ([98a234e](https://github.com/ScreamingFace/screamingface/commit/98a234e1e657a94872d3a8ccd167d57d2111f7b5))
* **screamingface:** keep the Studio sidecar build working without editable copies ([6f63231](https://github.com/ScreamingFace/screamingface/commit/6f63231e022e73a324bebea42df583ada8568f40))
* **screamingface:** keep the WS capability ticket out of runtime.log ([664c667](https://github.com/ScreamingFace/screamingface/commit/664c667ee384f416a42c66963408af1e89a013fa))
* **screamingface:** keep the WS capability ticket out of runtime.log ([1978eab](https://github.com/ScreamingFace/screamingface/commit/1978eabec77944aa424a49fdc1101852af5c22ad))
* **screamingface:** let pyright see the report view's inverted_grade read ([c3b90d0](https://github.com/ScreamingFace/screamingface/commit/c3b90d0692968efc31e3cc7a6ac2803f5e846b7a))
* **screamingface:** live notebook activity and a frontierscience panel that finishes ([ecff774](https://github.com/ScreamingFace/screamingface/commit/ecff7745967629fe4d3aecf4211f504eaf48582d))
* **screamingface:** make the All chip highlight on the first click ([4b94928](https://github.com/ScreamingFace/screamingface/commit/4b94928e774b08ab344dc364d77ed6f97278d8f5))
* **screamingface:** make the paid smoke's cost and timeout honest for a growing shelf ([d7e5667](https://github.com/ScreamingFace/screamingface/commit/d7e5667fedf43896c2c08fac99cf8ec52c26882d))
* **screamingface:** never raise from the redacting factory; redact quoted url4 intents ([a153189](https://github.com/ScreamingFace/screamingface/commit/a153189af0fc437ccd4e0fcb9f79203e0c1e574b))
* **screamingface:** pin the inverted_grade key's spelling on both sides ([a7381c3](https://github.com/ScreamingFace/screamingface/commit/a7381c323903220a1df19a30b074fe4fb4eb2b8d))
* **screamingface:** pin the SDK's inspect-ai to the Engine's version and bind them ([2d03a8f](https://github.com/ScreamingFace/screamingface/commit/2d03a8f2338b16b251509ab803561f6eeab3a620))
* **screamingface:** redact prompt carriers at the runtime log sink ([34e9052](https://github.com/ScreamingFace/screamingface/commit/34e905205c59976f9ed134aa1ffbc9694e147a97))
* **screamingface:** redact prompt carriers at the runtime log sink ([3960b4e](https://github.com/ScreamingFace/screamingface/commit/3960b4e6691d2b31ce9b07fd92f69b5b1eb39678))
* **screamingface:** resume the same capability after reconnect challenges and show reconnect progress ([#1099](https://github.com/ScreamingFace/screamingface/issues/1099)) ([d4af3cc](https://github.com/ScreamingFace/screamingface/commit/d4af3ccf5113cc7d1d5bd5bed1ab1e7bfb3bf056))
* **screamingface:** run the live url4 and apps from a dev checkout's editable install ([7008bc0](https://github.com/ScreamingFace/screamingface/commit/7008bc0e94f2dfa12a1404e637f9004c23c50eaf))
* **screamingface:** run the live url4 and apps from a dev checkout's editable install ([33c8ce5](https://github.com/ScreamingFace/screamingface/commit/33c8ce5f1030ae116cf77674008c153f3409e0d5))
* **screamingface:** stop only the failed run on a fatal reconnect rejection; keep the owner abort in effect while runs are in flight ([#1105](https://github.com/ScreamingFace/screamingface/issues/1105)) ([65ab8d1](https://github.com/ScreamingFace/screamingface/commit/65ab8d13db97aaf9a506940666977a9d48054750))
* **screamingface:** stop only the lost run when its stream gives up; never stop a completed run ([#1109](https://github.com/ScreamingFace/screamingface/issues/1109)) ([70054e4](https://github.com/ScreamingFace/screamingface/commit/70054e4a8ca1a02e41eb276122e258ab29156b77))
* **screamingface:** submit a run with any cache hit as a partial cost ([#1187](https://github.com/ScreamingFace/screamingface/issues/1187)) ([2c53213](https://github.com/ScreamingFace/screamingface/commit/2c532132f660b23e0e1c7bcd81eb12a1a2456f87))
* **screamingface:** use a panel that finishes frontierscience in notebook 12 ([a835bdd](https://github.com/ScreamingFace/screamingface/commit/a835bddc5e33c3ada2b7e53205ba0254e6ea3d23))


### Refactors

* **screamingface-engine:** say "needs an HF token" instead of "gated" ([aa9ac1b](https://github.com/ScreamingFace/screamingface/commit/aa9ac1ba4fee9a13ce0d18184bb4d3603ca748fa))
* **screamingface:** drop the review-only kubernetes comment and guard test ([95d374c](https://github.com/ScreamingFace/screamingface/commit/95d374cb20a3ef68360ca737eb6c5fc92d42b978))
* **screamingface:** take the live source directories from the runtime itself ([c5eb584](https://github.com/ScreamingFace/screamingface/commit/c5eb584dd4817b0bbfbaaddd23c1c47d9d2dafd4))


### Documentation

* **screamingface-engine:** model-graded imports are in scope — correct the env-var judge plan ([f17ad00](https://github.com/ScreamingFace/screamingface/commit/f17ad0006f69e92d1a11cb9a9444e7219e3a852e))
* **screamingface:** carry the just local-stack-notebooks line into the contracteval notebook ([e38ee18](https://github.com/ScreamingFace/screamingface/commit/e38ee182b9e598806cc38976ba945c07cd765213))
* **screamingface:** say an Engine with xstest_unsafe but no mark reads as unflipped ([88cff79](https://github.com/ScreamingFace/screamingface/commit/88cff79b192728c0b9c01390f3fa18674af5d210))
* **screamingface:** say the catalogue mark needs both Engine changes deployed ([414aa76](https://github.com/ScreamingFace/screamingface/commit/414aa7622e4455719b0ee70b57fc15ca7f59fa3e))
* **screamingface:** teach the judged board in the catalogue notebook ([fd36c2b](https://github.com/ScreamingFace/screamingface/commit/fd36c2beeda9f3b788350b786e4829ef4e2735c7))

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
