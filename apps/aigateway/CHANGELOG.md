# Changelog

All notable changes to the ScreamingFace AI Gateway are documented here.
This project follows [Semantic Versioning](https://semver.org/) and uses
release tags of the form `aigateway-v<version>`.

## [1.0.0](https://github.com/ScreamingFace/screamingface/compare/aigateway-v0.2.0...aigateway-v1.0.0) (2026-10-30)


### ⚠ BREAKING CHANGES

* **aigateway:** the wire value of scope in GET /v1/model-parameters changes from account_profile to account_connection, and contract_id and context.revision change once.
* **aigateway:** a provider plugin must implement the hooks under their new names; an old name is no longer called.
* **aigateway:** AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE no longer imports a credential at startup, and the Anthropic plugin settings claude_code_keychain_service and bootstrap_user are removed.
* **aigateway:** Profile-only credentials no longer resolve, and quarantined pairs return credential_pair_unresolved.
* **aigateway:** GET/POST/PATCH/PUT/DELETE on /v1/auth/profiles, /v1/auth/{provider}/profiles[...] and /v1/admin/accounts/{account_id}/profiles[...] now answer 410.
* **aigateway:** delete the dead chat shims and the saved-defaults pipeline (Stage E, E2b) ([#1456](https://github.com/ScreamingFace/screamingface/issues/1456))
* **aigateway:** reject explicit profile selectors ([#1114](https://github.com/ScreamingFace/screamingface/issues/1114))
* a deployment relying on the Cloudflare Access edge to attach `Cf-Access-Jwt-Assertion` must now send `Authorization: Bearer <token>` instead.

### Features

* admin cache-snapshot upload — gateway + console (OME-951) ([cf69fff](https://github.com/ScreamingFace/screamingface/commit/cf69fff81eb5f7e66da9ffbed6048b16a79d78c1))
* admin console for gateway tenants and API-key credentials (OME-705) ([#451](https://github.com/ScreamingFace/screamingface/issues/451)) ([14d54f0](https://github.com/ScreamingFace/screamingface/commit/14d54f0a5eb1a8a272bce9a9d7804ae32783fd98))
* adopt the Cloudflare Access identity headers (OME-684) ([#444](https://github.com/ScreamingFace/screamingface/issues/444)) ([3e363de](https://github.com/ScreamingFace/screamingface/commit/3e363dee80d094cbe3c57b52fbdc20fdd2b16ac3))
* **aigateway/chart:** render AIGATEWAY_SECRET_KEY from the auth secret + extraEnv passthrough ([#448](https://github.com/ScreamingFace/screamingface/issues/448)) ([43bb903](https://github.com/ScreamingFace/screamingface/commit/43bb90372df22cf3103691d9a6be4d27cef09f78))
* **aigateway:** add actionable API key validation ([#420](https://github.com/ScreamingFace/screamingface/issues/420)) ([66deae0](https://github.com/ScreamingFace/screamingface/commit/66deae0a787612c8a320ee3ad98f92109c87633f))
* **aigateway:** add direct OpenAI API-key provider ([#630](https://github.com/ScreamingFace/screamingface/issues/630)) ([bab02e3](https://github.com/ScreamingFace/screamingface/commit/bab02e3e8aeea1a798e3f62750c197d59bffbe81))
* **aigateway:** add global exact-request cache ([#507](https://github.com/ScreamingFace/screamingface/issues/507)) ([4f2a55e](https://github.com/ScreamingFace/screamingface/commit/4f2a55eacd06b28f8cf9506d37398c0e0fdebf30))
* **aigateway:** add Hugging Face provider (SF-345) ([#356](https://github.com/ScreamingFace/screamingface/issues/356)) ([c556e6c](https://github.com/ScreamingFace/screamingface/commit/c556e6ce29543f4611e64e1cc239020315070592))
* **aigateway:** add OpenRouter BYOK provider (OME-428) ([#416](https://github.com/ScreamingFace/screamingface/issues/416)) ([7e38134](https://github.com/ScreamingFace/screamingface/commit/7e38134359b210b5236e958a4e5f83a974a98f16))
* **aigateway:** add pair-addressed admin PUT and DELETE through the mutation bridge ([#1404](https://github.com/ScreamingFace/screamingface/issues/1404)) ([#1405](https://github.com/ScreamingFace/screamingface/issues/1405)) ([e79db82](https://github.com/ScreamingFace/screamingface/commit/e79db8205f6d345aa68853008562e0e3bc646045))
* **aigateway:** add per-provider call usage accounting ([#567](https://github.com/ScreamingFace/screamingface/issues/567)) ([72b35d7](https://github.com/ScreamingFace/screamingface/commit/72b35d7c0527bc32ba76e7100a366e126e3a0414))
* **aigateway:** add the offline purge of retired Profile storage (Stage E, E5b) ([#1573](https://github.com/ScreamingFace/screamingface/issues/1573)) ([1ccf80a](https://github.com/ScreamingFace/screamingface/commit/1ccf80a895d0045edcefe60df48ac7cf871da624))
* **aigateway:** admin cache-snapshot upload — routes, runner, COPY/merge loader ([267da57](https://github.com/ScreamingFace/screamingface/commit/267da5700470301c212ad8645f185cc3be97b09d))
* **aigateway:** cache direct OpenAI responses ([#675](https://github.com/ScreamingFace/screamingface/issues/675)) ([13fa4ea](https://github.com/ScreamingFace/screamingface/commit/13fa4ea39a417fabe5d88e335018b3fb57fc05a6))
* **aigateway:** cache Hugging Face router responses ([#704](https://github.com/ScreamingFace/screamingface/issues/704)) ([637e93d](https://github.com/ScreamingFace/screamingface/commit/637e93d0f51190ca4e69ba5a5bb710f2a763b5c5))
* **aigateway:** cache OpenRouter native web search ([79f21d6](https://github.com/ScreamingFace/screamingface/commit/79f21d6067cb54de9a87beefcf2ad0d960aaa3c5))
* **aigateway:** cache Tavily retrieval results in the global cache ([#782](https://github.com/ScreamingFace/screamingface/issues/782)) ([0ddcab9](https://github.com/ScreamingFace/screamingface/commit/0ddcab948790cf5a448d630e429d6efc31ea6b61))
* **aigateway:** cap request bodies and accept media only as data: URIs ([#1479](https://github.com/ScreamingFace/screamingface/issues/1479)) ([a2cbf70](https://github.com/ScreamingFace/screamingface/commit/a2cbf70bad450e41e9ee2d8be1c79967bd8da5f2))
* **aigateway:** carry gateway_call_id on every log line ([#898](https://github.com/ScreamingFace/screamingface/issues/898)) ([802bed9](https://github.com/ScreamingFace/screamingface/commit/802bed9aeac74d6b297d4b3e8fd2897b91d2b172))
* **aigateway:** check a gateway database before a pull, and say what one load_page transaction covers ([701fb82](https://github.com/ScreamingFace/screamingface/commit/701fb82790ba76e3b9de1e649ef2405b50d17828))
* **aigateway:** discover OpenRouter models live ([#739](https://github.com/ScreamingFace/screamingface/issues/739)) ([cc9deb4](https://github.com/ScreamingFace/screamingface/commit/cc9deb4a6702e0eb546bbc04772cf7de7b4f4e8d))
* **aigateway:** drop health-check probe server spans before export ([c1687f1](https://github.com/ScreamingFace/screamingface/commit/c1687f1dbf83edef81607c37f03a2753ef2a4c32))
* **aigateway:** drop health-check probe server spans before export (OME-1217) ([1305a07](https://github.com/ScreamingFace/screamingface/commit/1305a07b3f20529733362f4744dcf66712e3437d))
* **aigateway:** E14 B1 — frozen copy capture, seal and replay routes ([#1330](https://github.com/ScreamingFace/screamingface/issues/1330)) ([f068606](https://github.com/ScreamingFace/screamingface/commit/f06860621a900055ce69866c1369e2ceb34bae61))
* **aigateway:** emit spans so the gateway appears as an OTel service ([#909](https://github.com/ScreamingFace/screamingface/issues/909)) ([79a949e](https://github.com/ScreamingFace/screamingface/commit/79a949e11da38791a3f2e26281b4abb1eb879874))
* **aigateway:** enable local Fusion benchmark execution ([#1448](https://github.com/ScreamingFace/screamingface/issues/1448)) ([cddc9f5](https://github.com/ScreamingFace/screamingface/commit/cddc9f59d09cfc762f67fe5f21199dcf74dae338))
* **aigateway:** expand HuggingFace + Anthropic model seeds with live-verified ids ([#583](https://github.com/ScreamingFace/screamingface/issues/583)) ([a0a1cb2](https://github.com/ScreamingFace/screamingface/commit/a0a1cb2a0262be375623f2a5819e28c963e42252))
* **aigateway:** expand OpenRouter model seed with 58 live-verified slugs ([#581](https://github.com/ScreamingFace/screamingface/issues/581)) ([59543a4](https://github.com/ScreamingFace/screamingface/commit/59543a44dabee60f3ecf56650540f1d943a8eb66))
* **aigateway:** expose each model's input modalities on /v1/models ([#1451](https://github.com/ScreamingFace/screamingface/issues/1451)) ([2406ccd](https://github.com/ScreamingFace/screamingface/commit/2406ccd5aeaec7ac378bda22e8a3177b9398318b))
* **aigateway:** expose execution access in model discovery ([#932](https://github.com/ScreamingFace/screamingface/issues/932)) ([ba9049b](https://github.com/ScreamingFace/screamingface/commit/ba9049bc638ce1a4daae94fd25870b910ed35c7e))
* **aigateway:** expose model, provider, and search contracts ([2bee805](https://github.com/ScreamingFace/screamingface/commit/2bee8054969f2cb97b5150d7ee32636367b251ef))
* **aigateway:** expose OpenRouter price and privacy routing controls ([#450](https://github.com/ScreamingFace/screamingface/issues/450)) ([008b209](https://github.com/ScreamingFace/screamingface/commit/008b209e759b42a0b6c18263189676a0b99e1be8))
* **aigateway:** expose provider discovery ([c6161cf](https://github.com/ScreamingFace/screamingface/commit/c6161cf1d7852781d8a329acf96967eb66398d22))
* **aigateway:** expose provider parameter contracts ([#443](https://github.com/ScreamingFace/screamingface/issues/443)) ([4f9db97](https://github.com/ScreamingFace/screamingface/commit/4f9db97bfbda39cd200d23c28e510944f6b7fb4a))
* **aigateway:** fence ownership writers on the pair generation (G0 1/3) ([#1271](https://github.com/ScreamingFace/screamingface/issues/1271)) ([c76d399](https://github.com/ScreamingFace/screamingface/commit/c76d3997284ff00ead45104b496caaa9ada83d81))
* **aigateway:** give each Attempt of a Case its own global cache entry ([be0492f](https://github.com/ScreamingFace/screamingface/commit/be0492ffe8265f05dda16eb25749ba212e104ed9))
* **aigateway:** give each Attempt of a Case its own global cache entry (OME-1458, PR 4 of 7) ([7033181](https://github.com/ScreamingFace/screamingface/commit/703318120067288ff9b6e0279ea43116f1fa7fa1))
* **aigateway:** grant-filtered catalog and shared cache for configured endpoints ([#1590](https://github.com/ScreamingFace/screamingface/issues/1590)) ([5596302](https://github.com/ScreamingFace/screamingface/commit/559630247d67c9760a3beee7d44d244b522b0ed4))
* **aigateway:** join the inbound traceparent to the log context ([#902](https://github.com/ScreamingFace/screamingface/issues/902)) ([5ecac45](https://github.com/ScreamingFace/screamingface/commit/5ecac451f659e5de031a5020f21450a44b5c7a8d))
* **aigateway:** let a native connection repair a migrated pair's credential (Stage E, E1b) ([#1449](https://github.com/ScreamingFace/screamingface/issues/1449)) ([00c1bef](https://github.com/ScreamingFace/screamingface/commit/00c1bef11e673ce488538966e572cff5d9e08319))
* **aigateway:** list an account's provider credentials by pair (G1 1/3) ([#1397](https://github.com/ScreamingFace/screamingface/issues/1397)) ([1ed95ab](https://github.com/ScreamingFace/screamingface/commit/1ed95abdfb75c783117625d452573ac7090fcec9))
* **aigateway:** list provider availability by the rule chat resolves by ([#1610](https://github.com/ScreamingFace/screamingface/issues/1610)) ([fed613d](https://github.com/ScreamingFace/screamingface/commit/fed613da26785b4ad8fdf4b0fcc75aa5c05fa9c4))
* **aigateway:** log an unhandled exception once, by class name, with its call id ([db6757b](https://github.com/ScreamingFace/screamingface/commit/db6757bc56a7f6b49b38ae16e7059c06a55cda3f))
* **aigateway:** log an unhandled exception once, by class name, with its call id ([2ba9b6c](https://github.com/ScreamingFace/screamingface/commit/2ba9b6caed867ab04d04f397a5f560ca794e6f87))
* **aigateway:** log the concurrency limit applied per provider ([9689fac](https://github.com/ScreamingFace/screamingface/commit/9689fac4c8de7693f4e35c33ef01595e0402e1d4))
* **aigateway:** make tool-bearing requests cacheable per provider ([b60d997](https://github.com/ScreamingFace/screamingface/commit/b60d997e6fc00a12649024275e8c9502584db900))
* **aigateway:** make web-search-backed requests cacheable ([74069f1](https://github.com/ScreamingFace/screamingface/commit/74069f164d7b858752a6a23ea5fb6d81fdee4a57))
* **aigateway:** move provider-access backing toward connections ([#1029](https://github.com/ScreamingFace/screamingface/issues/1029)) ([7cff8a5](https://github.com/ScreamingFace/screamingface/commit/7cff8a569cb2b958b455a91bc4723efc929f5773))
* **aigateway:** page the community cache to signed-in callers and load pages into SQLite ([dc695cf](https://github.com/ScreamingFace/screamingface/commit/dc695cfd2227323d73ac5cc891cdc1f487271191))
* **aigateway:** page the community cache to signed-in callers and load pages into SQLite ([4a7aa2b](https://github.com/ScreamingFace/screamingface/commit/4a7aa2b748ecc0e0e5251b1a3847ffd0ec371f0d))
* **aigateway:** point every re-auth URL at the Connection API ([#1432](https://github.com/ScreamingFace/screamingface/issues/1432)) ([59545b2](https://github.com/ScreamingFace/screamingface/commit/59545b20bb9696681034032b33bff11bf0a0b6c5))
* **aigateway:** project provider-neutral web search ([d331575](https://github.com/ScreamingFace/screamingface/commit/d3315750374e813ef6f07e7ff9147f12c43498e0))
* **aigateway:** prove a legacy OAuth shadow by identity before PUT or DELETE (G1 3/3) ([#1408](https://github.com/ScreamingFace/screamingface/issues/1408)) ([3bfa2fd](https://github.com/ScreamingFace/screamingface/commit/3bfa2fd2439ed9e960b4d7440975b91e0f7f10ec))
* **aigateway:** publish OAuth refresh under the pair guard (G0 2/3) ([#1299](https://github.com/ScreamingFace/screamingface/issues/1299)) ([01875d2](https://github.com/ScreamingFace/screamingface/commit/01875d23f97758f59e5767cd6628ce7d77a61f9c))
* **aigateway:** publish the caller-scoped provider-access availability listing ([#1006](https://github.com/ScreamingFace/screamingface/issues/1006)) ([2da4589](https://github.com/ScreamingFace/screamingface/commit/2da458968400150bfca5f4744e12b0a738deaba7))
* **aigateway:** put the Profile management routes behind the provider-credential admin boundary ([#992](https://github.com/ScreamingFace/screamingface/issues/992)) ([a78d58d](https://github.com/ScreamingFace/screamingface/commit/a78d58da14403b2fd21a889f898a535f4c5ce877))
* **aigateway:** register benchmark model seeds ([d8525e0](https://github.com/ScreamingFace/screamingface/commit/d8525e08ecebbab63dac37a441763961dfe785f1))
* **aigateway:** register the open-weight notebook lineup members ([770257d](https://github.com/ScreamingFace/screamingface/commit/770257dccbb18fdbff596d903d9f6d3f93047f21))
* **aigateway:** reject explicit profile selectors ([#1114](https://github.com/ScreamingFace/screamingface/issues/1114)) ([3083640](https://github.com/ScreamingFace/screamingface/commit/3083640b6be5d67b909d93643c6878d5fe67e318))
* **aigateway:** relay the provider's sanitized error message (OME-1136) ([#1233](https://github.com/ScreamingFace/screamingface/issues/1233)) ([8d32145](https://github.com/ScreamingFace/screamingface/commit/8d32145515a4dcb35c56c7dabd9d814c1f90a1ee))
* **aigateway:** remove saved profile defaults ([#1061](https://github.com/ScreamingFace/screamingface/issues/1061)) ([e8c7d26](https://github.com/ScreamingFace/screamingface/commit/e8c7d262262e63970eb88624d32cda81274f19f9))
* **aigateway:** report image and file input tokens in chat usage ([#1481](https://github.com/ScreamingFace/screamingface/issues/1481)) ([b76556c](https://github.com/ScreamingFace/screamingface/commit/b76556ca3d1d8d68159c5a3d0b8933fc0bea874e))
* **aigateway:** report the successful attempt's direct cost and usage ([#1498](https://github.com/ScreamingFace/screamingface/issues/1498)) ([b57e2fc](https://github.com/ScreamingFace/screamingface/commit/b57e2fcbe6c21ffbd7dfd6772677b5eb990b7390))
* **aigateway:** return full cache metadata on hits and pin the cross-stack hit contract ([#1100](https://github.com/ScreamingFace/screamingface/issues/1100)) ([16bb09a](https://github.com/ScreamingFace/screamingface/commit/16bb09ae38a73eed25576763ba5a73ed65729f0e))
* **aigateway:** send images and PDFs natively to Gemini, Antigravity and Codex ([#1431](https://github.com/ScreamingFace/screamingface/issues/1431)) ([8c5b72b](https://github.com/ScreamingFace/screamingface/commit/8c5b72bd5786b254f141c40ffb4f1ac2d7ce70a9))
* **aigateway:** serve configured remote endpoints as provider instances ([#1527](https://github.com/ScreamingFace/screamingface/issues/1527)) ([ca31b88](https://github.com/ScreamingFace/screamingface/commit/ca31b88efbba4a33c9ab6d6f471b7bd2053d3900))
* **aigateway:** ship the OTLP endpoint and credential through the chart ([#919](https://github.com/ScreamingFace/screamingface/issues/919)) ([b93cde6](https://github.com/ScreamingFace/screamingface/commit/b93cde6d250c5728cd885e911ff00aa3570fb064))
* **aigateway:** stop forcing the OpenRouter web-search engine ([1d4c93d](https://github.com/ScreamingFace/screamingface/commit/1d4c93de6d06f0bdb99dc535078c84328f26c3d5))
* **aigateway:** support OpenRouter reasoning objects ([#1483](https://github.com/ScreamingFace/screamingface/issues/1483)) ([a4b2d84](https://github.com/ScreamingFace/screamingface/commit/a4b2d849ef80e062e4446563d79931090a1b401b))
* **aigateway:** validate reasoning_effort for the OpenRouter provider ([3812ba4](https://github.com/ScreamingFace/screamingface/commit/3812ba4ab56957ae014a1323ea68f449d3deb9d1))
* **aigateway:** weekly response-cache snapshot to Garage (OME-1021) ([#752](https://github.com/ScreamingFace/screamingface/issues/752)) ([64e5229](https://github.com/ScreamingFace/screamingface/commit/64e522949f0ccc9da7b3dd59f8ae399a11204eaa))
* **engine:** cut the chart over to the worker pool and retire the Job adapter ([#822](https://github.com/ScreamingFace/screamingface/issues/822)) ([4cdfa92](https://github.com/ScreamingFace/screamingface/commit/4cdfa920db7ae40280b2f8b9cc7c0b27fbd9ab7e))
* **models:** register the HealthBench judge route openrouter/openai/gpt-5.4 ([3021a73](https://github.com/ScreamingFace/screamingface/commit/3021a7372ee50ab74e147b168ed61a02462ef194))
* run any OpenRouter model — dynamic admission at preflight ([#633](https://github.com/ScreamingFace/screamingface/issues/633)) ([3938f66](https://github.com/ScreamingFace/screamingface/commit/3938f66b8090af65547c09cd8020de8428dc4f9e))
* **screamingface-engine:** E14 B2 — Tavily retrieval cache via gateway ([#1331](https://github.com/ScreamingFace/screamingface/issues/1331)) ([83ee7b1](https://github.com/ScreamingFace/screamingface/commit/83ee7b1e4e17fd5a6f02ffb74e704be9b7a3951b))
* **screamingface-engine:** rename apps/url4-cloud to apps/screamingface-engine ([3246d96](https://github.com/ScreamingFace/screamingface/commit/3246d96d05673e0707cf938cae65de2e696154c8))
* **screamingface-engine:** run configured endpoint chat routes privately with one world config ([#1606](https://github.com/ScreamingFace/screamingface/issues/1606)) ([143d4bc](https://github.com/ScreamingFace/screamingface/commit/143d4bcf8ea973fa30b6bda73fc270439f7bb168))
* **screamingface-engine:** send a Case's inline pictures to the model as image parts (OME-1678) ([36d5351](https://github.com/ScreamingFace/screamingface/commit/36d5351805943b47121bb815023c7b611661280f))
* **screamingface:** sf.cache.pull_from_remote, use_cache=, and the local cache on by default ([#1446](https://github.com/ScreamingFace/screamingface/issues/1446)) ([19d33e4](https://github.com/ScreamingFace/screamingface/commit/19d33e4c862e352e4dc7fa4e077341f42550a46d))
* standard metadata (cost, latency, tokens) on every cached response ([#930](https://github.com/ScreamingFace/screamingface/issues/930)) ([0d2c00f](https://github.com/ScreamingFace/screamingface/commit/0d2c00f829287b3d8fa1adc8dd380ff3e10b6b06))
* **url4-cloud:** add HealthBench challenge protocols ([3c0bef1](https://github.com/ScreamingFace/screamingface/commit/3c0bef18422b8bb4db7aaf2acff5b8facfcff193))
* **url4-cloud:** derive the web-search mechanism from the provider ([8059f7c](https://github.com/ScreamingFace/screamingface/commit/8059f7c321c10521f89a47ebc5354065cc105de7))


### Bug Fixes

* **aigateway:** address the PR [#1433](https://github.com/ScreamingFace/screamingface/issues/1433) re-review of the community-cache pages and loader ([e07060e](https://github.com/ScreamingFace/screamingface/commit/e07060ec958bf112dd56f3bed862058a30556eb0))
* **aigateway:** address the PR [#1433](https://github.com/ScreamingFace/screamingface/issues/1433) review of the community-cache pages and loader ([59cc202](https://github.com/ScreamingFace/screamingface/commit/59cc2028abaabcf8e2e4efc7e85f2ae8ce58fefa))
* **aigateway:** base the OpenRouter zero proofs on billing facts, not the reply format ([#1571](https://github.com/ScreamingFace/screamingface/issues/1571)) ([4cb803e](https://github.com/ScreamingFace/screamingface/commit/4cb803eab9dfb22306fa29412e56f813980fbdf7))
* **aigateway:** call the Codex test's hook by its credential name and drop a retired live model ([2876feb](https://github.com/ScreamingFace/screamingface/commit/2876feba97a4bd38ced3bd4d51be1f8762439292))
* **aigateway:** cast Tortoise CharField reads at the Literal alias boundaries ([#662](https://github.com/ScreamingFace/screamingface/issues/662)) ([3427d46](https://github.com/ScreamingFace/screamingface/commit/3427d464b301467b898c98c1bb04317700abb3d1))
* **aigateway:** check the pair before marking a Connection error (G0 3/3) ([#1396](https://github.com/ScreamingFace/screamingface/issues/1396)) ([123be84](https://github.com/ScreamingFace/screamingface/commit/123be8466eb10810263f33a0c935aca4c4c9819f))
* **aigateway:** close implicit web-search bypass ([2146fa0](https://github.com/ScreamingFace/screamingface/commit/2146fa0dd8aac9e50d1afd7733e6ec9addd180a5))
* **aigateway:** close three review gaps in the OpenRouter zero proofs ([#1575](https://github.com/ScreamingFace/screamingface/issues/1575)) ([27364bb](https://github.com/ScreamingFace/screamingface/commit/27364bbf38334d7379afff10733fe0bf2cff9a1a))
* **aigateway:** configurable componentLabel; refuse podLabels collision ([#796](https://github.com/ScreamingFace/screamingface/issues/796)) ([662897e](https://github.com/ScreamingFace/screamingface/commit/662897eb4b7d7bcc313ce26e8d26b632a4d6397e))
* **aigateway:** configure app logging so INFO records actually emit ([e0766e2](https://github.com/ScreamingFace/screamingface/commit/e0766e2299704a35bef67619caad6ab81c4f08cb))
* **aigateway:** count the rows after a cursor in one statement ([5153e3b](https://github.com/ScreamingFace/screamingface/commit/5153e3bfb839b9a7fd9d415a8d00709889dea0d3))
* **aigateway:** derive the Codex finish_reason instead of fabricating "stop" ([#501](https://github.com/ScreamingFace/screamingface/issues/501)) ([0571f44](https://github.com/ScreamingFace/screamingface/commit/0571f440df4cc341fe1f789a0b85d8066a9b1d12))
* **aigateway:** enable OpenRouter in prod chart values ([#533](https://github.com/ScreamingFace/screamingface/issues/533)) ([7ad2ed3](https://github.com/ScreamingFace/screamingface/commit/7ad2ed35a3f0efa8087d8be5989c5a258adfe045))
* **aigateway:** keep dispatch failures at one record when the handler raises ([#1230](https://github.com/ScreamingFace/screamingface/issues/1230)) ([643a496](https://github.com/ScreamingFace/screamingface/commit/643a4961599c64445c7ccccdbb584309cb831fe6))
* **aigateway:** keep exact usage evidence for large successful bodies ([#1520](https://github.com/ScreamingFace/screamingface/issues/1520)) ([476c0cc](https://github.com/ScreamingFace/screamingface/commit/476c0cc031ab66023812c422fd7ad8563a83cc94))
* **aigateway:** log a migrated pair's unusable-credential refusal ([#1317](https://github.com/ScreamingFace/screamingface/issues/1317)) ([3cf66b5](https://github.com/ScreamingFace/screamingface/commit/3cf66b545e998be98b997c91dc1b0752fe443555))
* **aigateway:** log one attributable record for every dispatch failure ([d92fc6e](https://github.com/ScreamingFace/screamingface/commit/d92fc6e2907db7d05d35adc1a23e2f6aacd03621))
* **aigateway:** log one attributable record for every dispatch failure (OME-968) ([52117d4](https://github.com/ScreamingFace/screamingface/commit/52117d44c9cf2c9d3e1353b6c06f3dffadd0b4cf))
* **aigateway:** map 402 to a dedicated insufficient-credits error ([7235dcf](https://github.com/ScreamingFace/screamingface/commit/7235dcfc1bc1985d95566aab9bc4888964b5755b))
* **aigateway:** map 402 to a dedicated insufficient-credits error ([b618597](https://github.com/ScreamingFace/screamingface/commit/b6185977624016b26f559ac09b67c3b2911f7357))
* **aigateway:** name the catch-all 500 gateway_internal_error ([722d53a](https://github.com/ScreamingFace/screamingface/commit/722d53aba64d30448ea2ff2bf1c1d443ed501c85))
* **aigateway:** never make a cache hit wait for a snapshot merge ([#1318](https://github.com/ScreamingFace/screamingface/issues/1318)) ([888a5f9](https://github.com/ScreamingFace/screamingface/commit/888a5f9bd96c735003a9ce2547770895147ff66d))
* **aigateway:** preserve proven-zero retry cost ([#1296](https://github.com/ScreamingFace/screamingface/issues/1296)) ([731b5c8](https://github.com/ScreamingFace/screamingface/commit/731b5c88e4a0bd56ab972078bbf98f487920f59f))
* **aigateway:** preserve web search cache bypass ([e2c5eae](https://github.com/ScreamingFace/screamingface/commit/e2c5eaebe23f8273cb33bf0cabd21e3d900b0f88))
* **aigateway:** price an OpenRouter refusal with a policy notice at $0 ([#1583](https://github.com/ScreamingFace/screamingface/issues/1583)) ([581c209](https://github.com/ScreamingFace/screamingface/commit/581c20969458820c33fde0b943e85d8d148083b0))
* **aigateway:** re-verify the LiteLLM runtime guard against 1.102.0 ([#1118](https://github.com/ScreamingFace/screamingface/issues/1118)) ([d35a465](https://github.com/ScreamingFace/screamingface/commit/d35a465374a1abe20b533bd5236cf6a8a567514b))
* **aigateway:** read litellm's bundled model list, never a download at start (OME-1615) ([0648030](https://github.com/ScreamingFace/screamingface/commit/0648030fa63a71041250f9034e4114a150554314))
* **aigateway:** read litellm's bundled model list, never a download at start (OME-1615) ([34fffb9](https://github.com/ScreamingFace/screamingface/commit/34fffb983bd1268f0c3098674c0028215fb153a4))
* **aigateway:** read probe-span exclusion from AIGW_TRACE_EXCLUDED_ROUTES ([3d74ab1](https://github.com/ScreamingFace/screamingface/commit/3d74ab1ddb64bc01612ebe74bbba5325503ecf34))
* **aigateway:** read probe-span exclusion from AIGW_TRACE_EXCLUDED_ROUTES (OME-1453) ([e155609](https://github.com/ScreamingFace/screamingface/commit/e1556093202e154589638ae0377b88513e4e6826))
* **aigateway:** recover BYOK connection auth type ([#795](https://github.com/ScreamingFace/screamingface/issues/795)) ([c8bd6a6](https://github.com/ScreamingFace/screamingface/commit/c8bd6a6555e2b5c9d521aeaa8fa2e542a3417010))
* **aigateway:** refuse :online ahead of the cache read ([9f0e8e8](https://github.com/ScreamingFace/screamingface/commit/9f0e8e8411c367caf2ec97f6aa8a7db0a151549f))
* **aigateway:** refuse a local database missing a cache column as outdated_gateway_database ([0047066](https://github.com/ScreamingFace/screamingface/commit/004706610eff7602572f0f9bab79c3812d200255))
* **aigateway:** refuse a page whose gateway does not report a revision the local side uses ([d4c0308](https://github.com/ScreamingFace/screamingface/commit/d4c030899306ca1fcb70fe7e22b6dec42941563f))
* **aigateway:** refuse file parts on Ollama instead of dropping them ([#1447](https://github.com/ScreamingFace/screamingface/issues/1447)) ([ec4b632](https://github.com/ScreamingFace/screamingface/commit/ec4b632b2267212783ca932c93a6c7314256ef3a))
* **aigateway:** reject invalid Unicode in remote completions ([#1539](https://github.com/ScreamingFace/screamingface/issues/1539)) ([bdf5746](https://github.com/ScreamingFace/screamingface/commit/bdf5746a41bffce68c8f8cf0aef204dcf6d5628d))
* **aigateway:** report credential operational outcomes ([#1240](https://github.com/ScreamingFace/screamingface/issues/1240)) ([a502cb9](https://github.com/ScreamingFace/screamingface/commit/a502cb9964f7c24ce92fcbbe04276b40b276064f))
* **aigateway:** roll Pods when the ConfigMap changes ([9f1d525](https://github.com/ScreamingFace/screamingface/commit/9f1d5256aed79f0a018e01fe408b37c59ad24d86))
* **aigateway:** roll Pods when the ConfigMap changes ([cc1b0ac](https://github.com/ScreamingFace/screamingface/commit/cc1b0acea2a48c2a394f7cf9cd45183b2d2ef15b))
* **aigateway:** sanitize streaming provider errors ([#424](https://github.com/ScreamingFace/screamingface/issues/424)) ([c55c56c](https://github.com/ScreamingFace/screamingface/commit/c55c56cf33c572b3b1549a6553cf314ae8ffc335))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([75f1b99](https://github.com/ScreamingFace/screamingface/commit/75f1b994bbecc7f3baee3e08f4b9f3e2347ac4a5))
* **aigateway:** serve the model-parameters datasheet without a connected profile ([44807b6](https://github.com/ScreamingFace/screamingface/commit/44807b63e8f034b4364ec4efb8d2fc496a1a0814))
* **aigateway:** size the frozen-copy entry cap from the request cap (OME-1756) ([9964821](https://github.com/ScreamingFace/screamingface/commit/9964821f4b7ce3cd6db613b6f73ac8d172086068))
* **aigateway:** size the frozen-copy entry cap from the request cap (OME-1756) ([8163138](https://github.com/ScreamingFace/screamingface/commit/81631389a1f82af9baa2ea98c15022d4acc66c42))
* **aigateway:** strip Datadog callback params, upgrade deps, unpin PyJWT ([#478](https://github.com/ScreamingFace/screamingface/issues/478)) ([30868c7](https://github.com/ScreamingFace/screamingface/commit/30868c7f2a78565420512263b2910c8c9aaaa570))
* **aigateway:** strip new LiteLLM 1.100.0 dynamic callback params ([#903](https://github.com/ScreamingFace/screamingface/issues/903)) ([f31084a](https://github.com/ScreamingFace/screamingface/commit/f31084a52fff5db6964ab296324cb37379d56150))
* **aigateway:** take a row read by both keyset parts once, and plan the query each part sends ([dadd95d](https://github.com/ScreamingFace/screamingface/commit/dadd95dca6d6205569e3a0a22c7e4f740f2f652d))
* **aigateway:** type the Codex model refusal and read the live Codex model list ([#1441](https://github.com/ScreamingFace/screamingface/issues/1441)) ([40908ac](https://github.com/ScreamingFace/screamingface/commit/40908acdd5f2521ed255ae2226393ef4151faa92))
* **ci:** publish to ghcr.io/screamingface after the org transfer ([#653](https://github.com/ScreamingFace/screamingface/issues/653)) ([9e05187](https://github.com/ScreamingFace/screamingface/commit/9e0518798dbff4c7c73014b4c5c4189d0de7dae5))
* **cost:** price an OpenRouter refusal before output as $0 ([#1557](https://github.com/ScreamingFace/screamingface/issues/1557)) ([4824603](https://github.com/ScreamingFace/screamingface/commit/482460344a2db023069362f8a6e80186c7d59962))
* **gateway:** bound provider phases and prevent stale waiter dispatch ([#1153](https://github.com/ScreamingFace/screamingface/issues/1153)) ([b83b967](https://github.com/ScreamingFace/screamingface/commit/b83b96708904d32caee2be5d30e4094e190f3a23))
* **py-screamingface:** raise local stack openrouter gateway concurrency to 32 ([25851fd](https://github.com/ScreamingFace/screamingface/commit/25851fdfa7a2ca50922b81a4dfc36da2febf67d9))
* raise the model-call budget to 30 minutes for long evaluations ([#1430](https://github.com/ScreamingFace/screamingface/issues/1430)) ([92645fe](https://github.com/ScreamingFace/screamingface/commit/92645fe66085733dc2a846fd86d1cc2f53e2330c))
* **repo:** align aigateway and scoreboard Dockerfiles on Python 3.13 ([#502](https://github.com/ScreamingFace/screamingface/issues/502)) ([1513af0](https://github.com/ScreamingFace/screamingface/commit/1513af0c756defa1332e2abc4594612b2583abf7))
* **repo:** complete the org repoint sweep ([32a3868](https://github.com/ScreamingFace/screamingface/commit/32a3868a06a52716efaabe7b51c47aed9d704e4f))
* **screamingface-engine:** keep misplaced pictures out of refusals and refuse pictures in grading calls ([afbe4bb](https://github.com/ScreamingFace/screamingface/commit/afbe4bbdfa3cbe1c903830f53bdbad37c40d36c6))
* **sdk:** warn once at the caller's line for duplicate members and tighten samples validation ([1dabc4b](https://github.com/ScreamingFace/screamingface/commit/1dabc4ba2569d1abf3174783dd96d16b699b063d))


### Performance

* **aigateway:** encode and gzip community-cache batches in a worker thread ([b61f48d](https://github.com/ScreamingFace/screamingface/commit/b61f48daad93b275c4048ea8f623ed29493cc08e))
* **aigateway:** start each community-cache batch at its cursor in the index ([cd5571e](https://github.com/ScreamingFace/screamingface/commit/cd5571ed7d672f6bd112ca527693bf38c1208527))


### Refactors

* **aigateway:** build both keyset forms from one pair of conditions ([22a6c58](https://github.com/ScreamingFace/screamingface/commit/22a6c5856ad16e4f6cc7d248d57ac96d408a4f76))
* **aigateway:** check the parameter contract by revisions.PARAMETER_CONTRACT_KEY ([5992399](https://github.com/ScreamingFace/screamingface/commit/599239908941bfe7b62fa4b8284a03c9d51a741d))
* **aigateway:** delete the dead chat shims and the saved-defaults pipeline (Stage E, E2b) ([#1456](https://github.com/ScreamingFace/screamingface/issues/1456)) ([1f873d9](https://github.com/ScreamingFace/screamingface/commit/1f873d95eda55fe87a5b01d72a038aa49efc1c08))
* **aigateway:** delete the Profile-era core left dead after route retirement (Stage E, E3b) ([#1480](https://github.com/ScreamingFace/screamingface/issues/1480)) ([aac2a1a](https://github.com/ScreamingFace/screamingface/commit/aac2a1ab2e734d182bea48b87304914e0be7e982))
* **aigateway:** exclude Tavily rows from community pages by TAVILY_PROVIDER ([708de24](https://github.com/ScreamingFace/screamingface/commit/708de24dffe4fe7ef2ee1ab11a2a98aea48e9fc2))
* **aigateway:** give the plugin hooks credential names ([#1523](https://github.com/ScreamingFace/screamingface/issues/1523)) ([eb31158](https://github.com/ScreamingFace/screamingface/commit/eb31158de2d6913fda5001e86b8f7863c7bb4e44))
* **aigateway:** make E4a readers connection-only ([#1491](https://github.com/ScreamingFace/screamingface/issues/1491)) ([b66f94f](https://github.com/ScreamingFace/screamingface/commit/b66f94f087a86787623b53f3ea50c0e51312117e))
* **aigateway:** mint a D18 PUT's row at its own address and retire the dead Profile conflict arms ([#1541](https://github.com/ScreamingFace/screamingface/issues/1541)) ([8cb1e54](https://github.com/ScreamingFace/screamingface/commit/8cb1e54e0f6ee8fd71d6f2a14a983e45d70ee9b7))
* **aigateway:** move the credential vocabulary out of profile_models (Stage E, E2a) ([#1458](https://github.com/ScreamingFace/screamingface/issues/1458)) ([4803a77](https://github.com/ScreamingFace/screamingface/commit/4803a77c9974b4708385e4eb87fea31150e0c7a3))
* **aigateway:** rename the contract scope to account_connection ([#1613](https://github.com/ScreamingFace/screamingface/issues/1613)) ([6c5f5c1](https://github.com/ScreamingFace/screamingface/commit/6c5f5c1cb61f93aa034f94de13d46a296a649324))
* **aigateway:** retire the legacy Profile HTTP routes with a 410 (Stage E, E3) ([#1464](https://github.com/ScreamingFace/screamingface/issues/1464)) ([08f5343](https://github.com/ScreamingFace/screamingface/commit/08f5343171422f8a36da02d9bbe901ec73f3af6c))
* **aigateway:** retire the Profile vocabulary from the gateway (Stage E, E5c) ([#1596](https://github.com/ScreamingFace/screamingface/issues/1596)) ([7cb0930](https://github.com/ScreamingFace/screamingface/commit/7cb0930146687c8f2b9df18f5f2958b3afc2b764))
* **aigateway:** stop writing Profile documents ([#1516](https://github.com/ScreamingFace/screamingface/issues/1516)) ([f7e5486](https://github.com/ScreamingFace/screamingface/commit/f7e54869bb84e36f9864808aeb7a0bea8ad09b33))
* **SF-348:** repo re-foundation — remove deprecated desktop/server + stale surface ([#371](https://github.com/ScreamingFace/screamingface/issues/371)) ([9a9cf82](https://github.com/ScreamingFace/screamingface/commit/9a9cf82dfde1085ef9e143571f8e8c547af67976))


### Documentation

* additively refresh repo READMEs — product framing + doc links ([c41c3b5](https://github.com/ScreamingFace/screamingface/commit/c41c3b5813014020b424aab10bd94648a807f361))
* additively refresh repo READMEs — product framing + doc links ([bed4b12](https://github.com/ScreamingFace/screamingface/commit/bed4b121a4c0569bb31923a258feb0dcbefa3325))
* **aigateway:** a replace restore and a late commit can fall behind a pull's cursor ([f894ad9](https://github.com/ScreamingFace/screamingface/commit/f894ad96235cc934488b022db402cc30b0ed8dc3))
* **aigateway:** anonymize deployment examples ([#525](https://github.com/ScreamingFace/screamingface/issues/525)) ([6abd6af](https://github.com/ScreamingFace/screamingface/commit/6abd6af70f69bb425b17058fe05548709476c778))
* **aigateway:** close OME-1541 ledger and mirror, correct the route-test ordering note ([#1437](https://github.com/ScreamingFace/screamingface/issues/1437)) ([8edd994](https://github.com/ScreamingFace/screamingface/commit/8edd994bff69a78b9d3a527335885dd403a0a151))
* **aigateway:** describe the two keyset reads after a cursor, and record what the second review left ([8e3213b](https://github.com/ScreamingFace/screamingface/commit/8e3213be0bbfa118e10fa982781b5a42abc17633))
* **aigateway:** name the litellm check the model-map setting feeds (OME-1615) ([997cb4f](https://github.com/ScreamingFace/screamingface/commit/997cb4f9188cbd67a355d6de19c9535a1c3b0bc0))
* **aigateway:** narrow the frozen-copy fit promise to its two exceptions (OME-1756) ([467e372](https://github.com/ScreamingFace/screamingface/commit/467e372083fd43dab523b422b105671609eb4b82))
* **aigateway:** say what the keyset dedupe and its exhausted flag cover ([405cc1c](https://github.com/ScreamingFace/screamingface/commit/405cc1c574577d07ec7013d7713665725944de6f))
* **aigateway:** state the float-rewrite exception and the old-copies gap (OME-1756) ([214e939](https://github.com/ScreamingFace/screamingface/commit/214e939322db4d75e2f0c2ec3ad6c7958575bf84))
* **aigateway:** the cache-entries route serves the anonymous account when auth is disabled ([3bb7de6](https://github.com/ScreamingFace/screamingface/commit/3bb7de6f6288d6bcbe13967350a8dd6b4a7e3c1e))
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
