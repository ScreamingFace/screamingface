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
- **Owner verify:** the bump-or-hold decision for the 47 rows (held here); if bumped, the replay-cost test on the dev Engine before any leaderboard entry moves.
