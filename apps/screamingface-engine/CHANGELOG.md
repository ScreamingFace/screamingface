# Changelog

## Unreleased

* Attribute collected IFEval model-call failures using the existing collected error kind from the candidate execution boundary, including Gateway-rewritten diagnostic codes. Unmarked errors and protected checker failures retain grading attribution.

## [2.0.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-engine-v1.5.0...screamingface-engine-v2.0.0) (2026-10-02)


### ⚠ BREAKING CHANGES

* **screamingface-engine:** the Engine REST API refuses a nonblank X-Profile header with 400 x_profile_unsupported on the execution, catalog, model-parameter, connection and sync routes. Send requests without the header; a blank value is still accepted as absent.
* **engine:** one executor for every engine request; remove the node tier ([#1085](https://github.com/ScreamingFace/screamingface/issues/1085))

### Features

* **aigateway:** log an unhandled exception once, by class name, with its call id ([db6757b](https://github.com/ScreamingFace/screamingface/commit/db6757bc56a7f6b49b38ae16e7059c06a55cda3f))
* **aigateway:** return full cache metadata on hits and pin the cross-stack hit contract ([#1100](https://github.com/ScreamingFace/screamingface/issues/1100)) ([16bb09a](https://github.com/ScreamingFace/screamingface/commit/16bb09ae38a73eed25576763ba5a73ed65729f0e))
* **chart:** let a platform own the node tier's NetworkPolicy ([#1062](https://github.com/ScreamingFace/screamingface/issues/1062)) ([1f1218e](https://github.com/ScreamingFace/screamingface/commit/1f1218eea8e4ad03e7668cbec6fbbd25504d1385))
* **engine:** attribute candidate model activity to benchmark cases ([#988](https://github.com/ScreamingFace/screamingface/issues/988)) ([36c9f36](https://github.com/ScreamingFace/screamingface/commit/36c9f366a70973507bac24f618abd62759da55fe))
* **engine:** benchmark stage events ([#1056](https://github.com/ScreamingFace/screamingface/issues/1056)) ([4335b94](https://github.com/ScreamingFace/screamingface/commit/4335b946b0b97b736801cb45449cb130a9ed1965))
* **engine:** declare gateway_internal_error in the failure vocabulary ([83b2c99](https://github.com/ScreamingFace/screamingface/commit/83b2c9901e2df5f66612185a78c7247f405b1122))
* **engine:** emit the control-plane accept span; url4.run becomes its child ([fc1cebb](https://github.com/ScreamingFace/screamingface/commit/fc1cebb1311f854804a3fe15ad62a342d084b2ec))
* **engine:** emit the control-plane accept span; url4.run becomes its child (OME-1218) ([d52b726](https://github.com/ScreamingFace/screamingface/commit/d52b7266611796d56ce7634763dbc2dac2ca97f4))
* **engine:** forward the caller's traceparent on the uncoalesced catalog calls ([5aefb75](https://github.com/ScreamingFace/screamingface/commit/5aefb75e8c19ac59d87cb347379d45d6e074bd9f))
* **engine:** forward the caller's traceparent on the uncoalesced catalog calls (OME-1134) ([c53f69e](https://github.com/ScreamingFace/screamingface/commit/c53f69ed7c96907b4fe93db9f0eba0e1f66d0fa1))
* **engine:** retain failed-run evidence past the 60 s subject purge ([4321dc8](https://github.com/ScreamingFace/screamingface/commit/4321dc8f49ba28e6470b0e0b9454662c1e543649))
* **engine:** retain failed-run evidence past the 60 s subject purge (OME-946) ([dcb4ef6](https://github.com/ScreamingFace/screamingface/commit/dcb4ef60777155b951f082e80704a98c3f5eeaa1))
* **engine:** surface the run's error detail and trace_id on the HTTP GET path ([4eca379](https://github.com/ScreamingFace/screamingface/commit/4eca379d1862a77345f5eb46b27bf32f2ae4b0e8))
* **engine:** surface the run's error detail and trace_id on the HTTP GET path ([f3def0e](https://github.com/ScreamingFace/screamingface/commit/f3def0eb83ec8e2126b74191f9c53a1009321760))
* **engine:** update live scores across shipped benchmarks ([#1096](https://github.com/ScreamingFace/screamingface/issues/1096)) ([e59f09b](https://github.com/ScreamingFace/screamingface/commit/e59f09b7d9f2dea43a149acc6eabfd90545211f5))
* **engine:** warn the client about an unclaimed queued run; 503 on broker publish failure ([#1098](https://github.com/ScreamingFace/screamingface/issues/1098)) ([7b76210](https://github.com/ScreamingFace/screamingface/commit/7b762102d460018bee08ac7c4944d3caa52fa471))
* **engine:** wire the dead observability config ([ee8d8e7](https://github.com/ScreamingFace/screamingface/commit/ee8d8e7eca9e57db6a541b740b7b7b9522e69ed5))
* **engine:** wire the dead observability config (OME-942) ([b855410](https://github.com/ScreamingFace/screamingface/commit/b85541002562bec2afd956602c45a77c740c996e))
* **py-screamingface:** refuse undeclared failure codes and pin the list to the engine's ([38768bd](https://github.com/ScreamingFace/screamingface/commit/38768bd3111413ed3a2e613b528db3025998c8f3))
* **screamingface-engine:** accept an answer key that names a choice by its value ([0ba6a62](https://github.com/ScreamingFace/screamingface/commit/0ba6a62eabf2a76f5a464259b632d3ccf189fea6))
* **screamingface-engine:** add the shared benchmark serving spine ([0bb4d58](https://github.com/ScreamingFace/screamingface/commit/0bb4d5809af4403d58b5bab36450bc709fb83731))
* **screamingface-engine:** add the shared benchmark serving spine ([6fda91e](https://github.com/ScreamingFace/screamingface/commit/6fda91e4e220cb3df28a26be4177724994cc80c1))
* **screamingface-engine:** assemble Task-replay Benchmarks, pinned by their Case Digest ([89fd3a1](https://github.com/ScreamingFace/screamingface/commit/89fd3a1cba72f928675ae3565c5c28c811441cc3))
* **screamingface-engine:** bake exactly the questions an inspect eval keeps after loading ([24948df](https://github.com/ScreamingFace/screamingface/commit/24948df6eecb3b16cf9a285ed310bef33c981980))
* **screamingface-engine:** bake exactly the questions an inspect eval keeps, and import onet_m6 ([0f8acf2](https://github.com/ScreamingFace/screamingface/commit/0f8acf234166496dec0deb3f5adacd8c23d1d997))
* **screamingface-engine:** bake gated datasets with a CI token and import xstest_safe ([fdda6f9](https://github.com/ScreamingFace/screamingface/commit/fdda6f9638f44c6f26ca4eae96b4ec8a58d77f37))
* **screamingface-engine:** bake gated datasets with a CI token and import xstest_safe ([c489c65](https://github.com/ScreamingFace/screamingface/commit/c489c65406d17ee36d1867f2a9be5993125bb340))
* **screamingface-engine:** bake sample metadata behind an opt-in and flag judged imports ([bf3d801](https://github.com/ScreamingFace/screamingface/commit/bf3d801a78c06ba56c709d719b13337fe5b35f67))
* **screamingface-engine:** bake sample metadata behind an opt-in and flag judged imports ([6779dff](https://github.com/ScreamingFace/screamingface/commit/6779dff7d55df90d23d0f54a2ecfd33c0fc15604))
* **screamingface-engine:** capture a Task-replay Case from the eval's own solvers ([412a1c9](https://github.com/ScreamingFace/screamingface/commit/412a1c9d102e90641522521a582f18d0bc1d8daa))
* **screamingface-engine:** capture Task-replay Cases from the eval's own solvers ([707636a](https://github.com/ScreamingFace/screamingface/commit/707636aabccff0ec6d6949e9c057f3193bf5f0a8))
* **screamingface-engine:** conserve data_files and features in the inspect importer ([1fd7c86](https://github.com/ScreamingFace/screamingface/commit/1fd7c86850e7136982344380f7bff527f701227b))
* **screamingface-engine:** conserve data_files and features in the inspect importer ([92d1866](https://github.com/ScreamingFace/screamingface/commit/92d18667be2361e89b9e49ac73a6f064c0770185))
* **screamingface-engine:** conserve shuffle_choices in the inspect importer ([e3a902a](https://github.com/ScreamingFace/screamingface/commit/e3a902ad597e1d458eaac54f27756b2e96f82323))
* **screamingface-engine:** conserve shuffle_choices in the inspect importer ([77cd863](https://github.com/ScreamingFace/screamingface/commit/77cd8638dab332bf2ca2228b366ac3375b69b65d))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([b6139b7](https://github.com/ScreamingFace/screamingface/commit/b6139b7ef6d880a9e8f29e2d11d8c9bef01ebdd0))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([382cce8](https://github.com/ScreamingFace/screamingface/commit/382cce8f67738145c64c1280d26fd5eca0ca80b1))
* **screamingface-engine:** declare the failure-code vocabulary and class helpers ([57c39dd](https://github.com/ScreamingFace/screamingface/commit/57c39ddc9893dcb4a8e9665dd6c52445c2d08f86))
* **screamingface-engine:** declare the failure-code vocabulary and class helpers ([253958f](https://github.com/ScreamingFace/screamingface/commit/253958fd7621535fed329753123ed239f2869f98))
* **screamingface-engine:** fail the PR image job when Task-replay Cases change ([ed6883a](https://github.com/ScreamingFace/screamingface/commit/ed6883a985fc3f71e836e7b7cd257d03faebe7b7))
* **screamingface-engine:** grade judges that answer in words ([33c69ae](https://github.com/ScreamingFace/screamingface/commit/33c69ae8daa833e9d80d51bea1abae9421700ddd))
* **screamingface-engine:** grade judges that answer in words ([a231bd2](https://github.com/ScreamingFace/screamingface/commit/a231bd2ab08e2a8d68dda2cb4ade0e6c7f6f3508))
* **screamingface-engine:** grant CORS to the Studio frontend's origins ([832d5ff](https://github.com/ScreamingFace/screamingface/commit/832d5ff9e9a0e5e008f6854478dc27debed8d40f))
* **screamingface-engine:** grant CORS to the Studio frontend's origins ([#1120](https://github.com/ScreamingFace/screamingface/issues/1120)) ([36981e0](https://github.com/ScreamingFace/screamingface/commit/36981e0fccc5e0a016a618eb63bd912cb3e8b30e))
* **screamingface-engine:** import agieval, medqa and mgsm_en by Task replay ([edabf7c](https://github.com/ScreamingFace/screamingface/commit/edabf7c06660eaf6e9c6b72128c344fc27c302da))
* **screamingface-engine:** import agieval, medqa and mgsm_en by Task replay ([75ca257](https://github.com/ScreamingFace/screamingface/commit/75ca2576da18a608918575eacd030f47701ae435))
* **screamingface-engine:** import bbq, piqa, cybermetric, worldsense and sevenllm by Task replay ([b5dc9d9](https://github.com/ScreamingFace/screamingface/commit/b5dc9d9c2f3dbde26a62edcc8a749af6fe728f58))
* **screamingface-engine:** import bbq, piqa, cybermetric, worldsense and sevenllm by Task replay ([a61d5e7](https://github.com/ScreamingFace/screamingface/commit/a61d5e782f2d9b89fe2c1c700978caf1a3c404d7))
* **screamingface-engine:** import Benchmarks by Task replay ([ce4d3b8](https://github.com/ScreamingFace/screamingface/commit/ce4d3b80c7b91a84c160137c541739f3425a00c2))
* **screamingface-engine:** import by Task replay from the CLI and gate the license ([a002037](https://github.com/ScreamingFace/screamingface/commit/a00203720acff5ecd8403c8d6f887b3d626d4782))
* **screamingface-engine:** import coconot's two halves, judged with no answer key ([ff5d6d7](https://github.com/ScreamingFace/screamingface/commit/ff5d6d7acb2fe4aa4e561c1aa20c5b0d458c32fa))
* **screamingface-engine:** import coconot's two halves, judged with no answer key ([1cd2ff1](https://github.com/ScreamingFace/screamingface/commit/1cd2ff10bb7dbbeeb6cf724be348deeecafbb8af))
* **screamingface-engine:** import FrontierScience, the first LLM-judged board ([5d898d8](https://github.com/ScreamingFace/screamingface/commit/5d898d8e4f5bd68b0a1dcfcbe6782fa159f9b21e))
* **screamingface-engine:** import FrontierScience, the first LLM-judged board ([a9ba30a](https://github.com/ScreamingFace/screamingface/commit/a9ba30adbe59140d54bd48c71ab5c16b44237dc0))
* **screamingface-engine:** import hellaswag, delivering its system instruction as leading input text ([c901210](https://github.com/ScreamingFace/screamingface/commit/c9012107d0b3d05d26b9b98f473489c757472c01))
* **screamingface-engine:** import hellaswag, delivering its system instruction as leading input text ([a4c5a92](https://github.com/ScreamingFace/screamingface/commit/a4c5a92887612d2c1d58fe683e17e4603d4885a5))
* **screamingface-engine:** import onet_m6 with its chain-of-thought prompt and a named exclusion ([ab8086b](https://github.com/ScreamingFace/screamingface/commit/ab8086b613d619a082f4007b129b135d1f4a30d9))
* **screamingface-engine:** import pubmedqa through its question filter ([ff1ac82](https://github.com/ScreamingFace/screamingface/commit/ff1ac82bd224c875f62c6622bb0b49a249eb292b))
* **screamingface-engine:** import pubmedqa through the task route ([af17a44](https://github.com/ScreamingFace/screamingface/commit/af17a447ed639dfc3495e9874925594bb6b0fefd))
* **screamingface-engine:** import the aime24 board ([abe90d0](https://github.com/ScreamingFace/screamingface/commit/abe90d09957cbfc7ad6e0741f4acb0a517e4298c))
* **screamingface-engine:** import the aime24 board ([916ddae](https://github.com/ScreamingFace/screamingface/commit/916ddae7911dfd9f45e463375590fae48b5d011e))
* **screamingface-engine:** import the aime25 board ([5005083](https://github.com/ScreamingFace/screamingface/commit/5005083b1ac61d2e8048cd31db38574e9e981bfe))
* **screamingface-engine:** import the aime25 board with a pinned serving shuffle ([1609a03](https://github.com/ScreamingFace/screamingface/commit/1609a03f80d481a6167eb3e3245cc1f21e474fdc))
* **screamingface-engine:** import the musr and wmdp boards ([733531c](https://github.com/ScreamingFace/screamingface/commit/733531cc743501166f37dfb28976ed87d576a41b))
* **screamingface-engine:** import the musr and wmdp boards ([7bf89ee](https://github.com/ScreamingFace/screamingface/commit/7bf89eeb76d70137b78e83d05daa44affb1ba7fe))
* **screamingface-engine:** import the six text LAB-Bench boards ([dd5b8e2](https://github.com/ScreamingFace/screamingface/commit/dd5b8e2d1c009cde911006ac62ff38614832feb0))
* **screamingface-engine:** import the six text LAB-Bench boards ([d9924b2](https://github.com/ScreamingFace/screamingface/commit/d9924b2c42738b31774f49803208655465e81f92))
* **screamingface-engine:** let a judged board's judge fill inspect's grader role ([8789dbc](https://github.com/ScreamingFace/screamingface/commit/8789dbc593f356e274c820bfa8fa0742742dac85))
* **screamingface-engine:** let a judged board's judge fill inspect's grader role ([84708ce](https://github.com/ScreamingFace/screamingface/commit/84708cefa5032e9cbb2abc37c4582e80ef6d5733))
* **screamingface-engine:** make the judge exam identity and bind its transport ([37a9e64](https://github.com/ScreamingFace/screamingface/commit/37a9e644ed419b7d054530dd83e3e9c5171c2fa3))
* **screamingface-engine:** make the judge exam identity and bind its transport ([575bb34](https://github.com/ScreamingFace/screamingface/commit/575bb3414bbcb7fd468248f83a9cd5e68f5ad5ae))
* **screamingface-engine:** per-case judge accounting and case-tagged judge log lines ([b76c195](https://github.com/ScreamingFace/screamingface/commit/b76c195af1dc56c463ff233a08af21953033a33c))
* **screamingface-engine:** per-case judge accounting and case-tagged judge log lines ([760fa4f](https://github.com/ScreamingFace/screamingface/commit/760fa4f0be925f97bd20dfd27d82a983df4f97a9))
* **screamingface-engine:** pin a serving shuffle for aime24 ([fb86302](https://github.com/ScreamingFace/screamingface/commit/fb863020870ca4de2ecc7eb08ecda781b4d04442))
* **screamingface-engine:** prepare Task-replay Benchmarks and check their Case Digest ([654ee62](https://github.com/ScreamingFace/screamingface/commit/654ee62746dfef6930e12973a764cc587bb1e32f))
* **screamingface-engine:** prepare Task-replay Cases in a clean child process, served only when their Case Digest matches ([50c68d9](https://github.com/ScreamingFace/screamingface/commit/50c68d9ea82baf91f69c45a49bc61b221b27c71a))
* **screamingface-engine:** read provider-access availability for hosted listings ([#1007](https://github.com/ScreamingFace/screamingface/issues/1007)) ([54fa867](https://github.com/ScreamingFace/screamingface/commit/54fa867391894b3c7594a673ed22e375c4907662))
* **screamingface-engine:** reclassify the catch-all failure sites into named classes ([03da591](https://github.com/ScreamingFace/screamingface/commit/03da59170439cee88661ce8a8578c1277b1bcae9))
* **screamingface-engine:** reclassify the catch-all failure sites into named classes ([4a5ec59](https://github.com/ScreamingFace/screamingface/commit/4a5ec59c1907f98e6c335ad765ccaa0b8f020a56))
* **screamingface-engine:** record every Case Source a Task replay fetches from ([d73fbc5](https://github.com/ScreamingFace/screamingface/commit/d73fbc52d95f980a68b651d765681af82c861e27))
* **screamingface-engine:** refuse undeclared failure codes on the Failure model ([1e18f6c](https://github.com/ScreamingFace/screamingface/commit/1e18f6cbadfb912d0e636e8b68b69de4aaec9920))
* **screamingface-engine:** refuse undeclared failure codes on the Failure model ([1b2857f](https://github.com/ScreamingFace/screamingface/commit/1b2857f01a7d6331cf0aed66cbc9d6ce8e03b9a2))
* **screamingface-engine:** refuse X-Profile at ingress and stop producing selector-bearing runs ([#1082](https://github.com/ScreamingFace/screamingface/issues/1082)) ([df6e9b9](https://github.com/ScreamingFace/screamingface/commit/df6e9b92d1a55fb7c3a898164c82fea117522d5c))
* **screamingface-engine:** render a Task-replay declaration with its Case Sources ([7458c8a](https://github.com/ScreamingFace/screamingface/commit/7458c8a0cdf17bc9d36aaf3675c314769a092a19))
* **screamingface-engine:** render a Task-replay import by capture ([f285062](https://github.com/ScreamingFace/screamingface/commit/f285062b009ddb4f6cd5c86b1686c3541b4933ca))
* **screamingface-engine:** replay a task for import with Case Sources and facts ([d481926](https://github.com/ScreamingFace/screamingface/commit/d481926fc9e8e607eedfee02ff13d52cf80e8cb8))
* **screamingface-engine:** route imported evals' judge calls through the gateway ([634f8e7](https://github.com/ScreamingFace/screamingface/commit/634f8e7e4dc0a69071241b917e57407ab7605d7b))
* **screamingface-engine:** route imported evals' judge calls through the gateway ([39ff656](https://github.com/ScreamingFace/screamingface/commit/39ff65617929842d42c2b9e535c442f93538e432))
* **screamingface-engine:** route the four fetch-blind refusals to Task replay ([15963c8](https://github.com/ScreamingFace/screamingface/commit/15963c8098a254c7d648466655e1f25438f00e36))
* **screamingface-engine:** score should-refuse Benchmarks by refusal rate ([ff41c93](https://github.com/ScreamingFace/screamingface/commit/ff41c93732453df753e08ecde6dc5142ffb16cb8))
* **screamingface-engine:** score should-refuse Benchmarks by refusal rate ([8a8e965](https://github.com/ScreamingFace/screamingface/commit/8a8e965a9e585cdadd582e3d54d393c9519ccf4c))
* **screamingface-engine:** seal a Task-replay import with a digest two runs agree on ([e974419](https://github.com/ScreamingFace/screamingface/commit/e974419f8960bb117523b1d0f9aeb56ba889c8b3))
* **screamingface-engine:** serve url4 mounts as a sync REST surface beside the ensemble path ([#1030](https://github.com/ScreamingFace/screamingface/issues/1030)) ([c6774ea](https://github.com/ScreamingFace/screamingface/commit/c6774ea1132e288659695d9dba18d379a95548ea))
* **screamingface-engine:** share the Case writer and add the Case Digest ([52359b3](https://github.com/ScreamingFace/screamingface/commit/52359b34dae5055ba6ecdbd62d67a7b9678a1488))
* **screamingface-engine:** show imported judges' reasoning in the notebook report ([6323ec8](https://github.com/ScreamingFace/screamingface/commit/6323ec88303b75af00dec8a511ca4ad0e7448916))
* **screamingface-engine:** show imported judges' reasoning in the notebook report ([3d61739](https://github.com/ScreamingFace/screamingface/commit/3d6173958307cb3f0eb2f2d4d14fe226fffa625a))
* **screamingface-engine:** treat Samples that carry choices as MCQ-shaped ([4cf1469](https://github.com/ScreamingFace/screamingface/commit/4cf1469856fa724ba728c8b9a7962761fe17098a))
* **screamingface:** mark Benchmarks scored by refusal rate in report.json ([a89a190](https://github.com/ScreamingFace/screamingface/commit/a89a19004219ec7a84c3f54a8ff185c8889297ee))
* **screamingface:** mark Benchmarks scored by refusal rate in report.json ([bf256b4](https://github.com/ScreamingFace/screamingface/commit/bf256b43e9cd6d354f3a5b3ffec8cb4f9d37fefb))


### Bug Fixes

* attribute judge activity and simplify log display ([#1071](https://github.com/ScreamingFace/screamingface/issues/1071)) ([3293550](https://github.com/ScreamingFace/screamingface/commit/3293550b3d0dd8cc87798a70a4cffde9c42da2e0))
* **engine:** attribute failures at the candidate execution boundary ([#1060](https://github.com/ScreamingFace/screamingface/issues/1060)) ([a59d82e](https://github.com/ScreamingFace/screamingface/commit/a59d82e87c40cdc10a48c675e00f47964898f1ec))
* **engine:** bound the OTLP flush and report dropped spans ([fd565a2](https://github.com/ScreamingFace/screamingface/commit/fd565a2fdff92c70f648f25f999f7101ddca2217))
* **engine:** bound the OTLP flush and report dropped spans ([e711c31](https://github.com/ScreamingFace/screamingface/commit/e711c313b6ab7fde5c2ac00d15c02e2cbda9ecbd))
* **engine:** enforce the OTLP close bound and count refused spans ([b796c4a](https://github.com/ScreamingFace/screamingface/commit/b796c4adabd1fa8b2225c38f07f5d7a2e3e9fffa))
* **engine:** flag a system message inspect rewrites before sending ([2b7fb6b](https://github.com/ScreamingFace/screamingface/commit/2b7fb6bf7d304f98565f394872bd946cdecf1405))
* **engine:** gate only the cold start on broker readiness (OME-942 D8) ([2a57398](https://github.com/ScreamingFace/screamingface/commit/2a5739853207a0ae26b20588d5b0653df686f8a1))
* **engine:** make the terminal-error allowlist actually vouch for the message ([0b6b0ae](https://github.com/ScreamingFace/screamingface/commit/0b6b0ae38916fa15c1bb7cb42f7729ae1734c845))
* **engine:** parent aigateway spans to the calling node, not the run root ([a2c3375](https://github.com/ScreamingFace/screamingface/commit/a2c3375daf13c139d865fb4ea82c4812aa12b59f))
* **engine:** parent aigateway spans to the calling node, not the run root ([ba5a28d](https://github.com/ScreamingFace/screamingface/commit/ba5a28dc2e72e4aa605ca5323c342d01184d1fb3))
* **engine:** pin the content screen and report control-plane terminal codes (OME-941) ([281ffac](https://github.com/ScreamingFace/screamingface/commit/281ffac6246ec52b002e4318b800ba8eb6fa4c0d))
* **engine:** refuse a task that applies two prompt templates ([b531cb5](https://github.com/ScreamingFace/screamingface/commit/b531cb5a3d8c9bf3d41ebf6d3b169d9de44c1a7e))
* **engine:** refuse file prompt templates, flag repeated and setup system messages ([62c1403](https://github.com/ScreamingFace/screamingface/commit/62c1403b8791eb7cdd7dfc7993668557ddb438cf))
* **engine:** report a missing row's real cause as its failure code ([f5a26db](https://github.com/ScreamingFace/screamingface/commit/f5a26db082e3cae3d70310da297cdc8c75608dd8))
* **engine:** report a missing row's real cause as its failure code ([3008da6](https://github.com/ScreamingFace/screamingface/commit/3008da684c6ef9f31d2a8c125fe62538d4537d51))
* **engine:** stop /readyz leaking the NATS URL and stop it blocking ([8254aa2](https://github.com/ScreamingFace/screamingface/commit/8254aa2b620dcef7148418a1bdfcb5d58ed6fc70))
* **engine:** stop the importer baking prompt text inspect rewrites ([b06959f](https://github.com/ScreamingFace/screamingface/commit/b06959ff74277ae2018ca78822b9ba18ae7ecec3))
* **py-screamingface:** make the conformance bind fire on either side's drift ([b4c6521](https://github.com/ScreamingFace/screamingface/commit/b4c6521d0da1f9e45885b6483573cfbba7828642))
* **screamingface-engine:** allowlist the judge's config and refuse tool-bearing judge calls ([6ca658a](https://github.com/ScreamingFace/screamingface/commit/6ca658a20f1394223b7ad4241100b46a11a1bc05))
* **screamingface-engine:** bind the importer through inspect_evals' variadic hf_dataset wrapper ([673c534](https://github.com/ScreamingFace/screamingface/commit/673c53439a7ee5b063dbc1a6e86b7121ba1fb7cf))
* **screamingface-engine:** bind the importer through inspect_evals' variadic hf_dataset wrapper ([0e89314](https://github.com/ScreamingFace/screamingface/commit/0e893149e1bfda9f894a2b7b0b129fa19974cb66))
* **screamingface-engine:** close the task-route gaps from review ([feaa6ba](https://github.com/ScreamingFace/screamingface/commit/feaa6bab07bb24c4be1d9f69cf0ee4eb68add394))
* **screamingface-engine:** close the xstest and CI-token gaps from review ([a11b685](https://github.com/ScreamingFace/screamingface/commit/a11b68512c1bcaa38676193cd548a1ccc1a7be59))
* **screamingface-engine:** declare contracteval's failure codes so a failed case reports instead of crashing ([fa8bbe8](https://github.com/ScreamingFace/screamingface/commit/fa8bbe859d8499c6a827e1f5f2a68a3c4cb6ab4c))
* **screamingface-engine:** declare contracteval's failure codes so failed cases report instead of crashing ([39cea39](https://github.com/ScreamingFace/screamingface/commit/39cea39fcc77ec08487b998429f86d3ab2cc7482))
* **screamingface-engine:** detect judged rows by kwarg, grade them on the run's loop, pin published revisions ([2c627ae](https://github.com/ScreamingFace/screamingface/commit/2c627aeba549bc81bed362f214bceeaf3885133f))
* **screamingface-engine:** detect MCQ by solver and render str scorer kwargs format-safe ([816e7a5](https://github.com/ScreamingFace/screamingface/commit/816e7a50e6d1f9f317acbd7c3fdd073c63da8853))
* **screamingface-engine:** detect MCQ by solver or choice scorer ([0ed4a96](https://github.com/ScreamingFace/screamingface/commit/0ed4a96a1b14ecb21e441186dea1517655d0fef5))
* **screamingface-engine:** give xstest_unsafe's conversion to inspect's refusal rate ([18ee645](https://github.com/ScreamingFace/screamingface/commit/18ee645c8894368bf1cc3970dad1d839d95e5b23))
* **screamingface-engine:** honest comparability note and three board-level pins for FrontierScience ([5190a53](https://github.com/ScreamingFace/screamingface/commit/5190a5372acc5d3d2a62e2bd6191fd4205318cea))
* **screamingface-engine:** identity-check the hf_dataset shim; harden importer refusals ([d83096d](https://github.com/ScreamingFace/screamingface/commit/d83096d5bb99d6c49184b5c8a002061559d85b8a))
* **screamingface-engine:** importer detects MCQ by solver and renders str scorer kwargs format-safe ([33d8ec6](https://github.com/ScreamingFace/screamingface/commit/33d8ec6d59fd39d6a35b07895571ad696dbb1125))
* **screamingface-engine:** json-encode scorer kwarg names in generated boards ([bda116d](https://github.com/ScreamingFace/screamingface/commit/bda116d8c6329290749b670e0d825a80334c8fe9))
* **screamingface-engine:** judged grading survives bad judge replies and stays on the run's loop ([521d215](https://github.com/ScreamingFace/screamingface/commit/521d2155958bd995cacd0562e3f02d3d08b0b2de))
* **screamingface-engine:** keep every model out of the capture child and give each Sample its own context ([1c2967c](https://github.com/ScreamingFace/screamingface/commit/1c2967c31ce8a9519214289c39bb43535d58b952))
* **screamingface-engine:** keep one Task replay's odd output from crashing the image build ([6b7b2e6](https://github.com/ScreamingFace/screamingface/commit/6b7b2e6471d73ada1138aa8bf3d18cb170bcac9e))
* **screamingface-engine:** let a judge keep the cache setting an eval hands it ([054a06a](https://github.com/ScreamingFace/screamingface/commit/054a06a8033a55409db7890cc0b1d76179c4fe16))
* **screamingface-engine:** let a judge keep the cache setting an eval hands it ([891c57c](https://github.com/ScreamingFace/screamingface/commit/891c57c6bb07afa6536d9b2ca706193fb02e7f30))
* **screamingface-engine:** make the Case Digest survive a JSON round trip ([aa451f3](https://github.com/ScreamingFace/screamingface/commit/aa451f3c23453031ce097c91f0c1d3a87f6490df))
* **screamingface-engine:** migrate the fourth DRACO-pinning test — the e2e failure tape ([1c5f93e](https://github.com/ScreamingFace/screamingface/commit/1c5f93ef359c00bcac0db493e420552f08177f62))
* **screamingface-engine:** pin a hellaswag serving shuffle and ride the system message on exam identity ([0c672d6](https://github.com/ScreamingFace/screamingface/commit/0c672d6ceb3caadc95d5d452c44f65a4626a769f))
* **screamingface-engine:** pin inspect back to the versions the published exams use ([e546d51](https://github.com/ScreamingFace/screamingface/commit/e546d5169a9da19a10747ec51ae3725f3af65a0e))
* **screamingface-engine:** redirect every replay cache, keep SKIPPED reasons to one line ([601dff2](https://github.com/ScreamingFace/screamingface/commit/601dff27237bc17a06672e75800fffd4b5353991))
* **screamingface-engine:** refuse combined shuffles when upstream seeds either one ([6078abe](https://github.com/ScreamingFace/screamingface/commit/6078abeeb6927db5ef0e85781afd842170027a17))
* **screamingface-engine:** refuse model_role=None on a role-bound judge; pin per-task roles ([ee6e1f3](https://github.com/ScreamingFace/screamingface/commit/ee6e1f399c6dba99db8f235933b3784304b74d56))
* **screamingface-engine:** refuse seed override and name choice-shuffle bake failures ([a940453](https://github.com/ScreamingFace/screamingface/commit/a940453150b329f15781502d0bda3ff918a1782a))
* **screamingface-engine:** report a Task-replay refusal from the command as an error line ([e51631e](https://github.com/ScreamingFace/screamingface/commit/e51631e51bc133ddb9a8452eac309438f9ea6d63))
* **screamingface-engine:** restore the data_files typing tightened off the pre-rebase branch ([ae1ae2b](https://github.com/ScreamingFace/screamingface/commit/ae1ae2bdfd1d163b3a261a04e32e6d8ade7214c4))
* **screamingface-engine:** restore the two importer fixes clobbered off the mcq-family branch ([e193463](https://github.com/ScreamingFace/screamingface/commit/e1934638049e6310e3e2c836a636db5dbcac5d14))
* **screamingface-engine:** say MedQA asks five options, not four ([a083ff2](https://github.com/ScreamingFace/screamingface/commit/a083ff2b26952afe4f288c6f9bb20536a8b02b2b))
* **screamingface-engine:** surface the folded source spelling at every public_error consumer ([8de8164](https://github.com/ScreamingFace/screamingface/commit/8de816471d812d28917b4ccf2be9e4e13e689521))
* **screamingface-engine:** tag render-time Case Sources, refuse inert seed flags on a Task-replay import ([ee7eb9d](https://github.com/ScreamingFace/screamingface/commit/ee7eb9d9fc05cae3fdca371f48ab584fbccbe0d5))
* **screamingface-engine:** the importer detects judged rows by kwarg and never pairs them with a check surface ([146adae](https://github.com/ScreamingFace/screamingface/commit/146adaebaa06c00e512b5e78ad0f65d9394b3eea))
* **screamingface-engine:** tighten data_files typing and correct a test docstring ([20f4235](https://github.com/ScreamingFace/screamingface/commit/20f423528a6b342d632c3dd1784cf4af48a6daf8))
* **screamingface-engine:** type the recorder for the extra-less typecheck CI runs ([83927e8](https://github.com/ScreamingFace/screamingface/commit/83927e85a8aa1e99c45bffc8f478940e16df59c1))
* **screamingface:** keep the SDK's inspect-ai pin on the Engine's version ([98a234e](https://github.com/ScreamingFace/screamingface/commit/98a234e1e657a94872d3a8ccd167d57d2111f7b5))
* **screamingface:** pin the inverted_grade key's spelling on both sides ([a7381c3](https://github.com/ScreamingFace/screamingface/commit/a7381c323903220a1df19a30b074fe4fb4eb2b8d))
* **screamingface:** pin the SDK's inspect-ai to the Engine's version and bind them ([2d03a8f](https://github.com/ScreamingFace/screamingface/commit/2d03a8f2338b16b251509ab803561f6eeab3a620))
* **screamingface:** resume the same capability after reconnect challenges and show reconnect progress ([#1099](https://github.com/ScreamingFace/screamingface/issues/1099)) ([d4af3cc](https://github.com/ScreamingFace/screamingface/commit/d4af3ccf5113cc7d1d5bd5bed1ab1e7bfb3bf056))


### Refactors

* **engine:** one executor for every engine request; remove the node tier ([#1085](https://github.com/ScreamingFace/screamingface/issues/1085)) ([d64d5e9](https://github.com/ScreamingFace/screamingface/commit/d64d5e942b37fab45ce14f95a015ee9a2e44a775))
* **screamingface-engine:** finish the bind_* renames on the record builders ([d1e66e1](https://github.com/ScreamingFace/screamingface/commit/d1e66e1f89ddbd9c661774d6532f8d4dceba8f2d))
* **screamingface-engine:** keep Sample for what is still an inspect Sample ([a1256cc](https://github.com/ScreamingFace/screamingface/commit/a1256ccc230205632ce6b3981ce16d8d2c5bd2ac))
* **screamingface-engine:** move the pubmedqa board to the question-filter names ([067f990](https://github.com/ScreamingFace/screamingface/commit/067f990b283da52d521d9070f09d21e229f9519f))
* **screamingface-engine:** name _cases_declaration's parameter benchmark_key ([1c1a941](https://github.com/ScreamingFace/screamingface/commit/1c1a9417c0a53376608c9cb08319415e5a98af1b))
* **screamingface-engine:** name our own concepts in our words, not inspect's ([88559b9](https://github.com/ScreamingFace/screamingface/commit/88559b976d2b29c22f08d7a33bf382f1bddacb25))
* **screamingface-engine:** name the grader-role judge by inspect's own model_role ([6aa1c5e](https://github.com/ScreamingFace/screamingface/commit/6aa1c5e0b308a7c7bea0db3fc2499ef8622879cb))
* **screamingface-engine:** name the inspect plugin's parts by what they do ([b7a4e65](https://github.com/ScreamingFace/screamingface/commit/b7a4e651d995337f38e274d35da5b96a5f4148bb))
* **screamingface-engine:** name the post-load filter in plain words before it lands ([3e5cd7f](https://github.com/ScreamingFace/screamingface/commit/3e5cd7fb93205382942968072dae0498acb9d876))
* **screamingface-engine:** name the shared grading code, phases and judge requests plainly ([445d1e1](https://github.com/ScreamingFace/screamingface/commit/445d1e14478e770f6c82976969e0b12222b0391d))
* **screamingface-engine:** name the strict switch for what it does ([8c1bbc7](https://github.com/ScreamingFace/screamingface/commit/8c1bbc7f25e684c133691043f4a7b0f3f6de91e9))
* **screamingface-engine:** rename the benchmark code to the glossary's words ([d4685ca](https://github.com/ScreamingFace/screamingface/commit/d4685caea6110a2a7b18b45f0148c3438216fe90))
* **screamingface-engine:** rename the wire-contract Python names, keep every wire string ([48b42cd](https://github.com/ScreamingFace/screamingface/commit/48b42cd5343ebd9b115c8780955b25f65f7569ce))
* **screamingface-engine:** say "needs an HF token" instead of "gated" ([aa9ac1b](https://github.com/ScreamingFace/screamingface/commit/aa9ac1ba4fee9a13ce0d18184bb4d3603ca748fa))
* **screamingface-engine:** say benchmark, not board ([3892c57](https://github.com/ScreamingFace/screamingface/commit/3892c57562e6ef7f49fdaca561403a6eef06d793))
* **screamingface-engine:** say prepare, not bake ([69ce0bd](https://github.com/ScreamingFace/screamingface/commit/69ce0bd45b1a1df4baa1307c3cc5c5952bd20578))
* **screamingface-engine:** say variant, not exam; case grade, not row ([c21b33a](https://github.com/ScreamingFace/screamingface/commit/c21b33ae5eae62b653277e324ac1654132507479))
* **screamingface-engine:** serve contracteval from the benchmark spine ([474ce8d](https://github.com/ScreamingFace/screamingface/commit/474ce8d4999e4118dcd518e7d6635459e23e91a6))
* **screamingface-engine:** serve contracteval from the benchmark spine ([af7d9eb](https://github.com/ScreamingFace/screamingface/commit/af7d9eb80704e1a7690391dc4920f3e1d53bd214))
* **screamingface-engine:** serve medxpert from the benchmark spine ([7c7e422](https://github.com/ScreamingFace/screamingface/commit/7c7e42263dde29bad1c1b04ebe778ebc5f1a13a7))
* **screamingface-engine:** serve medxpert from the benchmark spine ([e97de4e](https://github.com/ScreamingFace/screamingface/commit/e97de4e86142e7b8f42baebd4eabc39624d27aa1))
* **screamingface-engine:** use our own words where the engine borrowed inspect's ([42baa98](https://github.com/ScreamingFace/screamingface/commit/42baa9886e53a94c0abb4eb01859fb0d62f21088))


### Documentation

* close the OME-1404 ledger and mirror ([de54bb0](https://github.com/ScreamingFace/screamingface/commit/de54bb08507fa69a86139cb5218c440940b765d9))
* **engine:** state the missing-row rule exactly in the row reader ([3fe9029](https://github.com/ScreamingFace/screamingface/commit/3fe90299555acd71c61525f5bf9e3ed4d02416f4))
* **screamingface-engine:** cite both inspect versions the role fallback was verified on ([45fba7e](https://github.com/ScreamingFace/screamingface/commit/45fba7ed624eff46379defacc57b31a3865982e5))
* **screamingface-engine:** cite the inspect version the role fallback is verified on ([a7ac293](https://github.com/ScreamingFace/screamingface/commit/a7ac2935f7b0ded690aa7c24e51b9eba321924e1))
* **screamingface-engine:** document what we take from an inspect eval and who runs each step ([ec11a06](https://github.com/ScreamingFace/screamingface/commit/ec11a060875efc9657151b743cef2c14efddd7ed))
* **screamingface-engine:** document what we take from an inspect eval and who runs each step ([33f009b](https://github.com/ScreamingFace/screamingface/commit/33f009bbde87bb5de7f90190713e9c42ede9fc5f))
* **screamingface-engine:** explain why inspect is one call and we are many parts ([70f185f](https://github.com/ScreamingFace/screamingface/commit/70f185f99aec8ecce820e5c805717414b2955758))
* **screamingface-engine:** fix review round 1 on the inspect import page ([69de05d](https://github.com/ScreamingFace/screamingface/commit/69de05d925a8642a9dce8986ea3889d3f70dfd25))
* **screamingface-engine:** judge-declaration checklist item and review-round ledger ([9681844](https://github.com/ScreamingFace/screamingface/commit/9681844d833a48f34713afba393a72c1c6dc642f))
* **screamingface-engine:** mark capture as open PR in the eval-split diagram; record review round 1 in the ledger ([9582ce6](https://github.com/ScreamingFace/screamingface/commit/9582ce65b8ff69c941281df027855e8690c8e9b2))
* **screamingface-engine:** model-graded imports are in scope — correct the env-var judge plan ([f17ad00](https://github.com/ScreamingFace/screamingface/commit/f17ad0006f69e92d1a11cb9a9444e7219e3a852e))
* **screamingface-engine:** model-graded imports are in scope — correct the env-var judge plan ([4be2c98](https://github.com/ScreamingFace/screamingface/commit/4be2c980e8500d4246130d1fc8906590069f1edf))
* **screamingface-engine:** name the test behind the preflight late-binding note ([f3c74b5](https://github.com/ScreamingFace/screamingface/commit/f3c74b5b2599611c381d0d39135f70220cf70449))
* **screamingface-engine:** pin the ContractEval harness citations to its commit ([09efd6e](https://github.com/ScreamingFace/screamingface/commit/09efd6ecf03559360b39f557c51fd8a2a24440d0))
* **screamingface-engine:** pin the one-candidate-per-captured-run invariant on the grading owner ([796c510](https://github.com/ScreamingFace/screamingface/commit/796c51019948b43eead406d5e7cfe5edc3f96ee1))
* **screamingface-engine:** runbook carries the judged lane's late learnings ([db8c9bf](https://github.com/ScreamingFace/screamingface/commit/db8c9bfe94573a1e3d519068c0850f11b265c493))
* **screamingface-engine:** say Case, answer key and Grading where inspect's words meant ours ([766b495](https://github.com/ScreamingFace/screamingface/commit/766b495aa4d6e0081d2afb84ccab32b9f1b82d02))
* **screamingface-engine:** walk eval()'s five per-Sample steps and where OME-1273 cuts them ([4ecb008](https://github.com/ScreamingFace/screamingface/commit/4ecb00888e51a9256a4fd4033ba86eeedc462b06))
* **screamingface:** teach the judged board in the catalogue notebook ([fd36c2b](https://github.com/ScreamingFace/screamingface/commit/fd36c2beeda9f3b788350b786e4829ef4e2735c7))

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
