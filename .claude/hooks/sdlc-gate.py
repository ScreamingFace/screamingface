#!/usr/bin/env python3
"""UserPromptSubmit hook — re-inject the ScreamingFace SDLC work-item gate on every prompt.

Advisory rules in CLAUDE.md don't self-enforce (they lose to the immediate task framing).
This hook re-states the non-negotiable gate each turn so the epic-first work-item rule stays
salient. The issue is filed when the PR is opened — not at work start, and not on a commit or
a new branch — and only after the user confirms it (D19). Non-blocking: it only injects context,
never denies. Refs: OME-378, OME-1262.
"""

import json

GATE = (
    "[SDLC GATE — screamingface] If this turn will OPEN A PULL REQUEST: BEFORE opening that PR "
    "— NOT at work start, and NOT on a commit or a new branch — "
    "(1) ask the user to confirm, then file the Linear issue UNDER AN EPIC "
    "(OME-N, Engineering / 😱 ScreamingFace V1), SELF-ASSIGNED (assignee: me — never "
    "unassigned), with its docs/work ledger + docs/tasks mirror, and put `Refs: OME-N` in the "
    "PR body; "
    "no fitting epic → PROPOSE one (say 'I'm not allowed to create an epic on your behalf; "
    "this is a proposed epic — confirm and I'll create it'); on the user's consent create it in "
    "Triage with Irina + Kevin tagged for approval, then file the leaf under it and proceed "
    "(the PR does not block on their approval). "
    "Agents never file orphan tickets and never auto-create epics without the user's consent. "
    "ONE exception to all of this: a `bug`-labeled issue needs no epic — file it in Triage, "
    "left UNASSIGNED, with Irina + Kevin tagged for review. "
    "(2) invoke working-in-this-repo + task-management (+ the stack's sdlc-* skill for code); "
    "(3) order is spec → plan → code; (4) never commit to main — every change lands via PR. "
    "Committing and pushing a branch need no issue; only opening a PR does. "
    "Pure question / read-only / commit-or-branch-only turn? Ignore this line."
)

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": GATE,
            }
        }
    )
)
