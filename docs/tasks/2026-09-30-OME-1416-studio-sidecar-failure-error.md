---
id: OME-1416
linear_url: https://linear.app/openmined/issue/OME-1416
status: Pick Immediately
type: feature
priority: Medium
labels: [desktop, agentic, autonomous]
created: 2026-09-30
closed:
---

# Show an error in Studio when the runtime sidecar fails to start, instead of crashing

Leaf under epic `OME-1308` (E18 · A local app). It was found while verifying `OME-1415`.

Today a failed sidecar start returns an error from Tauri's setup hook. That panic cannot unwind,
so the installed app aborts silently (exit 134).

The fix: Studio opens anyway and shows the cause, the path to `runtime.log`, and a Retry button.
