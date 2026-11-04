---
id: OME-1808
linear_url: https://linear.app/openmined/issue/OME-1808/a-reduce-call-with-no-attachments-sends-an-empty-user-message-and
status: in_review
type: bug
priority: none
labels: [bug, screamingface-engine]
created: 2026-11-02
---

# A reduce call with no attachments sends an empty user message, and Anthropic rejects it with 400

`world/connector.py` `_messages` always added a user message carrying `context or ""`. A call with an
intent and an empty context (a default-route reduce, for example) therefore sent the system message
plus an empty user turn, which Anthropic rejects with 400. Now, when the context is empty and an intent
exists, the call sends the intent as the only user turn. Every other case builds byte-identical
messages, and request-identity keys are unchanged. Found by the OME-1551 end-to-end run.

Ledger: `docs/work/2026-11-02-empty-user-turn.md`.
