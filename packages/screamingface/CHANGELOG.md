# Changelog

## Unreleased

### Features

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

* **screamingface:** refuse a seeded evaluation before any spend when a Candidate Model's provider does not accept `seed`. The parameter preflight read the gateway's policy (`gateway_status`) and never the provider's evidence (`provider_support`) on the same contract row, so a fusion containing such a model passed the check, went to the wire, and died mid-run with `provider_error` — score `null`, coverage `0.0`, after the members that worked were already billed. It now raises `PlanningError` naming the Model and the parameter and saying the run cannot be reproducible, and likewise for **any** declared parameter the provider denies — `temperature`, `top_k` or anything else — not just `seed`. Only an explicit `unsupported` refuses: `conditional` and `unknown` pass through unchanged, and an unseeded run is unaffected. Declaring a seed per-Model only on the Models that accept it remains allowed, which is how a deliberately partial sitting is expressed.
* **screamingface:** accept `answer_seed` on the module-level `evaluate(...)`, not only on `Client.evaluate`. The one-line call every example notebook uses raised `TypeError: evaluate() got an unexpected keyword argument 'answer_seed'`, so seeded runs were unreachable for notebook users even though the feature above had shipped. Both branches forward it now — Recipes and a complete URL4 — and omitting it still declares no seed.
* **screamingface:** check every required Candidate Model before evaluation dispatch and raise `ProviderConnectionError` for Gateway-reported missing access. Sync and async Clients reuse model admission details; older Gateways preserve existing behavior.

## [0.2.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-v0.1.1...screamingface-v0.2.0) (2026-09-25)


### Features

