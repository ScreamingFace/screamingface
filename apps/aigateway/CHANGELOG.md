# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [1.0.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v1.0.0) (2026-10-23)


### ⚠ BREAKING CHANGES

* **aigateway:** a provider plugin must implement the hooks under their new names; an old name is no longer called.
* **aigateway:** AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE no longer imports a credential at startup, and the Anthropic plugin settings claude_code_keychain_service and bootstrap_user are removed.
* **aigateway:** Profile-only credentials no longer resolve, and quarantined pairs return credential_pair_unresolved.
* **aigateway:** GET/POST/PATCH/PUT/DELETE on /v1/auth/profiles, /v1/auth/{provider}/profiles[...] and /v1/admin/accounts/{account_id}/profiles[...] now answer 410.
* **aigateway:** delete the dead chat shims and the saved-defaults pipeline (Stage E, E2b) ([#1456](https://github.com/ScreamingFace/screamingface/issues/1456))

### Features

* **aigateway:** add pair-addressed admin PUT and DELETE through the mutation bridge ([#1404](https://github.com/ScreamingFace/screamingface/issues/1404)) ([#1405](https://github.com/ScreamingFace/screamingface/issues/1405)) ([e79db82](https://github.com/ScreamingFace/screamingface/commit/e79db8205f6d345aa68853008562e0e3bc646045))
* **aigateway:** cap request bodies and accept media only as data: URIs ([#1479](https://github.com/ScreamingFace/screamingface/issues/1479)) ([a2cbf70](https://github.com/ScreamingFace/screamingface/commit/a2cbf70bad450e41e9ee2d8be1c79967bd8da5f2))
* **aigateway:** check a gateway database before a pull, and say what one load_page transaction covers ([701fb82](https://github.com/ScreamingFace/screamingface/commit/701fb82790ba76e3b9de1e649ef2405b50d17828))
* **aigateway:** enable local Fusion benchmark execution ([#1448](https://github.com/ScreamingFace/screamingface/issues/1448)) ([cddc9f5](https://github.com/ScreamingFace/screamingface/commit/cddc9f59d09cfc762f67fe5f21199dcf74dae338))
* **aigateway:** expose each model's input modalities on /v1/models ([#1451](https://github.com/ScreamingFace/screamingface/issues/1451)) ([2406ccd](https://github.com/ScreamingFace/screamingface/commit/2406ccd5aeaec7ac378bda22e8a3177b9398318b))
* **aigateway:** let a native connection repair a migrated pair's credential (Stage E, E1b) ([#1449](https://github.com/ScreamingFace/screamingface/issues/1449)) ([00c1bef](https://github.com/ScreamingFace/screamingface/commit/00c1bef11e673ce488538966e572cff5d9e08319))
* **aigateway:** list an account's provider credentials by pair (G1 1/3) ([#1397](https://github.com/ScreamingFace/screamingface/issues/1397)) ([1ed95ab](https://github.com/ScreamingFace/screamingface/commit/1ed95abdfb75c783117625d452573ac7090fcec9))
* **aigateway:** page the community cache to signed-in callers and load pages into SQLite ([dc695cf](https://github.com/ScreamingFace/screamingface/commit/dc695cfd2227323d73ac5cc891cdc1f487271191))
* **aigateway:** page the community cache to signed-in callers and load pages into SQLite ([4a7aa2b](https://github.com/ScreamingFace/screamingface/commit/4a7aa2b748ecc0e0e5251b1a3847ffd0ec371f0d))
* **aigateway:** point every re-auth URL at the Connection API ([#1432](https://github.com/ScreamingFace/screamingface/issues/1432)) ([59545b2](https://github.com/ScreamingFace/screamingface/commit/59545b20bb9696681034032b33bff11bf0a0b6c5))
* **aigateway:** prove a legacy OAuth shadow by identity before PUT or DELETE (G1 3/3) ([#1408](https://github.com/ScreamingFace/screamingface/issues/1408)) ([3bfa2fd](https://github.com/ScreamingFace/screamingface/commit/3bfa2fd2439ed9e960b4d7440975b91e0f7f10ec))
* **aigateway:** relay the provider's sanitized error message (OME-1136) ([#1233](https://github.com/ScreamingFace/screamingface/issues/1233)) ([8d32145](https://github.com/ScreamingFace/screamingface/commit/8d32145515a4dcb35c56c7dabd9d814c1f90a1ee))
* **aigateway:** report image and file input tokens in chat usage ([#1481](https://github.com/ScreamingFace/screamingface/issues/1481)) ([b76556c](https://github.com/ScreamingFace/screamingface/commit/b76556ca3d1d8d68159c5a3d0b8933fc0bea874e))
* **aigateway:** report the successful attempt's direct cost and usage ([#1498](https://github.com/ScreamingFace/screamingface/issues/1498)) ([b57e2fc](https://github.com/ScreamingFace/screamingface/commit/b57e2fcbe6c21ffbd7dfd6772677b5eb990b7390))
* **aigateway:** send images and PDFs natively to Gemini, Antigravity and Codex ([#1431](https://github.com/ScreamingFace/screamingface/issues/1431)) ([8c5b72b](https://github.com/ScreamingFace/screamingface/commit/8c5b72bd5786b254f141c40ffb4f1ac2d7ce70a9))
* **aigateway:** serve configured remote endpoints as provider instances ([#1527](https://github.com/ScreamingFace/screamingface/issues/1527)) ([ca31b88](https://github.com/ScreamingFace/screamingface/commit/ca31b88efbba4a33c9ab6d6f471b7bd2053d3900))
* **aigateway:** support OpenRouter reasoning objects ([#1483](https://github.com/ScreamingFace/screamingface/issues/1483)) ([a4b2d84](https://github.com/ScreamingFace/screamingface/commit/a4b2d849ef80e062e4446563d79931090a1b401b))
* **screamingface-engine:** send a Case's inline pictures to the model as image parts (OME-1678) ([36d5351](https://github.com/ScreamingFace/screamingface/commit/36d5351805943b47121bb815023c7b611661280f))
* **screamingface:** sf.cache.pull_from_remote, use_cache=, and the local cache on by default ([#1446](https://github.com/ScreamingFace/screamingface/issues/1446)) ([19d33e4](https://github.com/ScreamingFace/screamingface/commit/19d33e4c862e352e4dc7fa4e077341f42550a46d))


### Bug Fixes

* **aigateway:** address the PR [#1433](https://github.com/ScreamingFace/screamingface/issues/1433) re-review of the community-cache pages and loader ([e07060e](https://github.com/ScreamingFace/screamingface/commit/e07060ec958bf112dd56f3bed862058a30556eb0))
* **aigateway:** address the PR [#1433](https://github.com/ScreamingFace/screamingface/issues/1433) review of the community-cache pages and loader ([59cc202](https://github.com/ScreamingFace/screamingface/commit/59cc2028abaabcf8e2e4efc7e85f2ae8ce58fefa))
* **aigateway:** call the Codex test's hook by its credential name and drop a retired live model ([2876feb](https://github.com/ScreamingFace/screamingface/commit/2876feba97a4bd38ced3bd4d51be1f8762439292))
* **aigateway:** check the pair before marking a Connection error (G0 3/3) ([#1396](https://github.com/ScreamingFace/screamingface/issues/1396)) ([123be84](https://github.com/ScreamingFace/screamingface/commit/123be8466eb10810263f33a0c935aca4c4c9819f))
* **aigateway:** count the rows after a cursor in one statement ([5153e3b](https://github.com/ScreamingFace/screamingface/commit/5153e3bfb839b9a7fd9d415a8d00709889dea0d3))
* **aigateway:** keep dispatch failures at one record when the handler raises ([#1230](https://github.com/ScreamingFace/screamingface/issues/1230)) ([643a496](https://github.com/ScreamingFace/screamingface/commit/643a4961599c64445c7ccccdbb584309cb831fe6))
* **aigateway:** keep exact usage evidence for large successful bodies ([#1520](https://github.com/ScreamingFace/screamingface/issues/1520)) ([476c0cc](https://github.com/ScreamingFace/screamingface/commit/476c0cc031ab66023812c422fd7ad8563a83cc94))
* **aigateway:** read litellm's bundled model list, never a download at start (OME-1615) ([0648030](https://github.com/ScreamingFace/screamingface/commit/0648030fa63a71041250f9034e4114a150554314))
* **aigateway:** read litellm's bundled model list, never a download at start (OME-1615) ([34fffb9](https://github.com/ScreamingFace/screamingface/commit/34fffb983bd1268f0c3098674c0028215fb153a4))
* **aigateway:** refuse a local database missing a cache column as outdated_gateway_database ([0047066](https://github.com/ScreamingFace/screamingface/commit/004706610eff7602572f0f9bab79c3812d200255))
* **aigateway:** refuse a page whose gateway does not report a revision the local side uses ([d4c0308](https://github.com/ScreamingFace/screamingface/commit/d4c030899306ca1fcb70fe7e22b6dec42941563f))
* **aigateway:** refuse file parts on Ollama instead of dropping them ([#1447](https://github.com/ScreamingFace/screamingface/issues/1447)) ([ec4b632](https://github.com/ScreamingFace/screamingface/commit/ec4b632b2267212783ca932c93a6c7314256ef3a))
* **aigateway:** reject invalid Unicode in remote completions ([#1539](https://github.com/ScreamingFace/screamingface/issues/1539)) ([bdf5746](https://github.com/ScreamingFace/screamingface/commit/bdf5746a41bffce68c8f8cf0aef204dcf6d5628d))
* **aigateway:** take a row read by both keyset parts once, and plan the query each part sends ([dadd95d](https://github.com/ScreamingFace/screamingface/commit/dadd95dca6d6205569e3a0a22c7e4f740f2f652d))
* **aigateway:** type the Codex model refusal and read the live Codex model list ([#1441](https://github.com/ScreamingFace/screamingface/issues/1441)) ([40908ac](https://github.com/ScreamingFace/screamingface/commit/40908acdd5f2521ed255ae2226393ef4151faa92))
* raise the model-call budget to 30 minutes for long evaluations ([#1430](https://github.com/ScreamingFace/screamingface/issues/1430)) ([92645fe](https://github.com/ScreamingFace/screamingface/commit/92645fe66085733dc2a846fd86d1cc2f53e2330c))
* **screamingface-engine:** keep misplaced pictures out of refusals and refuse pictures in grading calls ([afbe4bb](https://github.com/ScreamingFace/screamingface/commit/afbe4bbdfa3cbe1c903830f53bdbad37c40d36c6))


### Performance

* **aigateway:** encode and gzip community-cache batches in a worker thread ([b61f48d](https://github.com/ScreamingFace/screamingface/commit/b61f48daad93b275c4048ea8f623ed29493cc08e))
* **aigateway:** start each community-cache batch at its cursor in the index ([cd5571e](https://github.com/ScreamingFace/screamingface/commit/cd5571ed7d672f6bd112ca527693bf38c1208527))


### Refactors

* **aigateway:** build both keyset forms from one pair of conditions ([22a6c58](https://github.com/ScreamingFace/screamingface/commit/22a6c5856ad16e4f6cc7d248d57ac96d408a4f76))
* **aigateway:** check the parameter contract by revisions.PARAMETER_CONTRACT_KEY ([5992399](https://github.com/ScreamingFace/screamingface/commit/599239908941bfe7b62fa4b8284a03c9d51a741d))
* **aigateway:** delete the dead chat shims and the saved-defaults pipeline (Stage E, E2b) ([#1456](https://github.com/ScreamingFace/screamingface/issues/1456)) ([1f873d9](https://github.com/ScreamingFace/screamingface/commit/1f873d95eda55fe87a5b01d72a038aa49efc1c08))
* **aigateway:** delete the Profile-era core left dead after route retirement (Stage E, E3b) ([#1480](https://github.com/ScreamingFace/screamingface/issues/1480)) ([aac2a1a](https://github.com/ScreamingFace/screamingface/commit/aac2a1ab2e734d182bea48b87304914e0be7e982))
* **aigateway:** exclude Tavily rows from community pages by TAVILY_PROVIDER ([708de24](https://github.com/ScreamingFace/screamingface/commit/708de24dffe4fe7ef2ee1ab11a2a98aea48e9fc2))
* **aigateway:** give the plugin hooks credential names ([#1523](https://github.com/ScreamingFace/screamingface/issues/1523)) ([eb31158](https://github.com/ScreamingFace/screamingface/commit/eb31158de2d6913fda5001e86b8f7863c7bb4e44))
* **aigateway:** make E4a readers connection-only ([#1491](https://github.com/ScreamingFace/screamingface/issues/1491)) ([b66f94f](https://github.com/ScreamingFace/screamingface/commit/b66f94f087a86787623b53f3ea50c0e51312117e))
* **aigateway:** mint a D18 PUT's row at its own address and retire the dead Profile conflict arms ([#1541](https://github.com/ScreamingFace/screamingface/issues/1541)) ([8cb1e54](https://github.com/ScreamingFace/screamingface/commit/8cb1e54e0f6ee8fd71d6f2a14a983e45d70ee9b7))
* **aigateway:** move the credential vocabulary out of profile_models (Stage E, E2a) ([#1458](https://github.com/ScreamingFace/screamingface/issues/1458)) ([4803a77](https://github.com/ScreamingFace/screamingface/commit/4803a77c9974b4708385e4eb87fea31150e0c7a3))
* **aigateway:** retire the legacy Profile HTTP routes with a 410 (Stage E, E3) ([#1464](https://github.com/ScreamingFace/screamingface/issues/1464)) ([08f5343](https://github.com/ScreamingFace/screamingface/commit/08f5343171422f8a36da02d9bbe901ec73f3af6c))
* **aigateway:** stop writing Profile documents ([#1516](https://github.com/ScreamingFace/screamingface/issues/1516)) ([f7e5486](https://github.com/ScreamingFace/screamingface/commit/f7e54869bb84e36f9864808aeb7a0bea8ad09b33))


### Documentation

* **aigateway:** a replace restore and a late commit can fall behind a pull's cursor ([f894ad9](https://github.com/ScreamingFace/screamingface/commit/f894ad96235cc934488b022db402cc30b0ed8dc3))
* **aigateway:** close OME-1541 ledger and mirror, correct the route-test ordering note ([#1437](https://github.com/ScreamingFace/screamingface/issues/1437)) ([8edd994](https://github.com/ScreamingFace/screamingface/commit/8edd994bff69a78b9d3a527335885dd403a0a151))
* **aigateway:** describe the two keyset reads after a cursor, and record what the second review left ([8e3213b](https://github.com/ScreamingFace/screamingface/commit/8e3213be0bbfa118e10fa982781b5a42abc17633))
* **aigateway:** name the litellm check the model-map setting feeds (OME-1615) ([997cb4f](https://github.com/ScreamingFace/screamingface/commit/997cb4f9188cbd67a355d6de19c9535a1c3b0bc0))
* **aigateway:** say what the keyset dedupe and its exhausted flag cover ([405cc1c](https://github.com/ScreamingFace/screamingface/commit/405cc1c574577d07ec7013d7713665725944de6f))
* **aigateway:** the cache-entries route serves the anonymous account when auth is disabled ([3bb7de6](https://github.com/ScreamingFace/screamingface/commit/3bb7de6f6288d6bcbe13967350a8dd6b4a7e3c1e))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-v0.1.0...aigateway-v0.2.0) (2026-05-11)


### Features

* **SF-138:** scaffold apps/aigateway/ standalone LiteLLM-compatible service ([#122](https://github.com/OpenMined/screamingface/issues/122)) ([3a66bf9](https://github.com/OpenMined/screamingface/commit/3a66bf9269f20848b7bc3fadca5809527b7bb901))


### Bug Fixes

* **ci:** correct release-please tag separator + enable workflow chain ([#154](https://github.com/OpenMined/screamingface/issues/154)) ([c51abc3](https://github.com/OpenMined/screamingface/commit/c51abc3ecae2028d9a333bf6b5881f8d8b3dc7d8))

## [Unreleased]

## [0.1.0]

- Initial release.
