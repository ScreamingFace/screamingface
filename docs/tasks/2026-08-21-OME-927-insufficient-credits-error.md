---
id: OME-927
linear_url: https://linear.app/openmined/issue/OME-927/surface-a-meaningful-upstream-error-ideally-the-providers-own-when-a
status: In Progress
type: Task
priority: Medium
labels: [aigateway, agentic, autonomous]
created: 2026-08-21
closed:
---

# Surface a meaningful upstream error when a run runs out of credits

A run that exhausts upstream provider credits reports a generic
`candidate · case_execution_failed — The upstream provider returned an error.` instead of
telling the user they need to top up. Implementing the ticket's Option 2 fallback: map HTTP 402
to a dedicated `insufficient_credits` code/message in aigateway's error sanitizer — in **both**
the generic transport-error mapping (`chat_dispatch.py`) and OpenRouter's separate
embedded-in-200-body error mapping (`openrouter_provider/dispatch_errors.py`), since OpenRouter
— the ticket's own lead example — reports insufficient-credits through the latter path only.

Canonical artifacts:

- Ledger: `docs/work/2026-08-21-OME-927-insufficient-credits-error.md`
- PR: https://github.com/ScreamingFace/screamingface/pull/679 (open, CI pending)
