# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [1.0.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v1.0.0) (2026-10-02)


### ⚠ BREAKING CHANGES

* **aigateway:** reject explicit profile selectors ([#1114](https://github.com/ScreamingFace/screamingface/issues/1114))

### Features

* **aigateway:** drop health-check probe server spans before export ([c1687f1](https://github.com/ScreamingFace/screamingface/commit/c1687f1dbf83edef81607c37f03a2753ef2a4c32))
* **aigateway:** drop health-check probe server spans before export (OME-1217) ([1305a07](https://github.com/ScreamingFace/screamingface/commit/1305a07b3f20529733362f4744dcf66712e3437d))
* **aigateway:** log an unhandled exception once, by class name, with its call id ([db6757b](https://github.com/ScreamingFace/screamingface/commit/db6757bc56a7f6b49b38ae16e7059c06a55cda3f))
* **aigateway:** log an unhandled exception once, by class name, with its call id ([2ba9b6c](https://github.com/ScreamingFace/screamingface/commit/2ba9b6caed867ab04d04f397a5f560ca794e6f87))
* **aigateway:** move provider-access backing toward connections ([#1029](https://github.com/ScreamingFace/screamingface/issues/1029)) ([7cff8a5](https://github.com/ScreamingFace/screamingface/commit/7cff8a569cb2b958b455a91bc4723efc929f5773))
* **aigateway:** publish the caller-scoped provider-access availability listing ([#1006](https://github.com/ScreamingFace/screamingface/issues/1006)) ([2da4589](https://github.com/ScreamingFace/screamingface/commit/2da458968400150bfca5f4744e12b0a738deaba7))
* **aigateway:** put the Profile management routes behind the provider-credential admin boundary ([#992](https://github.com/ScreamingFace/screamingface/issues/992)) ([a78d58d](https://github.com/ScreamingFace/screamingface/commit/a78d58da14403b2fd21a889f898a535f4c5ce877))
* **aigateway:** reject explicit profile selectors ([#1114](https://github.com/ScreamingFace/screamingface/issues/1114)) ([3083640](https://github.com/ScreamingFace/screamingface/commit/3083640b6be5d67b909d93643c6878d5fe67e318))
* **aigateway:** remove saved profile defaults ([#1061](https://github.com/ScreamingFace/screamingface/issues/1061)) ([e8c7d26](https://github.com/ScreamingFace/screamingface/commit/e8c7d262262e63970eb88624d32cda81274f19f9))
* **aigateway:** return full cache metadata on hits and pin the cross-stack hit contract ([#1100](https://github.com/ScreamingFace/screamingface/issues/1100)) ([16bb09a](https://github.com/ScreamingFace/screamingface/commit/16bb09ae38a73eed25576763ba5a73ed65729f0e))


### Bug Fixes

* **aigateway:** log one attributable record for every dispatch failure ([d92fc6e](https://github.com/ScreamingFace/screamingface/commit/d92fc6e2907db7d05d35adc1a23e2f6aacd03621))
* **aigateway:** log one attributable record for every dispatch failure (OME-968) ([52117d4](https://github.com/ScreamingFace/screamingface/commit/52117d44c9cf2c9d3e1353b6c06f3dffadd0b4cf))
* **aigateway:** name the catch-all 500 gateway_internal_error ([722d53a](https://github.com/ScreamingFace/screamingface/commit/722d53aba64d30448ea2ff2bf1c1d443ed501c85))
* **aigateway:** re-verify the LiteLLM runtime guard against 1.102.0 ([#1118](https://github.com/ScreamingFace/screamingface/issues/1118)) ([d35a465](https://github.com/ScreamingFace/screamingface/commit/d35a465374a1abe20b533bd5236cf6a8a567514b))
* **aigateway:** read probe-span exclusion from AIGW_TRACE_EXCLUDED_ROUTES ([3d74ab1](https://github.com/ScreamingFace/screamingface/commit/3d74ab1ddb64bc01612ebe74bbba5325503ecf34))
* **aigateway:** read probe-span exclusion from AIGW_TRACE_EXCLUDED_ROUTES (OME-1453) ([e155609](https://github.com/ScreamingFace/screamingface/commit/e1556093202e154589638ae0377b88513e4e6826))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-v0.1.0...aigateway-v0.2.0) (2026-05-11)


### Features

* **SF-138:** scaffold apps/aigateway/ standalone LiteLLM-compatible service ([#122](https://github.com/OpenMined/screamingface/issues/122)) ([3a66bf9](https://github.com/OpenMined/screamingface/commit/3a66bf9269f20848b7bc3fadca5809527b7bb901))


### Bug Fixes

* **ci:** correct release-please tag separator + enable workflow chain ([#154](https://github.com/OpenMined/screamingface/issues/154)) ([c51abc3](https://github.com/OpenMined/screamingface/commit/c51abc3ecae2028d9a333bf6b5881f8d8b3dc7d8))

## [Unreleased]

## [0.1.0]

- Initial release.
