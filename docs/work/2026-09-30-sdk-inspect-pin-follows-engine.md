---
ticket: OME-1421
stack: screamingface + screamingface-engine
status: done
started: 2026-09-30
finished: 2026-09-30
---

# sdk-inspect-pin-follows-engine — the SDK's inspect-ai pin copies the Engine's, and a test keeps it that way

## Intent

The SDK's `inspect` extra exports a Report in inspect's `.eval` log format (OME-1117). Its
`pyproject.toml` says the pin must equal the Engine's, because the Engine hashes its exact
`inspect-ai` version into every Imported Benchmark's Benchmark Revision and "the exporter and
the importer must speak the same dialect". On main they differ: Engine `0.3.263`, SDK
`0.3.270`. OME-1411 reverted the Engine after #1026 and held inspect-ai in Dependabot for the
Engine directory only, so the SDK kept moving (#1119 → 0.3.269, #1135 → 0.3.270). Nothing
checks the rule. This unit makes the Engine's pin the single source of truth: the SDK copies
it, Dependabot holds inspect-ai in both directories, and a twin conformance test in each
package fails the moment the copy drifts.

## Planned changes

- `packages/screamingface/pyproject.toml`: `inspect-ai==0.3.263`; comment names the Engine's
  pin as the source and this test as the guard.
- `packages/screamingface/uv.lock`: relocked for that pin only.
- `.github/dependabot.yml`: `ignore: inspect-ai` on the `/packages/screamingface` entry, same
  reason and removal trigger (OME-1410) as the Engine's hold.
- `packages/screamingface/tests/unit/test_inspect_pin_conformance.py` (new).
- `apps/screamingface-engine/tests/unit/test_inspect_pin_conformance.py` (new twin).

## Test plan

- RED first, on today's pins (SDK 0.3.270): both twins fail, naming both versions and the
  Engine as the source to follow.
- Invariants pinned in each twin:
  - the SDK's `inspect` extra pins exactly the Engine's `inspect-ai` version;
  - both pins are exact `==` (a range would make "equal" meaningless);
  - both lockfiles resolve inspect-ai to that same version (a stale lock after a hand edit
    would install something else);
  - the other package's files present-but-moved FAIL, not skip (conformance-bind idiom).
- Why a twin on each side: CI is path-filtered, so an SDK-only Dependabot PR never runs the
  Engine's tests — exactly how this drift merged green.

## Acceptance

- Both twins green after the pin change; both red with the SDK pin locally set to 0.3.270.
- The SDK's inspect-export tests pass on 0.3.263.
- Both stacks' `run_gates.py` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.github/dependabot-ignores.yml` (the ignore registry is
  strict 1:1 with `dependabot.yml`; the audit fails on an unregistered hold) and a Lane 6 bullet
  in `.claude/agents/sf-code-review.md` codifying the pattern (both asked for by the owner
  mid-unit).
- **Commits:** `fix(screamingface): pin the SDK's inspect-ai to the Engine's version and bind them`.
- **Gates:** RED first: both twins failed on main's pins (SDK 0.3.270), 2 failed / 5 passed
  each; GREEN after the pin change, 7 passed each. SDK inspect-export tests
  (`tests/test_inspect_log_write.py`) 7 passed on 0.3.263. `audit_dependabot_ignores.py` exit 0.
  Relock moved only inspect-ai 0.3.270 → 0.3.263 plus the aioboto3/aiofiles pair it needs.
  `run_gates.py` for both stacks: GATES_PENDING.
- **Deviations:** the two scope additions above. `datasets` and `inspect-evals` stay out of
  scope (Engine-only); the wider "`datasets` is not in any Benchmark Revision" gap is recorded
  on OME-1410.
