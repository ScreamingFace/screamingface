---
id: OME-1980
linear_url: https://linear.app/openmined/issue/OME-1980/send-medxpertqas-turn-2-as-a-continuation-of-the-candidates-own-chat
status: done
type: fix
priority: high
labels: [screamingface-engine, agentic, design-session]
parent: OME-1299
created: 2026-11-20
closed: 2026-11-24
---

# Send MedXpertQA's turn 2 as a continuation of the Candidate's own chat

MedXpertQA's commit turn was a new chat holding one user message (a JSON object with the
question, the turn-1 reasoning and the trigger), so the model explained again and the
first-letter reader graded its first stray capital: an external researcher lost 475 of 2,450
Cases. Turn 2 now continues the Candidate's own chat (user prompt, assistant answer, user
trigger), the official harness's layout; the one model that wrote the turn-1 answer commits (a
Fusion's synthesizer alone, 5 calls per Case instead of 8, members' turn-1 rows kept as
evidence); the reader stops at a second trigger as the harness does. Sampling and the system
message stay the Candidate's, so turn 1 is byte-identical and reruns replay it from the cache.
Published revision `490235dc9a53b7d9` → `952ea002b0f5e3b0`, owner sign-off on the ticket.

- 2026-11-24: built in one PR. Owner actions left: merge; the paid two-run check on the dev
  Engine; deploy; the reruns (`OME-1981`); the Fidelity Record re-audit.
- Ledger: `docs/work/2026-11-24-medxpert-commit-continues-chat.md`
