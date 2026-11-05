# Which outside results may receive ranks?

Outside results may share ranks only when their question version, complete
coverage, grading rules and metric match the board. Prompts may differ, but the
difference must be recorded. Exact, documented score conversions are allowed.
Unknowns do not count as a match.

## Import procedure

1. Check the board against its reviewed profile in
   `src/scoreboard/scores/comparison_profiles.py`. Profiles pin the revision,
   question-set hash, case count, grader, metric, units and score range. A board
   with no profile cannot rank external results. Adding or changing a profile
   requires a reviewed code change with source evidence.
2. Check the result's actual evaluation against those requirements. A dataset
   containing 206 questions does not prove that a reported run answered all 206.
   Record public evidence for the question set, grading, run coverage and units.
3. Import with `metric_name`, `source_url`, `observed_at`, internal `attached_by`,
   and `metadata.comparison`. `reviewed_at` must follow the source observation.
   `attached_by` identifies the operator attaching the reviewed observation; it
   is not authenticated identity or a public field.
4. Check the returned `ranking_eligible` value. This is derived by the server,
   never accepted as an import input. The portal requires literal `true`.

An observation without a comparison review may still be stored and read through
the separate API `baselines` collection. It receives no table rank, summary count
or score bar. A malformed or incompatible supplied review rejects the import;
one rejected item rolls back the whole batch. An old API without eligibility
cannot accidentally approve a row in a newer portal.

The checks validate an operator's recorded evidence and the machine-checkable
requirements; they do not prove that a linked report is truthful. The importer
does not fetch links or judge source text. Operators must not copy target hashes
or grader names into the review without establishing the match.

## Review shape

Illustrative review for a hypothetical compatible SAT-English run, not approval
of either existing AGIEval trial result:

```json
{
  "policy_version": "1",
  "benchmark_revision": "092ea478f523193d",
  "question_set_sha256": "33fe87b32ff16ae7ba52b27bb398190b082253b3617a3eb9737005262ba12dd4",
  "grading_id": "inspect-ai-0.3.263-choice",
  "evaluated_case_count": 206,
  "original_score": 75.0,
  "original_unit": "percent",
  "conversion": "percent_to_fraction",
  "reviewed_at": "2026-11-04T10:00:00Z",
  "prompt_note": "Different instructions; same answer extraction and grading.",
  "evidence": {
    "questions": "https://example.org/report/questions",
    "grading": "https://example.org/report/grading",
    "coverage": "https://example.org/report/coverage",
    "units": "https://example.org/report/metric"
  }
}
```

Put this object under `metadata.comparison`; import its converted `score` as
`0.75`. Keep evidence public: source metadata is visible even on private boards.
The review's `prompt_note` is available through the portal's Comparison disclosure.

| Conversion | Requirements |
| --- | --- |
| `identity` | Original and board units match; value is in the board's range. |
| `percent_to_fraction` | Original units explicitly mean percent; divide by 100. |
| `fraction_to_percent` | Original units explicitly mean fraction; multiply by 100. |
| `count_to_fraction` | Integer correct count, accuracy metric, full verified case count as denominator. |

The importer checks decimal arithmetic against the supplied score, then stores
the original value, unit, conversion and evidence unchanged. It never guesses a
conversion from a number's size. Percentages must be between 0 and 100; fractions
between 0 and 1. Count conversions cannot use a partial run's denominator.
Conversions to unrelated metrics, unexplained “points”, or error rates with
unknown treatment of skipped/partial-credit answers are unsupported. A new exact
conversion can be added with evidence and tests rather than an arbitrary formula.

Eligibility is rechecked on reads. Changed board scope, invalid stored metadata,
or a replacement observation without a valid review removes eligibility. The
existing importer replaces metadata rather than retaining approval from an older
observation. It still does not provide edit history.

## SAT-English audit — 2026-11-05

**Neither trial row qualifies.** GPT-4o 93.2% and GPT-3.5 70.4% convert correctly to
0.932 and 0.704, but their published aggregates cannot repair different grading
rules or establish missing run-coverage evidence.

| Check | Evidence | Decision |
| --- | --- | --- |
| Board scope | Dev and production public APIs report revision `092ea478f523193d`, 206 cases. Dev has two trial baselines and zero community entries; production has four entries and zero baselines. | Scope unchanged. |
| Questions | The repository-pinned SAT-English file has 206 records, 1,101,726 bytes, SHA-256 `33fe87b32ff16ae7ba52b27bb398190b082253b3617a3eb9737005262ba12dd4`. | Source question match confirmed. |
| Prompts | Authors request continuation of “the answer is”; Inspect requests an answer marker. | Allowed when documented. |
| Answer extraction and grading | Authors' zero-shot parser takes the first capital A–F; Inspect parses the `ANSWER:` marker and validates choices. | Does not match. |
| Historical run coverage | No raw replies or complete-run record was obtained for these published aggregates. Dataset size alone is insufficient. | Not verified. |
| Deployment assets | Public board metadata was checked; deployed Engine asset bytes were not independently inspected. | Do not claim deployed-file verification. |

Re-executing the two pinned parser functions on synthetic replies produced:

| Reply | Authors' parser | Inspect parser |
| --- | --- | --- |
| `ANSWER: B` | A | B |
| `B` | B | No answer |
| `The answer is B.` | B | No answer |

These examples establish non-equivalence, not how many historical scores would
change. Each original prompt requests its own format. We cannot transform the
aggregate accuracy into a score under another parser without the actual replies.

Sources:

- [Published AGIEval results](https://github.com/ruixiangcui/AGIEval/blob/84ab72d94318290aad2e4ec820d535a95a1f7552/gpt_results.png).
- [Pinned questions](https://github.com/ruixiangcui/AGIEval/blob/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/sat-en.jsonl),
  [authors' parser](https://github.com/ruixiangcui/AGIEval/blob/84ab72d94318290aad2e4ec820d535a95a1f7552/src/post_process.py),
  [Inspect task](https://github.com/UKGovernmentBEIS/inspect_evals/blob/v0.20.0/src/inspect_evals/agieval/utils.py).
- [Inspect AI 0.3.263](https://pypi.org/project/inspect-ai/0.3.263/): wheel SHA-256
  `503e7ff509d77fcdf65989027a19fea966fb668deb88a234468c3290964fd86a`, verified against
  PyPI metadata; functions inspected from `solver/_multiple_choice.py` and
  `scorer/_choice.py`.
- [Dev board](https://leaderboard.dev.screamingface.ai/benchmark.html?id=inspect-agieval_sat_en)
  and [production board](https://leaderboard.screamingface.ai/benchmark.html?id=inspect-agieval_sat_en).

The stored dev trial observations remain intact. They have no qualifying review
and are held out automatically once the guarded portal is deployed. Qualifying
these reported results requires historical replies regraded with matching rules
and complete coverage evidence, or a newly measured compatible run. No paid run
or production data change is part of this audit.
