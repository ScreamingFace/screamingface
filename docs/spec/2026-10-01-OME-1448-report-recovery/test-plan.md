# Test plan: OME-1448 recovery and export

**Mode:** advisory. This plan is a design; nothing in it has run yet. Every result below is
[inferred] until the implementation runs it.

## 1. Risk model

| ID | Risk | Impact | Likelihood | Rigor | Tests |
|---|---|---|---|---|---|
| R1 | A finished, paid Evaluation cannot be rebuilt after a crash | H (money, a day of work) | H (it happened on 2026-10-01) | E2E spine + integration per hop | RC-E2E-1, RE-2, RE-3, RC-1 |
| R2 | The recovered Report differs from the original (wrong score, a missing field, different bytes) | H (wrong published results) | M | property + byte equality | RE-1, RC-1, RW-1, EX-2 |
| R3 | Recovery runs out of memory on the same laptop | H | M | memory-bound tests | RC-2, RW-4, EX-3 |
| R4 | A record write fails, or tears, and breaks a paid run | H | L | fault injection | RS-1, RS-6, RE-4 |
| R5 | A tampered record sends credentials to another host | H | L | negative inputs | RS-4, RS-5 |
| R6 | `export()` output changes for existing users | H | L | characterization | RW-0, EX-0 |
| R7 | The notice is wrong (noise, a missed recovery, a crash at import) | M | M | unit | RN-1 to RN-4 |
| R8 | The local writer and reader use different artifact folders | H | L | equality test | LA-1 |
| R9 | Concurrency (8 threads; two notebooks; two recovers) | M | M | concurrency tests | RS-2, RE-12, RC-19, RS-15 |

Rubric: impact H = money, data loss, or wrong results; likelihood H = it has already happened or
occurs on every large run.

## 2. TDD ground rules

- RED first. Run the test, and see it fail on an assertion about the missing behavior. A test
  that passes at once proves nothing: fix the test.
- GREEN with the smallest change. REFACTOR only on green.
- One behavior per test. The test name states the behavior.
- CHAR tests pin today's behavior. They pass on today's code by design, and they must stay green.
- This repo's tests are append-only. Change an existing test only with the owner's approval.
- Oracle rule: an expected value never comes from the code under test. The oracles here are
  `Report.export()` bytes from a control run (R2), the ticket's acceptance text (R1, R3), and the
  user's interview answers (`00-overview.md` §4).

## 3. Build order (across PRDs)

Core-out, because every flow depends on the store and the writer:

1. `prd/recovery-store.md`: RS-1 … RS-18
2. `prd/report-json-writer.md`: RW-0 … RW-6
3. `prd/export-report.md`: EX-0 … EX-7 (option D can merge alone after step 2)
4. `prd/local-durable-artifacts.md`: LA-0 … LA-7 (independent; can merge alone; LA-4 and LA-8 removed after review)
5. `prd/record-evaluation.md`: RE-0a … RE-13
6. `prd/recover-evaluation.md`: RC-E2E-1 first (it stays RED until step 6 is complete), then
   RC-1 … RC-21
7. `prd/recovery-notice.md`: RN-1 … RN-11
8. `ARCH-1`: the layering test from `contracts.md` K11

Suggested PRs, each one green alone: (2+3) export, (4) local folder, (1+5) record, (6+7+8)
recover and notice.

## 4. Levels (pyramid)

| Level | Count | What |
|---|---|---|
| unit | 55 | store invariants, codec, writer bytes, notice rules, path rules, layering |
| integration | 33 | transport hook order (httpx `MockTransport`), runner state transitions, recover per hop, local App restart |
| e2e | 1 | RC-E2E-1: a subprocess killed inside materialize, then recovery in a new process |

Each contract in `contracts.md` has at least one integration test.

## 5. Fixtures and environments

- **Fake Engine:** extend the existing `httpx.MockTransport` fixtures in
  `packages/screamingface/tests/test_transport_artifact_fetch.py` with `/token`, a WebSocket frame
  script, and `/artifacts/{id}` (200, 404, a wrong body, a slow body).
- **Result generator:** builds `candidate-result.v1` bodies of a chosen size (1 KB to 20 MB) with
  repeated `input` text, like ContractEval.
- **Memory tests:** `tracemalloc` peak ratios, not absolute RSS, so they are stable in CI. The
  200 MB incident scale is a manual benchmark (§7), not a CI gate.
- **Crash test:** `subprocess` + `SIGKILL` at a hook point (an env-gated test hook inside
  `_materialize_sync`, for tests only). Mark `@pytest.mark.slow`.
- **Clock and pid seams:** injected `now()` and `pid_alive()` for prune and owner tests.
- **No paid calls.** No real provider and no hosted Engine in CI.

## 6. Entry and exit criteria

- **Entry:** you approve this spec. The implementation plan is in `docs/plan/` (next step).
- **Exit:** every RED row is green; the RW-0 and EX-0 characterization tests are unchanged and
  green; the SDK gates pass (lint, pyright, tests with the coverage floor, the public surface
  snapshot updated for `recover` and `recoverable`); RC-E2E-1 passes 20 times in a row.

## 7. Not tested (with owners)

| Item | Why | Owner | Detection | Revisit when |
|---|---|---|---|---|
| The real 11 × 200 MB incident on a 16 GB laptop | too large for CI | @ionesio | one manual run of RC-2 at full scale before release, with the RSS recorded in the work ledger | before the PR that adds recover-to-file merges |
| The hosted bucket lifecycle | infra, out of scope (`ans:Q8`) | infra | a `result_expired` count in support reports | an infra ticket sets a rule |
| PID reuse that hides a crashed Evaluation | rare; `sf.recover(id)` still works | @ionesio | user report | if a report arrives |
| Windows file modes and `os.replace` behavior | the SDK targets macOS and Linux notebooks | @ionesio | — | Windows support is planned |
