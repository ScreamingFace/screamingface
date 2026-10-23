# Changelog

## [1.0.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-ui-v0.2.0...aigateway-ui-v1.0.0) (2026-10-23)


### ⚠ BREAKING CHANGES

* **aigateway:** GET/POST/PATCH/PUT/DELETE on /v1/auth/profiles, /v1/auth/{provider}/profiles[...] and /v1/admin/accounts/{account_id}/profiles[...] now answer 410.

### Features

* **aigateway-ui:** manage credentials through the pair-addressed connection API ([#1411](https://github.com/ScreamingFace/screamingface/issues/1411)) ([9be66ec](https://github.com/ScreamingFace/screamingface/commit/9be66ecb056aee1fc4ec1de6ec86404139dd0fc4))
* **aigateway:** point every re-auth URL at the Connection API ([#1432](https://github.com/ScreamingFace/screamingface/issues/1432)) ([59545b2](https://github.com/ScreamingFace/screamingface/commit/59545b20bb9696681034032b33bff11bf0a0b6c5))


### Refactors

* **aigateway:** retire the legacy Profile HTTP routes with a 410 (Stage E, E3) ([#1464](https://github.com/ScreamingFace/screamingface/issues/1464)) ([08f5343](https://github.com/ScreamingFace/screamingface/commit/08f5343171422f8a36da02d9bbe901ec73f3af6c))

## [0.2.0](https://github.com/OpenMined/screamingface/compare/aigateway-ui-v0.1.0...aigateway-ui-v0.2.0) (2026-08-04)


### Features

* admin console for gateway tenants and API-key credentials (OME-705) ([#451](https://github.com/OpenMined/screamingface/issues/451)) ([14d54f0](https://github.com/OpenMined/screamingface/commit/14d54f0a5eb1a8a272bce9a9d7804ae32783fd98))
* **aigateway-ui:** re-skin the admin console on ScreamingFace Design System v2 (OME-715, OME-716) ([#462](https://github.com/OpenMined/screamingface/issues/462)) ([e39f9fb](https://github.com/OpenMined/screamingface/commit/e39f9fbaec4827fe41a3bb9bd924e40b2e7eb2d2))
