---
ticket: OME-1939
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
---

# raise-hle-judge-token-cap — give HLE's judge room to finish its grade

## Intent

On about 1.5% of HLE Cases, the judge (`glm-5.3-flash`, `max_tokens` 32768 from inspect_evals'
`default.yaml`) reasoned through its whole budget and never wrote a `GRADE:` line, so the Case
counted 0 whatever the Candidate answered. Owner decision 2026-11-17: raise the cap to 131072
(the model's OpenRouter output limit) on `hle` and `hle_diamond`, which share one judge; keep
counting an ungradable Case 0 (CAIS's rule, already declared); HOLD both published revisions.
A re-grade and revision bump follow in their own PR (`OME-1909`).

## Planned changes

- `benchmarks.py`: both rows pin `max_tokens` 131072, with a named deviation.
- `judge_provider.py`: bind the judge role with the row's pinned settings, so inspect_evals'
  stanza (32768) cannot fill them in and trip the judge guard on every call.
- `single_shot.py`: pass the row's pins to the role binding.
- Tests: fingerprint pins (held rows), the HLE judge pins, a run-path test, a bare-binding test.
- Fidelity records `inspect-hle.md` (D6) and `hle_diamond.md` (D8).

## Test plan

- The run's grading face binds the grader role with 131072 (mutation: drop the pins at the
  call site → red).
- A role bound bare lets HLE's stanza ask for 32768 and the guard refuses it (why the pins must
  ride the binding).
- HLE's real `regex_judge` grades through the provider and the wire carries 131072.

## Acceptance

- Both rows serve their old published ids; fingerprints move and are pinned.
- No other judged row's wire changes (simpleqa's role already pins its scorer's 4096).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `test_judge_redraws_a_repeat.py` (its pins mirror the row)
  and `test_hle_cases.py` (the row's judge params).
- **Commits:** see the PR.
- **Gates:** 482 passed in 21 test files (`test_judge_*.py`, `test_hle_cases.py`,
  `test_hle_diamond_cases.py`, `test_benchmark_fingerprints.py`, `test_published_revision(s).py`,
  `test_judged_benchmark_assembly.py`, `test_single_turn_judged_imports.py`,
  `test_streamed_judged_aggregate.py`, `test_failure_policy_revisions.py`,
  `test_concurrent_judge_booking.py`); ruff + pyright clean on the 7 touched files, with and
  without the inspect extra.
- **Deviations:** the plan was "change one number"; reading the judge guard showed that alone
  would refuse every HLE judge call (the stanza fills 32768 into an unbound setting), so the role
  binding now carries the pins. Fidelity records amended, not re-audited: their fingerprints stay
  at the audited values, so `just engine fidelity-check` reports both stale until a re-audit.
- **Owner-verify:** a paid HLE run to confirm the ~1.5% of Cases now get a grade; the run id
  behind the 1.5% is still to be attached to OME-1939.
