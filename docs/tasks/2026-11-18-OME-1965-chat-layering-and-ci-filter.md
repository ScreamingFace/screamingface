---
id: OME-1965
linear_url: https://linear.app/openmined/issue/OME-1965/let-the-layering-gate-and-the-engine-ci-cover-the-chat-package-and-its
status: in_review
type: task
priority: low
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1297
created: 2026-11-18
closed:
---

# Let the layering gate and the Engine CI cover the chat package and its docs examples

Two small repo changes for the chat endpoint of the Engine. `check_layering.py` knows the new
Engine package `chat/` as a shared leaf. The Engine test workflow also starts when the chat docs
page or its snippets change, because Engine tests read those files. `CONTEXT.md` gets the terms
Chat Request, Chat Run, Final Step and Text View.

- Parent epic: `OME-1297`. It ships in the PR of `OME-1963`.
- Ledger: `docs/work/2026-11-17-engine-openai-chat-endpoint.md` (units U2 and U7)
