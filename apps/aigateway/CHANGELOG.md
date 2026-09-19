# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [0.3.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v0.3.0) (2026-09-19)


### Features

* admin cache-snapshot upload — gateway + console (OME-951) ([cf69fff](https://github.com/ScreamingFace/screamingface/commit/cf69fff81eb5f7e66da9ffbed6048b16a79d78c1))
* **aigateway:** admin cache-snapshot upload — routes, runner, COPY/merge loader ([267da57](https://github.com/ScreamingFace/screamingface/commit/267da5700470301c212ad8645f185cc3be97b09d))
* **aigateway:** cache Hugging Face router responses ([#704](https://github.com/ScreamingFace/screamingface/issues/704)) ([637e93d](https://github.com/ScreamingFace/screamingface/commit/637e93d0f51190ca4e69ba5a5bb710f2a763b5c5))
* **aigateway:** cache Tavily retrieval results in the global cache ([#782](https://github.com/ScreamingFace/screamingface/issues/782)) ([0ddcab9](https://github.com/ScreamingFace/screamingface/commit/0ddcab948790cf5a448d630e429d6efc31ea6b61))
* **aigateway:** carry gateway_call_id on every log line ([#898](https://github.com/ScreamingFace/screamingface/issues/898)) ([802bed9](https://github.com/ScreamingFace/screamingface/commit/802bed9aeac74d6b297d4b3e8fd2897b91d2b172))
* **aigateway:** discover OpenRouter models live ([#739](https://github.com/ScreamingFace/screamingface/issues/739)) ([cc9deb4](https://github.com/ScreamingFace/screamingface/commit/cc9deb4a6702e0eb546bbc04772cf7de7b4f4e8d))
* **aigateway:** emit spans so the gateway appears as an OTel service ([#909](https://github.com/ScreamingFace/screamingface/issues/909)) ([79a949e](https://github.com/ScreamingFace/screamingface/commit/79a949e11da38791a3f2e26281b4abb1eb879874))
* **aigateway:** expose execution access in model discovery ([#932](https://github.com/ScreamingFace/screamingface/issues/932)) ([ba9049b](https://github.com/ScreamingFace/screamingface/commit/ba9049bc638ce1a4daae94fd25870b910ed35c7e))
* **aigateway:** join the inbound traceparent to the log context ([#902](https://github.com/ScreamingFace/screamingface/issues/902)) ([5ecac45](https://github.com/ScreamingFace/screamingface/commit/5ecac451f659e5de031a5020f21450a44b5c7a8d))
* **aigateway:** ship the OTLP endpoint and credential through the chart ([#919](https://github.com/ScreamingFace/screamingface/issues/919)) ([b93cde6](https://github.com/ScreamingFace/screamingface/commit/b93cde6d250c5728cd885e911ff00aa3570fb064))
* **aigateway:** validate reasoning_effort for the OpenRouter provider ([3812ba4](https://github.com/ScreamingFace/screamingface/commit/3812ba4ab56957ae014a1323ea68f449d3deb9d1))
* **aigateway:** weekly response-cache snapshot to Garage (OME-1021) ([#752](https://github.com/ScreamingFace/screamingface/issues/752)) ([64e5229](https://github.com/ScreamingFace/screamingface/commit/64e522949f0ccc9da7b3dd59f8ae399a11204eaa))
* **engine:** cut the chart over to the worker pool and retire the Job adapter ([#822](https://github.com/ScreamingFace/screamingface/issues/822)) ([4cdfa92](https://github.com/ScreamingFace/screamingface/commit/4cdfa920db7ae40280b2f8b9cc7c0b27fbd9ab7e))
* standard metadata (cost, latency, tokens) on every cached response ([#930](https://github.com/ScreamingFace/screamingface/issues/930)) ([0d2c00f](https://github.com/ScreamingFace/screamingface/commit/0d2c00f829287b3d8fa1adc8dd380ff3e10b6b06))


### Bug Fixes

* **aigateway:** configurable componentLabel; refuse podLabels collision ([#796](https://github.com/ScreamingFace/screamingface/issues/796)) ([662897e](https://github.com/ScreamingFace/screamingface/commit/662897eb4b7d7bcc313ce26e8d26b632a4d6397e))
* **aigateway:** recover BYOK connection auth type ([#795](https://github.com/ScreamingFace/screamingface/issues/795)) ([c8bd6a6](https://github.com/ScreamingFace/screamingface/commit/c8bd6a6555e2b5c9d521aeaa8fa2e542a3417010))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([75f1b99](https://github.com/ScreamingFace/screamingface/commit/75f1b994bbecc7f3baee3e08f4b9f3e2347ac4a5))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([44807b6](https://github.com/ScreamingFace/screamingface/commit/44807b63e8f034b4364ec4efb8d2fc496a1a0814))
* **aigateway:** strip new LiteLLM 1.100.0 dynamic callback params ([#903](https://github.com/ScreamingFace/screamingface/issues/903)) ([f31084a](https://github.com/ScreamingFace/screamingface/commit/f31084a52fff5db6964ab296324cb37379d56150))
* **repo:** complete the org repoint sweep ([32a3868](https://github.com/ScreamingFace/screamingface/commit/32a3868a06a52716efaabe7b51c47aed9d704e4f))


### Documentation

* **repo:** repoint the remaining OpenMined org references to ScreamingFace ([9e739a0](https://github.com/ScreamingFace/screamingface/commit/9e739a051cf6abf1778b39b57198f2ad75701205))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-v0.1.0...aigateway-v0.2.0) (2026-05-11)


### Features

* **SF-138:** scaffold apps/aigateway/ standalone LiteLLM-compatible service ([#122](https://github.com/OpenMined/screamingface/issues/122)) ([3a66bf9](https://github.com/OpenMined/screamingface/commit/3a66bf9269f20848b7bc3fadca5809527b7bb901))


### Bug Fixes

* **ci:** correct release-please tag separator + enable workflow chain ([#154](https://github.com/OpenMined/screamingface/issues/154)) ([c51abc3](https://github.com/OpenMined/screamingface/commit/c51abc3ecae2028d9a333bf6b5881f8d8b3dc7d8))

## [Unreleased]

## [0.1.0]

- Initial release.
