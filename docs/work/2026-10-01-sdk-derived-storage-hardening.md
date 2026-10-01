---
ticket: OME-1448
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# sdk-derived-storage-hardening — complete the remaining SDK robustness review

## Intent

Keep saved paid results readable during download completion and local index damage,
keep fusion summaries bounded, and finalize handled evaluation failures accurately.
This is one SDK recovery correctness iteration; runtime PR #1217 is independent.

## Planned changes

- reports.py: sample only stable files and tolerate disappearing entries.
- accounting.py: one-pass nullable member usage accumulation.
- _results/cases.py and index validation helper: bind reusable indices to raw bytes and index bytes; atomically rebuild invalid derived storage.
- _evaluation/runner.py, _core/ports.py, _engine/transport.py: return the prepared lifecycle path and finalize handled failures at the evaluation boundary.
- scripts/check_report_memory.py: include fusion operations/accounting in memory fixtures.
- New tests only: races, bounded memory, nullable fields, damaged/stale indices, sync/async lifecycle.

## Test plan

Write and run regressions before production changes. Check sync/async recovery from changed rows and truncated indices, raw integrity rejection, index reuse without case decoding, missing/duplicate member accounting, unknown fields, empty inputs, and all decoding failures with lifecycle ready. Preserve cancellation/interruption state. Run full SDK card gates against pre-iteration HEAD.

## Acceptance

All four reported findings fixed in #1156, prior tests unchanged, all gates green,
no Engine/runtime changes or paid model calls. Remove remaining-followup PR wording.

## Outcome

- **Actual files:** planned modules, new `_results/index_integrity.py`, both new regression files, fusion memory harness, durable spec and evidence asset.
- **Commit:** `fix(client): harden saved-report derived storage` (this iteration).
- **RED evidence:** altered/truncated cached indices and stale raw content failed recovery assertions; member retention peaked at 393,111 / 7,561,296 bytes for 1,000 / 20,000 lazy cases before the change. Replaying the pre-iteration preparation boundary against the corrected sync/async fixtures failed on `running` versus `ready`. The original listing path also fails removal between successful `is_file()`/`stat()` calls; the new test samples once. Additional review regressions first failed for deleted directories, valid read-only legacy indices, and malformed read-only raw results hiding a healthy sibling.
- **Gates:** `packages/screamingface/.venv/bin/python -u .claude/scripts/run_gates.py screamingface --base 54520642` — ALL GATES GREEN after the final shared error translation. Append-only tests, Ruff, Pyright, full parallel pytest with 95% coverage, deterministic notebooks, build and distribution all passed. New focused suites: 39 passed. No prior test changed.
- **Memory evidence:** synthetic 100,000-case, one-candidate fusion fixture with two members and three operation-accounting records per case: raw 161,077,993 bytes, full export 146,479,522 bytes, peak RSS 55,787,520 bytes. Member accumulator traced peaks after fix: 22,351 / 7,792 bytes for 1,000 / 100,000 lazily constructed real Cases. Both member totals checked by the harness. This is local synthetic evidence, not a repeated paid or hosted evaluation.
- **Reviews:** separate SF standards/spec passes; no remaining required findings in final review. Both added edges found in review were fixed and tested.
- **Deviations:** added whole-directory disappearance and verified read-only legacy fallback after review; moved parser translation to the shared builder so read-only malformed candidates preserve healthy siblings. No Engine/runtime changes, external comments, or paid calls.

## Wisdom and confidence

Raw bytes remain authoritative. Hash receipts preserve bounded reuse without reconstructing
Cases; verification adds sequential disk I/O. Read-only legacy validation uses temporary disk
and row-by-row comparison, without retaining the dataset or accepting altered answers.
Nullable totals preserve unknown fields independently. The evaluation boundary owns final
state and the existing marker writer preserves overlapping presentation operations.
Tests assert returned reports, failures, persisted lifecycle and bounded retention. No public
wire schema or new dependency changed; recovery metadata contains no credentials.

## Reproduction

Run the SDK card gates above and the two new test files. Larger local fixture:
`packages/screamingface/.venv/bin/python packages/screamingface/scripts/check_report_memory.py --directory /fresh/writable/directory --candidates 1 --cases 100000 --prompt-bytes 20 --fusion`.
Evidence: `docs/work/assets/sdk-derived-storage-hardening.json`.
