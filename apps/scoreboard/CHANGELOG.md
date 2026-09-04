# Changelog

## [0.2.0](https://github.com/ScreamingFace/screamingface/compare/scoreboard-v0.1.1...scoreboard-v0.2.0) (2026-09-04)


### Features

* **benchmarks:** flatten public identities ([dfd8eb9](https://github.com/ScreamingFace/screamingface/commit/dfd8eb97b431d9ae02cf51edc334bd357c0b9b10))
* replace binary accuracy submissions with benchmark-native Leaderboard scores ([8bb79e1](https://github.com/ScreamingFace/screamingface/commit/8bb79e13d2002236e95646e788040f5f2b76de94))
* **scoreboard:** accept, store and rank benchmark-native scores ([44d5496](https://github.com/ScreamingFace/screamingface/commit/44d54967c38bde87faee817458d0d4958b2c8654))
* **scoreboard:** adopt the leaderboard-mvp landing copy and UI ([#631](https://github.com/ScreamingFace/screamingface/issues/631)) ([bf0d95f](https://github.com/ScreamingFace/screamingface/commit/bf0d95f8b5d775ff38e24e5a35f10df56a6a83d4))
* **scoreboard:** adopt the leaderboard-mvp masthead nav and landing copy ([#609](https://github.com/ScreamingFace/screamingface/issues/609)) ([0b191c7](https://github.com/ScreamingFace/screamingface/commit/0b191c755cc29e71194fde28475bbc29dbd47557))
* **scoreboard:** compute open-vs-closed frontier statistics ([#519](https://github.com/ScreamingFace/screamingface/issues/519)) ([62a0735](https://github.com/ScreamingFace/screamingface/commit/62a0735d5555a63bc978bfe0b854bb1bb759aecf))
* **scoreboard:** compute the Pareto frontier of score against cost (OME-923 part A) ([#778](https://github.com/ScreamingFace/screamingface/issues/778)) ([7cd4314](https://github.com/ScreamingFace/screamingface/commit/7cd431410db62bcc2902a06a7f4f7ae977560025))
* **scoreboard:** credit multiple authors on a leaderboard submission (OME-1051) ([#833](https://github.com/ScreamingFace/screamingface/issues/833)) ([83b1546](https://github.com/ScreamingFace/screamingface/commit/83b154634b9b3a31eb2c63c2c4dccfd2ff1dc496))
* **scoreboard:** default new submissions to verified as a placeholder ([#588](https://github.com/ScreamingFace/screamingface/issues/588)) ([f9bd72f](https://github.com/ScreamingFace/screamingface/commit/f9bd72fef7477cc484ad2ece7c737bcd6a042c16))
* **scoreboard:** draw Pareto score-cost chart (OME-923 part C) ([#791](https://github.com/ScreamingFace/screamingface/issues/791)) ([cf8d8ab](https://github.com/ScreamingFace/screamingface/commit/cf8d8ab054caa2a565a4a18c134eb3b3c048785e))
* **scoreboard:** fill the leaderboard board with ranked rows and core columns ([#569](https://github.com/ScreamingFace/screamingface/issues/569)) ([2a20c15](https://github.com/ScreamingFace/screamingface/commit/2a20c1540c925f53c280569c9eb8eaaade301b34))
* **scoreboard:** mark Pareto frontier rows ([#786](https://github.com/ScreamingFace/screamingface/issues/786)) ([d0e1d7d](https://github.com/ScreamingFace/screamingface/commit/d0e1d7dd6508cecdc5d0d4c6fe23aafbe124b1e8))
* **scoreboard:** publish only the local part of a submitter's email ([#602](https://github.com/ScreamingFace/screamingface/issues/602)) ([7c036d9](https://github.com/ScreamingFace/screamingface/commit/7c036d90e8f885237f4673e0fa85d9340a503f7f))
* **scoreboard:** rebuild leaderboard portal shell on SFDS v2 ([#558](https://github.com/ScreamingFace/screamingface/issues/558)) ([f43bd4a](https://github.com/ScreamingFace/screamingface/commit/f43bd4a8dc453c214838d28f5572fa759cc536ea))
* **scoreboard:** register DRACO, IFEval and HealthBench with revision identity ([#611](https://github.com/ScreamingFace/screamingface/issues/611)) ([e431b71](https://github.com/ScreamingFace/screamingface/commit/e431b71544ee89a65d3524ce141bfc3dacecad0f))
* **scoreboard:** rename the verification field to verified_by_screamingface ([#624](https://github.com/ScreamingFace/screamingface/issues/624)) ([d32ef0a](https://github.com/ScreamingFace/screamingface/commit/d32ef0ac81163d2c0942658095439509970ad61f))
* **scoreboard:** render benchmark explainer infographics on the portal ([fda71ce](https://github.com/ScreamingFace/screamingface/commit/fda71ced5b8e52b7a9525821680a855519cc6b18))
* **scoreboard:** render benchmark-native scores in the portal ([4259b7c](https://github.com/ScreamingFace/screamingface/commit/4259b7c198e6d5d81f95c41b671f9fb20225f07b))
* **scoreboard:** retire the legacy news demo benchmarks ([#726](https://github.com/ScreamingFace/screamingface/issues/726)) ([451dc1a](https://github.com/ScreamingFace/screamingface/commit/451dc1a8c592c76fe8079394d7fba8ee8e2a80e5))
* **scoreboard:** seed benchmark text from the Engine catalogue ([7e74662](https://github.com/ScreamingFace/screamingface/commit/7e74662c502033135f6277272a49eee207686919))
* **scoreboard:** seed benchmark text from the Engine catalogue ([9077ace](https://github.com/ScreamingFace/screamingface/commit/9077aceec461d6694c517266ae024915f55c9448))
* **scoreboard:** support private leaderboards ([#719](https://github.com/ScreamingFace/screamingface/issues/719)) ([21c17d5](https://github.com/ScreamingFace/screamingface/commit/21c17d531957307724a52bbf6e4c36d8b4a7830f))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/ScreamingFace/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* **screamingface-engine:** throttle the DRACO judge and retry transient failures ([8e03b96](https://github.com/ScreamingFace/screamingface/commit/8e03b96a60ba8e5e7fd6bccfdbb614ed5bd59160))


### Bug Fixes

* address Filip's PR [#626](https://github.com/ScreamingFace/screamingface/issues/626) review (both passes on bf7f12f) ([99ab98c](https://github.com/ScreamingFace/screamingface/commit/99ab98c3b76b509170cb9b13ef0b99fb211949a4))
* **ci:** publish to ghcr.io/screamingface after the org transfer ([#653](https://github.com/ScreamingFace/screamingface/issues/653)) ([9e05187](https://github.com/ScreamingFace/screamingface/commit/9e0518798dbff4c7c73014b4c5c4189d0de7dae5))
* **repo:** complete the org repoint sweep ([32a3868](https://github.com/ScreamingFace/screamingface/commit/32a3868a06a52716efaabe7b51c47aed9d704e4f))
* **scoreboard:** a benchmark without prose keeps its row ([c7416a8](https://github.com/ScreamingFace/screamingface/commit/c7416a82be571e76606ab0609b6c28ec515ede7c))
* **scoreboard:** call results reproducible, not rerunnable, on the masthead ([ae15b9c](https://github.com/ScreamingFace/screamingface/commit/ae15b9c56d52d8816760f894741551f035b8108e))
* **scoreboard:** cast Tortoise CharField reads at the Openness Literal boundaries ([#661](https://github.com/ScreamingFace/screamingface/issues/661)) ([19c8784](https://github.com/ScreamingFace/screamingface/commit/19c8784dc8907775b465430340d96442a4396aa7))
* **scoreboard:** close partial-run leaderboard follow-ups ([#820](https://github.com/ScreamingFace/screamingface/issues/820)) ([2b47ae3](https://github.com/ScreamingFace/screamingface/commit/2b47ae3cdbd9a6cccfac4e584e0c1c838f68028a))
* **scoreboard:** diagnose an auth-proxy sign-in page instead of falling back in silence ([20d8869](https://github.com/ScreamingFace/screamingface/commit/20d88690de382f04bff7e65975d02936f741c5c2))
* **scoreboard:** give the frontier and openness test helpers a benchmark revision ([#617](https://github.com/ScreamingFace/screamingface/issues/617)) ([f4684a8](https://github.com/ScreamingFace/screamingface/commit/f4684a833645480b443c33f1b623074a0f09baa8))
* **scoreboard:** keep partial runs out of the ranked leaderboard ([#785](https://github.com/ScreamingFace/screamingface/issues/785)) ([aed0724](https://github.com/ScreamingFace/screamingface/commit/aed0724991a1bd106da2a9ad4c395c55b796a8c2))
* **scoreboard:** make the single-copy promise hold when the Engine does not answer ([d34599d](https://github.com/ScreamingFace/screamingface/commit/d34599d3e38505e0832cd678cacac2c275600ed6))
* **scoreboard:** trim landing — drop stats strip + Dataset column ([#656](https://github.com/ScreamingFace/screamingface/issues/656)) ([6940205](https://github.com/ScreamingFace/screamingface/commit/6940205c8fda342902aa246cb5a5ffde3c4863e2))
* **screamingface:** point the runtime build hook at the renamed Engine ([b184878](https://github.com/ScreamingFace/screamingface/commit/b184878f924c74953d1984458cda1c648dd1879e))
* **screamingface:** seed the local board through the in-process Engine adapter ([00a3e5a](https://github.com/ScreamingFace/screamingface/commit/00a3e5a2896e0367122da3b68d80d4fedb4d56ae))


### Documentation

* repoint the remaining org references to ScreamingFace ([0379e66](https://github.com/ScreamingFace/screamingface/commit/0379e66d503a1e619acbde7faf1b005a20718678))
* **repo:** repoint the remaining OpenMined org references to ScreamingFace ([9e739a0](https://github.com/ScreamingFace/screamingface/commit/9e739a051cf6abf1778b39b57198f2ad75701205))
* **screamingface-engine:** update agent config, diagrams and stale paths ([1d2c047](https://github.com/ScreamingFace/screamingface/commit/1d2c047b2c522dee3df2dc9ea920d36f05584eea))
