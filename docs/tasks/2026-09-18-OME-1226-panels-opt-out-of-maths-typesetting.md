---
id: OME-1226
linear_url: https://linear.app/openmined/issue/OME-1226/text-with-dollar-signs-shows-up-garbled-and-run-together-in-notebook
status: done
type: task
priority: high
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-18
closed: 2026-09-18
---

# Text with dollar signs shows up garbled and run together in notebook panels

A benchmark prompt that mentions money reaches the notebook page with its `$` characters
intact — HTML escaping leaves them alone because `$` is not HTML-special. The notebook's
maths typesetter then runs as a later pass over the rendered DOM, pairs the dollars up, and
re-typesets the sentence between them as inline maths: italic, spaces deleted. GSM8K's
instruction text contains three of them, so the report panel shows something materially
different from what the model was actually asked.

Every panel root now carries the typesetter's opt-out classes — `mathjax_ignore` (MathJax 3
/ JupyterLab 4) and `tex2jax_ignore` (MathJax 2 / classic notebook and nbconvert) — so the
whole subtree is skipped and the text is displayed verbatim. Presentation only: no stored
artifact, protocol payload, or engine behaviour changes.

Ledger: `docs/work/2026-09-18-OME-1226-panels-opt-out-of-maths-typesetting.md`.
