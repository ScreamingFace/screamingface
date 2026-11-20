---
id: OME-1982
linear_url: https://linear.app/openmined/issue/OME-1982/state-medxpertqas-real-first-letter-rule-on-its-page
status: done
type: fix
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-20
closed: 2026-11-20
---

# State MedXpertQA's real first-letter rule on its page

MedXpertQA's answer-format sentence described `grading.extract_letter` (last letter wins), which
never runs when a Case is scored. Scoring runs `answering.extract_choice_letter`, the official
`answer_cleansing` port: the first capital option letter standing alone wins. An external user's
prose commits lost about 11 points to a stray article "A" (475 of 2,450 Cases). The sentence now
states the real rule, shows the prose trap, and tells recipe authors to make the commit reply the
letter alone. Description only: no published revision or fingerprint moves.

- 2026-11-20: filed under epic `OME-1299` at PR-open. The root cause (turn 2 is a fresh Candidate
  call, not a continuation) is `OME-1980`; the re-runs that fix forces are `OME-1981`. Owner
  action left: merge; the text reaches the leaderboard on the next deploy.
- Ledger: `docs/work/2026-11-20-medxpert-card-first-letter-rule.md`
