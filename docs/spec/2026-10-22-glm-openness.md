# Verified open-weight releases — OME-1716

The scoreboard defines open as downloadable, locally runnable weights, including
releases with custom or gated licenses. It does not claim unrestricted open-source
licensing. The user authorized expanding the original GLM correction to as many
verified models as possible.

## Evidence and scope

Audit the 468-route OpenRouter catalog observed on 2026-10-22, prioritizing routes
that the existing classifier leaves unknown and models present on public boards.
Check the linked model-author repositories for published weight files, configuration,
license metadata, and local inference instructions. A catalog Hugging Face ID alone
is insufficient. Record the 99 accepted exact routes across 32 owners in the
[evidence CSV](../../apps/scoreboard/docs/open-weight-evidence-2026-10-22.csv), including
repository revisions and primary route evidence. The route count includes explicit
free/batch variants and serving aliases; it is not a count of distinct checkpoints.
No weights were downloaded or inference runs performed as part of this audit.

Examples include GLM, MiniMax, Cohere Command, NVIDIA Nemotron, Tencent Hunyuan,
Microsoft Phi, IBM Granite, Liquid, StepFun, and Xiaomi MiMo. Retain unknown when
published matching weights cannot be established, including GLM Turbo, Grok 4.7,
MiniMax M3.1 Flash, and routing services whose own source code is not model weights.

Prime, FlashX, and MiMo UltraSpeed are accepted as documented acceleration aliases
of published releases, based on their serving-provider descriptions. This is a
route-to-release inference, not independent attestation of the hosted checkpoint.
Prime's provider describes inference acceleration of GLM-5.3; FlashX describes the
high-speed GLM-5.3-Flash variant; MiMo explicitly names the same base checkpoint.
See the per-route evidence URLs in the CSV. Do not generalize these mappings to
arbitrary suffixes or future releases.

## Classification contract

Use one exact route-to-weight-repository registry after existing normalization.
Do not add whole vendors or families. All-open ensembles become open; any
closed/unknown member still closes an entry. Operator overrides still win.

The two observed hosted Qwen routes (`qwen3.6-plus`, `qwen3.8-max-prime`) must return
unknown ahead of the existing owner rule. Alibaba distinguishes hosted and released
editions; the Qwen3.8 downloadable model is text-only, while hosted Max adds
capabilities. Related releases do not verify these exact hosted versions. Preserve
unknown-route diagnostics and closed ensemble labels until weights are verified.
Sources: [Alibaba model editions](https://www.alibabacloud.com/help/en/model-studio/deep-thinking),
[Qwen3.8 model card](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B).
Other legacy owner/family rules remain in place; this is not a complete replacement
of the existing classification policy.

Read-time classification updates current share and historical trend without changing
benchmark revisions, scores, costs, or Pareto membership.

## Observed impact

Replaying the 63 ranked public entries captured on 2026-10-22 changes nine labels:
seven closed to open (six GLM/base ensembles plus MuSiQue's solo Prime) and two open
to closed (Draco's Qwen Plus ensemble and MuSiQue's solo Qwen Max Prime). MuSiQue's
three-model ensemble remains closed because Qwen is unverified.
ContractEval's frontier moves from 2/5 to 3/5 open, Draco from 4/11 to 3/11;
the other three populated boards' frontier shares are unchanged. These are snapshot
predictions, not a claim that the change has been deployed.
