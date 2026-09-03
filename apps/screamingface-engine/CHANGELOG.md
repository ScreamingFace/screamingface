# Changelog

## [1.5.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-engine-v1.4.0...screamingface-engine-v1.5.0) (2026-08-27)


### Features

* **screamingface-benchmarks:** GDPVal text subset ([454253d](https://github.com/ScreamingFace/screamingface/commit/454253da0034cabb1fce3cc50f07fe6ac63e818f))
* **screamingface-engine:** bake the GDPval text-subset cases and rubrics ([c5d4c22](https://github.com/ScreamingFace/screamingface/commit/c5d4c22e6faebcf8acafafe1499e23cadd084416))
* **screamingface-engine:** derive hosted provider availability ([690450b](https://github.com/ScreamingFace/screamingface/commit/690450bdeba89056d1f30bb1c01ccb60296e51a0))
* **screamingface-engine:** derive hosted provider availability ([15302ac](https://github.com/ScreamingFace/screamingface/commit/15302ac41e74197d766e3d8a91c214353b364431))
* **screamingface-engine:** flatten GDPval references to text at build time ([03d5766](https://github.com/ScreamingFace/screamingface/commit/03d576626dcfa92154e642af65045e92435a4f8a))
* **screamingface-engine:** freeze the GDPval text subset and its rubric filter ([d76184d](https://github.com/ScreamingFace/screamingface/commit/d76184dd73f2a21abc7ce77c437ff32b23a8e790))
* **screamingface-engine:** pin the GDPval judge and parse its verdicts ([7d9281c](https://github.com/ScreamingFace/screamingface/commit/7d9281cde7fd6348f24aa137f20cc148e4e58051))
* **screamingface-engine:** score GDPval cases as points earned over points winnable ([29a38ef](https://github.com/ScreamingFace/screamingface/commit/29a38ef41ad3266fe80c68e4f3008cb4b1f9d44b))
* **screamingface-engine:** serve the GDPval text subset as a registered board ([cd9814c](https://github.com/ScreamingFace/screamingface/commit/cd9814c0ee8fa0da6c581202bdb89bda7f72bf9a))
* **screamingface-engine:** throttle the DRACO judge and retry transient failures ([8e03b96](https://github.com/ScreamingFace/screamingface/commit/8e03b96a60ba8e5e7fd6bccfdbb614ed5bd59160))
* **screamingface-engine:** throttle the GDPval judge's thinking and double its verdict budget ([2adab76](https://github.com/ScreamingFace/screamingface/commit/2adab766a5397fcdbd76cf9656a70d5a74b802ee))
* **screamingface:** serve the live checkout from screamingface up and retire the justfile ([ee9b915](https://github.com/ScreamingFace/screamingface/commit/ee9b9156111cf63554423f6237f2f3f88c142cfb))


### Bug Fixes

* **engine:** apply scheduling to Runner Jobs ([0b6a970](https://github.com/ScreamingFace/screamingface/commit/0b6a970c1d7888acf51c7766cdc2cdfa7e9adb1a))
* **engine:** apply scheduling to Runner Jobs ([509b83d](https://github.com/ScreamingFace/screamingface/commit/509b83dc6c2b38d8c935268f6f0c3ab5ee457091))
* **engine:** halve default result inline cap for NATS envelope headroom ([f64d763](https://github.com/ScreamingFace/screamingface/commit/f64d7632b47cd34f60b4827efaa43415ce59db28))
* **engine:** halve default result inline cap for NATS envelope headroom ([a65be95](https://github.com/ScreamingFace/screamingface/commit/a65be95c8d437023d50482568c093f175db86e82))
* **screamingface-benchmarks:** catch three delivery phrasings the rubric filter waved through ([dd63d05](https://github.com/ScreamingFace/screamingface/commit/dd63d0549465b74e608cdf9b17b1e9f3d84daa0d))
* **screamingface-benchmarks:** close the say-less exploit on conditional rubric criteria ([c752c9a](https://github.com/ScreamingFace/screamingface/commit/c752c9aa38e59041f198168262e82b2f0ec15770))
* **screamingface-benchmarks:** harden GDPval per review — strict decode, atomic fetch, lean image ([58553fc](https://github.com/ScreamingFace/screamingface/commit/58553fcb17dc388049fcb9b7dc869665df0b75b3))
* **screamingface-benchmarks:** keep the GDPval judge's raw reply on valid verdicts ([4369571](https://github.com/ScreamingFace/screamingface/commit/436957108dc461520fd1db2a7901ebcd6bf99fb2))
* **screamingface-engine:** accept the GDPval judge's fenced JSON verdicts ([0f48a00](https://github.com/ScreamingFace/screamingface/commit/0f48a00b7750a346b2508cd375a4cc5632da998c))
* **screamingface-engine:** adapt the GDPval preparer to the auditable-asset contract ([4cabd25](https://github.com/ScreamingFace/screamingface/commit/4cabd253bad521d4bb9b34da27d83545b43b56be))
* **screamingface-engine:** fail fast benchmark grading fan-outs so upstream errors survive ([cea8d52](https://github.com/ScreamingFace/screamingface/commit/cea8d5297990408c0f4d31bca39c45928b00ed82))
* **screamingface-engine:** garage container needs an explicit command — the image has no Entrypoint ([3f680ca](https://github.com/ScreamingFace/screamingface/commit/3f680ca8369ec77d9a64084b34f3b07d2a7d094b))
* **screamingface-engine:** garage container needs an explicit command — the image has no Entrypoint ([f668dbf](https://github.com/ScreamingFace/screamingface/commit/f668dbfc9ac1e973d81b164b96be558906249cf6))
* **screamingface-engine:** install GDPval's parsers in the benchmark image build ([ade3edd](https://github.com/ScreamingFace/screamingface/commit/ade3eddaf92a7c83f53848bcd7c1e2fae55b4d07))
* **screamingface-engine:** make benchmark asset preparation auditable (OME-925) ([#677](https://github.com/ScreamingFace/screamingface/issues/677)) ([0077216](https://github.com/ScreamingFace/screamingface/commit/00772161f0d38a75822e0521eca2f177e54252d0))
* **screamingface-engine:** pin GDPval v2 and fetch its reference files ([69e0213](https://github.com/ScreamingFace/screamingface/commit/69e0213e25518d036b231b42253d5da8a75f12e4))
* **screamingface-engine:** preserve upstream grading errors instead of masking them (OME-924) ([3e12e21](https://github.com/ScreamingFace/screamingface/commit/3e12e2186aedfe9f2784d1a5acf74c4c9b6e5791))
* **screamingface-engine:** reconcile OME-993 with OME-924's fail-fast grading ([6786aef](https://github.com/ScreamingFace/screamingface/commit/6786aefdff4c0161d7604e2d59b71fedd7c069fa))
* **screamingface-engine:** reject hosted provider mutations ([2918a5e](https://github.com/ScreamingFace/screamingface/commit/2918a5e48ed1c9b0ba27ed520aceb1c00442b268))
* **screamingface-engine:** repair HealthBench preparation summary ([#720](https://github.com/ScreamingFace/screamingface/issues/720)) ([be66253](https://github.com/ScreamingFace/screamingface/commit/be662533b757e3cfa628ee80d56ff3b497801fd0))
* **screamingface-engine:** retry aigateway transport failures in grading ([#751](https://github.com/ScreamingFace/screamingface/issues/751)) ([c67d1b7](https://github.com/ScreamingFace/screamingface/commit/c67d1b7eec39228b9382721eee83c8f671a4a0ee))
* **screamingface-engine:** serialize benchmark cases ([105fa74](https://github.com/ScreamingFace/screamingface/commit/105fa749eeb805179502fc645fc9e7b0e88a7657))
* **screamingface-engine:** serialize benchmark cases ([8caaecb](https://github.com/ScreamingFace/screamingface/commit/8caaecb1857e06fb927ac915e10663806268db74))
* **screamingface-engine:** stop requiring every board's assets to run one benchmark ([0c3cfa0](https://github.com/ScreamingFace/screamingface/commit/0c3cfa0d9053bd488e158a8c5dae25633b175848))
* **screamingface-engine:** stop requiring every board's assets to run one benchmark ([4fb4b27](https://github.com/ScreamingFace/screamingface/commit/4fb4b27daf9e7d043c0648b17914129a4ec37508))
* **screamingface-engine:** surface the real judge failure instead of an envelope error ([b53ccfe](https://github.com/ScreamingFace/screamingface/commit/b53ccfedff1465dd8c8e7abbd9febd345eee7ea1))
* **screamingface:** keep provider bootstrap opt-in and harden the stack guards ([0e2af79](https://github.com/ScreamingFace/screamingface/commit/0e2af7935777b2bc6995deffd4e96dd2257ac0f2))


### Documentation

* **screamingface-engine:** explain GDPval's three grading layers in the board docstring ([76b9528](https://github.com/ScreamingFace/screamingface/commit/76b95287d1c55c6c61adaadb77e18b8967b6c3d4))

## [1.4.0](https://github.com/OpenMined/screamingface/compare/screamingface-engine-v1.3.0...screamingface-engine-v1.4.0) (2026-08-19)


### Features

* deliver large Evaluation results in full instead of cutting them off at 1 MiB ([0712043](https://github.com/OpenMined/screamingface/commit/07120439865973cff99c5c280fc990bf9b5cb0d0))
* **screamingface-engine:** content-addressed artifact store for spilled results ([81a2f66](https://github.com/OpenMined/screamingface/commit/81a2f6649e5b065044fbd3ad2fd21873ef4fecdd))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/OpenMined/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* **screamingface-engine:** rename the app, package and chart from url4-cloud ([9b88857](https://github.com/OpenMined/screamingface/commit/9b88857993753e775d1ebdb085f9e6d4064c505f))
* **screamingface-engine:** serve spilled results over REST with TTL-only cleanup ([b4a7823](https://github.com/OpenMined/screamingface/commit/b4a7823d1f6faa5c1cda6d933742fcbb5254c39c))
* **screamingface-engine:** spill or refuse oversized results instead of truncating ([dbdb838](https://github.com/OpenMined/screamingface/commit/dbdb8386c911a230fd2a6601b1eb897245eee6a0))
* **url4:** result frames carry an inline body or an artifact claim ticket ([63cbf96](https://github.com/OpenMined/screamingface/commit/63cbf96f7a65872aa38fe73aed8fa51c1874cc74))


### Bug Fixes

* **screamingface-engine:** restart a parcel's TTL clock on every dedup hit ([3e6aba9](https://github.com/OpenMined/screamingface/commit/3e6aba91199c142a6f4fa2bdc7b35c79a0bf34cb))

## [1.3.0](https://github.com/OpenMined/screamingface/compare/url4-cloud-v1.2.1...url4-cloud-v1.3.0) (2026-08-13)


### Features

* **url4-cloud:** enforce benchmark result contract ([3121933](https://github.com/OpenMined/screamingface/commit/3121933370f9837ef88e14a6561603d2dfd31c71))
* **url4-cloud:** enforce benchmark result contract ([b9e8eb8](https://github.com/OpenMined/screamingface/commit/b9e8eb8c0f7d006777fe927851068eca4d0e7893))


### Bug Fixes

* **url4-cloud:** complete benchmark result invariants ([529d779](https://github.com/OpenMined/screamingface/commit/529d7790b4ff91c745672fb28147bf7c78d5ef9c))
* **url4-cloud:** dedupe duplicate rubric judgements in HealthBench checks ([e7585cc](https://github.com/OpenMined/screamingface/commit/e7585cc200ff7c0b984e97fde69b3d9d2309445e))
* **url4-cloud:** retain malformed HealthBench evaluation rows as failed Cases ([90bd3f0](https://github.com/OpenMined/screamingface/commit/90bd3f008b18a401dfa8af4a9695352393f9b5fc))


### Refactors

* **url4-cloud:** extract benchmark evaluation capabilities ([17f7643](https://github.com/OpenMined/screamingface/commit/17f7643b99a9cf38615cde381584713414742d59))
* **url4-cloud:** extract benchmark evaluation capabilities ([3c295a3](https://github.com/OpenMined/screamingface/commit/3c295a3c9dc694a22d2ee5be186b462d5ac9cd9b))

## [1.2.1](https://github.com/OpenMined/screamingface/compare/url4-cloud-v1.2.0...url4-cloud-v1.2.1) (2026-08-12)


### Documentation

* additively refresh repo READMEs — product framing + doc links ([c41c3b5](https://github.com/OpenMined/screamingface/commit/c41c3b5813014020b424aab10bd94648a807f361))
* additively refresh repo READMEs — product framing + doc links ([bed4b12](https://github.com/OpenMined/screamingface/commit/bed4b121a4c0569bb31923a258feb0dcbefa3325))

## [1.2.0](https://github.com/OpenMined/screamingface/compare/url4-cloud-v1.1.0...url4-cloud-v1.2.0) (2026-08-10)


### Features

* **url4-cloud:** add engine benchmark foundation ([a888401](https://github.com/OpenMined/screamingface/commit/a888401267d561dd18a3a7402f0870f45a858f36))
* **url4-cloud:** add Engine benchmark foundation ([bff2b4e](https://github.com/OpenMined/screamingface/commit/bff2b4e8298e75239626641a08067dbbc216a716))
* **url4-cloud:** deploy DRACO benchmark protocol ([529f316](https://github.com/OpenMined/screamingface/commit/529f316611b8d515a76bc09af1955694ea8796ab))
* **url4-cloud:** deploy DRACO benchmark protocol ([2b2f264](https://github.com/OpenMined/screamingface/commit/2b2f264a26df8af7cab2272f00b6dc2898f41b43))
* **url4-cloud:** expose only executable models ([9a1ea5a](https://github.com/OpenMined/screamingface/commit/9a1ea5af0608cc0c6e8f62dd631eccc1751ad997))
* **url4-cloud:** expose only executable models ([08ac80d](https://github.com/OpenMined/screamingface/commit/08ac80d9790e677f761b831f3425492e31112a34))
* **url4-cloud:** expose provider connections ([cea8b66](https://github.com/OpenMined/screamingface/commit/cea8b662dd8f5f484c85cca9d2b88ff5244f84e4))
* **url4-cloud:** expose provider connections ([d871689](https://github.com/OpenMined/screamingface/commit/d871689aa772b302338f4e47e15f7e68c9ee0ae8))
* **url4-cloud:** proxy model parameter contracts ([89b6c28](https://github.com/OpenMined/screamingface/commit/89b6c28852684309760d82310b465c4b5f4678a1))
* **url4-cloud:** proxy model parameter contracts ([d9db1e6](https://github.com/OpenMined/screamingface/commit/d9db1e6c68e564f2633d12fc6dfeed6d0d12638c))
* **url4:** per-run cache policy for the aigateway global response cache ([#518](https://github.com/OpenMined/screamingface/issues/518)) ([245e0a4](https://github.com/OpenMined/screamingface/commit/245e0a478d0c4d7635a90cf06a50b5b2ddf37d93))


### Bug Fixes

* **url4-cloud:** bind caller exclusions on a default-on search route ([d7d9af8](https://github.com/OpenMined/screamingface/commit/d7d9af8fa0ebb282f11dc77f2af26c21c8138c29))
* **url4-cloud:** bind Candidate outcomes to one model call ([9e79ed5](https://github.com/OpenMined/screamingface/commit/9e79ed57b17f604679994c569802be9e96826a5e))
* **url4-cloud:** report absent DRACO accuracy axis and correct asset claims ([c45876c](https://github.com/OpenMined/screamingface/commit/c45876cfaca25b1e63fa8ca34eeaf29ef90bb4d0))
* **url4-cloud:** scope declared-world failures to discovery ([08cc9d0](https://github.com/OpenMined/screamingface/commit/08cc9d0ba14473e7af86404a17aa667256524ac3))
* **url4-cloud:** validate every relative route and publish the Candidate binding ([2531b6d](https://github.com/OpenMined/screamingface/commit/2531b6d00d0ce061c399c50d24f4700d78859224))


### Refactors

* **url4-cloud:** clean DRACO module boundaries ([a70321b](https://github.com/OpenMined/screamingface/commit/a70321badb7ad0d167a192e722916ee9b9f22783))
* **url4-cloud:** make the local gateway address a setting ([24775b8](https://github.com/OpenMined/screamingface/commit/24775b8a81628327955b64798bbf6ff6666a077d))

## [1.1.0](https://github.com/OpenMined/screamingface/compare/url4-cloud-v1.0.0...url4-cloud-v1.1.0) (2026-08-05)


### Features

* **url4-cloud:** capture finish_reason and refusal, classify a refused turn ([#506](https://github.com/OpenMined/screamingface/issues/506)) ([b594d6f](https://github.com/OpenMined/screamingface/commit/b594d6fcc11b10c4593d1fbe4d95ab3c7adc4bc1))


### Bug Fixes

* **url4-cloud:** move both Docker build stages to Python 3.13 together ([#481](https://github.com/OpenMined/screamingface/issues/481)) ([0c45a5a](https://github.com/OpenMined/screamingface/commit/0c45a5ae365fd5df20b6d607161d7bcdeb0aed2c))

## [1.0.0](https://github.com/OpenMined/screamingface/compare/url4-cloud-v0.1.0...url4-cloud-v1.0.0) (2026-07-31)


### ⚠ BREAKING CHANGES

* a deployment relying on the Cloudflare Access edge to attach `Cf-Access-Jwt-Assertion` must now send `Authorization: Bearer <token>` instead.

### Features

* adopt the Cloudflare Access identity headers (OME-684) ([#444](https://github.com/OpenMined/screamingface/issues/444)) ([3e363de](https://github.com/OpenMined/screamingface/commit/3e363dee80d094cbe3c57b52fbdc20fdd2b16ac3))
* **url4-cloud:** add ai.url4.error outbound nack frame + bridge emission ([d076ec7](https://github.com/OpenMined/screamingface/commit/d076ec762c6920efdcd10a119aafa5126acac441))
* **url4-cloud:** add url4_cloud_nats CloudEvents bus (OME-516) ([fa2ecf0](https://github.com/OpenMined/screamingface/commit/fa2ecf066d7abda1259f535f9efef3ecf73f2cb9))
* **url4-cloud:** app-served Scalar + AsyncAPI reference pages ([ecc0d73](https://github.com/OpenMined/screamingface/commit/ecc0d73beefb673666acced4eddc226e0421b7be))
* **url4-cloud:** auth capability token + JWT + RFC 9457 Bearer guard (OME-517) ([0ccf78a](https://github.com/OpenMined/screamingface/commit/0ccf78ad29a9941e5be4f7360fa3b78f2293dc48))
* **url4-cloud:** CloudEvents WebSocket bridge with resume + heartbeat (OME-521) ([0909f25](https://github.com/OpenMined/screamingface/commit/0909f25ac65e6d3d7e6ed28e7f8e848b70a336cf))
* **url4-cloud:** declutter REST docs + document Prefer sync/async ([bccb5ee](https://github.com/OpenMined/screamingface/commit/bccb5ee09c038d3052c4307265b896e2d1d894ef))
* **url4-cloud:** dedicated URL4-Capability header, decoupled from Authorization ([79f6e9d](https://github.com/OpenMined/screamingface/commit/79f6e9dc768bf256035efa73ced7fe6920ded7de))
* **url4-cloud:** document REST responses on GET / and DELETE / ([5715c1c](https://github.com/OpenMined/screamingface/commit/5715c1cc094a4f3985b08d38ed39eaffb56252d0))
* **url4-cloud:** embed sync/async/streaming diagrams in the served docs ([ea5c04f](https://github.com/OpenMined/screamingface/commit/ea5c04f8a9a93c5f37e4b6ed8eddf53f12cabca7))
* **url4-cloud:** JobRunner port + k8s/docker adapters (OME-519) ([cf86281](https://github.com/OpenMined/screamingface/commit/cf86281b8a30d02954afcdad969636f45d4dd611))
* **url4-cloud:** k8s deploy + namespace RBAC bootstrap + Helm chart (OME-522) ([abadb9a](https://github.com/OpenMined/screamingface/commit/abadb9ae0dc1ef850209e1a51a40b00e04caf61f))
* **url4-cloud:** OpenAPI 3.1 + AsyncAPI 3.0 + Scalar + ops endpoints (OME-523) ([0d4f132](https://github.com/OpenMined/screamingface/commit/0d4f1321fb2687d6b0498ed8258e4047f02136de))
* **url4-cloud:** render /asyncapi with Scalar, unify the doc viewers ([ad4cc2f](https://github.com/OpenMined/screamingface/commit/ad4cc2f811ac9dac82809aca926109c3c2879b9b))
* **url4-cloud:** REST control plane — /token, GET start (Prefer sync/async), DELETE (OME-518) ([cb75b9c](https://github.com/OpenMined/screamingface/commit/cb75b9c2a3d3bc2225f431820b9f059f0d449da4))
* **url4-cloud:** runner Job entrypoint — execute + publish CloudEvents lifecycle (OME-520) ([94c2492](https://github.com/OpenMined/screamingface/commit/94c24928f95981a4a459a41b6f833e1cb86a53d9))
* **url4-cloud:** scaffold apps/url4-cloud (OME-514) ([11dfb39](https://github.com/OpenMined/screamingface/commit/11dfb39b39a3e76c9a4d6504db8ec6288fa16d2e))
* **url4-cloud:** unify docs into /docs (Scalar REST + AsyncAPI switcher) ([47d3ddd](https://github.com/OpenMined/screamingface/commit/47d3ddd63f7dea45f2c404b217f284f00c9d52b8))
* **url4-cloud:** url4 engine integration — backend/runner/shared split, observer seam, local mode ([#425](https://github.com/OpenMined/screamingface/issues/425)) ([ac888c5](https://github.com/OpenMined/screamingface/commit/ac888c5c5a56fb92b36760675c0cce8fcafc144c))
* **url4-cloud:** url4_cloud_protocol frame models + taxonomy invariants (OME-515) ([18ed7bf](https://github.com/OpenMined/screamingface/commit/18ed7bf18c385fd724afaa41be093e313b62cf96))


### Bug Fixes

* **url4-cloud:** style the AsyncAPI viewer via cssImportPath (shadow DOM) ([5fc2995](https://github.com/OpenMined/screamingface/commit/5fc29950ed6e12421c3464a876a900e100915351))
* **url4-cloud:** use JSON-Schema `examples` array, not singular `example` ([9099e36](https://github.com/OpenMined/screamingface/commit/9099e3635671526811dae0f57428e4e73292d8cd))


### Refactors

* **url4-cloud:** align protocol to CloudEvents 1.0 + OTel standards (OME-526) ([471a595](https://github.com/OpenMined/screamingface/commit/471a595306496fdc8718383a79ac46708ca0e3b0))
* **url4-cloud:** drop ai.url4.execute from the WS inbound surface ([a9314d8](https://github.com/OpenMined/screamingface/commit/a9314d8b8be3986368926fbcb2b5ddb10b1fcb45))
* **url4-cloud:** rename url4_cloud_protocol -&gt; url4_streaming_protocol (OME-527) ([3c40529](https://github.com/OpenMined/screamingface/commit/3c40529c8d75e8fca7c48cfcbea7116b0eca33fc))


### Documentation

* **url4-cloud:** record the AsyncAPI payload-dialect decision (no schemaFormat) ([18a2a58](https://github.com/OpenMined/screamingface/commit/18a2a580a7a1e5545da4b537d26ad847c0e96a1c))
