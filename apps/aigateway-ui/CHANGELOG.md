# Changelog

## [1.0.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-ui-v0.2.0...aigateway-ui-v1.0.0) (2026-10-30)


### ⚠ BREAKING CHANGES

* **aigateway:** GET/POST/PATCH/PUT/DELETE on /v1/auth/profiles, /v1/auth/{provider}/profiles[...] and /v1/admin/accounts/{account_id}/profiles[...] now answer 410.

### Features

* admin cache-snapshot upload — gateway + console (OME-951) ([cf69fff](https://github.com/ScreamingFace/screamingface/commit/cf69fff81eb5f7e66da9ffbed6048b16a79d78c1))
* **aigateway-ui:** log one server-side line per BFF error and wire LOG_LEVEL ([883a071](https://github.com/ScreamingFace/screamingface/commit/883a071d963dcad308c66089bd8f9e392cc8f3ac))
* **aigateway-ui:** log one server-side line per BFF error and wire LOG_LEVEL (OME-943) ([e8d9ae3](https://github.com/ScreamingFace/screamingface/commit/e8d9ae32ea1aa4a7a712bc32962ea45c74d94aa0))
* **aigateway-ui:** manage credentials through the pair-addressed connection API ([#1411](https://github.com/ScreamingFace/screamingface/issues/1411)) ([9be66ec](https://github.com/ScreamingFace/screamingface/commit/9be66ecb056aee1fc4ec1de6ec86404139dd0fc4))
* **aigateway-ui:** response-cache console section ([0c8b360](https://github.com/ScreamingFace/screamingface/commit/0c8b360b6068f0e91d2c19e0f842e52dd3ae72f6))
* **aigateway-ui:** stop authoring saved profile defaults ([#1043](https://github.com/ScreamingFace/screamingface/issues/1043)) ([2183244](https://github.com/ScreamingFace/screamingface/commit/21832443f097285ffe26b005d547c0a4bd290558))
* **aigateway:** point every re-auth URL at the Connection API ([#1432](https://github.com/ScreamingFace/screamingface/issues/1432)) ([59545b2](https://github.com/ScreamingFace/screamingface/commit/59545b20bb9696681034032b33bff11bf0a0b6c5))
* **aigateway:** remove saved profile defaults ([#1061](https://github.com/ScreamingFace/screamingface/issues/1061)) ([e8c7d26](https://github.com/ScreamingFace/screamingface/commit/e8c7d262262e63970eb88624d32cda81274f19f9))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/ScreamingFace/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* standard metadata (cost, latency, tokens) on every cached response ([#930](https://github.com/ScreamingFace/screamingface/issues/930)) ([0d2c00f](https://github.com/ScreamingFace/screamingface/commit/0d2c00f829287b3d8fa1adc8dd380ff3e10b6b06))


### Bug Fixes

* **aigateway-ui:** raise server-action body limit for snapshot uploads ([2daf1c5](https://github.com/ScreamingFace/screamingface/commit/2daf1c55dc04c2db701c1f590d1572e8edce7a67))
* **aigateway-ui:** remove stale X-Profile guidance ([#1210](https://github.com/ScreamingFace/screamingface/issues/1210)) ([57e78d7](https://github.com/ScreamingFace/screamingface/commit/57e78d71a9582b238ac4fe7cf0f682cb012c06a2))
* **ci:** publish to ghcr.io/screamingface after the org transfer ([#653](https://github.com/ScreamingFace/screamingface/issues/653)) ([9e05187](https://github.com/ScreamingFace/screamingface/commit/9e0518798dbff4c7c73014b4c5c4189d0de7dae5))
* **repo:** complete the org repoint sweep ([32a3868](https://github.com/ScreamingFace/screamingface/commit/32a3868a06a52716efaabe7b51c47aed9d704e4f))


### Refactors

* **aigateway:** retire the legacy Profile HTTP routes with a 410 (Stage E, E3) ([#1464](https://github.com/ScreamingFace/screamingface/issues/1464)) ([08f5343](https://github.com/ScreamingFace/screamingface/commit/08f5343171422f8a36da02d9bbe901ec73f3af6c))


### Documentation

* **repo:** repoint the remaining OpenMined org references to ScreamingFace ([9e739a0](https://github.com/ScreamingFace/screamingface/commit/9e739a051cf6abf1778b39b57198f2ad75701205))
* **screamingface-engine:** update agent config, diagrams and stale paths ([1d2c047](https://github.com/ScreamingFace/screamingface/commit/1d2c047b2c522dee3df2dc9ea920d36f05584eea))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-ui-v0.1.0...aigateway-ui-v0.2.0) (2026-08-04)


### Features

* admin console for gateway tenants and API-key credentials (OME-705) ([#451](https://github.com/OpenMined/screamingface/issues/451)) ([14d54f0](https://github.com/OpenMined/screamingface/commit/14d54f0a5eb1a8a272bce9a9d7804ae32783fd98))
* **aigateway-ui:** re-skin the admin console on ScreamingFace Design System v2 (OME-715, OME-716) ([#462](https://github.com/OpenMined/screamingface/issues/462)) ([e39f9fb](https://github.com/OpenMined/screamingface/commit/e39f9fbaec4827fe41a3bb9bd924e40b2e7eb2d2))
