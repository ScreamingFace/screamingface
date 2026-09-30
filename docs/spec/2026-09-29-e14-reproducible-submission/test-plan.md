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

## 3. Component split and delivery order

### 3.1 Delivery on one branch `[stated ans:Q19]` (D1)

- All units land on **one branch**, `e14-reproducible-submission-spec`. There is no PR, no
  Linear sub-issue and no CI merge gate per unit.
- Each unit is built in its own temporary worktree, on the branch `unit/<ID>`, made from the
  e14 branch HEAD: `git checkout -B unit/<ID> e14-reproducible-submission-spec`.
- Each unit keeps its `docs/work/` ledger. Its plan is
  `docs/plan/2026-09-29-e14-reproducible-submission/<ID>.md`.
- After each wave, an integrator merges the unit branches into the e14 branch **in sequence**,
  resolves the additive same-file overlaps, and runs the gates (§1 rule 8) on the merged
  branch. The next wave starts from the merged HEAD.

### 3.2 Components and test ownership

| Component | Units | Test ids | Count |
|---|---|---|---|
| `packages/url4` | URL4-fp | SR-2, SR-3, SR-4, SR-5 (parity with the scoreboard) | 4 |
| `apps/scoreboard` | SB-schema, SB-meta, SB-registry, SB-submit, SB-grants, SB-publish | SR-1, SR-6 to SR-20; MD-1 to MD-18, MD-20; SC-1 to SC-17, SC-22; RP-1 to RP-4, RP-6 to RP-10; PB-1 to PB-20 | 82 |
| `packages/screamingface` (SDK) | SDK-meta, SDK-submit, SDK-replay | MD-19; SC-18 to SC-20; RP-16 to RP-20; PB-21 | 10 |
| `apps/screamingface-engine` | ENG-freeze, ENG-replay | SC-21; RP-11 to RP-15 | 6 |
| `apps/aigateway` | GW-capture, GW-freeze, GW-replay | CV-1 to CV-28; RP-5 | 29 |
| Deploy and local wiring (`apps/scoreboard` admin route, both Helm charts, `charts.yml` / `verify_chart_wiring.py`, the keypair helper, the local runtime `screamingface up`) | WIRING `[stated ans:Q23]` | Plan-local ids only (it reuses the SDK-replay RP-20 key generator for `up`): for the `redistributable` admin route (admin only, audited), the chart wiring checks, and the keypair helper (raw base64, derived kid) | 1 |
| E2E (local runtime; the nightly sandbox repo for PB-22) | E2E | MD-21, SC-23, RP-21, PB-22 | 4 |
| **Total** | | | **135** (the per-PRD totals: SR 20, CV 28, MD 21, SC 23, RP 21, PB 22; RP-22 is dropped, Q30) |

**WIRING scope** `[stated ans:Q22, ans:Q23]`:

- The scoreboard admin route that sets `Benchmark.redistributable` (`contracts.md` C10,
  `erd.md` §2.7).
- The scoreboard chart: `SCOREBOARD_AUTH_MODE=cloudflare_headers` in
  `apps/scoreboard/charts/scoreboard/values-prod.yaml`, `SCOREBOARD_ALLOWED_NETWORKS`, a
  `FORWARDED_ALLOW_IPS` guard, the receipt public keys, the grant signing key and kid, the
  GitHub App config, the bucket read credentials, and the feature flags.
- The aigateway chart: `AIGW_CACHE_VERSIONS_ENABLED`, the bucket write credentials, the receipt
  signing key, the grant public keys, the Garage bucket and prefix, and the Secret templates.
  `charts.yml` and `verify_chart_wiring.py` cover the new values.
- An Ed25519 keypair helper: raw base64 keys, the derived kid (`contracts.md` C3, C6).
- The local runtime `screamingface up`: the flags on, the keys made on first start, and the
  archive directory set.
- Secrets stay out of git. AIGateway credentials stay only in `credential_blobs`.
- **Ops precondition (not a code task).** The production scoreboard host must be routed
  through the Cloudflare Access / Envoy edge before the auth mode changes
  `[existing docs/work/2026-08-03-OME-404-authenticated-leaderboard-submissions.md:94-98]`.

### 3.3 Waves `[stated]` (D2)

The units in one wave are built in parallel. A same-wave file overlap is allowed. Each plan
lists its shared files under "Integration notes", and the integrator merges in the order below.

