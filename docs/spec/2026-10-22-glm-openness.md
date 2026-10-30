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

## Source recheck requested by the owner

Re-fetched all 85 primary repositories at their recorded revisions and all 99 cited
route pages on 2026-10-22. Every repository resolves and lists nonempty weight blobs;
every cited route page resolves and the route remains in the current catalog. Checked
release names, architectures/modalities, and local inference documentation or published
standard model configuration/tokenizer. Also verified the complementary MiniMax-Text-01
repository, making 86 weight repositories inspected in this pass. No classifications
changed under the existing downloadable-and-locally-runnable definition.

`weight_file_count` and `weight_bytes` count every file in the primary repository's
manifest at the pinned revision whose extension is `safetensors`, `bin`, `gguf`, `pt` or
`pth` (review of PR #1534 found `.pt` artifacts omitted; recomputed 2026-10-28, which
changed five rows).

The evidence CSV now records full commit IDs, byte totals from manifests, access gates,
mapping basis, inference evidence, and specific qualifications:

- Four Cohere releases require automatic access acceptance; Muse Spark Open requires
  manual approval. Their public model cards and manifests establish a gated release;
  no gated access was requested and no inference was run.
- Several releases have commercial restrictions. The raw license tag is reported as
  metadata, not a judgment about unrestricted reuse. Cydonia and UnslopNemo have no
  explicit license metadata, now recorded as `not declared`; their published Mistral
  weights, configuration, and tokenizer establish local loadability.
- [Z.ai's own documentation](https://docs.z.ai/guides/vlm/glm-5.3-flash) jointly documents
  Flash and FlashX. This strengthens the serving-alias evidence beyond a catalog blurb.
  Prime remains supported by Alibaba's exact model page; MiMo UltraSpeed explicitly
  identifies the same checkpoint in its route description. These three mappings rely on
  provider statements, not independent verification of the bytes served by their APIs.
- MiniMax-01's hosted route covers text and vision; the audit now explicitly links both
  official component releases instead of documenting only the vision repository.
- Qwen's official Qwen3.6 catalog lists 27B/35B-A3B releases and their FP8 variants,
  not Plus. The Qwen3.8 model card explicitly distinguishes released text weights from
  the hosted Max edition with added features. Both audited hosted routes stay unknown.

Source verification establishes published releases and documented mappings. It does not
prove byte-for-byte hosted/local equivalence, access approval for every person, license
compatibility with every use, or successful execution of every model on local hardware.

## Known limit — hosted-edition deny list (PR #1534 review, 2026-10-28)

Routes are decoded from url4 spelling (`~` → `:`) before classification. The hosted-Qwen
deny list then matches the exact model segment, bare or with a trailing selector. It is best
effort while `qwen` remains an open owner: that rule credits any `qwen/...` name, so a
different model string (for example `qwen3.6-plus-x`) still classifies open, as before this
PR. A complete fix replaces the owner rule with registry entries and is out of scope here.
