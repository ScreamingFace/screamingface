# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [0.3.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.1...aigateway-v0.3.0) (2026-10-17)


### Features

* **aigateway:** add pair-addressed admin PUT and DELETE through the mutation bridge ([#1404](https://github.com/ScreamingFace/screamingface/issues/1404)) ([#1405](https://github.com/ScreamingFace/screamingface/issues/1405)) ([e79db82](https://github.com/ScreamingFace/screamingface/commit/e79db8205f6d345aa68853008562e0e3bc646045))
* **aigateway:** enable local Fusion benchmark execution ([#1448](https://github.com/ScreamingFace/screamingface/issues/1448)) ([cddc9f5](https://github.com/ScreamingFace/screamingface/commit/cddc9f59d09cfc762f67fe5f21199dcf74dae338))
* **aigateway:** let a native connection repair a migrated pair's credential (Stage E, E1b) ([#1449](https://github.com/ScreamingFace/screamingface/issues/1449)) ([00c1bef](https://github.com/ScreamingFace/screamingface/commit/00c1bef11e673ce488538966e572cff5d9e08319))
* **aigateway:** list an account's provider credentials by pair (G1 1/3) ([#1397](https://github.com/ScreamingFace/screamingface/issues/1397)) ([1ed95ab](https://github.com/ScreamingFace/screamingface/commit/1ed95abdfb75c783117625d452573ac7090fcec9))
* **aigateway:** point every re-auth URL at the Connection API ([#1432](https://github.com/ScreamingFace/screamingface/issues/1432)) ([59545b2](https://github.com/ScreamingFace/screamingface/commit/59545b20bb9696681034032b33bff11bf0a0b6c5))
* **aigateway:** prove a legacy OAuth shadow by identity before PUT or DELETE (G1 3/3) ([#1408](https://github.com/ScreamingFace/screamingface/issues/1408)) ([3bfa2fd](https://github.com/ScreamingFace/screamingface/commit/3bfa2fd2439ed9e960b4d7440975b91e0f7f10ec))
* **aigateway:** relay the provider's sanitized error message (OME-1136) ([#1233](https://github.com/ScreamingFace/screamingface/issues/1233)) ([8d32145](https://github.com/ScreamingFace/screamingface/commit/8d32145515a4dcb35c56c7dabd9d814c1f90a1ee))
* **aigateway:** send images and PDFs natively to Gemini, Antigravity and Codex ([#1431](https://github.com/ScreamingFace/screamingface/issues/1431)) ([8c5b72b](https://github.com/ScreamingFace/screamingface/commit/8c5b72bd5786b254f141c40ffb4f1ac2d7ce70a9))


### Bug Fixes

* **aigateway:** check the pair before marking a Connection error (G0 3/3) ([#1396](https://github.com/ScreamingFace/screamingface/issues/1396)) ([123be84](https://github.com/ScreamingFace/screamingface/commit/123be8466eb10810263f33a0c935aca4c4c9819f))
* **aigateway:** keep dispatch failures at one record when the handler raises ([#1230](https://github.com/ScreamingFace/screamingface/issues/1230)) ([643a496](https://github.com/ScreamingFace/screamingface/commit/643a4961599c64445c7ccccdbb584309cb831fe6))
* **aigateway:** read litellm's bundled model list, never a download at start (OME-1615) ([0648030](https://github.com/ScreamingFace/screamingface/commit/0648030fa63a71041250f9034e4114a150554314))
* **aigateway:** read litellm's bundled model list, never a download at start (OME-1615) ([34fffb9](https://github.com/ScreamingFace/screamingface/commit/34fffb983bd1268f0c3098674c0028215fb153a4))
* raise the model-call budget to 30 minutes for long evaluations ([#1430](https://github.com/ScreamingFace/screamingface/issues/1430)) ([92645fe](https://github.com/ScreamingFace/screamingface/commit/92645fe66085733dc2a846fd86d1cc2f53e2330c))
* **sdk:** warn once at the caller's line for duplicate members and tighten samples validation ([1dabc4b](https://github.com/ScreamingFace/screamingface/commit/1dabc4ba2569d1abf3174783dd96d16b699b063d))


### Documentation

* **aigateway:** close OME-1541 ledger and mirror, correct the route-test ordering note ([#1437](https://github.com/ScreamingFace/screamingface/issues/1437)) ([8edd994](https://github.com/ScreamingFace/screamingface/commit/8edd994bff69a78b9d3a527335885dd403a0a151))
* **aigateway:** name the litellm check the model-map setting feeds (OME-1615) ([997cb4f](https://github.com/ScreamingFace/screamingface/commit/997cb4f9188cbd67a355d6de19c9535a1c3b0bc0))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-v0.1.0...aigateway-v0.2.0) (2026-05-11)


### Features

* **SF-138:** scaffold apps/aigateway/ standalone LiteLLM-compatible service ([#122](https://github.com/OpenMined/screamingface/issues/122)) ([3a66bf9](https://github.com/OpenMined/screamingface/commit/3a66bf9269f20848b7bc3fadca5809527b7bb901))


### Bug Fixes

* **ci:** correct release-please tag separator + enable workflow chain ([#154](https://github.com/OpenMined/screamingface/issues/154)) ([c51abc3](https://github.com/OpenMined/screamingface/commit/c51abc3ecae2028d9a333bf6b5881f8d8b3dc7d8))

## [Unreleased]

## [0.1.0]

- Initial release.
