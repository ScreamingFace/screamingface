# Changelog

## Unreleased

### Features

* **screamingface:** expose and render why a published score will not rank

## [0.2.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-v0.1.1...screamingface-v0.2.0) (2026-09-12)


### Features

* **aigateway:** carry gateway_call_id on every log line ([#898](https://github.com/ScreamingFace/screamingface/issues/898)) ([802bed9](https://github.com/ScreamingFace/screamingface/commit/802bed9aeac74d6b297d4b3e8fd2897b91d2b172))
* **aigateway:** join the inbound traceparent to the log context ([#902](https://github.com/ScreamingFace/screamingface/issues/902)) ([5ecac45](https://github.com/ScreamingFace/screamingface/commit/5ecac451f659e5de031a5020f21450a44b5c7a8d))
* **benchmark-tests:** Test that provider failures land where each benchmark's failure policy says ([e50203c](https://github.com/ScreamingFace/screamingface/commit/e50203c2c142f7c829c3f2e14abf3c269c7a8555))
* **benchmark-tests:** Turn one real benchmark run into a free CI replay that fails when the published score drifts ([5cba291](https://github.com/ScreamingFace/screamingface/commit/5cba291bf720aeb3a25fb6ac58c67919bed74769))
* deliver large Evaluation results in full instead of cutting them off at 1 MiB ([0712043](https://github.com/ScreamingFace/screamingface/commit/07120439865973cff99c5c280fc990bf9b5cb0d0))
* **e2e:** add a setup validator for the traceability lanes (OME-1106) ([#832](https://github.com/ScreamingFace/screamingface/issues/832)) ([89aeb9f](https://github.com/ScreamingFace/screamingface/commit/89aeb9f90d12b95e3eedbc7ec2f56aaf1cc3319e))
* **engine:** log run identity and terminal evidence on the control plane ([#901](https://github.com/ScreamingFace/screamingface/issues/901)) ([a136e0f](https://github.com/ScreamingFace/screamingface/commit/a136e0ffd153dcb8275d409b9ccbb2b60f14eaf2))
* if local stack is running with `screamingface up`, `sf.connect()` now prefers to connect to it ([eb2017a](https://github.com/ScreamingFace/screamingface/commit/eb2017a58237116e136279777f0f78f1c2fa5bd8))
* **py-screamingface:** bless a fusion board's e2e replay from its saved report alone ([d04a87a](https://github.com/ScreamingFace/screamingface/commit/d04a87a56f7ddc1b8a3a135acb99fbada4999ba9))
* **py-screamingface:** bless corrective-loop goldens from fresh cache dumps ([749cc3c](https://github.com/ScreamingFace/screamingface/commit/749cc3c1258940c9f2146a1373915de438eef0b1))
* **py-screamingface:** bless the gdpval-text fusion golden ([3d15d53](https://github.com/ScreamingFace/screamingface/commit/3d15d531ccd35ba62241783b67853ac50b5620b5))
* **py-screamingface:** bless the ifeval corrective-loop golden ([5d470bd](https://github.com/ScreamingFace/screamingface/commit/5d470bdf28779e98e53996cf012c86ae6c8c3464))
* **py-screamingface:** guard ifeval and gdpval-text with e2e replay goldens ([c001fbb](https://github.com/ScreamingFace/screamingface/commit/c001fbb2acbfa046b8cda67c484d51ad5f1ae805))
* **py-screamingface:** let the keyless replay disarm the parameter preflight ([5b4beaa](https://github.com/ScreamingFace/screamingface/commit/5b4beaa54c137ac9b50cd6cc2aa1f2cc7e672073))
* **py-screamingface:** pin the healthbench fusion score with a CI replay blessed from its saved report ([9d5f015](https://github.com/ScreamingFace/screamingface/commit/9d5f015b4a03880ce194cbd10112c7d3d983b9ce))
* **py-screamingface:** redeem and verify artifact results in the transport ([412d843](https://github.com/ScreamingFace/screamingface/commit/412d84395819c835aef7840d3031be50b5e65f71))
* replace binary accuracy submissions with benchmark-native Leaderboard scores ([8bb79e1](https://github.com/ScreamingFace/screamingface/commit/8bb79e13d2002236e95646e788040f5f2b76de94))
* report real run cost from provider-authored OpenRouter evidence ([05d85f1](https://github.com/ScreamingFace/screamingface/commit/05d85f1fb136b24c8d8b43f4bf656e6c93a93f20))
* run any OpenRouter model — dynamic admission at preflight ([#633](https://github.com/ScreamingFace/screamingface/issues/633)) ([3938f66](https://github.com/ScreamingFace/screamingface/commit/3938f66b8090af65547c09cd8020de8428dc4f9e))
* **scoreboard:** explain revision-mismatch submissions ([#843](https://github.com/ScreamingFace/screamingface/issues/843)) ([f0531a5](https://github.com/ScreamingFace/screamingface/commit/f0531a5dd8485ee2e64877b2953dc96ed25ef47f))
* **scoreboard:** seed benchmark text from the Engine catalogue ([7e74662](https://github.com/ScreamingFace/screamingface/commit/7e74662c502033135f6277272a49eee207686919))
* **screamingface-benchmarks:** GDPVal text subset ([454253d](https://github.com/ScreamingFace/screamingface/commit/454253da0034cabb1fce3cc50f07fe6ac63e818f))
* **screamingface-benchmarks:** Pin the public import surface of `packages/screamingface` so that CIs fail when they are changed accidentally ([4cd19b0](https://github.com/ScreamingFace/screamingface/commit/4cd19b07954b3809446b2d482c51c1843089f1a8))
* **screamingface-engine:** add the full HealthBench Professional board (525 cases, official score) ([8835ebc](https://github.com/ScreamingFace/screamingface/commit/8835ebc80e72b466260278f364751713c585bf4e))
* **screamingface-engine:** onboard MedXpertQA as an exact-match MCQ benchmark ([0829106](https://github.com/ScreamingFace/screamingface/commit/0829106b1e91a80f76b23275ce865b52a72cd1e7))
* **screamingface-engine:** propagate the run's traceparent to aigateway (OME-1119) ([#849](https://github.com/ScreamingFace/screamingface/issues/849)) ([1220e2e](https://github.com/ScreamingFace/screamingface/commit/1220e2e64a24dd3439829fb773b39a093702fde4))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/ScreamingFace/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* **screamingface-engine:** retain operation accounting ([#762](https://github.com/ScreamingFace/screamingface/issues/762)) ([dd51ea8](https://github.com/ScreamingFace/screamingface/commit/dd51ea815374b92ce8b907d162476a690ec72d4a))
* **screamingface/benchmark:** E2E tests for benchmarks in CI from recorded responses (no paid calls) ([1ad7f1f](https://github.com/ScreamingFace/screamingface/commit/1ad7f1f420e22a5274277a17ac984927430e41c1))
* **screamingface:** add opt-in Scoreboard submit cells to example notebooks ([45ce2ce](https://github.com/ScreamingFace/screamingface/commit/45ce2ceefe66acdf527bd9fc5f77d4a5193007e1))
* **screamingface:** benchmark explainer infographics in the example notebooks ([ced3fdb](https://github.com/ScreamingFace/screamingface/commit/ced3fdba129a4ab8d8c81812fc3ee3409d43e722))
* **screamingface:** bless tool learns to re-key judges across a protocol delta ([5bd6954](https://github.com/ScreamingFace/screamingface/commit/5bd6954ce8d1bbaad92e9edbebeddb06972a57d3))
* **screamingface:** carry the run's trace id onto the candidate result ([#842](https://github.com/ScreamingFace/screamingface/issues/842)) ([a72960d](https://github.com/ScreamingFace/screamingface/commit/a72960ddc6e7dc7fa648ded09d6a8a79c18d7782))
* **screamingface:** connect to a running local stack by default ([b5f760d](https://github.com/ScreamingFace/screamingface/commit/b5f760d622ed978a4da80b09c6f3aacbfc3da068))
* **screamingface:** enhance LeaderboardScore with scoreboard_url and improve HTML rendering ([24855ce](https://github.com/ScreamingFace/screamingface/commit/24855ce4856093aa6f0500fc2b1a1a5e146606d9))
* **screamingface:** identify Client requests and generated notebooks ([#918](https://github.com/ScreamingFace/screamingface/issues/918)) ([0e52dbc](https://github.com/ScreamingFace/screamingface/commit/0e52dbcdd2d5073d692de17c90b9d278660097aa))
* **screamingface:** notebook helper to rebuild a CandidateResult from an exported report ([29c41e1](https://github.com/ScreamingFace/screamingface/commit/29c41e171a7bee4822d6315f1d544aeb045529b5))
* **screamingface:** originate the traceparent in the client ([#789](https://github.com/ScreamingFace/screamingface/issues/789)) ([c2b5895](https://github.com/ScreamingFace/screamingface/commit/c2b5895521101ee06f60b8e47e69678b239528b9))
* **screamingface:** pin each failed case's failure code in the e2e goldens ([7bcaac4](https://github.com/ScreamingFace/screamingface/commit/7bcaac44f9458763d55a2083f64ff51d74f20526))
* **screamingface:** pin each failed case's failure code in the e2e goldens ([e09a6a5](https://github.com/ScreamingFace/screamingface/commit/e09a6a52775a82f5df0508d31e80ff0a0873f44e))
* **screamingface:** prepare and demonstrate MedXpertQA ([c4c82e5](https://github.com/ScreamingFace/screamingface/commit/c4c82e557f37272190738ef21feaaa0ef369dc8f))
* **screamingface:** prepare and demonstrate the GDPval text subset ([d839f02](https://github.com/ScreamingFace/screamingface/commit/d839f029ea7295c43c1eaa959cb7f34978030b79))
* **screamingface:** say whether a refused case was declined by the provider or refused by the model ([748e2f9](https://github.com/ScreamingFace/screamingface/commit/748e2f953213268a9d7fc7cb8536680322fb6ace))
* **screamingface:** seed the local Scoreboard from the Engine's benchmark registry ([b3c3999](https://github.com/ScreamingFace/screamingface/commit/b3c399992e08d15a50a49939b10c861e24f7fbc3))
* **screamingface:** send the run cost on leaderboard submissions ([#770](https://github.com/ScreamingFace/screamingface/issues/770)) ([ea4c866](https://github.com/ScreamingFace/screamingface/commit/ea4c866aaa4d1f8b6e3ede5aa11b33f0e28d556b))
* **screamingface:** serve the live checkout from screamingface up and retire the justfile ([ee9b915](https://github.com/ScreamingFace/screamingface/commit/ee9b9156111cf63554423f6237f2f3f88c142cfb))
* **screamingface:** show cache provenance as a diagnostic band ([#684](https://github.com/ScreamingFace/screamingface/issues/684)) ([48dddda](https://github.com/ScreamingFace/screamingface/commit/48ddddabf31690c873fbae476c45a57978b7cd27))
* **screamingface:** show hosted provider availability ([#703](https://github.com/ScreamingFace/screamingface/issues/703)) ([75b63b1](https://github.com/ScreamingFace/screamingface/commit/75b63b1519a1a656ba83ff341c868975b83c48b0))
* **screamingface:** show live candidate progress ([#694](https://github.com/ScreamingFace/screamingface/issues/694)) ([09e6370](https://github.com/ScreamingFace/screamingface/commit/09e63707cb052c5caddba12fc02f519786989b75))
* **screamingface:** submit the Engine score verbatim; render native scores ([9d3f1f5](https://github.com/ScreamingFace/screamingface/commit/9d3f1f54407ec134ad6047adcf2efeaa48dd5087))
* **screamingface:** support leaderboard co-authors ([#830](https://github.com/ScreamingFace/screamingface/issues/830)) ([7d7b6a4](https://github.com/ScreamingFace/screamingface/commit/7d7b6a48680e3dcaddff19809b8a392e8fee69fb))
* **screamingface:** tell provider-declined from model refusals on refused cases ([f945c86](https://github.com/ScreamingFace/screamingface/commit/f945c86bec5adf1926f884e64139a664f9b8ecc0))
* serve the live checkout from screamingface up and retire the justfile ([1e6ea45](https://github.com/ScreamingFace/screamingface/commit/1e6ea45475c82bc9b6ff04f5b66d622d4bbef5c6))


### Bug Fixes

* address Filip's PR [#626](https://github.com/ScreamingFace/screamingface/issues/626) review (both passes on bf7f12f) ([99ab98c](https://github.com/ScreamingFace/screamingface/commit/99ab98c3b76b509170cb9b13ef0b99fb211949a4))
* **py-screamingface:** make the README quickstart runnable and correct the first-run docs ([#765](https://github.com/ScreamingFace/screamingface/issues/765)) ([0b5a1e0](https://github.com/ScreamingFace/screamingface/commit/0b5a1e00096878f21db7b0f7ba692dce3f3d4271))
* **py-screamingface:** make the saved report the only bless authority and refresh loop goldens intact ([374dfc8](https://github.com/ScreamingFace/screamingface/commit/374dfc8f9d9fae579022a2f9e2b9c9f47fd1c2b4))
* **py-screamingface:** mint a fresh capability token to redeem result artifacts ([4a45b6b](https://github.com/ScreamingFace/screamingface/commit/4a45b6bb9f01e2cff7ea722050cf82be9e753d45))
* **py-screamingface:** name legacy Engine truncation instead of 'must be JSON' ([013314a](https://github.com/ScreamingFace/screamingface/commit/013314a3c65732af9c61d4b6fdf3f369c3575571))
* **py-screamingface:** raise local stack openrouter gateway concurrency to 32 ([25851fd](https://github.com/ScreamingFace/screamingface/commit/25851fdfa7a2ca50922b81a4dfc36da2febf67d9))
* **py-screamingface:** raise local stack openrouter gateway concurrency to 32 ([0b5d4dc](https://github.com/ScreamingFace/screamingface/commit/0b5d4dc8f242407d969921b963befb2bd0f4f82d))
* **py-screamingface:** refuse a foreign gateway database and print the effective config at up ([01d0c13](https://github.com/ScreamingFace/screamingface/commit/01d0c13c49e8eb9a76242843833d69301150ec8e))
* **py-screamingface:** refuse a foreign gateway database and print the effective config at up ([1cbac78](https://github.com/ScreamingFace/screamingface/commit/1cbac78e2fb3efca17e79e0cfa32fe91ea949078))
* **py-screamingface:** refuse contradictory bless modes and police golden fields both ways ([b80bfde](https://github.com/ScreamingFace/screamingface/commit/b80bfdef3b04e3b1e9cb357d39f37ce6d3df85ff))
* **py-screamingface:** refuse contradictory bless modes and police golden fields both ways ([959932f](https://github.com/ScreamingFace/screamingface/commit/959932f3034dfa72c0fa3028fef722c95bd448bb))
* **py-screamingface:** refuse the foreign database before restart stops anything ([d48fa21](https://github.com/ScreamingFace/screamingface/commit/d48fa21c9c81b4673977cacab0f4bb8ee4333bc8))
* **py-screamingface:** render only answer and feedback into the loop coach prompt ([8befc9c](https://github.com/ScreamingFace/screamingface/commit/8befc9c46bf142aaa9fc1a4f1705f1d097cf07b3))
* **py-screamingface:** render only answer and feedback into the loop coach prompt ([a61e001](https://github.com/ScreamingFace/screamingface/commit/a61e001b52e865d0c8fccf81147004c3502d78d4))
* **runtime:** include gateway form dependency ([4811d45](https://github.com/ScreamingFace/screamingface/commit/4811d457e7ba5cd033cafe537b0ff7e3a8b711c5))
* **runtime:** make embedded shutdown cancellable ([#691](https://github.com/ScreamingFace/screamingface/issues/691)) ([ffac66d](https://github.com/ScreamingFace/screamingface/commit/ffac66dac6f4cccab1a83d45c5f5f7bd9c73a901))
* **runtime:** make shutdown waiter cancellable ([e085b29](https://github.com/ScreamingFace/screamingface/commit/e085b294affa835e40ad947a7948541962d28d74))
* **scoreboard:** close partial-run leaderboard follow-ups ([#820](https://github.com/ScreamingFace/screamingface/issues/820)) ([2b47ae3](https://github.com/ScreamingFace/screamingface/commit/2b47ae3cdbd9a6cccfac4e584e0c1c838f68028a))
* **screamingface-benchmarks:** harden GDPval per review — strict decode, atomic fetch, lean image ([58553fc](https://github.com/ScreamingFace/screamingface/commit/58553fcb17dc388049fcb9b7dc869665df0b75b3))
* **screamingface-engine:** fail fast benchmark grading fan-outs so upstream errors survive ([cea8d52](https://github.com/ScreamingFace/screamingface/commit/cea8d5297990408c0f4d31bca39c45928b00ed82))
* **screamingface-engine:** make benchmark asset preparation auditable (OME-925) ([#677](https://github.com/ScreamingFace/screamingface/issues/677)) ([0077216](https://github.com/ScreamingFace/screamingface/commit/00772161f0d38a75822e0521eca2f177e54252d0))
* **screamingface-engine:** preserve upstream grading errors instead of masking them (OME-924) ([3e12e21](https://github.com/ScreamingFace/screamingface/commit/3e12e2186aedfe9f2784d1a5acf74c4c9b6e5791))
* **screamingface:** always deliver connection-panel completions ([#680](https://github.com/ScreamingFace/screamingface/issues/680)) ([7a2f7e4](https://github.com/ScreamingFace/screamingface/commit/7a2f7e4848cf1935cc6471180e76d1d978f329bd))
* **screamingface:** apply Colab theme detection everywhere ([#723](https://github.com/ScreamingFace/screamingface/issues/723)) ([9281a9f](https://github.com/ScreamingFace/screamingface/commit/9281a9f259465626bab15a663b8fb9e146a5c874))
* **screamingface:** authenticate scoreboard requests ([#654](https://github.com/ScreamingFace/screamingface/issues/654)) ([f8a98a4](https://github.com/ScreamingFace/screamingface/commit/f8a98a495a91a20aea56abda36b0d5df0b9f55f4))
* **screamingface:** clean up Colab widget styling ([#711](https://github.com/ScreamingFace/screamingface/issues/711)) ([efd9f15](https://github.com/ScreamingFace/screamingface/commit/efd9f15495f68b395ec9dbd98ce9324ca76740da))
* **screamingface:** declare python-multipart so a fresh [runtime] install boots ([a6ef741](https://github.com/ScreamingFace/screamingface/commit/a6ef7413aae68ab429260985baecc5d5ef41ec93)), closes [#735](https://github.com/ScreamingFace/screamingface/issues/735)
* **screamingface:** detect a missing [runtime] extra before the local stack boots ([#777](https://github.com/ScreamingFace/screamingface/issues/777)) ([7e29bc6](https://github.com/ScreamingFace/screamingface/commit/7e29bc6734a9f6246497d4e8522b26305d06ba7b))
* **screamingface:** follow the rename in the bundled-config checkout fallback ([052eff7](https://github.com/ScreamingFace/screamingface/commit/052eff7a7c21f5bc17a65244a4ab50d8e61a8af8))
* **screamingface:** give disconnects a fresh recovery budget ([#874](https://github.com/ScreamingFace/screamingface/issues/874)) ([bc0f4c5](https://github.com/ScreamingFace/screamingface/commit/bc0f4c5128d0db932a5bde384634334f6d80357e))
* **screamingface:** group Report failures under Candidate headings ([#916](https://github.com/ScreamingFace/screamingface/issues/916)) ([26b1d76](https://github.com/ScreamingFace/screamingface/commit/26b1d7699a0f32ede9da75d7d38f913a985ed5f3))
* **screamingface:** include bundled runtime tracing dependencies ([#920](https://github.com/ScreamingFace/screamingface/issues/920)) ([48ec29d](https://github.com/ScreamingFace/screamingface/commit/48ec29d14ce91d99aedbd861a067bf4239839163))
* **screamingface:** keep provider bootstrap opt-in and harden the stack guards ([0e2af79](https://github.com/ScreamingFace/screamingface/commit/0e2af7935777b2bc6995deffd4e96dd2257ac0f2))
* **screamingface:** let the case report's task pane scroll and carry a 10k budget ([7c1cab2](https://github.com/ScreamingFace/screamingface/commit/7c1cab26eac10c17fae005dc268fd425ae8d6129))
* **screamingface:** point the runtime build hook at the renamed Engine ([b184878](https://github.com/ScreamingFace/screamingface/commit/b184878f924c74953d1984458cda1c648dd1879e))
* **screamingface:** port the GDPval notebook's hand edits into the notebook builder ([fb0f23d](https://github.com/ScreamingFace/screamingface/commit/fb0f23d1779fbface2c6164aad3d47e6b7840cbf))
* **screamingface:** raise the HealthBench notebook budget in the builder ([79e9e95](https://github.com/ScreamingFace/screamingface/commit/79e9e95b7867cafb2e1d63e9d9250018e343feae))
* **screamingface:** regenerate the public-surface snapshot for refusal_kind ([8ee418a](https://github.com/ScreamingFace/screamingface/commit/8ee418af701169ae3a51f6f9361d55db879d21ce))
* **screamingface:** render hosted providers as managed ([#634](https://github.com/ScreamingFace/screamingface/issues/634)) ([222756e](https://github.com/ScreamingFace/screamingface/commit/222756e114ea83fab47fa9dcc31d98ff39056585))
* **screamingface:** render rubric criterion chips as PASS/FAIL with the judge verdict in the tooltip ([5225926](https://github.com/ScreamingFace/screamingface/commit/5225926dc2b26a88f62bddab00eb101de8fdcffb))
* **screamingface:** render rubric criterion chips as PASS/FAIL with the judge verdict in the tooltip ([a496104](https://github.com/ScreamingFace/screamingface/commit/a496104034d9325455b7b4921bb0f0f5a0cfb886))
* **screamingface:** render the Report card score benchmark-native, not as a percent ([bf7f12f](https://github.com/ScreamingFace/screamingface/commit/bf7f12f7482f87ea0af1749f7ce12af94febc72f))
* **screamingface:** retry replay-safe requests on transient edge failures ([#835](https://github.com/ScreamingFace/screamingface/issues/835)) ([ad0c965](https://github.com/ScreamingFace/screamingface/commit/ad0c965df8a34cb2cd7023c83bcaa79222307354))
* **screamingface:** seed the local board through the in-process Engine adapter ([00a3e5a](https://github.com/ScreamingFace/screamingface/commit/00a3e5a2896e0367122da3b68d80d4fedb4d56ae))
* **screamingface:** ship python-multipart so a fresh [runtime] install boots ([901678c](https://github.com/ScreamingFace/screamingface/commit/901678cc199a00ba23745964c47b7772f2cdca82))
* **screamingface:** show the Access authorization link in the panel ([#682](https://github.com/ScreamingFace/screamingface/issues/682)) ([c720e53](https://github.com/ScreamingFace/screamingface/commit/c720e530aaaacc32faa97277076e9aa5eb0d137f))
* **screamingface:** stop logging prompts and make the runtime log private (OME-990) ([#780](https://github.com/ScreamingFace/screamingface/issues/780)) ([7c85f1a](https://github.com/ScreamingFace/screamingface/commit/7c85f1ae6edf86efe80c8c18c0fa3511c1d1c577))
* **screamingface:** stop passing a tooltip to the progress VBox ([b3dd561](https://github.com/ScreamingFace/screamingface/commit/b3dd56187afc48c55645913c60a231a1210f9137))
* **screamingface:** stop warning when a cost total has no breakdown ([22db813](https://github.com/ScreamingFace/screamingface/commit/22db813d9177f222dc8702282683d051f5d4a9d5))
* **screamingface:** warn on partial leaderboard submissions (OME-922) ([#676](https://github.com/ScreamingFace/screamingface/issues/676)) ([0323a7b](https://github.com/ScreamingFace/screamingface/commit/0323a7bceab8ea0cf27e483d48dd294789419e76))


### Refactors

* **py-screamingface:** derive the coach verdict projection from the revisioned field tuple ([fd8a2f0](https://github.com/ScreamingFace/screamingface/commit/fd8a2f081982b392a2cfe737f262b3e0be819cb8))
* **py-screamingface:** drop the replay preflight hatch now that model parameters are keyless ([9bef420](https://github.com/ScreamingFace/screamingface/commit/9bef420c1d58d734609d3743387f20106252be48))
* **screamingface-engine:** fold the draco boards onto the shared scored spine ([c1c9256](https://github.com/ScreamingFace/screamingface/commit/c1c9256283bd262294e67cf5f5ae45fbab8bbac5))
* **screamingface-engine:** fold the draco boards onto the shared scored spine ([cd3527b](https://github.com/ScreamingFace/screamingface/commit/cd3527bc47091708b5ae18d4354569661ddc935c))
* **screamingface-engine:** split provider refusal from graded refusal in case status ([a9b5da2](https://github.com/ScreamingFace/screamingface/commit/a9b5da2d059bf1a36b6f0268cec3d09f0d8f2543))
* **screamingface-engine:** split provider refusal from graded refusal in case status ([fe1a8cf](https://github.com/ScreamingFace/screamingface/commit/fe1a8cff48cc5287cb9883753ebf3d648c017f06))


### Documentation

* **py-screamingface:** add the MedXpertQA at-a-glance infographic to the example notebook ([3e9f88e](https://github.com/ScreamingFace/screamingface/commit/3e9f88e3ecb3fa64de15d579044809298819d2de))
* **py-screamingface:** author the MedXpertQA infographic at width 1200 in the notebook builder ([f41a168](https://github.com/ScreamingFace/screamingface/commit/f41a168d2aaaa482f373edcf007eed2f5ea3563d))
* **py-screamingface:** diagram how the ifeval golden guards the notebooks ([0bbf2d0](https://github.com/ScreamingFace/screamingface/commit/0bbf2d0f24b154909004d39b60b5b2e3d82ed4c3))
* **py-screamingface:** teach the MedXpertQA notebook the proven panel lineup ([032e31e](https://github.com/ScreamingFace/screamingface/commit/032e31e09340a1214ce440829b5dcf8e8af6a709))
* repoint the remaining org references to ScreamingFace ([0379e66](https://github.com/ScreamingFace/screamingface/commit/0379e66d503a1e619acbde7faf1b005a20718678))
* **repo:** repoint the remaining OpenMined org references to ScreamingFace ([9e739a0](https://github.com/ScreamingFace/screamingface/commit/9e739a051cf6abf1778b39b57198f2ad75701205))
* **screamingface-engine:** update agent config, diagrams and stale paths ([1d2c047](https://github.com/ScreamingFace/screamingface/commit/1d2c047b2c522dee3df2dc9ea920d36f05584eea))
* **screamingface:** cover both HealthBench boards in one example notebook ([5de05d8](https://github.com/ScreamingFace/screamingface/commit/5de05d8d9038e3ea7d03e9aa4b45da1771a894ef))
* **screamingface:** GDPval benchmark explainer infographic ([537ee99](https://github.com/ScreamingFace/screamingface/commit/537ee9977cc8192c0ec773369089ba261e65d883))
* **screamingface:** refresh the GDPval notebook with the sector map and rehearsal guidance ([3282f18](https://github.com/ScreamingFace/screamingface/commit/3282f18bc786e2c314f8e78c3ecf8edd87fad1e9))
* **screamingface:** visual guide for protecting a board's score end-to-end ([da07dea](https://github.com/ScreamingFace/screamingface/commit/da07dea2ee95c8fb35d052730443c77eaad9936b))

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
