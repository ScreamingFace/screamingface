---
id: OME-1168
linear_url: https://linear.app/openmined/issue/OME-1168/the-loops-judge-sees-internal-accounting-metadata-in-its-prompt-so-a
status: in_progress
type: fix
priority: High
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-10
closed:
---

# The loop's judge sees internal accounting metadata in its prompt, so a recorded run can't be replayed

The CorrectiveLoop coach prompt embeds the full round object, dragging each
member's Candidate Invocation envelope (accounting/usage, provider/model ids)
into the judge's paid prompt. Live vs replay accounting values differ, so
multi-round recorded runs never replay. Fix: client-side only — the coach's
`verdicts` becomes a per-member {answer, feedback} projection; the round object
(needed verbatim by gate/select/answer/result) is untouched. Tie path already
clean. Details + evidence: Linear issue; how: ledger
`docs/work/2026-09-10-OME-1168-judge-prompt-minimal.md`.
