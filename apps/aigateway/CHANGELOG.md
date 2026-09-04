# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [0.3.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v0.3.0) (2026-09-04)


### Features

* admin cache-snapshot upload — gateway + console (OME-951) ([cf69fff](https://github.com/ScreamingFace/screamingface/commit/cf69fff81eb5f7e66da9ffbed6048b16a79d78c1))
* **aigateway:** add direct OpenAI API-key provider ([#630](https://github.com/ScreamingFace/screamingface/issues/630)) ([bab02e3](https://github.com/ScreamingFace/screamingface/commit/bab02e3e8aeea1a798e3f62750c197d59bffbe81))
* **aigateway:** add per-provider call usage accounting ([#567](https://github.com/ScreamingFace/screamingface/issues/567)) ([72b35d7](https://github.com/ScreamingFace/screamingface/commit/72b35d7c0527bc32ba76e7100a366e126e3a0414))
* **aigateway:** admin cache-snapshot upload — routes, runner, COPY/merge loader ([267da57](https://github.com/ScreamingFace/screamingface/commit/267da5700470301c212ad8645f185cc3be97b09d))
* **aigateway:** cache direct OpenAI responses ([#675](https://github.com/ScreamingFace/screamingface/issues/675)) ([13fa4ea](https://github.com/ScreamingFace/screamingface/commit/13fa4ea39a417fabe5d88e335018b3fb57fc05a6))
* **aigateway:** cache Hugging Face router responses ([#704](https://github.com/ScreamingFace/screamingface/issues/704)) ([637e93d](https://github.com/ScreamingFace/screamingface/commit/637e93d0f51190ca4e69ba5a5bb710f2a763b5c5))
* **aigateway:** discover OpenRouter models live ([#739](https://github.com/ScreamingFace/screamingface/issues/739)) ([cc9deb4](https://github.com/ScreamingFace/screamingface/commit/cc9deb4a6702e0eb546bbc04772cf7de7b4f4e8d))
* **aigateway:** expand HuggingFace + Anthropic model seeds with live-verified ids ([#583](https://github.com/ScreamingFace/screamingface/issues/583)) ([a0a1cb2](https://github.com/ScreamingFace/screamingface/commit/a0a1cb2a0262be375623f2a5819e28c963e42252))
* **aigateway:** expand OpenRouter model seed with 58 live-verified slugs ([#581](https://github.com/ScreamingFace/screamingface/issues/581)) ([59543a4](https://github.com/ScreamingFace/screamingface/commit/59543a44dabee60f3ecf56650540f1d943a8eb66))
* **aigateway:** log the concurrency limit applied per provider ([9689fac](https://github.com/ScreamingFace/screamingface/commit/9689fac4c8de7693f4e35c33ef01595e0402e1d4))
* **aigateway:** make web-search-backed requests cacheable ([74069f1](https://github.com/ScreamingFace/screamingface/commit/74069f164d7b858752a6a23ea5fb6d81fdee4a57))
* **aigateway:** register the open-weight notebook lineup members ([770257d](https://github.com/ScreamingFace/screamingface/commit/770257dccbb18fdbff596d903d9f6d3f93047f21))
* **aigateway:** stop forcing the OpenRouter web-search engine ([1d4c93d](https://github.com/ScreamingFace/screamingface/commit/1d4c93de6d06f0bdb99dc535078c84328f26c3d5))
* **aigateway:** validate reasoning_effort for the OpenRouter provider ([3812ba4](https://github.com/ScreamingFace/screamingface/commit/3812ba4ab56957ae014a1323ea68f449d3deb9d1))
* **aigateway:** weekly response-cache snapshot to Garage (OME-1021) ([#752](https://github.com/ScreamingFace/screamingface/issues/752)) ([64e5229](https://github.com/ScreamingFace/screamingface/commit/64e522949f0ccc9da7b3dd59f8ae399a11204eaa))
* **models:** register the HealthBench judge route openrouter/openai/gpt-5.4 ([3021a73](https://github.com/ScreamingFace/screamingface/commit/3021a7372ee50ab74e147b168ed61a02462ef194))
* run any OpenRouter model — dynamic admission at preflight ([#633](https://github.com/ScreamingFace/screamingface/issues/633)) ([3938f66](https://github.com/ScreamingFace/screamingface/commit/3938f66b8090af65547c09cd8020de8428dc4f9e))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/ScreamingFace/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* **url4-cloud:** add HealthBench challenge protocols ([3c0bef1](https://github.com/ScreamingFace/screamingface/commit/3c0bef18422b8bb4db7aaf2acff5b8facfcff193))
* **url4-cloud:** derive the web-search mechanism from the provider ([8059f7c](https://github.com/ScreamingFace/screamingface/commit/8059f7c321c10521f89a47ebc5354065cc105de7))


### Bug Fixes

* **aigateway:** cast Tortoise CharField reads at the Literal alias boundaries ([#662](https://github.com/ScreamingFace/screamingface/issues/662)) ([3427d46](https://github.com/ScreamingFace/screamingface/commit/3427d464b301467b898c98c1bb04317700abb3d1))
* **aigateway:** configurable componentLabel; refuse podLabels collision ([#796](https://github.com/ScreamingFace/screamingface/issues/796)) ([662897e](https://github.com/ScreamingFace/screamingface/commit/662897eb4b7d7bcc313ce26e8d26b632a4d6397e))
* **aigateway:** configure app logging so INFO records actually emit ([e0766e2](https://github.com/ScreamingFace/screamingface/commit/e0766e2299704a35bef67619caad6ab81c4f08cb))
* **aigateway:** map 402 to a dedicated insufficient-credits error ([7235dcf](https://github.com/ScreamingFace/screamingface/commit/7235dcfc1bc1985d95566aab9bc4888964b5755b))
* **aigateway:** map 402 to a dedicated insufficient-credits error ([b618597](https://github.com/ScreamingFace/screamingface/commit/b6185977624016b26f559ac09b67c3b2911f7357))
* **aigateway:** recover BYOK connection auth type ([#795](https://github.com/ScreamingFace/screamingface/issues/795)) ([c8bd6a6](https://github.com/ScreamingFace/screamingface/commit/c8bd6a6555e2b5c9d521aeaa8fa2e542a3417010))
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
