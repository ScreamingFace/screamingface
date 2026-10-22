---
id: OME-1706
linear_url: https://linear.app/openmined/issue/OME-1706/keep-the-exact-openrouter-cost-for-successful-responses-over-256-kib
status: in_progress
type: fix
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1287
created: 2026-10-21
closed:
---

# Keep the exact OpenRouter cost for successful responses over 256 KiB

An OpenRouter 200 with a body over 256 KiB (a long reasoning answer) lost its exact cost. The
usage-accounting hook dropped the raw body, the mapper fell back to LiteLLM's float cost, and the
call was unpriced (`succeeded_attempt_direct_cost.status = "unavailable"`). A 2xx body up to 8 MiB
is now parsed losslessly, and only `id`, `model` and `usage` are kept. Error bodies keep the
256 KiB full-evidence cap.
