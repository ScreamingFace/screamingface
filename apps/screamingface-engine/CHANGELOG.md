# Changelog

## Unreleased

* Attribute collected IFEval model-call failures using the existing collected error kind from the candidate execution boundary, including Gateway-rewritten diagnostic codes. Unmarked errors and protected checker failures retain grading attribution.

## [1.6.0](https://github.com/ScreamingFace/screamingface/compare/screamingface-engine-v1.5.0...screamingface-engine-v1.6.0) (2026-10-17)


### Features

* **aigateway:** enable local Fusion benchmark execution ([#1448](https://github.com/ScreamingFace/screamingface/issues/1448)) ([cddc9f5](https://github.com/ScreamingFace/screamingface/commit/cddc9f59d09cfc762f67fe5f21199dcf74dae338))
* **aigateway:** relay the provider's sanitized error message (OME-1136) ([#1233](https://github.com/ScreamingFace/screamingface/issues/1233)) ([8d32145](https://github.com/ScreamingFace/screamingface/commit/8d32145515a4dcb35c56c7dabd9d814c1f90a1ee))
* **chart:** one per-slot memory value; runner children reserve no unused address space ([0d9dc57](https://github.com/ScreamingFace/screamingface/commit/0d9dc57ef1f2907def9e9dde6c7afc501c8e5952))
* **engine:** abstain a merge, projection or pick that finds no usable value ([21066be](https://github.com/ScreamingFace/screamingface/commit/21066be469a6dd540ee3993cf40b54ffb4a056b3))
* **engine:** abstain a top-k cut that cannot be met with cut_not_met ([1da2d62](https://github.com/ScreamingFace/screamingface/commit/1da2d62bb7f9288d506624d16424339507c9b028))
* **engine:** abstain instead of failing when no member gives a usable value ([b64b238](https://github.com/ScreamingFace/screamingface/commit/b64b238f06474111edf0be8e83e05a542495a209))
* **engine:** add combine ports and declare the E4a failure codes ([233c2fb](https://github.com/ScreamingFace/screamingface/commit/233c2fb056dcf12636a8fc8a50f914a99278d1ce))
* **engine:** add the budget.v1 records and the charge rule ([2c3cf71](https://github.com/ScreamingFace/screamingface/commit/2c3cf71892912cd65daacff441ab2ea50fb3fa87))
* **engine:** add the combine spec parser, evidence model and endpoint ([ea6c590](https://github.com/ScreamingFace/screamingface/commit/ea6c590b76b0a36518d539433b2c4c5b511cbe9c))
* **engine:** add the filter reducer and let pick run without an extract ([38cd878](https://github.com/ScreamingFace/screamingface/commit/38cd87865aa42eaed225b193679f13dacd60a678))
* **engine:** add the immutable combine operator registry ([c0c3485](https://github.com/ScreamingFace/screamingface/commit/c0c34857bd5f2e0c2ac8ccf7b70969764d2dd2ab))
* **engine:** add the inspect_number, inspect_aime and inspect_numeric operators ([b5d0e37](https://github.com/ScreamingFace/screamingface/commit/b5d0e370e240eac09e07b0ef4742ea0f6bf87223))
* **engine:** add the pick and merge field operators ([539a1ba](https://github.com/ScreamingFace/screamingface/commit/539a1ba79720398b1211a5b6db0a8d476d06fec8))
* **engine:** add the rank and concat combine operators (top_k, join, all) ([d20e6b4](https://github.com/ScreamingFace/screamingface/commit/d20e6b43e398aa27f91bbe846702d14a5d748d13))
* **engine:** add the regex@1 extractor with a static backtracking ban ([3cc5fe5](https://github.com/ScreamingFace/screamingface/commit/3cc5fe52d7d991d18d9c9cd673649ce5c657704b))
* **engine:** add the set@1 normalizer ([ad9398b](https://github.com/ScreamingFace/screamingface/commit/ad9398b0b92c326b885bd4aafe8a4b92dc6403ba))
* **engine:** add the strict judge combine operators ([9de7001](https://github.com/ScreamingFace/screamingface/commit/9de70010e1efaa45b052e0af1d02bb20b8bcb237))
* **engine:** add the v1 combine answer operators ([fb8b761](https://github.com/ScreamingFace/screamingface/commit/fb8b761d13bd30b1fe2e0e99cb92e20f27ffdc9b))
* **engine:** cap combine weights, give ReducerRule a weights column, and clip spec error locations ([bf6f040](https://github.com/ScreamingFace/screamingface/commit/bf6f04077ef3ccd54ce411bb985f4b363682eeda))
* **engine:** carry combine evidence on the operation output and attribute judge and writer bindings ([48ce2a6](https://github.com/ScreamingFace/screamingface/commit/48ce2a6a4d90baaa44146f69b178650cd87578e4))
* **engine:** carry the abstain mark through every benchmark's case record ([0000bd2](https://github.com/ScreamingFace/screamingface/commit/0000bd2e7be91635e825de3255af784c819f44c3))
* **engine:** concat, rank, filter and argmax over a quorum panel ([b188b65](https://github.com/ScreamingFace/screamingface/commit/b188b6577b98cfbd234b2aa25030b2b8e3f78959))
* **engine:** declare the GSM8K and AIME answer rules in the benchmark catalog ([7f0699d](https://github.com/ScreamingFace/screamingface/commit/7f0699d820562c828d25153775153488ec2d2e99))
* **engine:** filter members by a signal threshold or a regex check (filter@1, kept@1) ([ba1be14](https://github.com/ScreamingFace/screamingface/commit/ba1be14666ca24a3356665da5914e0c289d5c20d))
* **engine:** give combine members an Answer with status, reason and a computed result ([2026d30](https://github.com/ScreamingFace/screamingface/commit/2026d30be64b25af75a88d158eb96343f9100473))
* **engine:** install the combine route for every benchmark world ([48da137](https://github.com/ScreamingFace/screamingface/commit/48da137c700a83f488dbf1a0e3310d4e5858f17c))
* **engine:** judge only the members a quorum panel holds ([38c908e](https://github.com/ScreamingFace/screamingface/commit/38c908e112d15fda655123651c5c5452beeb8391))
* **engine:** keep each model call's original signal accounting ([698a3ea](https://github.com/ScreamingFace/screamingface/commit/698a3ea69dcceb37a96a59ac832c1d237e041fcc))
* **engine:** let a signal-weighted vote skip members with no usable weight ([77a46e0](https://github.com/ScreamingFace/screamingface/commit/77a46e08b68748224d12d05be9b11d41ee116865))
* **engine:** let top_k@1 keep the lowest scores with order min ([4b04a83](https://github.com/ScreamingFace/screamingface/commit/4b04a83a4f2626910b284ea441ce92c1125874cf))
* **engine:** look up member accounting by exact call fingerprint in the combine route ([d747fff](https://github.com/ScreamingFace/screamingface/commit/d747fff90ee22f72487ae9128f782ee993b3ac6b))
* **engine:** make the binding model param attribution-only ([ab2863f](https://github.com/ScreamingFace/screamingface/commit/ab2863fbc584a0ec57053d2bd832bf4016440090))
* **engine:** mark a candidate invocation whose final combine abstained ([d0c3a98](https://github.com/ScreamingFace/screamingface/commit/d0c3a9878975f86d8d6b830e7bd62de4ce00eacc))
* **engine:** rank members by a named signal (by_signal@1, best_holder@1) ([15b3de4](https://github.com/ScreamingFace/screamingface/commit/15b3de46112868b0588f216b51d1ec57ddf0b964))
* **engine:** read a Fusion quorum panel in the combine core ([8ddeb17](https://github.com/ScreamingFace/screamingface/commit/8ddeb1707025c4e935de9fb518ee0579d2d3e4bc))
* **engine:** register the v1 answer operators as the combine built-ins ([1270691](https://github.com/ScreamingFace/screamingface/commit/1270691a9ce844fbe3e2c670b0d59adf432d428d))
* **engine:** resolve field and accounting signals in the combine core ([a88e284](https://github.com/ScreamingFace/screamingface/commit/a88e2840db5acb0850f0f1cb4852896f59960722))
* **engine:** resolve the score:judge signal from the judge reply ([f720bc4](https://github.com/ScreamingFace/screamingface/commit/f720bc47457599ffc15897478c54dc4e4a305be5))
* **engine:** run regex@1 on RE2 and drop the static backtracking ban ([8924335](https://github.com/ScreamingFace/screamingface/commit/8924335bcec9e2061e0c67bcbba076e6460324ad))
* **engine:** score an abstained case 0.0 and keep the grader's metrics and checks ([edaa691](https://github.com/ScreamingFace/screamingface/commit/edaa69132778fa157b7275dd726fb7dde9cf9f16))
* **engine:** serve the combine operator catalog at GET /v1/operators ([aa9dbb1](https://github.com/ScreamingFace/screamingface/commit/aa9dbb1f69b1d533344ad82ab0911bb6d851f0e4))
* **engine:** vendor Inspect's numeric answer rule ([b31b644](https://github.com/ScreamingFace/screamingface/commit/b31b644738a0ee40bbadbdb1964249a034221abd))
* **engine:** verify the combine tally, bound scores, log plugin bugs, and resolve operators before args ([e1b9b7e](https://github.com/ScreamingFace/screamingface/commit/e1b9b7ed09584e12ed7d9e2d3557eedc60e4569a))
* **layering:** add the COMBINE_CORE rule to the layering gate ([8351e11](https://github.com/ScreamingFace/screamingface/commit/8351e11985dd1dfb0ebdf55c3639be0d318caf22))
* **layering:** ban url4 under combine/ and I/O modules in combine plugins ([8252101](https://github.com/ScreamingFace/screamingface/commit/82521010439f130feab604b7c33b67b7a75651e1))
* **screamingface-engine:** add ifeval as a local inspect Task with its pooled run metric ([ed57b07](https://github.com/ScreamingFace/screamingface/commit/ed57b073f5ae2dd9c63e8d1d83e043368402f2c2))
* **screamingface-engine:** count an abstained Case as failing ifeval's run metric ([b318ef2](https://github.com/ScreamingFace/screamingface/commit/b318ef2e253534ead4c4b8555c620ece5c68eab1))
* **screamingface-engine:** keep healthbench's published revisions ([a7a1d82](https://github.com/ScreamingFace/screamingface/commit/a7a1d8211fd46d7e22f8c302a7a588403e413935))
* **screamingface-engine:** keep ifeval's published revision ([0efd04a](https://github.com/ScreamingFace/screamingface/commit/0efd04a1c79cbcb2c1865eb1bcba5b8d791dd305))
* **screamingface-engine:** land the unseen-judge and model-read guards on main (OME-1602, PR 2 and 3 of 7) ([05550cc](https://github.com/ScreamingFace/screamingface/commit/05550cc97b48a73bbd24789e5012dba232ae03f3))
* **screamingface-engine:** let a migrated Benchmark keep its published revision ([ee4e963](https://github.com/ScreamingFace/screamingface/commit/ee4e963bc34d5609436ad5b36e72c96970f4f7c2))
* **screamingface-engine:** let a migrated Benchmark keep its published revision ([5f3df2e](https://github.com/ScreamingFace/screamingface/commit/5f3df2ed23ed178b00f927298924f53c0f0b4c4d))
* **screamingface-engine:** offer an owner-allowed Benchmark's Draft Feedback without an answer key ([8133f87](https://github.com/ScreamingFace/screamingface/commit/8133f872899d6220f61e0013103f10edeec03a9d))
* **screamingface-engine:** offer an owner-allowed Benchmark's Draft Feedback without an answer key (OME-1527, PR 13 of 20) ([e72d122](https://github.com/ScreamingFace/screamingface/commit/e72d1222805442678d5546b505ac825fa53a9a2f))
* **screamingface-engine:** refuse an extra scorer with its own whole-run metric (OME-1602) ([9778914](https://github.com/ScreamingFace/screamingface/commit/9778914867398ffa8a7872d00c1dec317858307a))
* **screamingface-engine:** refuse Cases built for a model named none or judged inside the solver chain (OME-1602, PR 3 of 7) ([38ba203](https://github.com/ScreamingFace/screamingface/commit/38ba203ce7da0d3a56582cadaa8b66742912f9ac))
* **screamingface-engine:** refuse Cases built for the model under test, or judged inside the solver chain (OME-1602) ([3188d45](https://github.com/ScreamingFace/screamingface/commit/3188d45903f4379250dff1439a8d1733d23b8723))
* **screamingface-engine:** refuse scorer arguments and extra-scorer metrics the importer can't copy (OME-1602, PR 1 of 7) ([8eef979](https://github.com/ScreamingFace/screamingface/commit/8eef9791d2d4dde8e327574a7718ddd216c1bb2c))
* **screamingface-engine:** refuse scorer arguments inspect logs by name (OME-1602) ([35a6e77](https://github.com/ScreamingFace/screamingface/commit/35a6e773387f5c0ed66212e585b9b528276714ee))
* **screamingface-engine:** see judges a scorer reaches without naming them (OME-1602, PR 2 of 7) ([8aba819](https://github.com/ScreamingFace/screamingface/commit/8aba819c44bfbf1b25c5e00451806ab682769507))
* **screamingface-engine:** see judges a scorer reaches without naming them (OME-1602) ([819865e](https://github.com/ScreamingFace/screamingface/commit/819865ed9cf450d8b3a5fefcba55124441f67a9c))
* **screamingface-engine:** send an allowed Benchmark's partial score and checker words as Draft Feedback (OME-1527, PR 12 of 20) ([4c053b6](https://github.com/ScreamingFace/screamingface/commit/4c053b683eb2badbe23f62867f364a961834f5d4))
* **screamingface-engine:** serve draco and draco-3pass as local inspect Tasks (OME-1527, PR 18 of 20) ([1a18cfe](https://github.com/ScreamingFace/screamingface/commit/1a18cfedd2a2f33f27a8a5d32c61c2a65876301b))
* **screamingface-engine:** serve FRAMES with its gold articles given, judged by the paper's prompt ([3bb468e](https://github.com/ScreamingFace/screamingface/commit/3bb468eef25f3731c2f05e9ba2795aac74180581))
* **screamingface-engine:** serve FRAMES with its gold articles given, judged by the paper's prompt (OME-1481, PR 1 of 2) ([5efd4cb](https://github.com/ScreamingFace/screamingface/commit/5efd4cb98907d93ea2fe835a2ff9f12f6895543a))
* **screamingface-engine:** serve healthbench worst-30 and professional as local inspect Tasks ([358c782](https://github.com/ScreamingFace/screamingface/commit/358c78233ad9519bf6de3aee1327c145d895a3e0))
* **screamingface-engine:** serve healthbench worst-30 and professional as local inspect Tasks (OME-1527, PR 20 of 20) ([33e98c0](https://github.com/ScreamingFace/screamingface/commit/33e98c002b6e03c1aac3b812862f1046e5981930))
* **screamingface-engine:** serve ifeval as a local inspect Task (OME-1527, PR 15 of 20) ([1b9fe76](https://github.com/ScreamingFace/screamingface/commit/1b9fe76c72d232145536dfa34487bce805e2e8ee))
* **sdk:** add constant weights to sf.Vote and pin the weighted vote engine contract data ([1e589a1](https://github.com/ScreamingFace/screamingface/commit/1e589a17de02b05a9c1d3ab5726f9351be79344c))
* **sdk:** add sf.Vote and sf.Median and pin their engine contract data ([2821a53](https://github.com/ScreamingFace/screamingface/commit/2821a530b539f7e9b8a53030ad5f704bd30d7489))
* **sdk:** decode combine evidence into CaseOperation and pin the engine contract fixture ([c5a127b](https://github.com/ScreamingFace/screamingface/commit/c5a127bec21145c3a14c75bbb988d2636411ab0f))


### Bug Fixes

* **engine:** compare real JSON numbers as numbers and harden the field operators ([2848656](https://github.com/ScreamingFace/screamingface/commit/28486561ddc684d236626f54134085a7ad6c2754))
* **engine:** compile regex@1 with silent, size-capped RE2 options ([61dbc0c](https://github.com/ScreamingFace/screamingface/commit/61dbc0cc3ad31a9116081176fec42b10f6131b2e))
* **engine:** count overlapping separator matches when flagging a concat collision ([ad05d29](https://github.com/ScreamingFace/screamingface/commit/ad05d299c61ba072919eb840993b1898e5037d58))
* **engine:** harden combine median and nearest inputs and read the whole comma run ([fe8f945](https://github.com/ScreamingFace/screamingface/commit/fe8f94586fb702714e0873d2f4da023b96978989))
* **engine:** judged grading holds only the Cases near the clerk, not the whole run ([cbaf6e0](https://github.com/ScreamingFace/screamingface/commit/cbaf6e0cf2a91f1e74e0c57d0c62339a83ff4e70))
* **engine:** keep asset-defect failures failed on an abstained case ([cbf7fa9](https://github.com/ScreamingFace/screamingface/commit/cbf7fa92a8c3a00a16179af053c9b6926bbc9b63))
* **engine:** move the answer operators onto the core's Answer port ([7a366b4](https://github.com/ScreamingFace/screamingface/commit/7a366b4ba9447e57f9f70b162454ff2b81e1d2d2))
* **engine:** move the field operators onto the core's Answer port ([c5579ff](https://github.com/ScreamingFace/screamingface/commit/c5579ffa3ceb85d09d406ffc6baa215966cb2a78))
* **engine:** move the judge operators onto the core's Answer port ([0b1a9b8](https://github.com/ScreamingFace/screamingface/commit/0b1a9b83c90c85cff5c15cd8066007c7eb112208))
* **engine:** name writer signals writer_&lt;field&gt; so url4 struct can carry them ([45743d9](https://github.com/ScreamingFace/screamingface/commit/45743d926ee190d0457d3f4488d78bfb2a98ca7b))
* **engine:** pin rank and concat evidence in the Answer-row wire ([f5f5b2e](https://github.com/ScreamingFace/screamingface/commit/f5f5b2e4a832ece68307648d67f95491414b19fa))
* **engine:** pin the combine evidence key order with the core's new fields ([50c5689](https://github.com/ScreamingFace/screamingface/commit/50c5689074e7b9bbcb27b922a3e82c0cecfb916b))
* **engine:** review fixes — robust memory watch, release-on-finish grading, root on redelivery ([d47a272](https://github.com/ScreamingFace/screamingface/commit/d47a272c39eaea0f3235d41a07c2349255328915))
* **engine:** score every named score of an abstained case 0.0 ([ba74136](https://github.com/ScreamingFace/screamingface/commit/ba7413612624d9f58dd9cb0caac2a69c3537f11c))
* **engine:** treat a non-finite cost or token count as unpriced ([bbe657e](https://github.com/ScreamingFace/screamingface/commit/bbe657ec12a702a865a889a71d6a0f89a53472d1))
* **engine:** worker terminal frames end the client run; per-run resident memory budget ([04dac33](https://github.com/ScreamingFace/screamingface/commit/04dac3392e3bf6b0ac7288160571055ea9bca9d1))
* raise the model-call budget to 30 minutes for long evaluations ([#1430](https://github.com/ScreamingFace/screamingface/issues/1430)) ([92645fe](https://github.com/ScreamingFace/screamingface/commit/92645fe66085733dc2a846fd86d1cc2f53e2330c))
* **screamingface-engine:** add up each Case's judge-verdict counts so the grading warning fires again ([b459f66](https://github.com/ScreamingFace/screamingface/commit/b459f66f5c0446ff64fd0febb8d221c96c4cba63))
* **screamingface-engine:** add up each Case's judge-verdict counts so the grading warning fires again (OME-1527, PR 18b of 20) ([1bc092f](https://github.com/ScreamingFace/screamingface/commit/1bc092ff604048854f95734a6f85f6cec2b7f6bc))
* **screamingface-engine:** count a role read with no role bound as a read of the model under test ([54c2293](https://github.com/ScreamingFace/screamingface/commit/54c22938d9430a1e7103e5d28a4ad11d53408735))
* **screamingface-engine:** hand the whole-run metric an abstained Case's 0.0 ([5e904d0](https://github.com/ScreamingFace/screamingface/commit/5e904d0085424ed6613b151f3b459c09dfa581f1))
* **screamingface-engine:** judged runs fit their slot, and a dead run child ends the client run (OME-1607) ([bc08d99](https://github.com/ScreamingFace/screamingface/commit/bc08d99d50e965b608a70922d69a8032fb051e78))
* **screamingface-engine:** keep a Fusion's combine evidence when folding Attempts ([4a5ce85](https://github.com/ScreamingFace/screamingface/commit/4a5ce85a07a7460c04a5179ac8752726c54ee47f))
* **screamingface-engine:** keep a judge Fusion's pick record when merging Attempts (OME-1633) ([e2965eb](https://github.com/ScreamingFace/screamingface/commit/e2965ebf8680bef2abc95c2346744bdea28feccd))
* **screamingface-engine:** name a missing inspect install instead of an unseen judge ([7d761b3](https://github.com/ScreamingFace/screamingface/commit/7d761b3831e67cb0dd74d77999f0b629181b74fc))
* **screamingface-engine:** read a dict-valued kept Score by its headline and mark abstains ([edd8aa2](https://github.com/ScreamingFace/screamingface/commit/edd8aa2b9f45119491b8d4106c2bdfeaaf86a3ff))
* **screamingface-engine:** refuse a scorer the argument recorder never saw ([185dd7b](https://github.com/ScreamingFace/screamingface/commit/185dd7bab7b09f3c71c23394d56c545c4ae6e23b))
* **screamingface-engine:** refuse a scorer the judge reader cannot read in full ([ca99a0c](https://github.com/ScreamingFace/screamingface/commit/ca99a0c2a0438c3bf1a0931e23ee37eba4ec7e05))
* **sdk:** cap vote weights like the Engine, validate recovered weights and tighten the weighted vote tests ([b3b6cb4](https://github.com/ScreamingFace/screamingface/commit/b3b6cb4a39c485a9fe9fd9f457c63dc3b2c8f441))
* **sdk:** tighten the vote and median recovery, round trip test and docs after review ([02199d9](https://github.com/ScreamingFace/screamingface/commit/02199d9c70466cc1422e341e8335dccfd361c924))
* **sdk:** word writer-template@1 for plain text replies and document it ([e2e8495](https://github.com/ScreamingFace/screamingface/commit/e2e849540389cf51a85302a91eddf4ae57d103da))


### Refactors

* **engine:** decide the combine outcome in one place and pick the weight source once ([ad3e750](https://github.com/ScreamingFace/screamingface/commit/ad3e750410402c56d072e058908b266a055a7d7b))
* **engine:** derive the order choices from SignalOrder and inline the filter message ([1b30a34](https://github.com/ScreamingFace/screamingface/commit/1b30a34f64d21e9acc38068cee8b19e4698c25ab))
* **engine:** fold the round-trip accounting statements into one helper ([766ca26](https://github.com/ScreamingFace/screamingface/commit/766ca26273d8d95640f480ce047b82e8883ac3fb))
* **engine:** group JUDGE_SIGNAL with the signal keys and give the judge fence its own name ([7d4027a](https://github.com/ScreamingFace/screamingface/commit/7d4027a54aafcaf773a2711ad0c9548aef791c67))
* **engine:** keep combine free of url4 and serve the route from world/combine.py ([82bf0b9](https://github.com/ScreamingFace/screamingface/commit/82bf0b9bc11632ed0ac1bf650719204c0fa5732b))
* **engine:** name the abstain mark once and splat it from one helper ([02bd490](https://github.com/ScreamingFace/screamingface/commit/02bd490eeb50f3bb1e311c83b4b5ba63946ccee9))
* **engine:** read json_field@1 paths through the ports field-path walk ([a462abc](https://github.com/ScreamingFace/screamingface/commit/a462abca627b13695534857ed6f7a17e2d5b5ccc))
* **engine:** read json_object and values paths through the ports helpers ([ea852eb](https://github.com/ScreamingFace/screamingface/commit/ea852eb0f7b3579a07ed81bab1f56548889e3111))
* **engine:** read judge scores through one ports parser ([9e6d38b](https://github.com/ScreamingFace/screamingface/commit/9e6d38b4da4930e9244b3362ead4ccc5dbf61368))
* **engine:** read the cache reference once and reuse the accounting key order ([ba6697f](https://github.com/ScreamingFace/screamingface/commit/ba6697ff17c3e07e8097e1224de3e48881876af0))
* **engine:** share one finite-float rule across ports, endpoint and accounting ([a35b17a](https://github.com/ScreamingFace/screamingface/commit/a35b17aa1b51a1bcd63cfff09968e1bb545ff0d1))
* **engine:** share the conditional JSON response and pin the combine catalog wiring ([3c0531f](https://github.com/ScreamingFace/screamingface/commit/3c0531fec3c53dcb0d14c4b2eb26d017bfaa84dd))
* **engine:** tidy ports lookups and exports, and tighten two combine tests ([71239cd](https://github.com/ScreamingFace/screamingface/commit/71239cd90accdc430ef9642c0087998fac4269de))
* **screamingface-engine:** delete the hand-built ifeval folder and serve the local Task ([2d04f78](https://github.com/ScreamingFace/screamingface/commit/2d04f781094793d831f2e0795448b2ba8e97e55d))
* **screamingface-engine:** drop computed_revision and the fingerprint pins ([ec1526d](https://github.com/ScreamingFace/screamingface/commit/ec1526d5eb3d5c90e571e0e4ed3d3d852be8a384))
* **screamingface-engine:** drop computed_revision and the fingerprint pins ([0328125](https://github.com/ScreamingFace/screamingface/commit/032812557edfeac5d3e0003fbeddd1ce8ed6d752))
* **screamingface-engine:** mirror healthbench's published_revision commit byte for byte ([d158713](https://github.com/ScreamingFace/screamingface/commit/d158713154d7edcd9a4523759640fdad205d7aad))
* **screamingface-engine:** publish a hand-set revision and alarm on its fingerprint in a test ([1068b56](https://github.com/ScreamingFace/screamingface/commit/1068b56b8ce3c7b839b252671de5aa115b55ed5c))
* **screamingface-engine:** publish a hand-set revision and pin the fingerprint in tests ([5263997](https://github.com/ScreamingFace/screamingface/commit/5263997b2f2460d4895501b84d55e342bee813ae))


### Documentation

* **engine:** a combine plugin imports only the ports and the standard library ([06e99e3](https://github.com/ScreamingFace/screamingface/commit/06e99e3c372472e6b59096a57e126c6721b78d1f))
* **engine:** state the JSON-only field reading rule and the combine OperationCall ([0cdd9fa](https://github.com/ScreamingFace/screamingface/commit/0cdd9fab7dce7162a5ea01e7280df393c969041e))
* **OME-1607:** spec, plan, ledger, task mirror and run-memory measurement ([1534471](https://github.com/ScreamingFace/screamingface/commit/15344717247a92e886a30fbcc533d6117c06d334))
* **screamingface-engine:** fix the redraw docstring and pin the healthbench reference link ([b2c417f](https://github.com/ScreamingFace/screamingface/commit/b2c417f80100185d9441d85009a614e4a33b047e))
* **screamingface:** add the FRAMES example notebook (OME-1481, PR 2 of 2) ([8c5b0e5](https://github.com/ScreamingFace/screamingface/commit/8c5b0e5bbb0c5c6e16471597184e1ac071f9b08b))
* **screamingface:** add the FRAMES example notebook and point frames_oracle at it ([c34a4cf](https://github.com/ScreamingFace/screamingface/commit/c34a4cf77161915fb18dd3006e28a5d2931a1420))
* **test:** say what the schema freeze does not catch ([36ec8d9](https://github.com/ScreamingFace/screamingface/commit/36ec8d9347ffbdb5ba631472462c7c0e501342c5))

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
