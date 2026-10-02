---
ticket: OME-1454
stack: screamingface
status: done
started: 2026-10-02
finished: 2026-10-02
---

# Runtime artifacts — deterministic accounting assertions

## Intent

Fix PR #1217's false-positive accounting test. CI matched archive money text in a timestamp rather than an accounting field. The owner explicitly approved replacing the two broad JSON substring assertions with accounting-field assertions.

## Planned changes

- Update only the affected test assertions; retain the archive-money exclusion contract and all production code.
- Add coverage using the exact CI timestamp to make the false-positive scenario deterministic.

## Test plan

- Reproduce the original test failure using 2026-10-01T22:00:00.565488Z.
- Verify the updated test passes, while deliberate archive-money injection still fails.
- Run full SDK gates with the explicitly approved test transition recorded.

## Acceptance

- Timestamp text cannot trigger accounting assertions; archive money still cannot appear in result or submission accounting; push the tested fix to the existing PR.

## Outcome

- **Actual files:** replaced the two approved whole-JSON substring assertions in `test_cache_saved_cost_submission.py` with submission spend/status and export saving/usage assertions. Added `test_cache_saved_cost_timestamp.py` with the exact CI timestamp and another money-like timestamp. Production code unchanged.
- **Commits:** `test(screamingface): check accounting fields instead of timestamp substrings`.
- **Gates:** all SDK gates green: Ruff lint/format, Pyright, complete parallel pytest with the unchanged 95% coverage floor, notebooks, build and distribution. Focused suite: 22 passed. Both new timestamp cases failed before the fix and passed after it. Manual injection into submission spend, export saving and export spend produced three expected assertion failures.
- **Deviations:** the user explicitly approved changing these two existing assertions, so the runner used its documented `--skip-append-only` flag for this transition; no quality gate or coverage floor changed. Fresh checkout required the declared notebook extra for widget imports; `UV_NO_SYNC=1` retained that prepared environment during the gates.
- **Wisdom review:** assertions now target the accounting contract and reject real money corruption without inspecting unrelated timestamps. No dependency, schema, public API or production behavior changed.
