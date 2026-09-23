---
id: OME-1322
linear_url: https://linear.app/openmined/issue/OME-1322/aigateway-ui-stop-authoring-saved-profile-defaults
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous, repo]
parent: OME-1138
created: 2026-09-23
closed:
---

# AIGateway UI: stop authoring saved Profile defaults

This is the UI-first step of Stage C of `OME-1138`. The Admin UI's attach/replace-key form no longer
offers saved request defaults. The key write sends only `{ "api_key": … }` to the existing legacy
admin endpoint, with no `defaults` property. Today's gateway treats an absent key as `null` and
preserves any stored values.

It blocks `OME-1323`, which removes the gateway's stored-default read/merge and rejects writes that
carry defaults. This unit alone does not finish Stage C.

- Ledger: `docs/work/2026-09-23-OME-1322-aigateway-ui-stop-authoring-profile-defaults.md`
- 2026-09-23: started; worktree from `origin/main` at `c6774ea1`.
- 2026-09-23: implemented; the six UI card gates pass (238 tests). Prior defaults tests were retired with a recorded mapping. Not committed.
- 2026-09-23: owner approved the retired defaults tests and a narrowly scoped same-branch correction to the repo append-only check. An exact before/after blob manifest for the three changed TS/TSX tests now lets the full gate runner pass while all other test edits remain protected. `run_gates.py aigateway-ui --base origin/main` reports ALL GATES GREEN. Owner subsequently authorised staging, commit, push and a PR for this unit, including this Markdown path and its ledger; publication outcome is reported separately.
