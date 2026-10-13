# PRD: The benchmark's answer rule (grader parity)

**Source:** PRD "Extract and normalize", criterion A2 · ans:Q5 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) — graders and combine operators exist, separate
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [block-api](block-api.md).

## 1. Summary and user story

As a researcher, I want `sf.Vote(extract="benchmark")` to group answers with the benchmark's own
grading rule, so that a vote tally and the benchmark score can never disagree about whether two
answers are the same.

## 2. Background and constraints

- "The same library grades the benchmark, so a Reduce tally and a benchmark score cannot
  disagree about whether two answers are the same." `[stated prompt]`
- "`Extract` … produces the same `value` as the benchmark grader on the GSM8K and MATH fixtures."
  `[stated prompt]`
- "Vendor Inspect's match(numeric) rule as pinned operators (precedent: ifeval/vendor). Each
  benchmark declares its answer rule; `Vote(extract='benchmark')` uses it. A parity test runs the
  real Inspect scorer against the operators on GSM8K and AIME fixtures. MATH waits until a MATH
  benchmark is imported." `[stated ans:Q5]`
- "Where does normalization equivalence live …? Recommendation: the benchmark declares it, the
  recipe can only tighten it." `[stated prompt]` (PRD open question)

### 2.1 Current behavior

- GSM8K is graded by `inspect_ai.scorer:match(numeric=True)`
  `[existing EI/benchmarks.py:93]`. `inspect-aime24` and `inspect-aime25` by
  `inspect_evals.aime2024.aime2024:aime_scorer` and `inspect_evals.aime2025.aime2025:aime_scorer`
  `[existing EI/benchmarks.py:345]`.
