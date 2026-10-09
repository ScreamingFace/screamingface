# Changelog

## Unreleased

* Attribute collected IFEval model-call failures using the existing collected error kind from the candidate execution boundary, including Gateway-rewritten diagnostic codes. Unmarked errors and protected checker failures retain grading attribution.

## [2.0.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-engine-v1.5.0...screamingface-engine-v2.0.0) (2026-10-09)


### ⚠ BREAKING CHANGES

* **screamingface-engine:** the Engine REST API refuses a nonblank X-Profile header with 400 x_profile_unsupported on the execution, catalog, model-parameter, connection and sync routes. Send requests without the header; a blank value is still accepted as absent.
* **engine:** one executor for every engine request; remove the node tier ([#1085](https://github.com/ScreamingFace/screamingface/issues/1085))

### Features

* **aigateway:** log an unhandled exception once, by class name, with its call id ([db6757b](https://github.com/ScreamingFace/screamingface/commit/db6757bc56a7f6b49b38ae16e7059c06a55cda3f))
* **aigateway:** return full cache metadata on hits and pin the cross-stack hit contract ([#1100](https://github.com/ScreamingFace/screamingface/issues/1100)) ([16bb09a](https://github.com/ScreamingFace/screamingface/commit/16bb09ae38a73eed25576763ba5a73ed65729f0e))
* **engine:** cap retained failed-run subjects and cover the runner hand-offs ([#1238](https://github.com/ScreamingFace/screamingface/issues/1238)) ([efeb662](https://github.com/ScreamingFace/screamingface/commit/efeb66261ea3fed07acbb885755e6a0665f1521a))
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
* **screamingface-engine:** a local Task's Benchmark id is its bare key, not inspect-&lt;key&gt; ([c665820](https://github.com/ScreamingFace/screamingface/commit/c665820af4192ad1aa25d6421392469652053911))
* **screamingface-engine:** accept an answer key that names a choice by its value ([0ba6a62](https://github.com/ScreamingFace/screamingface/commit/0ba6a62eabf2a76f5a464259b632d3ccf189fea6))
* **screamingface-engine:** assemble Task-replay Benchmarks, pinned by their Case Digest ([89fd3a1](https://github.com/ScreamingFace/screamingface/commit/89fd3a1cba72f928675ae3565c5c28c811441cc3))
* **screamingface-engine:** bake exactly the questions an inspect eval keeps after loading ([24948df](https://github.com/ScreamingFace/screamingface/commit/24948df6eecb3b16cf9a285ed310bef33c981980))
* **screamingface-engine:** bake exactly the questions an inspect eval keeps, and import onet_m6 ([0f8acf2](https://github.com/ScreamingFace/screamingface/commit/0f8acf234166496dec0deb3f5adacd8c23d1d997))
* **screamingface-engine:** bake gated datasets with a CI token and import xstest_safe ([fdda6f9](https://github.com/ScreamingFace/screamingface/commit/fdda6f9638f44c6f26ca4eae96b4ec8a58d77f37))
* **screamingface-engine:** bake gated datasets with a CI token and import xstest_safe ([c489c65](https://github.com/ScreamingFace/screamingface/commit/c489c65406d17ee36d1867f2a9be5993125bb340))
* **screamingface-engine:** capture a Task-replay Case from the eval's own solvers ([412a1c9](https://github.com/ScreamingFace/screamingface/commit/412a1c9d102e90641522521a582f18d0bc1d8daa))
* **screamingface-engine:** capture Task-replay Cases from the eval's own solvers ([707636a](https://github.com/ScreamingFace/screamingface/commit/707636aabccff0ec6d6949e9c057f3193bf5f0a8))
* **screamingface-engine:** carry a Benchmark's Named Scores through grading ([eb43a3b](https://github.com/ScreamingFace/screamingface/commit/eb43a3b4ebeeae9c66b852f2b625a2c20820a4f9))
* **screamingface-engine:** carry a Benchmark's Named Scores through grading (OME-1268, PR 3 of 5) ([1637fd3](https://github.com/ScreamingFace/screamingface/commit/1637fd3b518323572c5b985fa76288a9e25848d3))
* **screamingface-engine:** declare Benchmark provenance and serve a saturation verdict ([7d1efb4](https://github.com/ScreamingFace/screamingface/commit/7d1efb4b61d1c06ea0acb014b44ad966a3947a25))
* **screamingface-engine:** declare Benchmark provenance and serve a saturation verdict (OME-1455, PR 2 of 4) ([8561d57](https://github.com/ScreamingFace/screamingface/commit/8561d57af23c348ad4ae2885b04853d6e28fb54c))
* **screamingface-engine:** enforce the declaration's Hub revision and seeds in Task replay (OME-1460, PR 1 of 2) ([44fe60a](https://github.com/ScreamingFace/screamingface/commit/44fe60a33402bf720c0db6636ff2945d3903b587))
* **screamingface-engine:** fail the PR image job when Task-replay Cases change ([ed6883a](https://github.com/ScreamingFace/screamingface/commit/ed6883a985fc3f71e836e7b7cd257d03faebe7b7))
* **screamingface-engine:** force the declaration's Hub revision and seeds on a replay's fetches ([acb25a0](https://github.com/ScreamingFace/screamingface/commit/acb25a054229da7da654af2cefb6559f8ddfe4aa))
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
* **screamingface-engine:** import four SAD-mini tasks by Task replay ([57115f1](https://github.com/ScreamingFace/screamingface/commit/57115f12b5fbc0a6ab297484d7055b8fbd3bded2))
* **screamingface-engine:** import MATH and SQuAD with Named Scores ([3268965](https://github.com/ScreamingFace/screamingface/commit/326896527acefd4f4364398f295abf8b0b44132a))
* **screamingface-engine:** import MATH and SQuAD with Named Scores (OME-1268, PR 5 of 5) ([f70e3cb](https://github.com/ScreamingFace/screamingface/commit/f70e3cbf03fd899a3822414c0fc68c8c34e0ec20))
* **screamingface-engine:** import onet_m6 with its chain-of-thought prompt and a named exclusion ([ab8086b](https://github.com/ScreamingFace/screamingface/commit/ab8086b613d619a082f4007b129b135d1f4a30d9))
* **screamingface-engine:** import pre_flight and bbeh by Task replay ([8f2306f](https://github.com/ScreamingFace/screamingface/commit/8f2306ffce6d79c31889b058d94b19d836dfb3df))
* **screamingface-engine:** import pre_flight and bbeh by Task replay (OME-1273) ([4adfca7](https://github.com/ScreamingFace/screamingface/commit/4adfca73a80392c40fac831bbf1a7250b2739f57))
* **screamingface-engine:** import pubmedqa through its question filter ([ff1ac82](https://github.com/ScreamingFace/screamingface/commit/ff1ac82bd224c875f62c6622bb0b49a249eb292b))
* **screamingface-engine:** import pubmedqa through the task route ([af17a44](https://github.com/ScreamingFace/screamingface/commit/af17a447ed639dfc3495e9874925594bb6b0fefd))
* **screamingface-engine:** import sad_stages_full and mitre_frr by Task replay ([b11f6b2](https://github.com/ScreamingFace/screamingface/commit/b11f6b23ec9a7e72bf0d2869f8535ccf1c0c7820))
* **screamingface-engine:** import SAD-mini and CyberSecEval mitre_frr by Task replay ([606528f](https://github.com/ScreamingFace/screamingface/commit/606528fd7261b38c8d5ad5975f3c1387bb960538))
* **screamingface-engine:** import Tasks with several scorers and list answer keys ([0ba6587](https://github.com/ScreamingFace/screamingface/commit/0ba6587f1f5d733de15f63f3d760a44aec93fb78))
* **screamingface-engine:** import Tasks with several scorers and list answer keys (OME-1268, PR 4 of 5) ([e89335c](https://github.com/ScreamingFace/screamingface/commit/e89335c63f6c07225c2bdbe821e628f4a6dd660d))
* **screamingface-engine:** keep where each Imported bundle's Cases came from ([128b4b4](https://github.com/ScreamingFace/screamingface/commit/128b4b40820daa61b2e02c1a9fc4760ba726acf3))
* **screamingface-engine:** keep where each Imported bundle's Cases came from (OME-1492, PR 1 of 3) ([12b29d7](https://github.com/ScreamingFace/screamingface/commit/12b29d7d52c7b235c9b2e8398ad3b48b24cf25b2))
* **screamingface-engine:** let a judged board's judge fill inspect's grader role ([8789dbc](https://github.com/ScreamingFace/screamingface/commit/8789dbc593f356e274c820bfa8fa0742742dac85))
* **screamingface-engine:** let a judged board's judge fill inspect's grader role ([84708ce](https://github.com/ScreamingFace/screamingface/commit/84708cefa5032e9cbb2abc37c4582e80ef6d5733))
* **screamingface-engine:** let a Task-replay import keep Sample metadata a Judge reads ([adbc005](https://github.com/ScreamingFace/screamingface/commit/adbc0054c0cd10d810a586998e55a1a9cc091aa5))
* **screamingface-engine:** link each paid-smoke dataset source to its pinned commit and keep the labels in the debug bundle (OME-1524) ([4cd0634](https://github.com/ScreamingFace/screamingface/commit/4cd063445c6ac730ba4fa1cc7e143ee117da7bb1))
* **screamingface-engine:** link each provenance source to its pinned commit and keep the labels in the paid-smoke bundle ([6b910e2](https://github.com/ScreamingFace/screamingface/commit/6b910e2c03aae96b6cfccab160e5b875505c8515))
* **screamingface-engine:** make Draft Feedback an owner decision per Benchmark; only IFEval keeps it ([3aac5cf](https://github.com/ScreamingFace/screamingface/commit/3aac5cf13895b5b35a5166012961972f242259f2))
* **screamingface-engine:** pin the Hub commit on medqa, bbq and piqa ([615e24a](https://github.com/ScreamingFace/screamingface/commit/615e24a5e6281505fd27b507f62f1132271bb199))
* **screamingface-engine:** pin the Hub commit on pre_flight and bbeh ([58bfc65](https://github.com/ScreamingFace/screamingface/commit/58bfc651cd18a350031c060f2e80d0d2ea74a9f9))
* **screamingface-engine:** prepare every Imported Benchmark by Task replay and delete the Hugging Face path (OME-1460, PR 2 of 2) ([dfbe0b7](https://github.com/ScreamingFace/screamingface/commit/dfbe0b7a17986ff54e59b4c3e3ff88617b7ea8ce))
* **screamingface-engine:** prepare Task-replay Benchmarks and check their Case Digest ([654ee62](https://github.com/ScreamingFace/screamingface/commit/654ee62746dfef6930e12973a764cc587bb1e32f))
* **screamingface-engine:** prepare Task-replay Cases in a clean child process, served only when their Case Digest matches ([50c68d9](https://github.com/ScreamingFace/screamingface/commit/50c68d9ea82baf91f69c45a49bc61b221b27c71a))
* **screamingface-engine:** prepare the 30 Hugging Face-path Benchmarks by Task replay ([75524d9](https://github.com/ScreamingFace/screamingface/commit/75524d9742451616792b85fd332252181df4f56e))
* **screamingface-engine:** record every Case Source a Task replay fetches from ([d73fbc5](https://github.com/ScreamingFace/screamingface/commit/d73fbc52d95f980a68b651d765681af82c861e27))
* **screamingface-engine:** record where each hand-built bundle's Cases came from ([3b48f43](https://github.com/ScreamingFace/screamingface/commit/3b48f434876c8ff26c6e3cdd3c28f491ca29720a))
* **screamingface-engine:** record where each hand-built bundle's Cases came from (OME-1492, PR 3 of 3) ([f3e3c6f](https://github.com/ScreamingFace/screamingface/commit/f3e3c6f5d6cd057062d2f8e1aa3ab9b53023047e))
* **screamingface-engine:** refuse a declared seed the eval never needs ([e90a658](https://github.com/ScreamingFace/screamingface/commit/e90a65856bad656647fb9a4dbf14a66024ed4e63))
* **screamingface-engine:** refuse an inspect Task that asks each question several times (OME-1458, PR 2 of 7) ([93fef7a](https://github.com/ScreamingFace/screamingface/commit/93fef7ae5659cb30ae5d11970f855a93ef0e1ec4))
* **screamingface-engine:** refuse an inspect Task that declares more than one epoch ([c66c4aa](https://github.com/ScreamingFace/screamingface/commit/c66c4aa575e8564ea65b4be4a2260ceb489b5b78))
* **screamingface-engine:** refuse X-Profile at ingress and stop producing selector-bearing runs ([#1082](https://github.com/ScreamingFace/screamingface/issues/1082)) ([df6e9b9](https://github.com/ScreamingFace/screamingface/commit/df6e9b92d1a55fb7c3a898164c82fea117522d5c))
* **screamingface-engine:** render a Task-replay declaration with its Case Sources ([7458c8a](https://github.com/ScreamingFace/screamingface/commit/7458c8a0cdf17bc9d36aaf3675c314769a092a19))
* **screamingface-engine:** render a Task-replay import by capture ([f285062](https://github.com/ScreamingFace/screamingface/commit/f285062b009ddb4f6cd5c86b1686c3541b4933ca))
* **screamingface-engine:** replay a task for import with Case Sources and facts ([d481926](https://github.com/ScreamingFace/screamingface/commit/d481926fc9e8e607eedfee02ff13d52cf80e8cb8))
* **screamingface-engine:** route the four fetch-blind refusals to Task replay ([15963c8](https://github.com/ScreamingFace/screamingface/commit/15963c8098a254c7d648466655e1f25438f00e36))
* **screamingface-engine:** say whether only the order moved when an Imported seal breaks ([13d2b8e](https://github.com/ScreamingFace/screamingface/commit/13d2b8e7cf9dfc4d614448473802e143040d709a))
* **screamingface-engine:** say whether only the order moved when an Imported seal breaks (OME-1492, PR 2 of 3) ([2954e07](https://github.com/ScreamingFace/screamingface/commit/2954e0768e99e98f0bdabb45dd835f44f874ca43))
* **screamingface-engine:** score should-refuse Benchmarks by refusal rate ([ff41c93](https://github.com/ScreamingFace/screamingface/commit/ff41c93732453df753e08ecde6dc5142ffb16cb8))
* **screamingface-engine:** score should-refuse Benchmarks by refusal rate ([8a8e965](https://github.com/ScreamingFace/screamingface/commit/8a8e965a9e585cdadd582e3d54d393c9519ccf4c))
* **screamingface-engine:** seal a Task-replay import with a digest two runs agree on ([e974419](https://github.com/ScreamingFace/screamingface/commit/e974419f8960bb117523b1d0f9aeb56ba889c8b3))
* **screamingface-engine:** seal Hub commits and seeds on Task-replay declarations ([cb02225](https://github.com/ScreamingFace/screamingface/commit/cb022256efeb6b334e1584d277dfe5f3166ff18a))
* **screamingface-engine:** serve MuSiQue-Ans as the first local inspect Task ([7b84c73](https://github.com/ScreamingFace/screamingface/commit/7b84c7357a76e0f9c0c1f5fff5c42ca26f9026fe))
* **screamingface-engine:** serve MuSiQue-Ans as the first local inspect Task (OME-1513) ([21d2b2e](https://github.com/ScreamingFace/screamingface/commit/21d2b2ebc3100a0aae10dfc6c85b78bd2702522c))
* **screamingface-engine:** share the Case writer and add the Case Digest ([52359b3](https://github.com/ScreamingFace/screamingface/commit/52359b34dae5055ba6ecdbd62d67a7b9678a1488))
* **screamingface-engine:** show imported judges' reasoning in the notebook report ([6323ec8](https://github.com/ScreamingFace/screamingface/commit/6323ec88303b75af00dec8a511ca4ad0e7448916))
* **screamingface-engine:** show imported judges' reasoning in the notebook report ([3d61739](https://github.com/ScreamingFace/screamingface/commit/3d6173958307cb3f0eb2f2d4d14fe226fffa625a))
* **screamingface-engine:** source the provenance of every registered Benchmark and empty the allowlist ([37fef37](https://github.com/ScreamingFace/screamingface/commit/37fef37d8786b051ff440854b0dcc93f77e3415f))
* **screamingface-engine:** source the provenance of every registered Benchmark and empty the allowlist (OME-1455, PR 3 of 4) ([ec767b1](https://github.com/ScreamingFace/screamingface/commit/ec767b168f98bf7760591d30dbbbe325a69a6a42))
* **screamingface-engine:** treat Samples that carry choices as MCQ-shaped ([4cf1469](https://github.com/ScreamingFace/screamingface/commit/4cf1469856fa724ba728c8b9a7962761fe17098a))
* **screamingface-engine:** write Hub pins, seeds and the gate into generated Task-replay rows ([e0e8b03](https://github.com/ScreamingFace/screamingface/commit/e0e8b03fa38db9d0b7d5329758fbfb46e735e253))
* **screamingface:** mark Benchmarks scored by refusal rate in report.json ([a89a190](https://github.com/ScreamingFace/screamingface/commit/a89a19004219ec7a84c3f54a8ff185c8889297ee))
* **screamingface:** mark Benchmarks scored by refusal rate in report.json ([bf256b4](https://github.com/ScreamingFace/screamingface/commit/bf256b43e9cd6d354f3a5b3ffec8cb4f9d37fefb))


### Bug Fixes

* attribute judge activity and simplify log display ([#1071](https://github.com/ScreamingFace/screamingface/issues/1071)) ([3293550](https://github.com/ScreamingFace/screamingface/commit/3293550b3d0dd8cc87798a70a4cffde9c42da2e0))
* **engine:** align transport with provider admission budgets ([#1152](https://github.com/ScreamingFace/screamingface/issues/1152)) ([d0534a2](https://github.com/ScreamingFace/screamingface/commit/d0534a23d52587cd87c51e9311fe1d72f9c8ee96))
* **engine:** bound the OTLP flush and report dropped spans ([fd565a2](https://github.com/ScreamingFace/screamingface/commit/fd565a2fdff92c70f648f25f999f7101ddca2217))
* **engine:** bound the OTLP flush and report dropped spans ([e711c31](https://github.com/ScreamingFace/screamingface/commit/e711c313b6ab7fde5c2ac00d15c02e2cbda9ecbd))
* **engine:** enforce the OTLP close bound and count refused spans ([b796c4a](https://github.com/ScreamingFace/screamingface/commit/b796c4adabd1fa8b2225c38f07f5d7a2e3e9fffa))
* **engine:** flag a system message inspect rewrites before sending ([2b7fb6b](https://github.com/ScreamingFace/screamingface/commit/2b7fb6bf7d304f98565f394872bd946cdecf1405))
* **engine:** gate only the cold start on broker readiness (OME-942 D8) ([2a57398](https://github.com/ScreamingFace/screamingface/commit/2a5739853207a0ae26b20588d5b0653df686f8a1))
* **engine:** give the App Deployment the OTLP env so url4.accept exports ([#1255](https://github.com/ScreamingFace/screamingface/issues/1255)) ([d578cba](https://github.com/ScreamingFace/screamingface/commit/d578cba9e2e72bdc97e0e79c56436aac663926c8))
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
* **screamingface-engine:** address the fold's review round ([067b42c](https://github.com/ScreamingFace/screamingface/commit/067b42c94c1662b640111a156604b4ac0a0f14e0))
* **screamingface-engine:** check Named Score names against the scorers and approve plain means by identity ([d5a4f59](https://github.com/ScreamingFace/screamingface/commit/d5a4f59037285bcba77991d1ea9ec006596cb832))
* **screamingface-engine:** check Named Score names where inspect is already loaded, not at assembly ([3359450](https://github.com/ScreamingFace/screamingface/commit/3359450f1a5f897270cbfb752893397bd8561e09))
* **screamingface-engine:** cite the SQuAD 2.0 paper, pin sympy into MATH's revision, and tier SQuAD medium ([2bba6bb](https://github.com/ScreamingFace/screamingface/commit/2bba6bbc28bbb2925611ed5b449f8fa02c68039d))
* **screamingface-engine:** close the task-route gaps from review ([feaa6ba](https://github.com/ScreamingFace/screamingface/commit/feaa6bab07bb24c4be1d9f69cf0ee4eb68add394))
* **screamingface-engine:** close the xstest and CI-token gaps from review ([a11b685](https://github.com/ScreamingFace/screamingface/commit/a11b68512c1bcaa38676193cd548a1ccc1a7be59))
* **screamingface-engine:** declare the importer seam's seed and metadata options ([e560da9](https://github.com/ScreamingFace/screamingface/commit/e560da9acbe1fffa3ae4008d7e15e858f737888b))
* **screamingface-engine:** give xstest_unsafe's conversion to inspect's refusal rate ([18ee645](https://github.com/ScreamingFace/screamingface/commit/18ee645c8894368bf1cc3970dad1d839d95e5b23))
* **screamingface-engine:** keep every model out of the capture child and give each Sample its own context ([1c2967c](https://github.com/ScreamingFace/screamingface/commit/1c2967c31ce8a9519214289c39bb43535d58b952))
* **screamingface-engine:** keep one Task replay's odd output from crashing the image build ([6b7b2e6](https://github.com/ScreamingFace/screamingface/commit/6b7b2e6471d73ada1138aa8bf3d18cb170bcac9e))
* **screamingface-engine:** let a cached Hugging Face login reach the replay child ([cabf634](https://github.com/ScreamingFace/screamingface/commit/cabf634ca246b717600425210fd791b92ce88198))
* **screamingface-engine:** let a judge keep the cache setting an eval hands it ([054a06a](https://github.com/ScreamingFace/screamingface/commit/054a06a8033a55409db7890cc0b1d76179c4fe16))
* **screamingface-engine:** let a judge keep the cache setting an eval hands it ([891c57c](https://github.com/ScreamingFace/screamingface/commit/891c57c6bb07afa6536d9b2ca706193fb02e7f30))
* **screamingface-engine:** make the Case Digest survive a JSON round trip ([aa451f3](https://github.com/ScreamingFace/screamingface/commit/aa451f3c23453031ce097c91f0c1d3a87f6490df))
* **screamingface-engine:** pin a local Task's own source into its Benchmark revision ([eb58715](https://github.com/ScreamingFace/screamingface/commit/eb587151139c34021c91296e1ed9d7eb9740a4b7))
* **screamingface-engine:** pin inspect back to the versions the published exams use ([e546d51](https://github.com/ScreamingFace/screamingface/commit/e546d5169a9da19a10747ec51ae3725f3af65a0e))
* **screamingface-engine:** pin the Draft Feedback rule catalogue-wide and close the review's gaps ([1b3aaea](https://github.com/ScreamingFace/screamingface/commit/1b3aaea2f53176894d5f79c8544639830e82a191))
* **screamingface-engine:** point the IFEval label at the real file and list GDPval's unpinned references ([2171fd6](https://github.com/ScreamingFace/screamingface/commit/2171fd6c1a089d5fadd504fd52d21f64c27bdee5))
* **screamingface-engine:** redirect every replay cache, keep SKIPPED reasons to one line ([601dff2](https://github.com/ScreamingFace/screamingface/commit/601dff27237bc17a06672e75800fffd4b5353991))
* **screamingface-engine:** refuse a used bundle directory before its label is touched ([649fd11](https://github.com/ScreamingFace/screamingface/commit/649fd1156f7391b6f0204b70b21d1f9f403e212b))
* **screamingface-engine:** refuse an extra scorer with arguments or a shared name, and note a grouped block in words ([6cd0d18](https://github.com/ScreamingFace/screamingface/commit/6cd0d183408abe15c74d9ced8971bb9177ba2f29))
* **screamingface-engine:** refuse model_role=None on a role-bound judge; pin per-task roles ([ee6e1f3](https://github.com/ScreamingFace/screamingface/commit/ee6e1f399c6dba99db8f235933b3784304b74d56))
* **screamingface-engine:** report a Task-replay refusal from the command as an error line ([e51631e](https://github.com/ScreamingFace/screamingface/commit/e51631e51bc133ddb9a8452eac309438f9ea6d63))
* **screamingface-engine:** say MedQA asks five options, not four ([a083ff2](https://github.com/ScreamingFace/screamingface/commit/a083ff2b26952afe4f288c6f9bb20536a8b02b2b))
* **screamingface-engine:** tag render-time Case Sources, refuse inert seed flags on a Task-replay import ([ee7eb9d](https://github.com/ScreamingFace/screamingface/commit/ee7eb9d9fc05cae3fdca371f48ab584fbccbe0d5))
* **screamingface-engine:** type the recorder for the extra-less typecheck CI runs ([83927e8](https://github.com/ScreamingFace/screamingface/commit/83927e85a8aa1e99c45bffc8f478940e16df59c1))
* **screamingface-engine:** typecheck the MuSiQue local Task without the inspect extra ([9ab9245](https://github.com/ScreamingFace/screamingface/commit/9ab92452a5e6cd77cfa4011d5fcd4e30730a2c21))
* **screamingface-engine:** write a printable non-ASCII excluded Sample id ([50dfcc8](https://github.com/ScreamingFace/screamingface/commit/50dfcc86f7433a47e0daa0e0003f1cbb64a34c81))
* **screamingface:** keep the SDK's inspect-ai pin on the Engine's version ([98a234e](https://github.com/ScreamingFace/screamingface/commit/98a234e1e657a94872d3a8ccd167d57d2111f7b5))
* **screamingface:** pin the inverted_grade key's spelling on both sides ([a7381c3](https://github.com/ScreamingFace/screamingface/commit/a7381c323903220a1df19a30b074fe4fb4eb2b8d))
* **screamingface:** pin the SDK's inspect-ai to the Engine's version and bind them ([2d03a8f](https://github.com/ScreamingFace/screamingface/commit/2d03a8f2338b16b251509ab803561f6eeab3a620))
* **screamingface:** resume the same capability after reconnect challenges and show reconnect progress ([#1099](https://github.com/ScreamingFace/screamingface/issues/1099)) ([d4af3cc](https://github.com/ScreamingFace/screamingface/commit/d4af3ccf5113cc7d1d5bd5bed1ab1e7bfb3bf056))


### Refactors

* **engine:** one executor for every engine request; remove the node tier ([#1085](https://github.com/ScreamingFace/screamingface/issues/1085)) ([d64d5e9](https://github.com/ScreamingFace/screamingface/commit/d64d5e942b37fab45ce14f95a015ee9a2e44a775))
* **engine:** remove retired profile carrier ([#1231](https://github.com/ScreamingFace/screamingface/issues/1231)) ([641601f](https://github.com/ScreamingFace/screamingface/commit/641601f37a7c40ea6cf96abda187a565a2108df8))
* **screamingface-engine:** delete the Hugging Face preparation path ([a6faeee](https://github.com/ScreamingFace/screamingface/commit/a6faeeefa1e35c77d0b2c5807f48c453ccfb5bc8))
* **screamingface-engine:** drop the explicit with_check_surface=False rows; the field defaults off ([e54c52d](https://github.com/ScreamingFace/screamingface/commit/e54c52d531ddb73fc15f7ddfde561136393d4564))
* **screamingface-engine:** finish the bind_* renames on the record builders ([d1e66e1](https://github.com/ScreamingFace/screamingface/commit/d1e66e1f89ddbd9c661774d6532f8d4dceba8f2d))
* **screamingface-engine:** head each vendored MuSiQue file with a link to its source, not the authors' docstring ([76f4b63](https://github.com/ScreamingFace/screamingface/commit/76f4b63f51636df76b0c39151452165b161de091))
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
* **screamingface-engine:** mark capture as open PR in the eval-split diagram; record review round 1 in the ledger ([9582ce6](https://github.com/ScreamingFace/screamingface/commit/9582ce65b8ff69c941281df027855e8690c8e9b2))
* **screamingface-engine:** one Case Preparation path in the glossary, the how-to and the architecture page ([6e9ecdc](https://github.com/ScreamingFace/screamingface/commit/6e9ecdc348f435a6ba8c46d6e0f84ce41cc3afe9))
* **screamingface-engine:** say a local Task needs the file-level pyright directive ([bfd5347](https://github.com/ScreamingFace/screamingface/commit/bfd534721ba19e7436440e638640921c7344e9ca))
* **screamingface-engine:** say a web download links to its own address, not a commit ([939fcc6](https://github.com/ScreamingFace/screamingface/commit/939fcc6c59f9f76114a5c77477ae77b56796eb64))
* **screamingface-engine:** say Case, answer key and Grading where inspect's words meant ours ([766b495](https://github.com/ScreamingFace/screamingface/commit/766b495aa4d6e0081d2afb84ccab32b9f1b82d02))
* **screamingface-engine:** say this is PR 2 of 7 and closes nothing in its ledger ([8741c9c](https://github.com/ScreamingFace/screamingface/commit/8741c9c49756f3aac1f6aebdc508daaa423dd25e))
* **screamingface-engine:** say why the vendored graders are fenced off from ruff, pyright and coverage ([59a5fd3](https://github.com/ScreamingFace/screamingface/commit/59a5fd30319776da9fc85be779b0577f03e212aa))
* **screamingface-engine:** walk eval()'s five per-Sample steps and where OME-1273 cuts them ([4ecb008](https://github.com/ScreamingFace/screamingface/commit/4ecb00888e51a9256a4fd4033ba86eeedc462b06))
* **screamingface:** add the MuSiQue example notebook and point its card at it ([bdd6c68](https://github.com/ScreamingFace/screamingface/commit/bdd6c6885f3dea450fd2e67b8cf6271240574596))
* **screamingface:** add the MuSiQue example notebook and point its card at it (OME-1513) ([88c0631](https://github.com/ScreamingFace/screamingface/commit/88c0631c11a7dfe377bec6530e9e45c16dc599ee))

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
