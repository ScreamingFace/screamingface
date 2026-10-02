---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# exact-case-navigation — preserve string Case identity before numeric fallback

## Intent

Fix Go to case selecting an integer or rejecting a valid string when an exact retained
string ID contains surrounding whitespace. User explicitly requested the narrow fix.

## Planned changes

- _ui/case_navigation.py: match the original query as a string; strip only for integer fallback.
- New test_case_navigation_whitespace.py: padded textual/numeric IDs, string/integer
  collisions, candidate filtering, numeric fallback, live selection preserving identity.

## Test plan

New regressions fail before implementation. Preserve all existing tests. Run focused
navigation/browser tests and full SDK card gates against 7cfc942b; SF review before commit.

## Acceptance

Exact string IDs win unchanged. Numeric fallback still accepts surrounding whitespace.
No candidate payload materialization, runtime changes, or posted review comments.

## Outcome

- **Actual files:** planned navigation module and new tests, plus the durable spec's exact-ID requirement.
- **Commit:** `fix(client): preserve exact string case navigation` (this unit).
- **RED:** six of the initial seven regressions selected the stripped ID instead of its exact padded string; integer fallback already passed. Added the supplied padded-string/integer-only collision explicitly.
- **GREEN:** eight new regression cases; 17 navigation cases passed, including live browser focus and candidate filtering.
- **Gates:** `packages/screamingface/.venv/bin/python -u .claude/scripts/run_gates.py screamingface --base 7cfc942b` — ALL GATES GREEN. Append-only tests, Ruff, Pyright, full parallel pytest/95% coverage, notebooks, build and distribution passed.
- **Reviews:** SF standards/spec reviewers found no actionable defect and each ran the 17 navigation tests.
- **Deviations:** none. No prior test edited, Engine/runtime change, paid calls or review posts.

## Wisdom and confidence

The smallest change preserves the original string before normalization. Integer fallback
keeps the existing convenience behavior and selected-candidate boundary. Tests assert
actual browser focus and typed identity, rather than only successful navigation. No new
state, schema, dependency or data materialization is introduced.