| Wave | Units | Merge order inside the wave |
|---|---|---|
| W1 | SB-schema, URL4-fp, GW-capture | any; URL4-fp carries the one-line engine `uv.lock` change (D7, X-25) |
| W2 | SB-meta, SB-registry, GW-freeze, ENG-freeze, SDK-meta | **SB-meta before SB-registry** (shared scoreboard files) |
| W3 | SB-submit, GW-replay, ENG-replay, SDK-submit | any |
| W4 | SB-grants, SB-publish, SDK-replay | **SB-grants before SB-publish** (shared scoreboard files) |
| W5 | WIRING, E2E | WIRING before E2E |

A unit depends only on real code dependencies from earlier waves (for example, SB-registry
needs SB-schema and URL4-fp; SB-submit needs SB-registry and SB-meta; GW-replay needs
GW-freeze). Build against fakes where a plan says so.

**Release order** (after the merge to `main`). Deploy the scoreboard units (SB-meta, SB-submit,
SB-grants, SB-publish) before a release of the SDK, because `ScoreSubmission` is
`extra="forbid"`.

## 4. Pyramid and levels

- Unit: about 60% of the cases. These are the pure rules: fingerprint, pin parsing, state
  machine, validators, token claims.
- Integration: about 36%. Each contract C1–C10 and C12 has at least one test. Postgres-backed tests
  for the races (two sessions). A MinIO/Garage testcontainer for C8. `httpx.MockTransport` for the SDK HTTP (respx is not an SDK dependency; D7, X-20).
  Recorded fixtures for GitHub (C7).
- E2E: 4, one or two per flow spine, on the local runtime. PB-22 runs nightly against a
  sandbox GitHub repo, never in the per-unit or per-wave gates.
- Property-based (Hypothesis): SR-2 (fingerprint stability) and CV-12 (archive bytes are
  canonical and reproducible).

## 5. Non-functional checks

| Check | Budget | How |
|---|---|---|
| Capture overhead | ≤ 5 ms p99 per chat call | A micro-benchmark in gateway CI: 1,000 calls with and without capture, compared at p99. Postgres runs with durable commit off (`fsync`, `synchronous_commit` and `full_page_writes` off). One transaction per call gives one commit (`ans:Q31`) |
| Replay hit latency | ≤ 30 ms p99 | The same harness, grant cache warm |
| Freeze time | ≤ 10 s for 5,000 entries | An integration test with a seeded ledger |
| Results list | ≤ 200 ms p99 at 10,000 results | A seeded Postgres test |
| Security | R1, R2, R12 | The listed tests, plus a review with the `sf-code-review` agent for each unit before the wave merge |

## 6. Not tested (with owner and revisit condition)

| Item | Why not | Owner | Detection in production | Revisit when |
|---|---|---|---|---|
| Real GitHub in every gate run | Needs a token and network; slow | the SB-publish unit owner | the nightly PB-22 and `scoreboard_publish_attempts_total{result="error"}` | a publish failure escapes nightly |
| Bit-exact replay of repeated sampled calls | Out of scope by design (RP-D5) | the ENG-replay unit owner | the report `repeated_key_collapses` | users report non-reproducible voting results |
| Capture of streaming bodies | Out of scope (CV-D8) | the GW-capture unit owner | `aigw_cache_version_missing_total` | the engine starts to stream |
| Load at 30 users | Depends on E23 (OME-1314) | E23 owner | the capacity dashboards | E6 gives the capacity number |
| RP-22: E2E for a changed recipe pinned by date, with partial hits (dropped, Q30) | The owner decided (2026-09-30) that no paid run is used as a test. The test needs a fixture that only a paid run can make. | the ENG-replay unit owner | the report counters `hits` and `misses` and the `replay` block on `GET /v1/scores/{id}/results` | the owner approves a paid run as a test fixture. The behavior stays covered by RP-6, RP-7 (pin by date), CV-17 and RP-13 (a miss falls through and is counted), and RP-21 (the E2E replay spine) |

## 7. Entry and exit criteria per unit

- **Entry.** The plan for that unit exists in `docs/plan/2026-09-29-e14-reproducible-submission/<ID>.md`, with approval, and the units of the earlier waves are merged into the e14 branch.
- **Exit.**
  - All the component's TDD rows are green.
  - The CHAR rows are unchanged.
  - The gates are green.
  - The contract tests for each connection that the unit touches are green.
  - After the integrator merges the wave, the gates are green on the e14 branch.
  - No open High risk from §2 lacks its test.
