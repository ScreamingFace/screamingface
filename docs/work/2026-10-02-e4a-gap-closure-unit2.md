---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 2 -- Answer operators: regex, set, Inspect rules, signal weights

## Intent

Fold the answer-operator part of the E4a gap-closure into the v1 operators, on top of the unit 1
core (`Answer`, `NoVotes`, signals). Add `regex@1` with a static backtracking ban, `set@1`,
`inspect_number@1`, `inspect_aime@1` and `inspect_numeric@1` (a vendored copy of Inspect's numeric
answer rule, guarded against drift), and let a signal-weighted vote skip a member with no usable
weight. Move `json_field@1` onto the ports field-path walk. The branch is rebased onto
`e4a-combine-core`; one repair commit moves the replayed operators onto the core's `Answer` port.

## Planned changes

- Rebase repair: `reduce.py`, `select.py` use `Answer` and `.member_id`; the golden support builds
  `Answer` rows from the stage-reading fixture format (F2).
- `operators/extract.py`: `json_field@1` reads through `ports` (`FIELD_PATH`, `decode_json_reply`,
  `walk_field_path`); `regex@1`; `inspect_number@1`; `inspect_aime@1`.
- `operators/_regex_ban.py` (new): static ReDoS ban over the stdlib parse tree.
- `operators/normalize.py`: `set@1`, `inspect_numeric@1`.
- `operators/reduce.py`: `weighted_mode@1` skips a voter with no usable signal weight.
- `operators/_inspect_vendor.py` (new): verbatim copies of the Inspect numeric rule + pins.
- `pyproject.toml`: the vendor file leaves ruff, pyright and coverage (F19).
- Tests and fixtures, listed below.

## Test plan

A: this ledger. B: repair, no RED (restores green). C: rows 1-2. D: SR#1-4 (rows 3-7).
E: RX#1, RX#1b, RX#2-7 (rows 8-18). F: RX#8-9 (rows 19-20). G: GP#1, GP#2, GP#7 (rows 21-26).
H: GP#13, GP#3-6 and the base-lane Inspect rule tests (rows 27-34). I: RX#12 (row 35).
J: ledger close.

## Notes

Decisions F1-F22 (from the unit spec):

- F1 the rebase has no textual conflict; the breakage is semantic and fixed in one repair commit.
- F2 fixture JSON keeps the stage-reading format; the loader maps rows to `Answer` via `answer_status`.
- F3 `weighted_mode@1`: `weight is None` and non-empty signals -> does not vote; empty signals -> `SpecInvalid`.
- F4-F9 (the static backtracking ban, `_regex_ban.py`) are SUPERSEDED by the RE2 decision below; the
  ban and its tests are deleted.
- F10 `remove_boxed_from_ans` is vendored verbatim; `inspect_aime@1` calls the linear `_unbox`.
- F11 Inspect number rule: exact semantics plus one sound ASCII fast exit; a guard test pins the cost (tripwire).
- F12 the vendor file holds only verbatim definitions; `match_str` paths are adapters.
- F13 `UNIDATA_VERSION` is pinned for Python 3.13 only; other minors skip that one test.
- F14 `inspect_numeric(inspect_number(text))` equals `match_str`: parity corpus pins it.
- F15 parity corpora are inline constants in the parity test.
- F16 `set@1` counts distinct, non-empty, normalized items against 256.
- F17 the AIME scorer is `importlib.import_module("inspect_evals.aime2024.aime2024").aime_scorer`.
- F18 `re._parser` is imported with a type-ignore and a WHY comment.
- F19 the vendor file is excluded from ruff, pyright and coverage (ifeval precedent).
- F20 SDK half of RX#2, RX#10, RX#11 are not in this unit.
- F21 the vendor file keeps its module-level sets and dicts; they are never mutated or imported.
- F22 `_parse_chinese_number` is hash-seed independent; a determinism scenario pins it.

## Results

- Commit B (`fix(engine): move the answer operators onto the core's Answer port`) restores green and
  has no RED of its own: before it, the unit 2 suite failed at collection (ImportError on
  `MemberReading`); after it, every unit 1 and unit 2 combine test passed (501 tests).