- `match(location="end", numeric=True)` at inspect-ai **0.3.263** (the engine's locked version):
  strip, casefold, strip `$ € £ , * _` (and their LaTeX escapes), split on whitespace, take the
  **last word that parses as a finite number** (float syntax plus Unicode forms: vulgar fractions,
  superscripts, full-width digits, CJK numerals), trim `!?:;()[]{}'"\``, and compare
  `format(n, ".5g")` of both sides `[existing SP/inspect_ai/scorer/_common.py:40]`
  `[existing SP/inspect_ai/_util/text.py:36]`.
- `aime_scorer` (inspect-evals **0.20.0**): last substantive line → remove `\boxed{}` → the same
  `match_str(..., location="end", numeric=True)` `[existing SP/inspect_evals/utils/aime_common.py:71]`.
- The combine `last_number@1` + `numeric@1` differ: `"x=42"` → Inspect finds no number, combine
  finds `42`; `123456` vs `123457` → equal in Inspect (5 significant digits), different in combine;
  `"1,23"` → Inspect reads `123`, combine marks `not_numeric`
  `[existing E/combine/operators/extract.py:56]` `[existing E/combine/operators/normalize.py:35]`.
- No shared code and no parity test. The engine has no MATH benchmark.

**Delta.**
1. Vendor the Inspect number rule (stdlib only) as `E/combine/operators/_inspect_vendor.py`, with
   the MIT notice and the pinned versions in its header. Copy **only** these functions: from
   `inspect_ai/scorer/_common.py` the numeric path of `match_str` (location `end`), `_is_number`,
   `_parse_number`, `_clean_numeric_word`, `first_number_normalized`, `normalize_number`; from
   `inspect_ai/_util/text.py` only `strip_numeric_punctuation` (that module imports `random` and
   `logging`, which plugins may not import `[existing .claude/scripts/check_layering.py:118]`); from
   `inspect_ai/scorer/_unicode.py` `unicode_number_to_float` and its helpers (`unicodedata` only);
   from `inspect_evals/utils/aime_common.py` `_find_last_substantive_line` and
   `remove_boxed_from_ans`. No number found → `status="fail"`, `reason="empty"`.
2. New operators: `inspect_number@1` (extract, GSM8K rule), `inspect_aime@1` (extract, AIME rule),
   `inspect_numeric@1` (normalize, `.5g`).
3. `Benchmark.answer_rule` / `BenchmarkSpec.answer_rule` (optional), emitted in the catalog entry
   when set ([erd.md §7](../erd.md#7-benchmark_answer_rule--new-engine-catalog-field)).
4. SDK: `extract="benchmark"` resolves the rule **before any spend**, at the place where the
   operator catalog check runs `[existing S/_evaluation/runner.py:99]`, and writes the concrete op
   ids into the url4.
5. Parity tests in the Inspect CI lane: the real scorer against the operators.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **GP-1** Given `sf.Vote(extract="benchmark")` on `inspect-gsm8k`, when the evaluation compiles,
  then the url4 spec pins `inspect_number@1` + `inspect_numeric@1`, and no model call ran before
  the resolution. `[stated ans:Q5]`
- **GP-2** Given the GSM8K parity corpus, for every (text, target): Inspect `match(numeric=True)`
  says correct ⇔ `inspect_numeric(inspect_number(text)) == inspect_numeric(target)`.
  `[stated ans:Q5]`
- **GP-3** Given the AIME parity corpus, the same equivalence holds with `inspect_aime@1` and
  `aime_scorer`. `[stated ans:Q5]`
- **GP-4** Given two members whose texts the grader marks equal (for example `"$1,200."` and
  `"1200"`), then they fall in one tally row. `[stated prompt]`

### 3.2 Error paths

- **GP-E1** Given `extract="benchmark"` on a benchmark with no `answer_rule` (for example
  `inspect-mmlu`), then `ValueError` before any spend names the benchmark and the rules it can
  use. `[implied]`
- **GP-E2** Given `extract="benchmark"` with an explicit `normalize=`, then `ValueError`: the
  benchmark declares the normalizer; v1 does not let a recipe change it. `[proposed]` (the PRD
  allows "tighten"; v1 has no safe definition of tighter, so it refuses)
- **GP-E3** Given an Engine whose operator catalog lacks `inspect_number@1` (an Engine from
  before this change), then `EngineCapabilityError` before any spend. An entry with no
  `answer_rule` is GP-E1. `[existing S/_engine/catalog.py:427]`

### 3.3 Derived scenarios (risk-ordered)

- **GP-D1** Version drift `[proposed]` (H×M): a test fails when the installed `inspect-ai` or
  `inspect-evals` version, or `unicodedata.unidata_version`, is not the one pinned in the vendored
  header. A dependency bump then forces
  a re-vendor and a parity re-run.
- **GP-D2** Non-numeric target `[existing SP/inspect_ai/scorer/_common.py:61]` (M×M): when a target
  does not parse as a number, Inspect falls back to a text match. The parity corpus covers only
  numeric targets; GSM8K and AIME targets are always numeric. A test pins that every GSM8K and AIME
  fixture target parses as a number.
- **GP-D3** Corpus edge cases `[proposed]` (H×M), each a parity row: commas, bad grouping
  (`1,23`), currency, LaTeX `\$`, trailing `.`, `.0`, negatives, Unicode minus, `½`, `3²`,
  full-width digits, CJK numerals, exponent (`3.5e10`), `x=42`, `(42)`, `42%`, `~42`, empty text,
  boxed with nesting (AIME), multi-line with a trailing explanation (AIME).
- **GP-D4** Property `[proposed]` (M×M): a seeded `random.Random(1289)` generator (no new test
  dependency) builds 2000 numeric words and sentences; the equivalence holds for all of them.
- **GP-D5** Url4 is benchmark-specific `[stated ans:Q12]` (M×M): a candidate with
  `extract="benchmark"` compiles to a different url4 per benchmark; its identity is recipe +
  benchmark. The Report keeps the url4 that ran
  `[existing S/report.py:298]`, so a replay needs no benchmark lookup.
- **GP-D6** Replay of the resolved url4 `[implied]` (M×L): `client.evaluate("<url4>")` runs the
  pinned ops; it does not resolve `benchmark` again.
- **GP-D7** Layering `[existing .claude/scripts/check_layering.py:102]` (H×L): the vendored module
  imports only the standard library; the COMBINE_CORE gate stays green.
- **GP-D8** Catalog cache `[existing E/rest/benchmarks.py:21]` (L×M): adding `answer_rule` changes
  the benchmark catalog ETag; the SDK cache revalidates.

## 4. Non-functional requirements

- Resolution adds at most one catalog request per evaluation (cached by ETag) `[proposed]`.
- The parity lane runs only with the `inspect` extra, like the existing Inspect tests
  `[existing ET/inspect/test_combine_gsm8k_check.py:1]`.
- A2 is met for the **benchmark rule**. The built-in rules (`boxed`, `last_number`, `field`,
  `regex`) keep their own semantics and can differ from a grader by design; AIME stands in for MATH
  until a MATH benchmark exists `[stated ans:Q5]`.

## 5. Out of scope

- A MATH benchmark and LaTeX equivalence (waits for a MATH import) `[stated ans:Q5]`.
- Answer rules for multiple-choice (`choice()`) and yes/no (`pattern`, `includes`) benchmarks
  `[proposed]` (follow-up; same mechanism).
- Moving the graders onto the combine operators (spec D3).

## 6. Open questions

None.

## 7. TDD plan

Risk-first: the drift guard and the parity corpus before the SDK sugar.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: `last_number@1`+`numeric@1` disagree with Inspect on `x=42`, `123457`, `1,23` (documents the gap) | unit (inspect lane) | [existing E/combine/operators/extract.py:56] | — | passes today |
| 2 | `vendored_rule_pins_installed_inspect_versions` | unit (inspect lane) | GP-D1 | H×M | header constants vs `importlib.metadata` |
| 3 | `gsm8k_parity_corpus_matches_inspect_match_numeric` | unit (inspect lane, parametrized) | GP-2, GP-D3 | H×H | vendor `_inspect_vendor.py`; `inspect_number@1`, `inspect_numeric@1` |
| 4 | `aime_parity_corpus_matches_aime_scorer` | unit (inspect lane) | GP-3, GP-D3 | H×H | `inspect_aime@1` |
| 5 | `parity_holds_for_generated_numbers` | unit (property, inspect lane) | GP-D4 | M×M | — |
| 6 | `every_gsm8k_and_aime_target_is_numeric` | unit (inspect lane) | GP-D2 | M×M | — |
| 7 | `vendored_module_imports_only_stdlib` | unit (layering gate) | GP-D7 | H×L | keep `check_layering.py` green |
| 8 | `gsm8k_and_aime_declare_answer_rules_in_catalog` | integration (REST) | delta 3 | H×M | `BenchmarkSpec.answer_rule`; catalog entry |
| 9 | `benchmark_extract_resolves_before_spend` | unit (SDK, forbidden transport) | GP-1 | H×H | resolve in `runner.py` pre-spend block |
| 10 | `benchmark_without_rule_raises_before_spend` | unit (SDK) | GP-E1 | H×M | — |
| 11 | `benchmark_extract_with_normalize_raises` | unit (SDK) | GP-E2 | M×M | — |
| 12 | `engine_without_inspect_operators_raises_capability_error` | unit (SDK) | GP-E3 | M×L | — |
| 13 | `grader_equal_texts_share_one_tally_row` | unit (engine) | GP-4 | M×M | golden case |
| 14 | `resolved_url4_replays_without_benchmark_lookup` | unit (SDK) | GP-D6 | M×L | — |
| 15 | `benchmark_extract_compiles_a_different_url4_per_benchmark` | unit (SDK) | GP-D5 | M×M | — |
| 16 | `answer_rule_changes_benchmark_catalog_etag` | integration (REST) | GP-D8 | L×M | — |
