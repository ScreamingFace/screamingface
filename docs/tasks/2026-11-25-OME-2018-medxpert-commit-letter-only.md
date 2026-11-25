---
id: OME-2018
linear_url: https://linear.app/openmined/issue/OME-2018/tell-the-model-medxpertqas-turn-2-wants-the-option-letter-only
status: done
type: fix
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-25
closed: 2026-11-25
---

# Tell the model MedXpertQA's turn 2 wants the option letter only

MedXpertQA's turn 2 sent the bare trigger "Therefore, among A through J, the answer is" and
relied on the model finishing the sentence. On the first paid run of revision
`952ea002b0f5e3b0` the model wrote a new essay on 2 of 2 Cases and changed one turn-1 answer
from the key to a wrong letter. Turn 2's last message is now one instruction line ("Finish the
sentence below with the option letter only, and nothing else."), a blank line, then the
trigger: a declared deviation from the official harness. The reader also reads a letter in
underscores (`__E__`). Published revision `952ea002b0f5e3b0` → `5f6e01e4fa673215`, owner
sign-off 2026-11-25; neither middle id reached a release, so production moves from
`1e5a3b8a461a52f7` straight to the new id.

- 2026-11-25: built in one PR. Owner actions left: merge; the paid check on the dev Engine
  (about 20 Cases, one solo model and one Fusion); deploy; the reruns (`OME-1981`); the
  Fidelity Record re-audit.
- Ledger: `docs/work/2026-11-25-medxpert-commit-letter-only.md`