- Commit D CHAR row SR#1: the existing `weighted_mode@1` and `max_weight_holder@1` goldens
  (`weighted_mode@1.json`, `max_weight_holder@1.json`) stayed green with no edit. SR#4 (the
  field-signal vote) is green on the new core without an operator change, as the core already
  resolves the weights; only the missing-weight rows (SR#2, SR#3) needed the operator change.
- Gates, run from the worktree with `--base e4a-combine-core --skip-append-only`:
  `screamingface-engine`, `screamingface` and `repo` all ended `ALL GATES GREEN`.
- Inspect lane (`uv run --extra inspect pytest -q -rs tests/unit/inspect`, Python 3.13): 605 passed,
  0 skipped; the grep guard for `could not import|no tests ran` found nothing.
- Python 3.12 (isolated env): the regex, vendor, determinism, golden and Inspect-lane suites pass;
  the unidata test skips with a reason that does not contain "could not import" (F13).

## Tripwires (expected to fire first)

- RX-D1 (F9): no longer applies; `regex@1` runs on RE2 (see the review round below).
- F11: the Inspect number rule costs about 1 s per MiB on a text of many `1a ` or `é ` words
  (measured 0.33 s and 0.50 s at 256 KiB). `test_inspect_rules_stay_linear_on_hostile_input` fails
  above 2 s at 256 KiB.

## Deviations from the unit spec

- The Inspect-lane tests (`tests/unit/inspect/`) do not import `combine_golden_support`: the
  directory `tests/unit` is not on that lane's import path. The parity file runs the built-in
  operators through `BUILTIN_OPERATORS.resolve(...)` and reads the golden fixtures by path.
- Row 13 uses a registry whose `regex@1` run function raises, to prove that a bad pattern fails the
  spec check before any member is read.
- Row 26 also accepts `AnnAssign` at the top level, because `VENDORED_NAMES` is annotated.
- Rows 8-11 (the ban tests) were deleted in the RE2 review round.

## Review round: regex@1 on RE2 (user decision, 2026-10-02)

The Opus review found that the static ban let through patterns that freeze a worker: `(a+){10}$`
took 56 s on 41 characters, and `[^x]+X+[^x]+X+$`, `(a|aa){1,60}$`, `(?:a+)?(?:a+)?(?:a+)?$` were
slow too. The user decided to run `regex@1` on the linear-time RE2 engine and delete the deny-list.

- Dependency: `google-re2>=1.1,<2` in `apps/screamingface-engine/pyproject.toml`. `uv.lock` pins
  `google-re2 1.1.20251105` with wheels for cp312 and cp313 on `manylinux_2_26_aarch64`,
  `manylinux_2_27_x86_64` and `macosx_13/14/15` arm64 and x86_64 (also cp314 and Windows). The engine
  image is `python:3.13-slim-bookworm` (glibc 2.36), which the manylinux wheels support.
- Layering: `.claude/scripts/check_layering.py` `COMBINE_PLUGIN_THIRD_PARTY = {"re2"}` is the one
  third-party module a plugin may import; any other third-party import in a plugin is now an
  offender (before, only the stdlib deny-list applied), and the core may not import `re2`. The core
  does import `pydantic`, so the rule for the core is "no `re2`", not "no third-party module".
- `regex@1`: RE2 syntax. `\d` and `\w` are ASCII (use `\p{L}` and `\p{N}`); lookarounds,
  backreferences, `(?a:...)` and repeats over 1000 do not compile (`combine_spec_invalid`, message
  without the pattern). `ignore_case` prepends `(?i)`.
- Lone surrogates: RE2 takes UTF-8 only, so a member text with a lone surrogate (JSON can carry
  one) would crash the call. The window reads each surrogate as U+FFFD; a pattern with one is
  `SpecInvalid`. Pinned by a test. This is an addition beyond the fix file; it prevents a crash.
- Compile cost, measured on the dev machine (3.13, macOS arm64): `re2.compile` of
  `Final: (\w+)` takes 8.7 us uncached and 2.7 us through the library's own cache; a whole
  `regex@1` call on a 1008-character text takes 9.9 us at p50. That is below the 0.1 ms bar, so the
  operator compiles per call and keeps no cache of its own (a plugin holds no module state).
- RE2 logs a line to stderr (absl) for each pattern that fails to compile. It only happens when a
  spec is checked, not per member.
- Tests: `test_catastrophic_patterns_run_in_linear_time` (8 patterns, each under 5 ms on its worst
  1024-character input), `test_re2_unsupported_syntax_is_spec_invalid`, the Unicode rules re-pinned
  to RE2, and the layering tests. RED for the first was a freeze: `(a+){10}$` ran past a 20 s
  alarm on the old engine. The quadratic-under-`re` shapes `(\d+)\s*$` and `[a-z]+[0-9]+` are in
  the timed list too.
- Minors: the vendor structure test now allows only docstring, imports, functions and assignments;
  RX#2 cases check the message does not contain the pattern; `_listed` uses a cast; the
  `set@1` docstring states the JSON number spelling (F16).
