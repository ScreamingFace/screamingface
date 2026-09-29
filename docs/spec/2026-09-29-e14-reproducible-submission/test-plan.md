# Test plan — E14 reproducible submission (OME-1307)

**Mode:** advisory. This plan is written before the code, so no result here is executed. Each
PRD's TDD table is the authority for its cases. This file adds the cross-cutting rules, the
risk register, the component split, and the not-tested list.

## 1. TDD ground rules (every implementer inherits these)

1. **RED first.** Write the test, run it, and see it fail **for the right reason**: an
   assertion on the missing behavior, not an import error or a broken fixture. Create empty
   modules and stub routes first, so the failure is behavioral. A test that passes at once
   proves nothing: fix the test.
2. **GREEN minimally.** Make the smallest change that passes. Do not build ahead of the next
   test.
3. **REFACTOR only on green.** The tests stay green the whole time.
4. **CHAR tests first on existing code.** The tests marked `CHAR` pin today's behavior. They
   pass on the current code by design. They are the safety net, not a RED step.
5. **One behavior per test.** The test name states the behavior.
6. **Oracles.** An expected value comes from the PRD scenario (and so from the ticket, an
   `ans:Qn` or a `[proposed]` rule). It never comes from the output of the code under test.
7. **No weakening.** Never loosen an assertion, add a sleep or a retry, or skip a test to get
   a green result. Classify the failure first: product defect, test defect, environment, or
   flake.
8. The repo gates apply (`run_gates.py` through the `sdlc-python` skill). Coverage is
   append-only.

## 2. Risk register (qa-tester scales: Impact × Likelihood)

| ID | Risk | I×L | Mitigating tests |
|---|---|---|---|
| R1 | A private version, or a gated benchmark's prompts, leak to a non-owner (replay or GitHub) | H×M | RP-1, RP-2, RP-5, PB-1, PB-2, CV-9, CV-18 |
| R2 | A client forges a fingerprint, receipt or replay claim, and takes another system's cluster or version | H×M | SR-1, SC-4, SC-5, SC-6, C4 trust rule |
| R3 | A retry makes duplicate rows, versions or releases | H×H | SC-3, CV-8, PB-4, MD-15, PB-16 |
| R4 | A later result changes the ranked head (it breaks "original ranks") | H×H | SC-9, MD-9 |
| R5 | Capture slows or fails live chat traffic | H×M | CV-3, CV-D1 NFR benchmark |
| R6 | A version holds wrong or incomplete content, silently, including a late freeze | H×M | CV-7, CV-10, CV-11, CV-12, CV-27, CV-28, PB-3 |
| R7 | A race on the first submit makes two heads, two names or two revisions | H×M | SR-12, SR-14, SR-15, SC-10 |
| R8 | A lost metadata update (two editors) | H×M | MD-6, MD-7, MD-8 |
| R9 | A replay silently turns into a paid live run, or fails halfway | M×M | RP-9, RP-14, RP-19, RP-D3 |
| R10 | A takedown does not remove the public copy | H×L | PB-10, PB-11, PB-9 |
| R11 | The legacy leaderboard changes on deploy | H×L | MD-1, SC-1, SC-11, `erd.md` §6 (no merge) |
| R12 | XSS through `paper_url` or the release body | H×L | MD-20, PB-18 |

## 3. Component split (CLAUDE.md rule 8: one sub-issue per app or package)

| Component | Test ids | Count |
|---|---|---|
| `packages/url4` | SR-2, SR-3, SR-4, SR-5 (parity with the scoreboard) | 4 |
| `apps/scoreboard` | SR-1, SR-6 to SR-20; MD-1 to MD-18, MD-20; SC-1 to SC-17, SC-22; RP-1 to RP-4, RP-6 to RP-10; PB-1 to PB-20 | 82 |
| `packages/screamingface` (SDK and local runtime) | MD-19; SC-18 to SC-20; RP-16 to RP-20; PB-21 | 10 |
| `apps/screamingface-engine` | SC-21; RP-11 to RP-15 | 6 |
| `apps/aigateway` | CV-1 to CV-28; RP-5 | 29 |
| E2E (local `screamingface up`; the nightly sandbox repo for PB-22) | MD-21, SC-23, RP-21, RP-22, PB-22 | 5 |
| **Total** | | **136** (the per-PRD totals: SR 20, CV 28, MD 21, SC 23, RP 22, PB 22) |

**Suggested delivery order** (each step has its own spec → plan → code cycle):

1. **E14a**: MD-*. It is independent, and it ships first.
2. `url4` fingerprint (SR-2 to SR-5), then the registry (SR-*).
3. The gateway capture and freeze (CV-1 to CV-15, CV-22 to CV-28), then the engine freeze
   proxy (SC-21).
4. Submit and cluster (SC-*).
5. Replay (CV-16 to CV-21, RP-*).
6. Publish and takedown (PB-*).

## 4. Pyramid and levels

- Unit: about 60% of the cases. These are the pure rules: fingerprint, pin parsing, state
  machine, validators, token claims.
- Integration: about 36%. Each contract C1–C10 has at least one test. Postgres-backed tests
  for the races (two sessions). A MinIO/Garage testcontainer for C8. respx for the SDK HTTP.
  Recorded fixtures for GitHub (C7).
- E2E: 5, one or two per flow spine, on the local runtime. PB-22 runs nightly against a
  sandbox GitHub repo, never on PRs.
- Property-based (Hypothesis): SR-2 (fingerprint stability) and CV-12 (archive bytes are
  canonical and reproducible).

## 5. Non-functional checks

| Check | Budget | How |
|---|---|---|
| Capture overhead | ≤ 5 ms p99 per chat call | A micro-benchmark in gateway CI: 1,000 calls with and without capture, compared at p99 |
| Replay hit latency | ≤ 30 ms p99 | The same harness, grant cache warm |
| Freeze time | ≤ 10 s for 5,000 entries | An integration test with a seeded ledger |
| Results list | ≤ 200 ms p99 at 10,000 results | A seeded Postgres test |
| Security | R1, R2, R12 | The listed tests, plus a review with the `sf-code-review` agent for each component PR |

## 6. Not tested (with owner and revisit condition)

| Item | Why not | Owner | Detection in production | Revisit when |
|---|---|---|---|---|
| Real GitHub on every PR | Needs a token and network; slow | the scoreboard sub-issue owner | the nightly PB-22 and `scoreboard_publish_attempts_total{result="error"}` | a publish failure escapes nightly |
| Bit-exact replay of repeated sampled calls | Out of scope by design (RP-D5) | the replay sub-issue owner | the report `repeated_key_collapses` | users report non-reproducible voting results |
| Capture of streaming bodies | Out of scope (CV-D8) | the gateway sub-issue owner | `aigw_cache_version_missing_total` | the engine starts to stream |
| Load at 30 users | Depends on E23 (OME-1314) | E23 owner | the capacity dashboards | E6 gives the capacity number |

## 7. Entry and exit criteria per component PR

- **Entry.** The plan for that component exists in `docs/plan/`, with approval.
- **Exit.**
  - All the component's TDD rows are green.
  - The CHAR rows are unchanged.
  - The gates are green.
  - The contract tests for each connection that the PR touches are green.
  - No open High risk from §2 lacks its test.
