# Changelog

## [1.5.1](https://github.com/ScreamingFace/screamingface/compare/url4-v1.5.0...url4-v1.5.1) (2026-08-27)


### Bug Fixes

* **screamingface-engine:** preserve upstream grading errors instead of masking them (OME-924) ([3e12e21](https://github.com/ScreamingFace/screamingface/commit/3e12e2186aedfe9f2784d1a5acf74c4c9b6e5791))
* **screamingface-engine:** reconcile OME-993 with OME-924's fail-fast grading ([6786aef](https://github.com/ScreamingFace/screamingface/commit/6786aefdff4c0161d7604e2d59b71fedd7c069fa))
* **screamingface-engine:** surface the real judge failure instead of an envelope error ([b53ccfe](https://github.com/ScreamingFace/screamingface/commit/b53ccfedff1465dd8c8e7abbd9febd345eee7ea1))
* **url4:** preserve code and retryable in collected error payloads ([e102c9a](https://github.com/ScreamingFace/screamingface/commit/e102c9a0ff12430383b1cd15840178aec99829d1))
* **url4:** preserve remote span authority ([8c7c8bf](https://github.com/ScreamingFace/screamingface/commit/8c7c8bf9e4aeb1b99fbf90235762c8042348cf34))
* **url4:** report relative routes in span names ([3e3da86](https://github.com/ScreamingFace/screamingface/commit/3e3da86ee6605cbd0da93736f14bbe9c3e7b1377))
* **url4:** report relative routes in span names ([34cea42](https://github.com/ScreamingFace/screamingface/commit/34cea424b4fc1f5bd7735a30f8311c6b8abc9ecc))


### Refactors

* **url4:** keep route span detail minimal ([e0c7ac5](https://github.com/ScreamingFace/screamingface/commit/e0c7ac504d7a25f2dce75ac8bcc431e3ce806f83))

## [1.5.0](https://github.com/OpenMined/screamingface/compare/url4-v1.4.1...url4-v1.5.0) (2026-08-19)


### Features

* deliver large Evaluation results in full instead of cutting them off at 1 MiB ([0712043](https://github.com/OpenMined/screamingface/commit/07120439865973cff99c5c280fc990bf9b5cb0d0))
* report real run cost from provider-authored OpenRouter evidence ([05d85f1](https://github.com/OpenMined/screamingface/commit/05d85f1fb136b24c8d8b43f4bf656e6c93a93f20))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/OpenMined/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* **url4:** allow a total-only cost and widen the usage seam ([f51d3d3](https://github.com/OpenMined/screamingface/commit/f51d3d37d6d82717687d2be5829fcb0c4739d35c))
* **url4:** result frames carry an inline body or an artifact claim ticket ([63cbf96](https://github.com/OpenMined/screamingface/commit/63cbf96f7a65872aa38fe73aed8fa51c1874cc74))


### Documentation

* **screamingface-engine:** update agent config, diagrams and stale paths ([1d2c047](https://github.com/OpenMined/screamingface/commit/1d2c047b2c522dee3df2dc9ea920d36f05584eea))

## [1.4.1](https://github.com/OpenMined/screamingface/compare/url4-v1.4.0...url4-v1.4.1) (2026-08-12)


### Documentation

* additively refresh repo READMEs — product framing + doc links ([c41c3b5](https://github.com/OpenMined/screamingface/commit/c41c3b5813014020b424aab10bd94648a807f361))
* additively refresh repo READMEs — product framing + doc links ([bed4b12](https://github.com/OpenMined/screamingface/commit/bed4b121a4c0569bb31923a258feb0dcbefa3325))

## [1.4.0](https://github.com/OpenMined/screamingface/compare/url4-v1.3.0...url4-v1.4.0) (2026-08-10)


### Features

* **url4:** per-run cache policy for the aigateway global response cache ([#518](https://github.com/OpenMined/screamingface/issues/518)) ([245e0a4](https://github.com/OpenMined/screamingface/commit/245e0a478d0c4d7635a90cf06a50b5b2ddf37d93))

## [1.3.0](https://github.com/OpenMined/screamingface/compare/url4-v1.2.0...url4-v1.3.0) (2026-08-06)


### Features

* **url4:** add benchmark runtime foundations ([1d6ca0c](https://github.com/OpenMined/screamingface/commit/1d6ca0c75c6684e37834035231d849d73c7fef82))
* **url4:** let a command route take the intent on stdin ([1eef717](https://github.com/OpenMined/screamingface/commit/1eef7179605baa7e208a88b62f9bab094fa00788))


### Bug Fixes

* **url4:** report the model that actually served a call ([7980f36](https://github.com/OpenMined/screamingface/commit/7980f364af969fd257c731ad1cf28386e1fdfe78))
* **url4:** the AST path wires outer bindings into an iteration body too ([a4a5a2c](https://github.com/OpenMined/screamingface/commit/a4a5a2c61e6bc730b2a30f05485c04793d24382d))
* **url4:** wire outer scope bindings into iteration bodies ([84f9d38](https://github.com/OpenMined/screamingface/commit/84f9d38ebf13ae3791e7871fb0447c48bc81f989))


### Refactors

* **url4:** the AST reference walk reads the reserved row names too ([238c51c](https://github.com/OpenMined/screamingface/commit/238c51c879fba569c59bd52bd10e9e2de2e55419))

## [1.2.0](https://github.com/OpenMined/screamingface/compare/url4-v1.1.0...url4-v1.2.0) (2026-08-05)


### Features

* **url4-cloud:** capture finish_reason and refusal, classify a refused turn ([#506](https://github.com/OpenMined/screamingface/issues/506)) ([b594d6f](https://github.com/OpenMined/screamingface/commit/b594d6fcc11b10c4593d1fbe4d95ab3c7adc4bc1))
* **url4:** add a ModelResponse observation event and its ctx-less sink ([#488](https://github.com/OpenMined/screamingface/issues/488)) ([b787cf5](https://github.com/OpenMined/screamingface/commit/b787cf5d63ab364928229723adfc7655d220a779))

## [1.1.0](https://github.com/OpenMined/screamingface/compare/url4-v1.0.0...url4-v1.1.0) (2026-07-31)


### Features

* **url4-cloud:** url4 engine integration — backend/runner/shared split, observer seam, local mode ([#425](https://github.com/OpenMined/screamingface/issues/425)) ([ac888c5](https://github.com/OpenMined/screamingface/commit/ac888c5c5a56fb92b36760675c0cce8fcafc144c))

## [1.0.0](https://github.com/OpenMined/screamingface/compare/url4-v0.1.0...url4-v1.0.0) (2026-07-27)


### ⚠ BREAKING CHANGES

* **url4:** url4 serve/eval CLI — commands, read registries, path-qualified @ (OME-466) ([#402](https://github.com/OpenMined/screamingface/issues/402))

### Features

* **url4:** url4 serve/eval CLI — commands, read registries, path-qualified @ (OME-466) ([#402](https://github.com/OpenMined/screamingface/issues/402)) ([5d8a701](https://github.com/OpenMined/screamingface/commit/5d8a701a77b22b4e975138a7299b505d3225df19))

## 0.1.0 (2026-07-15)


### Features

* **url4:** package v1 SDK ([#389](https://github.com/OpenMined/screamingface/issues/389)) ([56f932b](https://github.com/OpenMined/screamingface/commit/56f932b61dd0e3bee8532c68914d4fbb07947b5d))
