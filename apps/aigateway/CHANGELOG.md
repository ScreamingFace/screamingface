# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [0.3.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v0.3.0) (2026-09-12)


### Features

* admin cache-snapshot upload — gateway + console (OME-951) ([cf69fff](https://github.com/ScreamingFace/screamingface/commit/cf69fff81eb5f7e66da9ffbed6048b16a79d78c1))
* **aigateway:** add direct OpenAI API-key provider ([#630](https://github.com/ScreamingFace/screamingface/issues/630)) ([bab02e3](https://github.com/ScreamingFace/screamingface/commit/bab02e3e8aeea1a798e3f62750c197d59bffbe81))
* **aigateway:** admin cache-snapshot upload — routes, runner, COPY/merge loader ([267da57](https://github.com/ScreamingFace/screamingface/commit/267da5700470301c212ad8645f185cc3be97b09d))
* **aigateway:** cache direct OpenAI responses ([#675](https://github.com/ScreamingFace/screamingface/issues/675)) ([13fa4ea](https://github.com/ScreamingFace/screamingface/commit/13fa4ea39a417fabe5d88e335018b3fb57fc05a6))
* **aigateway:** cache Hugging Face router responses ([#704](https://github.com/ScreamingFace/screamingface/issues/704)) ([637e93d](https://github.com/ScreamingFace/screamingface/commit/637e93d0f51190ca4e69ba5a5bb710f2a763b5c5))
* **aigateway:** cache Tavily retrieval results in the global cache ([#782](https://github.com/ScreamingFace/screamingface/issues/782)) ([0ddcab9](https://github.com/ScreamingFace/screamingface/commit/0ddcab948790cf5a448d630e429d6efc31ea6b61))
* **aigateway:** carry gateway_call_id on every log line ([#898](https://github.com/ScreamingFace/screamingface/issues/898)) ([802bed9](https://github.com/ScreamingFace/screamingface/commit/802bed9aeac74d6b297d4b3e8fd2897b91d2b172))
* **aigateway:** discover OpenRouter models live ([#739](https://github.com/ScreamingFace/screamingface/issues/739)) ([cc9deb4](https://github.com/ScreamingFace/screamingface/commit/cc9deb4a6702e0eb546bbc04772cf7de7b4f4e8d))
* **aigateway:** emit spans so the gateway appears as an OTel service ([#909](https://github.com/ScreamingFace/screamingface/issues/909)) ([79a949e](https://github.com/ScreamingFace/screamingface/commit/79a949e11da38791a3f2e26281b4abb1eb879874))
* **aigateway:** join the inbound traceparent to the log context ([#902](https://github.com/ScreamingFace/screamingface/issues/902)) ([5ecac45](https://github.com/ScreamingFace/screamingface/commit/5ecac451f659e5de031a5020f21450a44b5c7a8d))
* **aigateway:** log the concurrency limit applied per provider ([9689fac](https://github.com/ScreamingFace/screamingface/commit/9689fac4c8de7693f4e35c33ef01595e0402e1d4))
* **aigateway:** validate reasoning_effort for the OpenRouter provider ([3812ba4](https://github.com/ScreamingFace/screamingface/commit/3812ba4ab56957ae014a1323ea68f449d3deb9d1))
* **aigateway:** weekly response-cache snapshot to Garage (OME-1021) ([#752](https://github.com/ScreamingFace/screamingface/issues/752)) ([64e5229](https://github.com/ScreamingFace/screamingface/commit/64e522949f0ccc9da7b3dd59f8ae399a11204eaa))
* **engine:** cut the chart over to the worker pool and retire the Job adapter ([#822](https://github.com/ScreamingFace/screamingface/issues/822)) ([4cdfa92](https://github.com/ScreamingFace/screamingface/commit/4cdfa920db7ae40280b2f8b9cc7c0b27fbd9ab7e))
* run any OpenRouter model — dynamic admission at preflight ([#633](https://github.com/ScreamingFace/screamingface/issues/633)) ([3938f66](https://github.com/ScreamingFace/screamingface/commit/3938f66b8090af65547c09cd8020de8428dc4f9e))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/ScreamingFace/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))


### Bug Fixes

* **aigateway:** cast Tortoise CharField reads at the Literal alias boundaries ([#662](https://github.com/ScreamingFace/screamingface/issues/662)) ([3427d46](https://github.com/ScreamingFace/screamingface/commit/3427d464b301467b898c98c1bb04317700abb3d1))
* **aigateway:** configurable componentLabel; refuse podLabels collision ([#796](https://github.com/ScreamingFace/screamingface/issues/796)) ([662897e](https://github.com/ScreamingFace/screamingface/commit/662897eb4b7d7bcc313ce26e8d26b632a4d6397e))
* **aigateway:** configure app logging so INFO records actually emit ([e0766e2](https://github.com/ScreamingFace/screamingface/commit/e0766e2299704a35bef67619caad6ab81c4f08cb))
* **aigateway:** map 402 to a dedicated insufficient-credits error ([7235dcf](https://github.com/ScreamingFace/screamingface/commit/7235dcfc1bc1985d95566aab9bc4888964b5755b))
* **aigateway:** map 402 to a dedicated insufficient-credits error ([b618597](https://github.com/ScreamingFace/screamingface/commit/b6185977624016b26f559ac09b67c3b2911f7357))
* **aigateway:** recover BYOK connection auth type ([#795](https://github.com/ScreamingFace/screamingface/issues/795)) ([c8bd6a6](https://github.com/ScreamingFace/screamingface/commit/c8bd6a6555e2b5c9d521aeaa8fa2e542a3417010))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([75f1b99](https://github.com/ScreamingFace/screamingface/commit/75f1b994bbecc7f3baee3e08f4b9f3e2347ac4a5))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([44807b6](https://github.com/ScreamingFace/screamingface/commit/44807b63e8f034b4364ec4efb8d2fc496a1a0814))
* **ci:** publish to ghcr.io/screamingface after the org transfer ([#653](https://github.com/ScreamingFace/screamingface/issues/653)) ([9e05187](https://github.com/ScreamingFace/screamingface/commit/9e0518798dbff4c7c73014b4c5c4189d0de7dae5))
* **py-screamingface:** raise local stack openrouter gateway concurrency to 32 ([25851fd](https://github.com/ScreamingFace/screamingface/commit/25851fdfa7a2ca50922b81a4dfc36da2febf67d9))
* **repo:** complete the org repoint sweep ([32a3868](https://github.com/ScreamingFace/screamingface/commit/32a3868a06a52716efaabe7b51c47aed9d704e4f))


### Documentation

* **repo:** repoint the remaining OpenMined org references to ScreamingFace ([9e739a0](https://github.com/ScreamingFace/screamingface/commit/9e739a051cf6abf1778b39b57198f2ad75701205))
* **screamingface-engine:** update agent config, diagrams and stale paths ([1d2c047](https://github.com/ScreamingFace/screamingface/commit/1d2c047b2c522dee3df2dc9ea920d36f05584eea))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-v0.1.0...aigateway-v0.2.0) (2026-05-11)


### Features

* **SF-138:** scaffold apps/aigateway/ standalone LiteLLM-compatible service ([#122](https://github.com/OpenMined/screamingface/issues/122)) ([3a66bf9](https://github.com/OpenMined/screamingface/commit/3a66bf9269f20848b7bc3fadca5809527b7bb901))


### Bug Fixes

* **ci:** correct release-please tag separator + enable workflow chain ([#154](https://github.com/OpenMined/screamingface/issues/154)) ([c51abc3](https://github.com/OpenMined/screamingface/commit/c51abc3ecae2028d9a333bf6b5881f8d8b3dc7d8))

## [Unreleased]

## [0.1.0]

- Initial release.
