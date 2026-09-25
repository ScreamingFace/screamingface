# Changelog

## Unreleased

* Attribute collected IFEval model-call failures using the existing collected error kind from the candidate execution boundary, including Gateway-rewritten diagnostic codes. Unmarked errors and protected checker failures retain grading attribution.

## [1.6.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-engine-v1.5.0...screamingface-engine-v1.6.0) (2026-09-25)


### Features

* **chart:** let a platform own the node tier's NetworkPolicy ([#1062](https://github.com/ScreamingFace/screamingface/issues/1062)) ([1f1218e](https://github.com/ScreamingFace/screamingface/commit/1f1218eea8e4ad03e7668cbec6fbbd25504d1385))
* connect optional observers to Engine execution ([#915](https://github.com/ScreamingFace/screamingface/issues/915)) ([c9c6761](https://github.com/ScreamingFace/screamingface/commit/c9c6761f5f6cf719b72cd02a2e285d1648b650d7))
* **engine:** add the durable run queue (OME-1088) ([#816](https://github.com/ScreamingFace/screamingface/issues/816)) ([4c16c49](https://github.com/ScreamingFace/screamingface/commit/4c16c4926fb7c32d1a098ee3d3641d83909d7d1c))
* **engine:** add the runner worker (OME-1089) ([#818](https://github.com/ScreamingFace/screamingface/issues/818)) ([b68fdfb](https://github.com/ScreamingFace/screamingface/commit/b68fdfb01d23702b6ac1f34c8f8bf91186b96904))
* **engine:** admit runs on queue depth and fair-schedule them per caller ([#821](https://github.com/ScreamingFace/screamingface/issues/821)) ([5263388](https://github.com/ScreamingFace/screamingface/commit/526338880a7eee573685134ba123c34d788b82e2))
* **engine:** assemble imported benchmarks from data rows (1/3) ([4e079ee](https://github.com/ScreamingFace/screamingface/commit/4e079ee6239187a2d1ada4f45e4ebb3f167d9550))
* **engine:** assemble imported boards from data rows ([74c7990](https://github.com/ScreamingFace/screamingface/commit/74c799080eda6a3fe4ee61f2df85e2be9a30d401))
* **engine:** assemble imported single-shot evals into complete boards ([afe5c7e](https://github.com/ScreamingFace/screamingface/commit/afe5c7e89067459850101fa7822636d0ecfb8aea))
* **engine:** assemble imported single-shot evals into complete boards (4/6) ([a8f9586](https://github.com/ScreamingFace/screamingface/commit/a8f95862f7712120f1b10616d556ff325f67bd1d))
* **engine:** attribute candidate model activity to benchmark cases ([#988](https://github.com/ScreamingFace/screamingface/issues/988)) ([36c9f36](https://github.com/ScreamingFace/screamingface/commit/36c9f366a70973507bac24f618abd62759da55fe))
* **engine:** bake imported boards' dataset snapshots at image build ([ed5f4bb](https://github.com/ScreamingFace/screamingface/commit/ed5f4bb77b8ae3c27af569a51aae247d44821719))
* **engine:** bake imported boards' dataset snapshots at image build (3/6) ([9c09374](https://github.com/ScreamingFace/screamingface/commit/9c0937407359cc1c787054618e32cf3fe33cbdd8))
* **engine:** benchmark stage events ([#1056](https://github.com/ScreamingFace/screamingface/issues/1056)) ([4335b94](https://github.com/ScreamingFace/screamingface/commit/4335b946b0b97b736801cb45449cb130a9ed1965))
* **engine:** cut the chart over to the worker pool and retire the Job adapter ([#822](https://github.com/ScreamingFace/screamingface/issues/822)) ([4cdfa92](https://github.com/ScreamingFace/screamingface/commit/4cdfa920db7ae40280b2f8b9cc7c0b27fbd9ab7e))
* **engine:** default tracing on so ArgoCD ships it ([#921](https://github.com/ScreamingFace/screamingface/issues/921)) ([56334ee](https://github.com/ScreamingFace/screamingface/commit/56334ee97593e9a534b93dd29fb6a41830e6357c))
* **engine:** define optional execution observation ports ([#899](https://github.com/ScreamingFace/screamingface/issues/899)) ([dcaba22](https://github.com/ScreamingFace/screamingface/commit/dcaba22847278241ec5ea0b3931ac953bb888e51))
* **engine:** derive run status from the event stream and make cancellation queue-aware ([#819](https://github.com/ScreamingFace/screamingface/issues/819)) ([2804531](https://github.com/ScreamingFace/screamingface/commit/2804531dd5d5cbae56347a99cd0ee5079221f02c))
* **engine:** discover plugin benchmark deployments via entry points ([66e97ec](https://github.com/ScreamingFace/screamingface/commit/66e97ec472b8d45fb9d19ce18b57733f8cdd1652))
* **engine:** discover plugin benchmark deployments via entry points (1/6) ([20429a3](https://github.com/ScreamingFace/screamingface/commit/20429a3ad30faf0380eb429e57088e9cd6e1d6c0))
* **engine:** emit generated board rows in place - the importer's write stage ([28d2021](https://github.com/ScreamingFace/screamingface/commit/28d2021df423d5158ed6d05683bd3c7ea9b1e990))
* **engine:** emit generated board rows in place — the importer's write stage ([4669826](https://github.com/ScreamingFace/screamingface/commit/466982638b072fbced9c6158cc486fe4179a4ff3))
* **engine:** enable model-call activity in local and deployed runs ([#935](https://github.com/ScreamingFace/screamingface/issues/935)) ([59cbc39](https://github.com/ScreamingFace/screamingface/commit/59cbc395af2db9cd866d5707de0a9b4710d0d3c0))
* **engine:** export a run's span frames to OTLP ([#905](https://github.com/ScreamingFace/screamingface/issues/905)) ([59c22b0](https://github.com/ScreamingFace/screamingface/commit/59c22b0abcfc629a13ecad9983dd33c89eb088a6))
* **engine:** implement removable model-call activity plugin ([#931](https://github.com/ScreamingFace/screamingface/issues/931)) ([3da758f](https://github.com/ScreamingFace/screamingface/commit/3da758f2094b37584dd0edc807d68b28d00ca84d))
* **engine:** land eight generated boards and the choice-template render ([3641a9a](https://github.com/ScreamingFace/screamingface/commit/3641a9a1640ea7700d6626c26e62d4d794fd7b50))
* **engine:** land eight generated boards and the choice-template render ([b6c0b9d](https://github.com/ScreamingFace/screamingface/commit/b6c0b9df9f9c66aac94f46bca37b47aec0632690))
* **engine:** land the imported gsm8k board as the first table row ([a4e8e37](https://github.com/ScreamingFace/screamingface/commit/a4e8e3785cbe30d7b2fe70ff104cbe0d25af2dff))
* **engine:** land the imported gsm8k board as the first table row (2/3) ([bbfb078](https://github.com/ScreamingFace/screamingface/commit/bbfb0785bdfd2a5d73cc4b08f8aa774b83d42061))
* **engine:** land the imported mmlu board row and close the OME-1115 docs ([dbab233](https://github.com/ScreamingFace/screamingface/commit/dbab2332da1430aa2aaa3fa8ffc51e8a3f6f223b))
* **engine:** land the imported mmlu board row and close the OME-1115 docs ([3ecdff7](https://github.com/ScreamingFace/screamingface/commit/3ecdff74d8642c267975015fd216aaf924c07fd2))
* **engine:** log run identity and terminal evidence on the control plane ([#901](https://github.com/ScreamingFace/screamingface/issues/901)) ([a136e0f](https://github.com/ScreamingFace/screamingface/commit/a136e0ffd153dcb8275d409b9ccbb2b60f14eaf2))
* **engine:** read an inspect task's exam facts for the pin generator ([e10ad42](https://github.com/ScreamingFace/screamingface/commit/e10ad42e7cd02c26db4ae9ad4b1284a6a853c84a))
* **engine:** read an inspect task's exam facts for the pin generator ([816d790](https://github.com/ScreamingFace/screamingface/commit/816d790a7c8c3388bc064414e132bd8224237490))
* **engine:** record each benchmark's origin in the catalogue ([3fff687](https://github.com/ScreamingFace/screamingface/commit/3fff687d005dc721d8096dda229e1fb7ba137ebe))
* **engine:** record each benchmark's origin in the catalogue ([c152051](https://github.com/ScreamingFace/screamingface/commit/c152051e5b785d2eef9a11dc0f011bb722ab1887))
* **engine:** refuse a run when the namespace quota has no headroom (OME-1065) ([#808](https://github.com/ScreamingFace/screamingface/issues/808)) ([ed1c67b](https://github.com/ScreamingFace/screamingface/commit/ed1c67b7a66e95454571dc3c441c04fddef0e4c6))
* **engine:** refuse mutable dataset-revision refs at bake and assembly ([59bfe23](https://github.com/ScreamingFace/screamingface/commit/59bfe234a56515cbff6d0ae7265054befb8a5bb5))
* **engine:** retain Client version in ephemeral run evidence ([#924](https://github.com/ScreamingFace/screamingface/issues/924)) ([ee9765a](https://github.com/ScreamingFace/screamingface/commit/ee9765afd1cfa40aeb85e205337448dd3c819790))
* **engine:** ship the OTLP endpoint and credential through the chart ([#908](https://github.com/ScreamingFace/screamingface/issues/908)) ([b052aca](https://github.com/ScreamingFace/screamingface/commit/b052aca696b9896f9d1fd7896218fcad61593464))
* **engine:** wrap any inspect scorer as a grade_case hook ([18c1f99](https://github.com/ScreamingFace/screamingface/commit/18c1f995f87c14bd75c7a87cdf497b082abf3e2f))
* **engine:** wrap any inspect scorer as a grade_case hook (2/6) ([1312122](https://github.com/ScreamingFace/screamingface/commit/1312122842d651c0f065d66fa9254f083f4251d7))
* **py-screamingface:** refuse undeclared failure codes and pin the list to the engine's ([38768bd](https://github.com/ScreamingFace/screamingface/commit/38768bd3111413ed3a2e613b528db3025998c8f3))
* **screamingface-engine:** add the shared benchmark serving spine ([0bb4d58](https://github.com/ScreamingFace/screamingface/commit/0bb4d5809af4403d58b5bab36450bc709fb83731))
* **screamingface-engine:** add the shared benchmark serving spine ([6fda91e](https://github.com/ScreamingFace/screamingface/commit/6fda91e4e220cb3df28a26be4177724994cc80c1))
* **screamingface-engine:** back the in-flight heartbeat off instead of spamming ([4812470](https://github.com/ScreamingFace/screamingface/commit/4812470d41f1061b6b61a076849a3e9131495146))
* **screamingface-engine:** bake sample metadata behind an opt-in and flag judged imports ([bf3d801](https://github.com/ScreamingFace/screamingface/commit/bf3d801a78c06ba56c709d719b13337fe5b35f67))
* **screamingface-engine:** bake sample metadata behind an opt-in and flag judged imports ([6779dff](https://github.com/ScreamingFace/screamingface/commit/6779dff7d55df90d23d0f54a2ecfd33c0fc15604))
* **screamingface-engine:** conserve data_files and features in the inspect importer ([1fd7c86](https://github.com/ScreamingFace/screamingface/commit/1fd7c86850e7136982344380f7bff527f701227b))
* **screamingface-engine:** conserve data_files and features in the inspect importer ([92d1866](https://github.com/ScreamingFace/screamingface/commit/92d18667be2361e89b9e49ac73a6f064c0770185))
* **screamingface-engine:** conserve shuffle_choices in the inspect importer ([e3a902a](https://github.com/ScreamingFace/screamingface/commit/e3a902ad597e1d458eaac54f27756b2e96f82323))
* **screamingface-engine:** conserve shuffle_choices in the inspect importer ([77cd863](https://github.com/ScreamingFace/screamingface/commit/77cd8638dab332bf2ca2228b366ac3375b69b65d))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([b6139b7](https://github.com/ScreamingFace/screamingface/commit/b6139b7ef6d880a9e8f29e2d11d8c9bef01ebdd0))
* **screamingface-engine:** declare a difficulty tier on every benchmark ([382cce8](https://github.com/ScreamingFace/screamingface/commit/382cce8f67738145c64c1280d26fd5eca0ca80b1))
* **screamingface-engine:** declare failure policy + interaction per benchmark; extract shared failure ladder ([0867af8](https://github.com/ScreamingFace/screamingface/commit/0867af888c173c81f972f0255d1addd5990889cf))
* **screamingface-engine:** declare failure policy + interaction per benchmark; extract shared failure ladder ([0ba4d39](https://github.com/ScreamingFace/screamingface/commit/0ba4d39ee8f1cd370b640296a2070475a96e63ec))
* **screamingface-engine:** declare the failure-code vocabulary and class helpers ([57c39dd](https://github.com/ScreamingFace/screamingface/commit/57c39ddc9893dcb4a8e9665dd6c52445c2d08f86))
* **screamingface-engine:** declare the failure-code vocabulary and class helpers ([253958f](https://github.com/ScreamingFace/screamingface/commit/253958fd7621535fed329753123ed239f2869f98))
* **screamingface-engine:** import FrontierScience, the first LLM-judged board ([5d898d8](https://github.com/ScreamingFace/screamingface/commit/5d898d8e4f5bd68b0a1dcfcbe6782fa159f9b21e))
* **screamingface-engine:** import FrontierScience, the first LLM-judged board ([a9ba30a](https://github.com/ScreamingFace/screamingface/commit/a9ba30adbe59140d54bd48c71ab5c16b44237dc0))
* **screamingface-engine:** import hellaswag, delivering its system instruction as leading input text ([c901210](https://github.com/ScreamingFace/screamingface/commit/c9012107d0b3d05d26b9b98f473489c757472c01))
* **screamingface-engine:** import hellaswag, delivering its system instruction as leading input text ([a4c5a92](https://github.com/ScreamingFace/screamingface/commit/a4c5a92887612d2c1d58fe683e17e4603d4885a5))
* **screamingface-engine:** import the aime24 board ([abe90d0](https://github.com/ScreamingFace/screamingface/commit/abe90d09957cbfc7ad6e0741f4acb0a517e4298c))
* **screamingface-engine:** import the aime24 board ([916ddae](https://github.com/ScreamingFace/screamingface/commit/916ddae7911dfd9f45e463375590fae48b5d011e))
* **screamingface-engine:** import the aime25 board ([5005083](https://github.com/ScreamingFace/screamingface/commit/5005083b1ac61d2e8048cd31db38574e9e981bfe))
* **screamingface-engine:** import the aime25 board with a pinned serving shuffle ([1609a03](https://github.com/ScreamingFace/screamingface/commit/1609a03f80d481a6167eb3e3245cc1f21e474fdc))
* **screamingface-engine:** import the musr and wmdp boards ([733531c](https://github.com/ScreamingFace/screamingface/commit/733531cc743501166f37dfb28976ed87d576a41b))
* **screamingface-engine:** import the musr and wmdp boards ([7bf89ee](https://github.com/ScreamingFace/screamingface/commit/7bf89eeb76d70137b78e83d05daa44affb1ba7fe))
* **screamingface-engine:** import the six text LAB-Bench boards ([dd5b8e2](https://github.com/ScreamingFace/screamingface/commit/dd5b8e2d1c009cde911006ac62ff38614832feb0))
* **screamingface-engine:** import the six text LAB-Bench boards ([d9924b2](https://github.com/ScreamingFace/screamingface/commit/d9924b2c42738b31774f49803208655465e81f92))
* **screamingface-engine:** let a run declare an answer seed ([0e8749e](https://github.com/ScreamingFace/screamingface/commit/0e8749e477dd55a981d4ce265fbdebe519d081f1))
* **screamingface-engine:** let a run declare an answer seed ([343b8ef](https://github.com/ScreamingFace/screamingface/commit/343b8ef8ed8e1ed53336e7307a438f36d56cfbe1))
* **screamingface-engine:** let an interrupted asset bake resume ([8a4bc7e](https://github.com/ScreamingFace/screamingface/commit/8a4bc7e2c9a376e5b9d98db5136b426a82ea8a08))
* **screamingface-engine:** log each model call's completion, failure, and stalls ([da36c20](https://github.com/ScreamingFace/screamingface/commit/da36c20a00eee65dc16c982f26a6f2def09286ca))
* **screamingface-engine:** make the judge exam identity and bind its transport ([37a9e64](https://github.com/ScreamingFace/screamingface/commit/37a9e644ed419b7d054530dd83e3e9c5171c2fa3))
* **screamingface-engine:** make the judge exam identity and bind its transport ([575bb34](https://github.com/ScreamingFace/screamingface/commit/575bb3414bbcb7fd468248f83a9cd5e68f5ad5ae))
* **screamingface-engine:** make the runner pool's max_ack_pending an explicit per-caller allowance ([#855](https://github.com/ScreamingFace/screamingface/issues/855)) ([eaa8d96](https://github.com/ScreamingFace/screamingface/commit/eaa8d96cb98a3299e9f4b59a3ad8f4fb69bdc4a1))
* **screamingface-engine:** onboard MedXpertQA as an exact-match MCQ benchmark ([0829106](https://github.com/ScreamingFace/screamingface/commit/0829106b1e91a80f76b23275ce865b52a72cd1e7))
* **screamingface-engine:** per-case judge accounting and case-tagged judge log lines ([b76c195](https://github.com/ScreamingFace/screamingface/commit/b76c195af1dc56c463ff233a08af21953033a33c))
* **screamingface-engine:** per-case judge accounting and case-tagged judge log lines ([760fa4f](https://github.com/ScreamingFace/screamingface/commit/760fa4f0be925f97bd20dfd27d82a983df4f97a9))
* **screamingface-engine:** pin a serving shuffle for aime24 ([fb86302](https://github.com/ScreamingFace/screamingface/commit/fb863020870ca4de2ecc7eb08ecda781b4d04442))
* **screamingface-engine:** propagate the run's traceparent to aigateway (OME-1119) ([#849](https://github.com/ScreamingFace/screamingface/issues/849)) ([1220e2e](https://github.com/ScreamingFace/screamingface/commit/1220e2e64a24dd3439829fb773b39a093702fde4))
* **screamingface-engine:** read provider-access availability for hosted listings ([#1007](https://github.com/ScreamingFace/screamingface/issues/1007)) ([54fa867](https://github.com/ScreamingFace/screamingface/commit/54fa867391894b3c7594a673ed22e375c4907662))
* **screamingface-engine:** rebuild the ContractEval board on the spine ([c735b7e](https://github.com/ScreamingFace/screamingface/commit/c735b7ef32725ccd2c094b0f229143ef64a96030))
* **screamingface-engine:** reclassify the catch-all failure sites into named classes ([03da591](https://github.com/ScreamingFace/screamingface/commit/03da59170439cee88661ce8a8578c1277b1bcae9))
* **screamingface-engine:** reclassify the catch-all failure sites into named classes ([4a5ec59](https://github.com/ScreamingFace/screamingface/commit/4a5ec59c1907f98e6c335ad765ccaa0b8f020a56))
* **screamingface-engine:** refuse undeclared failure codes on the Failure model ([1e18f6c](https://github.com/ScreamingFace/screamingface/commit/1e18f6cbadfb912d0e636e8b68b69de4aaec9920))
* **screamingface-engine:** refuse undeclared failure codes on the Failure model ([1b2857f](https://github.com/ScreamingFace/screamingface/commit/1b2857f01a7d6331cf0aed66cbc9d6ce8e03b9a2))
* **screamingface-engine:** route imported evals' judge calls through the gateway ([634f8e7](https://github.com/ScreamingFace/screamingface/commit/634f8e7e4dc0a69071241b917e57407ab7605d7b))
* **screamingface-engine:** route imported evals' judge calls through the gateway ([39ff656](https://github.com/ScreamingFace/screamingface/commit/39ff65617929842d42c2b9e535c442f93538e432))
* **screamingface-engine:** runner traceability and logging layer ([#797](https://github.com/ScreamingFace/screamingface/issues/797)) ([1d665d1](https://github.com/ScreamingFace/screamingface/commit/1d665d171cbef779ab0a2d8940b604f633005180))
* **screamingface-engine:** serve MedXpertQA as an exact-match MCQ board ([ed9f035](https://github.com/ScreamingFace/screamingface/commit/ed9f03513ef0ef4eecf03587a9162c6a7ba6932b))
* **screamingface-engine:** serve url4 mounts as a sync REST surface beside the ensemble path ([#1030](https://github.com/ScreamingFace/screamingface/issues/1030)) ([c6774ea](https://github.com/ScreamingFace/screamingface/commit/c6774ea1132e288659695d9dba18d379a95548ea))
* **screamingface-engine:** ship the imported boards and document the one-command stack ([c828935](https://github.com/ScreamingFace/screamingface/commit/c828935fe016e4afe3e21c543dbc378b174f0457))
* **screamingface-engine:** stamp the official MedXpertQA slice tags on every report case ([2f4885a](https://github.com/ScreamingFace/screamingface/commit/2f4885a32c2fd8c88f8e0363ed533cab4ae86d12))
* **screamingface:** example notebook walks the imported benchmark catalogue ([1df9166](https://github.com/ScreamingFace/screamingface/commit/1df9166d587d3d0826b52a521930ed56c691fa33))
* standard metadata (cost, latency, tokens) on every cached response ([#930](https://github.com/ScreamingFace/screamingface/issues/930)) ([0d2c00f](https://github.com/ScreamingFace/screamingface/commit/0d2c00f829287b3d8fa1adc8dd380ff3e10b6b06))


### Bug Fixes

* **engine:** attribute failures at the candidate execution boundary ([#1060](https://github.com/ScreamingFace/screamingface/issues/1060)) ([a59d82e](https://github.com/ScreamingFace/screamingface/commit/a59d82e87c40cdc10a48c675e00f47964898f1ec))
* **engine:** attribute known IFEval Gateway failures to candidate ([#929](https://github.com/ScreamingFace/screamingface/issues/929)) ([eba2866](https://github.com/ScreamingFace/screamingface/commit/eba2866d02aeda8016cbd274f4f0e568376af55b))
* **engine:** classify empty model responses as retryable ([#872](https://github.com/ScreamingFace/screamingface/issues/872)) ([e42904e](https://github.com/ScreamingFace/screamingface/commit/e42904ebfdcc2e8183f5b0dd609b812051189d79))
* **engine:** conserve every hf_dataset kwarg the importer reads ([d4f803d](https://github.com/ScreamingFace/screamingface/commit/d4f803d4e31b25e357367af87b20c45bba6f5bd7))
* **engine:** forward structured Logs with safe buffer admission ([#884](https://github.com/ScreamingFace/screamingface/issues/884)) ([b47853e](https://github.com/ScreamingFace/screamingface/commit/b47853ea5dc1938360362fd46edf28b7d951fde1))
* **engine:** harden the importer's write stage against bad keys and half-writes ([8770471](https://github.com/ScreamingFace/screamingface/commit/8770471a911ffaa4dcafb7afd770520030dc6c52))
* **engine:** refuse wrong-sized, dirty, or malformed imported-board bakes ([ba1b658](https://github.com/ScreamingFace/screamingface/commit/ba1b6584a3d1f350609017d16f71f818c62e0f06))
* **engine:** review round 2 — provenance notes and charset anchors ([003d033](https://github.com/ScreamingFace/screamingface/commit/003d033c54990001d69a1ff1c6cd0f47648837ed))
* **engine:** typecheck the shim without the inspect extra installed ([0e8324d](https://github.com/ScreamingFace/screamingface/commit/0e8324d11c11bb670c8bc8e19021089ee60574c3))
* **py-screamingface:** make the conformance bind fire on either side's drift ([b4c6521](https://github.com/ScreamingFace/screamingface/commit/b4c6521d0da1f9e45885b6483573cfbba7828642))
* **scoreboard:** close partial-run leaderboard follow-ups ([#820](https://github.com/ScreamingFace/screamingface/issues/820)) ([2b47ae3](https://github.com/ScreamingFace/screamingface/commit/2b47ae3cdbd9a6cccfac4e584e0c1c838f68028a))
* **screamingface-engine:** adopt the OME-1037 refusal split in the MedXpertQA reducer ([69d67a5](https://github.com/ScreamingFace/screamingface/commit/69d67a5e2a6dc78547a2f5ea53cc61ebd4770661))
* **screamingface-engine:** allowlist the judge's config and refuse tool-bearing judge calls ([6ca658a](https://github.com/ScreamingFace/screamingface/commit/6ca658a20f1394223b7ad4241100b46a11a1bc05))
* **screamingface-engine:** bind the importer through inspect_evals' variadic hf_dataset wrapper ([673c534](https://github.com/ScreamingFace/screamingface/commit/673c53439a7ee5b063dbc1a6e86b7121ba1fb7cf))
* **screamingface-engine:** bind the importer through inspect_evals' variadic hf_dataset wrapper ([0e89314](https://github.com/ScreamingFace/screamingface/commit/0e893149e1bfda9f894a2b7b0b129fa19974cb66))
* **screamingface-engine:** carry the MedXpertQA turn-one reasoning into the report ([e8e66f1](https://github.com/ScreamingFace/screamingface/commit/e8e66f17e4c4aa0819013c44c20b89bdd16f440a))
* **screamingface-engine:** declare contracteval's failure codes so a failed case reports instead of crashing ([fa8bbe8](https://github.com/ScreamingFace/screamingface/commit/fa8bbe859d8499c6a827e1f5f2a68a3c4cb6ab4c))
* **screamingface-engine:** declare contracteval's failure codes so failed cases report instead of crashing ([39cea39](https://github.com/ScreamingFace/screamingface/commit/39cea39fcc77ec08487b998429f86d3ab2cc7482))
* **screamingface-engine:** deliver real inputs to both MedXpertQA turns ([4f8a4f5](https://github.com/ScreamingFace/screamingface/commit/4f8a4f5eda9c5069b0d9a2118d48179be151929c))
* **screamingface-engine:** detect judged rows by kwarg, grade them on the run's loop, pin published revisions ([2c627ae](https://github.com/ScreamingFace/screamingface/commit/2c627aeba549bc81bed362f214bceeaf3885133f))
* **screamingface-engine:** detect MCQ by solver and render str scorer kwargs format-safe ([816e7a5](https://github.com/ScreamingFace/screamingface/commit/816e7a50e6d1f9f317acbd7c3fdd073c63da8853))
* **screamingface-engine:** detect MCQ by solver or choice scorer ([0ed4a96](https://github.com/ScreamingFace/screamingface/commit/0ed4a96a1b14ecb21e441186dea1517655d0fef5))
* **screamingface-engine:** grade MedXpertQA Cases end to end ([8573e66](https://github.com/ScreamingFace/screamingface/commit/8573e66468d564534efa4184cb33ce249e85bcbe))
* **screamingface-engine:** honest comparability note and three board-level pins for FrontierScience ([5190a53](https://github.com/ScreamingFace/screamingface/commit/5190a5372acc5d3d2a62e2bd6191fd4205318cea))
* **screamingface-engine:** identity-check the hf_dataset shim; harden importer refusals ([d83096d](https://github.com/ScreamingFace/screamingface/commit/d83096d5bb99d6c49184b5c8a002061559d85b8a))
* **screamingface-engine:** importer detects MCQ by solver and renders str scorer kwargs format-safe ([33d8ec6](https://github.com/ScreamingFace/screamingface/commit/33d8ec6d59fd39d6a35b07895571ad696dbb1125))
* **screamingface-engine:** json-encode scorer kwarg names in generated boards ([bda116d](https://github.com/ScreamingFace/screamingface/commit/bda116d8c6329290749b670e0d825a80334c8fe9))
* **screamingface-engine:** judged grading survives bad judge replies and stays on the run's loop ([521d215](https://github.com/ScreamingFace/screamingface/commit/521d2155958bd995cacd0562e3f02d3d08b0b2de))
* **screamingface-engine:** migrate the fourth DRACO-pinning test — the e2e failure tape ([1c5f93e](https://github.com/ScreamingFace/screamingface/commit/1c5f93ef359c00bcac0db493e420552f08177f62))
* **screamingface-engine:** name the model, not the gateway, for a reasoning-only reply ([7c22441](https://github.com/ScreamingFace/screamingface/commit/7c22441a31fe2da45ddcd8a497241e90a5a8d15a))
* **screamingface-engine:** pin a hellaswag serving shuffle and ride the system message on exam identity ([0c672d6](https://github.com/ScreamingFace/screamingface/commit/0c672d6ceb3caadc95d5d452c44f65a4626a769f))
* **screamingface-engine:** preflight ContractEval assets before serving the booklet ([24d314b](https://github.com/ScreamingFace/screamingface/commit/24d314bd8082215ac53207711ec73bfa62b724e9))
* **screamingface-engine:** read the k8s client's default_request attribute ([#813](https://github.com/ScreamingFace/screamingface/issues/813)) ([1cd3b89](https://github.com/ScreamingFace/screamingface/commit/1cd3b8918de0577ba5a2d261e6973975762e590a))
* **screamingface-engine:** refuse combined shuffles when upstream seeds either one ([6078abe](https://github.com/ScreamingFace/screamingface/commit/6078abeeb6927db5ef0e85781afd842170027a17))
* **screamingface-engine:** refuse seed override and name choice-shuffle bake failures ([a940453](https://github.com/ScreamingFace/screamingface/commit/a940453150b329f15781502d0bda3ff918a1782a))
* **screamingface-engine:** restore the data_files typing tightened off the pre-rebase branch ([ae1ae2b](https://github.com/ScreamingFace/screamingface/commit/ae1ae2bdfd1d163b3a261a04e32e6d8ade7214c4))
* **screamingface-engine:** restore the two importer fixes clobbered off the mcq-family branch ([e193463](https://github.com/ScreamingFace/screamingface/commit/e1934638049e6310e3e2c836a636db5dbcac5d14))
* **screamingface-engine:** scope the answer seed to the Candidate invocation ([a9159f1](https://github.com/ScreamingFace/screamingface/commit/a9159f1b0a17bcaa8ab4ba3ebc8656263fc5e495))
* **screamingface-engine:** skip the Linux-only memory-cap test off-Linux ([0dc1b84](https://github.com/ScreamingFace/screamingface/commit/0dc1b8454a50b232fdc83da3e8da7d76821315a3))
* **screamingface-engine:** skip the Linux-only memory-cap test off-Linux ([226e52a](https://github.com/ScreamingFace/screamingface/commit/226e52aab12727988197a4f1744af74de0984261))
* **screamingface-engine:** stamp imported boards with the collection they came from ([0a6077d](https://github.com/ScreamingFace/screamingface/commit/0a6077d447e8698614631645144804f910613508))
* **screamingface-engine:** stop mislabelling decode failures and close the ifeval resume trap ([498d8e7](https://github.com/ScreamingFace/screamingface/commit/498d8e72da167c6418626e5eff806ee443b5afe7))
* **screamingface-engine:** surface the folded source spelling at every public_error consumer ([8de8164](https://github.com/ScreamingFace/screamingface/commit/8de816471d812d28917b4ccf2be9e4e13e689521))
* **screamingface-engine:** survive a cold gateway when fetching model parameters ([dcfb59a](https://github.com/ScreamingFace/screamingface/commit/dcfb59ab0d1ba51c091f0ef136e187e3bf9dae55))
* **screamingface-engine:** survive a cold gateway when fetching model parameters ([64fad82](https://github.com/ScreamingFace/screamingface/commit/64fad82b6c3e55ca25965ac62464dd6a3ccf7552))
* **screamingface-engine:** the importer detects judged rows by kwarg and never pairs them with a check surface ([146adae](https://github.com/ScreamingFace/screamingface/commit/146adaebaa06c00e512b5e78ad0f65d9394b3eea))
* **screamingface-engine:** tighten data_files typing and correct a test docstring ([20f4235](https://github.com/ScreamingFace/screamingface/commit/20f423528a6b342d632c3dd1784cf4af48a6daf8))
* **screamingface-engine:** withdraw the MedXpertQA check surface until a handler serves it ([26e65d4](https://github.com/ScreamingFace/screamingface/commit/26e65d4c66e3e27439b0a6d6122876ff6b46c563))
* **url4:** correct the JobRunner capacity contract ([#815](https://github.com/ScreamingFace/screamingface/issues/815)) ([ead1c84](https://github.com/ScreamingFace/screamingface/commit/ead1c849397930b9345504435411d5366ca07e93))


### Refactors

* **engine:** make the snapshot bake fully data-driven ([b03b38f](https://github.com/ScreamingFace/screamingface/commit/b03b38f2f0abb42ae8b7476d9bad5b5408dd5bdc))
* **engine:** name snapshot prompt renderers by eval family, not board ([8c461bb](https://github.com/ScreamingFace/screamingface/commit/8c461bb4d3f0b73336a2b09f09d419d3e6888f0b))
* **engine:** rename STATIC_REGISTRATIONS to BUILTIN_REGISTRATIONS ([98c869d](https://github.com/ScreamingFace/screamingface/commit/98c869ddf38ff410c2346de67a0e71c83cf13b13))
* **screamingface-engine:** annotate the spine's non-trivial locals ([ef3ae8b](https://github.com/ScreamingFace/screamingface/commit/ef3ae8b81fe4f00cdb10a817296f298fe940a793))
* **screamingface-engine:** fold ifeval onto the shared scored spine ([9f3d46a](https://github.com/ScreamingFace/screamingface/commit/9f3d46a2c1ac979938becff00db74304368e971e))
* **screamingface-engine:** fold ifeval onto the shared scored spine ([cdeec4f](https://github.com/ScreamingFace/screamingface/commit/cdeec4f23da7cb2e055b922bc4785500fc560eea))
* **screamingface-engine:** fold MedXpertQA's grading orchestration onto the shared scored path ([78adad0](https://github.com/ScreamingFace/screamingface/commit/78adad0c8c5cb251dcc07c2fa70346441facff2d))
* **screamingface-engine:** fold MedXpertQA's grading orchestration onto the shared scored path ([d4065d3](https://github.com/ScreamingFace/screamingface/commit/d4065d3c860507d353e5fa7a2993a138b174b393))
* **screamingface-engine:** fold the draco boards onto the shared scored spine ([c1c9256](https://github.com/ScreamingFace/screamingface/commit/c1c9256283bd262294e67cf5f5ae45fbab8bbac5))
* **screamingface-engine:** fold the draco boards onto the shared scored spine ([cd3527b](https://github.com/ScreamingFace/screamingface/commit/cd3527bc47091708b5ae18d4354569661ddc935c))
* **screamingface-engine:** merge the drifted judge-verdict parsers into one typed shared parser ([138bf5a](https://github.com/ScreamingFace/screamingface/commit/138bf5abe3f570ed1711363dc2ba04ad153a880f))
* **screamingface-engine:** merge the drifted judge-verdict parsers into one typed spine parser ([d0282dd](https://github.com/ScreamingFace/screamingface/commit/d0282dd527c04df50e9e0597a084fa9f447f95c2))
* **screamingface-engine:** read benchmark rows through one shared spine reader ([5057f98](https://github.com/ScreamingFace/screamingface/commit/5057f980d6a042019f705abdc4d7f1e7f277a047))
* **screamingface-engine:** read benchmark rows through one shared spine reader ([0b83739](https://github.com/ScreamingFace/screamingface/commit/0b837391df9d29f9a0289add81c139f485cfcded))
* **screamingface-engine:** rename CaseLadder to CaseGrader; snake_case coverage_declare ([9caa692](https://github.com/ScreamingFace/screamingface/commit/9caa69283a7fae8a4a18985b027d4f169cf68f4d))
* **screamingface-engine:** serve contracteval from the benchmark spine ([474ce8d](https://github.com/ScreamingFace/screamingface/commit/474ce8d4999e4118dcd518e7d6635459e23e91a6))
* **screamingface-engine:** serve contracteval from the benchmark spine ([af7d9eb](https://github.com/ScreamingFace/screamingface/commit/af7d9eb80704e1a7690391dc4920f3e1d53bd214))
* **screamingface-engine:** serve medxpert from the benchmark spine ([7c7e422](https://github.com/ScreamingFace/screamingface/commit/7c7e42263dde29bad1c1b04ebe778ebc5f1a13a7))
* **screamingface-engine:** serve medxpert from the benchmark spine ([e97de4e](https://github.com/ScreamingFace/screamingface/commit/e97de4e86142e7b8f42baebd4eabc39624d27aa1))
* **screamingface-engine:** share the rubric scored path behind a grade_case hook ([ce31f07](https://github.com/ScreamingFace/screamingface/commit/ce31f071cfb463a9cc77fb26ee9be7769ef522ce))
* **screamingface-engine:** share the rubric scored path behind a grade_case hook ([eac8acd](https://github.com/ScreamingFace/screamingface/commit/eac8acde32892dbf98c1bffb648238134eda5cdf))
* **screamingface-engine:** split provider refusal from graded refusal in case status ([a9b5da2](https://github.com/ScreamingFace/screamingface/commit/a9b5da2d059bf1a36b6f0268cec3d09f0d8f2543))
* **screamingface-engine:** split provider refusal from graded refusal in case status ([fe1a8cf](https://github.com/ScreamingFace/screamingface/commit/fe1a8cff48cc5287cb9883753ebf3d648c017f06))
* **screamingface-engine:** type the candidate row fields and teach the spine docstrings ([70fd787](https://github.com/ScreamingFace/screamingface/commit/70fd787e7fe679dd8631bfe2c12f60bbd6523f3d))
* **screamingface-engine:** type the grading spine's locals and land the candidate-fields dataclass ([2dfb1fd](https://github.com/ScreamingFace/screamingface/commit/2dfb1fd0ee6cb2c4d5fd4144798578de9b129d4b))


### Documentation

* **engine:** add the imported-benchmark onboarding runbook ([df51026](https://github.com/ScreamingFace/screamingface/commit/df51026e11f656442a95620eac1b9625eac88ac2))
* **engine:** add the imported-benchmark onboarding runbook ([f458a6a](https://github.com/ScreamingFace/screamingface/commit/f458a6a1c9e25986dfd5e09cb4bb5fc2ef76ef7d))
* **engine:** explain pins.py as the imported exams' lockfile ([8e1b6c8](https://github.com/ScreamingFace/screamingface/commit/8e1b6c866c88f51a20992df27ea2c9bf839a0b48))
* **screamingface-engine:** add the adding-a-benchmark author guide ([d0f16a6](https://github.com/ScreamingFace/screamingface/commit/d0f16a6ecfc7712f239a3d0a11509f2c80824bc5))
* **screamingface-engine:** explain each failure policy at its definition site ([46b7cea](https://github.com/ScreamingFace/screamingface/commit/46b7cea849cfa9d314d375dcd81087c5b9deac85))
* **screamingface-engine:** judge-declaration checklist item and review-round ledger ([9681844](https://github.com/ScreamingFace/screamingface/commit/9681844d833a48f34713afba393a72c1c6dc642f))
* **screamingface-engine:** make the adding-a-benchmark guide diagram-first ([5871e86](https://github.com/ScreamingFace/screamingface/commit/5871e86f074d3402608fab0e1e60ca8bcaedf27a))
* **screamingface-engine:** model-graded imports are in scope — correct the env-var judge plan ([f17ad00](https://github.com/ScreamingFace/screamingface/commit/f17ad0006f69e92d1a11cb9a9444e7219e3a852e))
* **screamingface-engine:** model-graded imports are in scope — correct the env-var judge plan ([4be2c98](https://github.com/ScreamingFace/screamingface/commit/4be2c980e8500d4246130d1fc8906590069f1edf))
* **screamingface-engine:** name the test behind the preflight late-binding note ([f3c74b5](https://github.com/ScreamingFace/screamingface/commit/f3c74b5b2599611c381d0d39135f70220cf70449))
* **screamingface-engine:** name which fan-out the row reader reads ([7092a5c](https://github.com/ScreamingFace/screamingface/commit/7092a5cfac647892ac3c6208e7ca428c21246272))
* **screamingface-engine:** pin the ContractEval harness citations to its commit ([09efd6e](https://github.com/ScreamingFace/screamingface/commit/09efd6ecf03559360b39f557c51fd8a2a24440d0))
* **screamingface-engine:** pin the one-candidate-per-captured-run invariant on the grading owner ([796c510](https://github.com/ScreamingFace/screamingface/commit/796c51019948b43eead406d5e7cfe5edc3f96ee1))
* **screamingface-engine:** plain words for the grading checks ([332ce20](https://github.com/ScreamingFace/screamingface/commit/332ce201a343a7115ec73902852c3d77ca6cc41b))
* **screamingface-engine:** render the execution-flow doc as mermaid and fix stale references ([6bc9145](https://github.com/ScreamingFace/screamingface/commit/6bc9145c7d00628565e0921030023f544981f2bf))
* **screamingface-engine:** restore the SubscriberGate step lost in the mermaid conversion ([8cb9810](https://github.com/ScreamingFace/screamingface/commit/8cb98102f2822142d6d40bb13e48062c5d99b631))
* **screamingface-engine:** runbook carries the judged lane's late learnings ([db8c9bf](https://github.com/ScreamingFace/screamingface/commit/db8c9bfe94573a1e3d519068c0850f11b265c493))
* **screamingface-engine:** say what preparing assets actually does ([0c22ae4](https://github.com/ScreamingFace/screamingface/commit/0c22ae49ca6ab007ddc3c55ebfc57f691eae227f))
* **screamingface-engine:** write the adding-a-benchmark author guide ([b58a866](https://github.com/ScreamingFace/screamingface/commit/b58a866e8a5bb77506c39bda3d0b6342857c6388))
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
