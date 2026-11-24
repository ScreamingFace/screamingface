---
id: OME-1907
linear_url: https://linear.app/openmined/issue/OME-1907/grade-a-multiple-choice-letter-inside-a-wrapper-like-dollarb-b-or-b
status: done
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-13
closed: 2026-11-13
---

# Grade a multiple-choice letter inside a wrapper like $B, **B** or (B) against its key

inspect_ai reads only a bare answer after `ANSWER:`, so `ANSWER: $B`, `ANSWER: **B**`,
`ANSWER: (B)` or `ANSWER: \boxed{B}` score 0 even when the letter is right (inspect_ai issue
5055). When inspect reads no answer, the Engine now peels one wrapper layer at a time, at most
3, from a copy of the reply and asks inspect's parser again; the stored reply is never
rewritten and every reply inspect already reads keeps its grade. 46 rows graded from option
marks, mathvista and bbh's yes/no subsets are covered; 47 fingerprints move, and the published
revisions move in OME-1958. The OME-1906 answer-format sentence now says wrapped letters count, and 23
fidelity records move to `unverified`.

- 2026-11-13: filed under epic `OME-1299`, built in one PR stacked on the OME-1906 PR.
- 2026-11-17: the owner chose to bump the 47 rows' published revisions; they move in OME-1958
  (the bump PR, merged and deployed right before its batch re-grade, which moves the old leaderboard entries onto the new ids).
- Ledger: `docs/work/2026-11-13-wrapped-answer-letter.md`
