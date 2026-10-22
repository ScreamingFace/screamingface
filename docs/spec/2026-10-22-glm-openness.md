# GLM-5.3 openness correction — OME-1716

Recognize exactly `z-ai/glm-5.3` after existing route normalization.
The official [model card](https://huggingface.co/zai-org/GLM-5.3),
[weights](https://huggingface.co/zai-org/GLM-5.3/tree/main), and
[license](https://huggingface.co/zai-org/GLM-5.3/blob/main/LICENSE) establish
downloadable, locally runnable weights, the existing scoreboard definition of open.
The license is custom, not MIT. Evidence checked 2026-10-22.

This exception must not grant openness to the vendor, Prime, a future version,
or another owner's model. All-open ensembles become open; any closed/unknown
member still closes an entry. Operator overrides still win.
Read-time classification updates the current share and historical trend without
changing benchmark revisions, scores, costs, or Pareto membership.

Prime checkpoint verification and the broader Qwen policy are outside this fix.
The user approved implementation after the audit and versioning explanation.
