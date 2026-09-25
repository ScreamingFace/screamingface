# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [0.3.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v0.3.0) (2026-09-25)


### Features

* **aigateway:** cache Tavily retrieval results in the global cache ([#782](https://github.com/ScreamingFace/screamingface/issues/782)) ([0ddcab9](https://github.com/ScreamingFace/screamingface/commit/0ddcab948790cf5a448d630e429d6efc31ea6b61))
* **aigateway:** carry gateway_call_id on every log line ([#898](https://github.com/ScreamingFace/screamingface/issues/898)) ([802bed9](https://github.com/ScreamingFace/screamingface/commit/802bed9aeac74d6b297d4b3e8fd2897b91d2b172))
* **aigateway:** emit spans so the gateway appears as an OTel service ([#909](https://github.com/ScreamingFace/screamingface/issues/909)) ([79a949e](https://github.com/ScreamingFace/screamingface/commit/79a949e11da38791a3f2e26281b4abb1eb879874))
* **aigateway:** expose execution access in model discovery ([#932](https://github.com/ScreamingFace/screamingface/issues/932)) ([ba9049b](https://github.com/ScreamingFace/screamingface/commit/ba9049bc638ce1a4daae94fd25870b910ed35c7e))
* **aigateway:** join the inbound traceparent to the log context ([#902](https://github.com/ScreamingFace/screamingface/issues/902)) ([5ecac45](https://github.com/ScreamingFace/screamingface/commit/5ecac451f659e5de031a5020f21450a44b5c7a8d))
* **aigateway:** move provider-access backing toward connections ([#1029](https://github.com/ScreamingFace/screamingface/issues/1029)) ([7cff8a5](https://github.com/ScreamingFace/screamingface/commit/7cff8a569cb2b958b455a91bc4723efc929f5773))
* **aigateway:** publish the caller-scoped provider-access availability listing ([#1006](https://github.com/ScreamingFace/screamingface/issues/1006)) ([2da4589](https://github.com/ScreamingFace/screamingface/commit/2da458968400150bfca5f4744e12b0a738deaba7))
* **aigateway:** put the Profile management routes behind the provider-credential admin boundary ([#992](https://github.com/ScreamingFace/screamingface/issues/992)) ([a78d58d](https://github.com/ScreamingFace/screamingface/commit/a78d58da14403b2fd21a889f898a535f4c5ce877))
* **aigateway:** remove saved profile defaults ([#1061](https://github.com/ScreamingFace/screamingface/issues/1061)) ([e8c7d26](https://github.com/ScreamingFace/screamingface/commit/e8c7d262262e63970eb88624d32cda81274f19f9))
* **aigateway:** ship the OTLP endpoint and credential through the chart ([#919](https://github.com/ScreamingFace/screamingface/issues/919)) ([b93cde6](https://github.com/ScreamingFace/screamingface/commit/b93cde6d250c5728cd885e911ff00aa3570fb064))
* **engine:** cut the chart over to the worker pool and retire the Job adapter ([#822](https://github.com/ScreamingFace/screamingface/issues/822)) ([4cdfa92](https://github.com/ScreamingFace/screamingface/commit/4cdfa920db7ae40280b2f8b9cc7c0b27fbd9ab7e))
* standard metadata (cost, latency, tokens) on every cached response ([#930](https://github.com/ScreamingFace/screamingface/issues/930)) ([0d2c00f](https://github.com/ScreamingFace/screamingface/commit/0d2c00f829287b3d8fa1adc8dd380ff3e10b6b06))


### Bug Fixes

* **aigateway:** configurable componentLabel; refuse podLabels collision ([#796](https://github.com/ScreamingFace/screamingface/issues/796)) ([662897e](https://github.com/ScreamingFace/screamingface/commit/662897eb4b7d7bcc313ce26e8d26b632a4d6397e))
* **aigateway:** recover BYOK connection auth type ([#795](https://github.com/ScreamingFace/screamingface/issues/795)) ([c8bd6a6](https://github.com/ScreamingFace/screamingface/commit/c8bd6a6555e2b5c9d521aeaa8fa2e542a3417010))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([75f1b99](https://github.com/ScreamingFace/screamingface/commit/75f1b994bbecc7f3baee3e08f4b9f3e2347ac4a5))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([44807b6](https://github.com/ScreamingFace/screamingface/commit/44807b63e8f034b4364ec4efb8d2fc496a1a0814))
* **aigateway:** strip new LiteLLM 1.100.0 dynamic callback params ([#903](https://github.com/ScreamingFace/screamingface/issues/903)) ([f31084a](https://github.com/ScreamingFace/screamingface/commit/f31084a52fff5db6964ab296324cb37379d56150))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-v0.1.0...aigateway-v0.2.0) (2026-05-11)


### Features

* **SF-138:** scaffold apps/aigateway/ standalone LiteLLM-compatible service ([#122](https://github.com/OpenMined/screamingface/issues/122)) ([3a66bf9](https://github.com/OpenMined/screamingface/commit/3a66bf9269f20848b7bc3fadca5809527b7bb901))


### Bug Fixes

* **ci:** correct release-please tag separator + enable workflow chain ([#154](https://github.com/OpenMined/screamingface/issues/154)) ([c51abc3](https://github.com/OpenMined/screamingface/commit/c51abc3ecae2028d9a333bf6b5881f8d8b3dc7d8))

## [Unreleased]

## [0.1.0]

- Initial release.