* **aigateway:** carry gateway_call_id on every log line ([#898](https://github.com/ScreamingFace/screamingface/issues/898)) ([802bed9](https://github.com/ScreamingFace/screamingface/commit/802bed9aeac74d6b297d4b3e8fd2897b91d2b172))
* **aigateway:** join the inbound traceparent to the log context ([#902](https://github.com/ScreamingFace/screamingface/issues/902)) ([5ecac45](https://github.com/ScreamingFace/screamingface/commit/5ecac451f659e5de031a5020f21450a44b5c7a8d))
* **client:** preserve run Client version in reports ([#1059](https://github.com/ScreamingFace/screamingface/issues/1059)) ([b39b9bc](https://github.com/ScreamingFace/screamingface/commit/b39b9bc284f7bca4729c42fb925cc7f4011e213b))
* **client:** show stages and dynamic activity in candidate rows ([#983](https://github.com/ScreamingFace/screamingface/issues/983)) ([a171901](https://github.com/ScreamingFace/screamingface/commit/a1719014f9a4e68b1ce924e9a5d02384ee013031))
* **e2e:** add a setup validator for the traceability lanes (OME-1106) ([#832](https://github.com/ScreamingFace/screamingface/issues/832)) ([89aeb9f](https://github.com/ScreamingFace/screamingface/commit/89aeb9f90d12b95e3eedbc7ec2f56aaf1cc3319e))
* **engine:** attribute candidate model activity to benchmark cases ([#988](https://github.com/ScreamingFace/screamingface/issues/988)) ([36c9f36](https://github.com/ScreamingFace/screamingface/commit/36c9f366a70973507bac24f618abd62759da55fe))
* **engine:** log run identity and terminal evidence on the control plane ([#901](https://github.com/ScreamingFace/screamingface/issues/901)) ([a136e0f](https://github.com/ScreamingFace/screamingface/commit/a136e0ffd153dcb8275d409b9ccbb2b60f14eaf2))
* **py-screamingface:** bless corrective-loop goldens from fresh cache dumps ([749cc3c](https://github.com/ScreamingFace/screamingface/commit/749cc3c1258940c9f2146a1373915de438eef0b1))
* **py-screamingface:** bless the gdpval-text fusion golden ([3d15d53](https://github.com/ScreamingFace/screamingface/commit/3d15d531ccd35ba62241783b67853ac50b5620b5))
* **py-screamingface:** bless the ifeval corrective-loop golden ([5d470bd](https://github.com/ScreamingFace/screamingface/commit/5d470bdf28779e98e53996cf012c86ae6c8c3464))
* **py-screamingface:** export a report in inspect's .eval log format ([0ad3a2f](https://github.com/ScreamingFace/screamingface/commit/0ad3a2f8aa8a3868bb04a7db1755153a68c712e1))
* **py-screamingface:** export a report in inspect's .eval log format ([4b47628](https://github.com/ScreamingFace/screamingface/commit/4b47628781de07eea1b5b370fa2312870f4d074c))
* **py-screamingface:** guard ifeval and gdpval-text with e2e replay goldens ([c001fbb](https://github.com/ScreamingFace/screamingface/commit/c001fbb2acbfa046b8cda67c484d51ad5f1ae805))
* **py-screamingface:** let the keyless replay disarm the parameter preflight ([5b4beaa](https://github.com/ScreamingFace/screamingface/commit/5b4beaa54c137ac9b50cd6cc2aa1f2cc7e672073))
* **py-screamingface:** refuse undeclared failure codes and pin the list to the engine's ([38768bd](https://github.com/ScreamingFace/screamingface/commit/38768bd3111413ed3a2e613b528db3025998c8f3))
* **py-screamingface:** refuse undeclared failure codes and pin the list to the engine's ([685fdc6](https://github.com/ScreamingFace/screamingface/commit/685fdc67cb948af087dcf56ff2627b3355613a10))
* **scoreboard:** explain revision-mismatch submissions ([#843](https://github.com/ScreamingFace/screamingface/issues/843)) ([f0531a5](https://github.com/ScreamingFace/screamingface/commit/f0531a5dd8485ee2e64877b2953dc96ed25ef47f))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([b6139b7](https://github.com/ScreamingFace/screamingface/commit/b6139b7ef6d880a9e8f29e2d11d8c9bef01ebdd0))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([382cce8](https://github.com/ScreamingFace/screamingface/commit/382cce8f67738145c64c1280d26fd5eca0ca80b1))
* **screamingface-engine:** let a run declare an answer seed ([0e8749e](https://github.com/ScreamingFace/screamingface/commit/0e8749e477dd55a981d4ce265fbdebe519d081f1))
* **screamingface-engine:** let an interrupted asset bake resume ([8a4bc7e](https://github.com/ScreamingFace/screamingface/commit/8a4bc7e2c9a376e5b9d98db5136b426a82ea8a08))
* **screamingface-engine:** onboard MedXpertQA as an exact-match MCQ benchmark ([0829106](https://github.com/ScreamingFace/screamingface/commit/0829106b1e91a80f76b23275ce865b52a72cd1e7))
* **screamingface-engine:** propagate the run's traceparent to aigateway (OME-1119) ([#849](https://github.com/ScreamingFace/screamingface/issues/849)) ([1220e2e](https://github.com/ScreamingFace/screamingface/commit/1220e2e64a24dd3439829fb773b39a093702fde4))
* **screamingface-engine:** rebuild the ContractEval board on the spine ([c735b7e](https://github.com/ScreamingFace/screamingface/commit/c735b7ef32725ccd2c094b0f229143ef64a96030))
* **screamingface-engine:** reclassify the catch-all failure sites into named classes ([03da591](https://github.com/ScreamingFace/screamingface/commit/03da59170439cee88661ce8a8578c1277b1bcae9))
* **screamingface-engine:** ship the imported boards and document the one-command stack ([c828935](https://github.com/ScreamingFace/screamingface/commit/c828935fe016e4afe3e21c543dbc378b174f0457))
* **screamingface:** carry the run's trace id onto the candidate result ([#842](https://github.com/ScreamingFace/screamingface/issues/842)) ([a72960d](https://github.com/ScreamingFace/screamingface/commit/a72960ddc6e7dc7fa648ded09d6a8a79c18d7782))
* **screamingface:** example notebook walks the imported benchmark catalogue ([1df9166](https://github.com/ScreamingFace/screamingface/commit/1df9166d587d3d0826b52a521930ed56c691fa33))
* **screamingface:** example notebook walks the imported benchmark catalogue ([7588e10](https://github.com/ScreamingFace/screamingface/commit/7588e1070eec5b60f9f206d851d4ba900ce2363f))
* **screamingface:** identify Client requests and generated notebooks ([#918](https://github.com/ScreamingFace/screamingface/issues/918)) ([0e52dbc](https://github.com/ScreamingFace/screamingface/commit/0e52dbcdd2d5073d692de17c90b9d278660097aa))
* **screamingface:** name the answer seed in the run report ([a57917e](https://github.com/ScreamingFace/screamingface/commit/a57917e9e36b0fcf4d51cc43c55933865210e942))
* **screamingface:** one command opens every example notebook ([c6d72fe](https://github.com/ScreamingFace/screamingface/commit/c6d72fe63e94b5abb7e7b481048a31c668bcaa86))
* **screamingface:** originate the traceparent in the client ([#789](https://github.com/ScreamingFace/screamingface/issues/789)) ([c2b5895](https://github.com/ScreamingFace/screamingface/commit/c2b5895521101ee06f60b8e47e69678b239528b9))
* **screamingface:** pin each failed case's failure code in the e2e goldens ([7bcaac4](https://github.com/ScreamingFace/screamingface/commit/7bcaac44f9458763d55a2083f64ff51d74f20526))
* **screamingface:** pin each failed case's failure code in the e2e goldens ([e09a6a5](https://github.com/ScreamingFace/screamingface/commit/e09a6a52775a82f5df0508d31e80ff0a0873f44e))
* **screamingface:** prepare and demonstrate MedXpertQA ([c4c82e5](https://github.com/ScreamingFace/screamingface/commit/c4c82e557f37272190738ef21feaaa0ef369dc8f))
* **screamingface:** render the catalogue as a faceted map with chips ([a61549a](https://github.com/ScreamingFace/screamingface/commit/a61549a11b095013c027e454721dbb76b03b73af))
* **screamingface:** render the catalogue as a faceted map with chips ([a2af7bb](https://github.com/ScreamingFace/screamingface/commit/a2af7bbe196addc1a9b6e0b1724ee82c744c1138))
* **screamingface:** run more imported boards and export a run from the notebook ([9f004ff](https://github.com/ScreamingFace/screamingface/commit/9f004ffc87b4cb36710387a39bc75548c643c9f9))
* **screamingface:** run two more imported boards in the example notebook ([7427ab3](https://github.com/ScreamingFace/screamingface/commit/7427ab3706995d4eefb31b5542e34799d3b1d07f))
* **screamingface:** scroll the listing body after roughly a screenful ([0bb7e86](https://github.com/ScreamingFace/screamingface/commit/0bb7e86bd890a1f1716daeac784a66b93c8c3643))
* **screamingface:** send run_cost_status beside the run cost ([#1017](https://github.com/ScreamingFace/screamingface/issues/1017)) ([b44fa78](https://github.com/ScreamingFace/screamingface/commit/b44fa781ff8c21cc47b36889817a8e573f8e76c9))
* **screamingface:** send the declared model routes on a submission ([#923](https://github.com/ScreamingFace/screamingface/issues/923)) ([72a8295](https://github.com/ScreamingFace/screamingface/commit/72a82950a8a321cf71cbecc2c01db5b0721cea73))
* **screamingface:** send what the cache saved on a leaderboard submission ([#1075](https://github.com/ScreamingFace/screamingface/issues/1075)) ([4168da1](https://github.com/ScreamingFace/screamingface/commit/4168da148ed2e5c38c7f4043a9dd85c427b72bd8))
* **screamingface:** show the benchmark catalogue as one tab per origin ([a4d61ad](https://github.com/ScreamingFace/screamingface/commit/a4d61ad4edfa02e0a5420e30ae4a44c2cdae1733))
* **screamingface:** show the benchmark catalogue as one tab per origin ([6b03f24](https://github.com/ScreamingFace/screamingface/commit/6b03f24c658bafc0ffe873da73ed8b710cccb22e))
* **screamingface:** support leaderboard co-authors ([#830](https://github.com/ScreamingFace/screamingface/issues/830)) ([7d7b6a4](https://github.com/ScreamingFace/screamingface/commit/7d7b6a48680e3dcaddff19809b8a392e8fee69fb))


### Bug Fixes

* **engine:** attribute failures at the candidate execution boundary ([#1060](https://github.com/ScreamingFace/screamingface/issues/1060)) ([a59d82e](https://github.com/ScreamingFace/screamingface/commit/a59d82e87c40cdc10a48c675e00f47964898f1ec))
* **py-screamingface:** harden the inspect export boundary per review ([cfe0128](https://github.com/ScreamingFace/screamingface/commit/cfe0128799ef6cb74ba15e35836152482c20ebe2))
* **py-screamingface:** keep report.json as the export path default ([0638bf8](https://github.com/ScreamingFace/screamingface/commit/0638bf85c4a63489c718f05dfa7781b44ffccdec))
* **py-screamingface:** make the conformance bind fire on either side's drift ([b4c6521](https://github.com/ScreamingFace/screamingface/commit/b4c6521d0da1f9e45885b6483573cfbba7828642))
* **py-screamingface:** make the saved report the only bless authority and refresh loop goldens intact ([374dfc8](https://github.com/ScreamingFace/screamingface/commit/374dfc8f9d9fae579022a2f9e2b9c9f47fd1c2b4))
* **py-screamingface:** never double-count ensemble usage in the exported log ([aca6dda](https://github.com/ScreamingFace/screamingface/commit/aca6ddaf2ad7123aad2ec0bdacf90fe789c88efd))
* **py-screamingface:** omit unmetered token counts instead of exporting zeros ([b35a96b](https://github.com/ScreamingFace/screamingface/commit/b35a96b5bb7cf6c25c292216beffba58d67e96f1))
* **py-screamingface:** refuse a foreign gateway database and print the effective config at up ([01d0c13](https://github.com/ScreamingFace/screamingface/commit/01d0c13c49e8eb9a76242843833d69301150ec8e))
* **py-screamingface:** refuse a foreign gateway database and print the effective config at up ([1cbac78](https://github.com/ScreamingFace/screamingface/commit/1cbac78e2fb3efca17e79e0cfa32fe91ea949078))
* **py-screamingface:** refuse a seeded run the provider cannot reproduce ([ce14738](https://github.com/ScreamingFace/screamingface/commit/ce147387fe9ca97defba363aabf85b779e6e0089))
* **py-screamingface:** refuse a seeded run the provider cannot reproduce ([781ac80](https://github.com/ScreamingFace/screamingface/commit/781ac80375675011e37ea035c58ff9aaa16a5073))
* **py-screamingface:** refuse contradictory bless modes and police golden fields both ways ([b80bfde](https://github.com/ScreamingFace/screamingface/commit/b80bfdef3b04e3b1e9cb357d39f37ce6d3df85ff))
* **py-screamingface:** refuse contradictory bless modes and police golden fields both ways ([959932f](https://github.com/ScreamingFace/screamingface/commit/959932f3034dfa72c0fa3028fef722c95bd448bb))
* **py-screamingface:** refuse the foreign database before restart stops anything ([d48fa21](https://github.com/ScreamingFace/screamingface/commit/d48fa21c9c81b4673977cacab0f4bb8ee4333bc8))
* **py-screamingface:** render only answer and feedback into the loop coach prompt ([8befc9c](https://github.com/ScreamingFace/screamingface/commit/8befc9c46bf142aaa9fc1a4f1705f1d097cf07b3))
* **py-screamingface:** render only answer and feedback into the loop coach prompt ([a61e001](https://github.com/ScreamingFace/screamingface/commit/a61e001b52e865d0c8fccf81147004c3502d78d4))
* **py-screamingface:** stop the notebook typesetting panel text as maths ([73c5e1e](https://github.com/ScreamingFace/screamingface/commit/73c5e1e32e3e01b2550468b18d4731d3ee4da065))
* **py-screamingface:** stop the notebook typesetting panel text as maths ([bcfb948](https://github.com/ScreamingFace/screamingface/commit/bcfb9484fc20160f10f304d74c4aa504f075575e))
* **py-screamingface:** typecheck the live inspect test without the extra installed ([7fd8df3](https://github.com/ScreamingFace/screamingface/commit/7fd8df33423ece1dd62b3f756da387c2f474bf46))
* **scoreboard:** close partial-run leaderboard follow-ups ([#820](https://github.com/ScreamingFace/screamingface/issues/820)) ([2b47ae3](https://github.com/ScreamingFace/screamingface/commit/2b47ae3cdbd9a6cccfac4e584e0c1c838f68028a))
* **screamingface-engine:** declare contracteval's failure codes so a failed case reports instead of crashing ([fa8bbe8](https://github.com/ScreamingFace/screamingface/commit/fa8bbe859d8499c6a827e1f5f2a68a3c4cb6ab4c))
* **screamingface-engine:** declare contracteval's failure codes so failed cases report instead of crashing ([39cea39](https://github.com/ScreamingFace/screamingface/commit/39cea39fcc77ec08487b998429f86d3ab2cc7482))
* **screamingface-engine:** migrate the fourth DRACO-pinning test — the e2e failure tape ([1c5f93e](https://github.com/ScreamingFace/screamingface/commit/1c5f93ef359c00bcac0db493e420552f08177f62))
* **screamingface-engine:** scope the answer seed to the Candidate invocation ([a9159f1](https://github.com/ScreamingFace/screamingface/commit/a9159f1b0a17bcaa8ab4ba3ebc8656263fc5e495))
* **screamingface-engine:** stop mislabelling decode failures and close the ifeval resume trap ([498d8e7](https://github.com/ScreamingFace/screamingface/commit/498d8e72da167c6418626e5eff806ee443b5afe7))
* **screamingface:** check provider access before evaluation ([#933](https://github.com/ScreamingFace/screamingface/issues/933)) ([d441f0a](https://github.com/ScreamingFace/screamingface/commit/d441f0a288ce5434356ea9bc5dcaf28495c2172b))
* **screamingface:** give disconnects a fresh recovery budget ([#874](https://github.com/ScreamingFace/screamingface/issues/874)) ([bc0f4c5](https://github.com/ScreamingFace/screamingface/commit/bc0f4c5128d0db932a5bde384634334f6d80357e))
* **screamingface:** give the frontierscience panel room to finish and keep constraints ([8a80b51](https://github.com/ScreamingFace/screamingface/commit/8a80b5163ee76e3581f2dabce5a61ae7a2f1b170))
* **screamingface:** give the notebook kernel the exporter it tells you to use ([7d71512](https://github.com/ScreamingFace/screamingface/commit/7d71512d30b12dde1e5dfb7ab85a8af0bd548a68))
* **screamingface:** group Report failures under Candidate headings ([#916](https://github.com/ScreamingFace/screamingface/issues/916)) ([26b1d76](https://github.com/ScreamingFace/screamingface/commit/26b1d7699a0f32ede9da75d7d38f913a985ed5f3))
* **screamingface:** guard the Engine port and tear down only what the recipe started ([28e7ea9](https://github.com/ScreamingFace/screamingface/commit/28e7ea9f7c85b1f95f20bf9971ca21453bb273cd))
* **screamingface:** include bundled runtime tracing dependencies ([#920](https://github.com/ScreamingFace/screamingface/issues/920)) ([48ec29d](https://github.com/ScreamingFace/screamingface/commit/48ec29d14ce91d99aedbd861a067bf4239839163))
* **screamingface:** keep the Studio sidecar build working without editable copies ([6f63231](https://github.com/ScreamingFace/screamingface/commit/6f63231e022e73a324bebea42df583ada8568f40))
* **screamingface:** let sf.evaluate take the seed Client.evaluate already takes ([479c1b0](https://github.com/ScreamingFace/screamingface/commit/479c1b076eb7db418437ed0df10e5fbccb5e815b))
* **screamingface:** let sf.evaluate take the seed Client.evaluate already takes ([a43ddd1](https://github.com/ScreamingFace/screamingface/commit/a43ddd110c4042926d4a7a425107b49e7412ebe6))
* **screamingface:** live notebook activity and a frontierscience panel that finishes ([ecff774](https://github.com/ScreamingFace/screamingface/commit/ecff7745967629fe4d3aecf4211f504eaf48582d))
* **screamingface:** make the All chip highlight on the first click ([4b94928](https://github.com/ScreamingFace/screamingface/commit/4b94928e774b08ab344dc364d77ed6f97278d8f5))
* **screamingface:** make the notebook recipe work from the repo root and survive a failed bake ([db25c4c](https://github.com/ScreamingFace/screamingface/commit/db25c4c120f3e2eb73d63f2630811125b4b8fff8))
* **screamingface:** retry replay-safe requests on transient edge failures ([#835](https://github.com/ScreamingFace/screamingface/issues/835)) ([ad0c965](https://github.com/ScreamingFace/screamingface/commit/ad0c965df8a34cb2cd7023c83bcaa79222307354))
* **screamingface:** run the live url4 and apps from a dev checkout's editable install ([7008bc0](https://github.com/ScreamingFace/screamingface/commit/7008bc0e94f2dfa12a1404e637f9004c23c50eaf))
* **screamingface:** run the live url4 and apps from a dev checkout's editable install ([33c8ce5](https://github.com/ScreamingFace/screamingface/commit/33c8ce5f1030ae116cf77674008c153f3409e0d5))
* **screamingface:** stop logging prompts and make the runtime log private (OME-990) ([#780](https://github.com/ScreamingFace/screamingface/issues/780)) ([7c85f1a](https://github.com/ScreamingFace/screamingface/commit/7c85f1ae6edf86efe80c8c18c0fa3511c1d1c577))
* **screamingface:** stop the imported-catalogue notebook promising an unsupported path ([e061dc0](https://github.com/ScreamingFace/screamingface/commit/e061dc03d8c3024ee8a290f6c4d65cf0ef9e4475))
* **screamingface:** trust a parsed marker, the ownership check, and the local Scoreboard ([4a1fb2b](https://github.com/ScreamingFace/screamingface/commit/4a1fb2b1ee5cfaa17ef4d95dbd39ef495962d500))
* **screamingface:** use a panel that finishes frontierscience in notebook 12 ([a835bdd](https://github.com/ScreamingFace/screamingface/commit/a835bddc5e33c3ada2b7e53205ba0254e6ea3d23))


### Refactors

* **py-screamingface:** derive the coach verdict projection from the revisioned field tuple ([fd8a2f0](https://github.com/ScreamingFace/screamingface/commit/fd8a2f081982b392a2cfe737f262b3e0be819cb8))
* **py-screamingface:** drop the replay preflight hatch now that model parameters are keyless ([9bef420](https://github.com/ScreamingFace/screamingface/commit/9bef420c1d58d734609d3743387f20106252be48))
* **screamingface-engine:** fold the draco boards onto the shared scored spine ([c1c9256](https://github.com/ScreamingFace/screamingface/commit/c1c9256283bd262294e67cf5f5ae45fbab8bbac5))
* **screamingface-engine:** fold the draco boards onto the shared scored spine ([cd3527b](https://github.com/ScreamingFace/screamingface/commit/cd3527bc47091708b5ae18d4354569661ddc935c))
* **screamingface-engine:** split provider refusal from graded refusal in case status ([a9b5da2](https://github.com/ScreamingFace/screamingface/commit/a9b5da2d059bf1a36b6f0268cec3d09f0d8f2543))
* **screamingface-engine:** split provider refusal from graded refusal in case status ([fe1a8cf](https://github.com/ScreamingFace/screamingface/commit/fe1a8cff48cc5287cb9883753ebf3d648c017f06))
* **screamingface:** take the live source directories from the runtime itself ([c5eb584](https://github.com/ScreamingFace/screamingface/commit/c5eb584dd4817b0bbfbaaddd23c1c47d9d2dafd4))


### Documentation

* **py-screamingface:** add the MedXpertQA at-a-glance infographic to the example notebook ([3e9f88e](https://github.com/ScreamingFace/screamingface/commit/3e9f88e3ecb3fa64de15d579044809298819d2de))
* **py-screamingface:** author the MedXpertQA infographic at width 1200 in the notebook builder ([f41a168](https://github.com/ScreamingFace/screamingface/commit/f41a168d2aaaa482f373edcf007eed2f5ea3563d))
* **py-screamingface:** diagram how the ifeval golden guards the notebooks ([0bbf2d0](https://github.com/ScreamingFace/screamingface/commit/0bbf2d0f24b154909004d39b60b5b2e3d82ed4c3))
* **py-screamingface:** show a seeded run on the imported gsm8k board ([0c514b1](https://github.com/ScreamingFace/screamingface/commit/0c514b1a8d31cebb42a06ce003e40c718770452f))
* **py-screamingface:** teach the MedXpertQA notebook the proven panel lineup ([032e31e](https://github.com/ScreamingFace/screamingface/commit/032e31e09340a1214ce440829b5dcf8e8af6a709))
* **screamingface-engine:** model-graded imports are in scope — correct the env-var judge plan ([f17ad00](https://github.com/ScreamingFace/screamingface/commit/f17ad0006f69e92d1a11cb9a9444e7219e3a852e))
* **screamingface-engine:** say what preparing assets actually does ([0c22ae4](https://github.com/ScreamingFace/screamingface/commit/0c22ae49ca6ab007ddc3c55ebfc57f691eae227f))
* **screamingface:** carry the just local-stack-notebooks line into the contracteval notebook ([e38ee18](https://github.com/ScreamingFace/screamingface/commit/e38ee182b9e598806cc38976ba945c07cd765213))
* **screamingface:** rename the imported-boards notebook and drop its export sections ([9f6188a](https://github.com/ScreamingFace/screamingface/commit/9f6188a4792f4042e1f58b0d7dc40765fae7a494))
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
