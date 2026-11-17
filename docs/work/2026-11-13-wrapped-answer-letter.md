---
ticket: OME-1907
stack: screamingface-engine
status: done
started: 2026-11-13
finished: 2026-11-13
---

# wrapped-answer-letter — grade a letter inside a wrapper like $B, **B** or (B) against its key

## Intent

inspect_ai's parsers read only a bare letter after `ANSWER:`, so `ANSWER: $B`, `ANSWER: **B**`,
`ANSWER: (B)` or `ANSWER: \boxed{B}` score 0 even when B is right ([inspect_ai issue
5055](https://github.com/UKGovernmentBEIS/inspect_ai/issues/5055), open; the one fix attempt,
[PR 5058](https://github.com/UKGovernmentBEIS/inspect_ai/pull/5058), closed). Muse Wonder lost 68
of 200 MMLU-Pro replies to it (OME-1886). When inspect reads no valid answer, we peel one
wrapper layer at a time (at most 3) from a copy of the reply and ask inspect's own parser again.
The stored reply is never rewritten, and any reply inspect reads today keeps its reading. The
rule is a Named Deviation package whose source is pinned into every row it grades, so 46
fingerprints move while every published revision is held (the documented OME-1610 rule for a
grading fix that keeps every Case). Stacked on #1780 (OME-1906): its answer-format sentence
must now say wrapped letters count.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine_inspect/named_deviations/wrapped_letter/` — the peel rule, inspect-first answer parsing, a peel-and-retry for pattern scorers, and the mathvista scorer
- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py` — option marking calls the wrapped parser
- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/bbh/bbh.py` — the yes/no subsets retry through the peel
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — the option-marking pin on the 45 mark-reading rows; mathvista's scorer swapped
- `apps/screamingface-engine/src/screamingface_engine_inspect/answer_formats/_choice.py` — the sentence says wrapped letters count
- tests: a new `test_named_deviation_wrapped_letter.py`; `test_benchmark_fingerprints.py` literals; `test_answer_formats.py` follows the sentence
- 22 fidelity records (21 comparable-to-inspect, pubmedqa comparable-to-paper) → `unverified`
- `docs/tasks/` mirror of OME-1907

## Test plan

- the 25 reply shapes of the OME-1907 table through the real `parse_answers` (fixed, unchanged, refused)
- tripwire: the pinned inspect_ai still reads `ANSWER: $B$` as no answer
- the adapter marks option B for `ANSWER: $B` on a real Case
- mathvista: wrapped letter and wrapped free-form answer graded; an unwrapped wrong answer stays wrong
- bbh: `ANSWER: **Yes**` graded on a yes/no subset
- the option-marking pin lands on exactly the mark-reading rows

## Acceptance

- every wrapped shape in the OME-1907 table grades against its key; every shape inspect reads today keeps its grade; the refusals stay refused
- 47 fingerprint literals move, no `published_revision` moves

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `answer_formats/__init__.py` (worked example), `CHANGELOG.md`, `test_scorer_source_pins.py` (mathvista joins the deviating rows) and 23 fidelity records, not 22 (mathvista's was comparable-to-inspect too).
- **Commits:** the OME-1907 PR's commits, on top of the OME-1906 stack.
- **Gates:** run with the inspect extra: 252 passed in the 4 touched test files, 979 passed in the 11 files that import the changed modules (adapter, bbh, mathvista, revisions, real-grader replays); ruff check and format clean; pyright clean on the new package, the adapter and bbh. `fidelity_check.py` exits 0 (47 records stale by this PR's fingerprints, to re-audit).
- **Deviations:** stereoset out of scope (its scorer re-reads the reply, like SAD's; 0 leaderboard entries). 47 fingerprints move, not 48. bbh's multiple-choice subsets needed no scorer change: they grade from the adapter's option marks.
- **Review round 1 (2026-11-13):** the peel unwrapped every `ANSWER:`, so a retracted draft at a line start (`ANSWER: (A)` … `Final ANSWER: $C$`) became inspect's strict match and was read over the final answer; now only the last `ANSWER:` (label included) is peeled, pinned by 3 retracted-draft tests. The pin test claimed more than it checked (both sides built from one list): reworded, plus a test that every scorer named *choice* is classified as reading marks or not. `peeled_score` documents that it is only for last-site patterns. 47 fingerprints moved again with the rule's source (mmlu_pro `ecef3997b0210b15`). 1,160 passed in the 12 relevant test files.
- **Review round 2 (2026-11-17):** the peel unwrapped only the first answer after the label, so a wrapped hedge (`ANSWER: (A) (B) (C) (D)`) read as A and scored 1, and a wrapped list on cyse4 (`ANSWER: (A), (B)`) read as A alone. Now each later answer on the answer line is unwrapped too: every wrapper of the first one's kind, and any wrapper around a single letter or word, so the list reads as its bare form. Prose in brackets after the answer is kept (`$B$ (the second option)` still reads B). Accepted cost: `ANSWER: $B$ (C)` reads as the hedge `B C`, no answer, as on main. Pinned by 5 hedge tests, 5 list/prose shapes and a cyse4 end-to-end test; all 11 new tests fail with the list peel disabled. 47 fingerprints moved again (mmlu `4ae3b8ad8939d06a`); the prior-test edits are approved in `.claude/test-change-approvals/OME-1907.json`. 1,208 passed in the 12 relevant test files; ruff and pyright clean; `fidelity_check.py` exits 0. Still read as no answer (scored 0 before too, so not regressions): `**Final Answer:** $B$`, `*B*`, `"B"`, `\(B\)`, `\textbf{B}`, `$\text{B}$`.
- **Merge of main (2026-11-17):** after #1780, #1781 and #1785 merged, OME-1906's answer-format sentences said a wrapped letter scores 0 on rows this rule now grades. The choice sentence (35 rows; `**ANSWER:** B` now counts too), lab_bench (8 rows), the two cyberseceval rows, bbh (letters and yes/no) and mathvista (rekeyed to our scorer) now say wrapped answers count; every quoted reply is still graded through each row's real grader (`test_answer_formats.py`). 1,477 passed in the 14 relevant test files.
- **Hedge check (2026-11-17, owner's call):** probing 15 edge shapes against inspect's real parser on the hand-stripped bare form found one class the peel still credited: `ANSWER: (A)/(B)`, `ANSWER: (A) - no wait, (B)` and letters on separate lines peel to a form inspect's fallback reads as A. A peeled reading that leaves out a capital option letter the reply names after its last `ANSWER:` is now no answer; inspect's own reading (`ANSWER: A/B` → A) is untouched. Accepted cost: `ANSWER: **B** (not A)` is refused, as on main. 5 new tests, all failing with the check disabled; 47 fingerprints moved (mmlu `e6a95e4c1f1ced71`); 1,483 passed in the 14 relevant test files.
- **Owner verify:** the bump-or-hold decision for the 47 rows (held here); if bumped, the replay-cost test on the dev Engine before any leaderboard entry moves. If held: the 119 leaderboard entries on 30 rows graded the old way share an id with re-graded results, so the owner replays their pinned caches through this grader on prod after deploy (the dev Engine cannot replay prod caches).
