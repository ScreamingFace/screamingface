---
id: OME-1974
linear_url: https://linear.app/openmined/issue/OME-1974
status: Triage
type: bug
priority: Medium
labels: [bug, client-sf, agentic, autonomous]
created: 2026-11-19
closed:
---

# Colab: analytics status shows unknown/disabled although enrollment and delivery succeed

In Colab, a background `eval_js` call only gets a reply while its cell is still running. The
SDK's analytics setup and final event upload often went out after the cell ended. Status then
read `unknown`/`invalid_response`, although consent and events reached PostHog. The fix
finishes those round trips inside the cell.

Filed as a bug with no parent epic (Filip, 2026-11-19). Related: OME-1768.

Ledger: docs/work/2026-11-19-colab-analytics-status.md
Spec: docs/spec/2026-11-19-colab-analytics-in-cell.md
Plan: docs/plan/2026-11-19-colab-analytics-in-cell.md
