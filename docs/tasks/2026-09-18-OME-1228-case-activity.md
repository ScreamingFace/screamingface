---
id: OME-1228
linear_url: https://linear.app/openmined/issue/OME-1228
status: In Progress
priority: High
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-18
---
# Carry benchmark case identity into live model activity

Independent of stage PR #980; existing model-call activity receives authoritative Case identity outside prompts. See ../spec/2026-09-18-OME-1228-case-activity.md and ../plan/2026-09-18-OME-1228-case-activity.md. Stage/grading integration remains in OME-1222; broader semantic attribution remains in OME-699.

Selected-case numbering now uses the shared protocol's requested dataset order, carried outside model input. Positions are candidate-independent and optional on plain requests. Engine gates and 70 focused checks pass; four cached benchmark replays preserve outcomes. OME-1229 owns the four expression-only golden migrations. PR #988 is open for review; #980 consumes the scope for activity.

Review correction (2026-09-22): restore installation-time dataset route validation through the
shared selector. Registry discovery now inspects local call context source lists, including
nested calls and empty slots; quoted text, holdings and remote contexts retain their runtime
semantics. New regression coverage is additive. Ledger:
`docs/work/2026-09-22-OME-1228-selector-route-validation.md`. PR remains open; no merge or issue
closure is requested.
