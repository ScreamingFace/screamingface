# E14 — Each leaderboard submission is a reproducible research artifact (OME-1307)

**Status:** spec, for review · **Date:** 2026-09-29 · **Epic:** [OME-1307](https://linear.app/openmined/issue/OME-1307)
· **Ledger:** `docs/work/2026-09-29-e14-reproducible-submission-spec.md`

## 1. Summary

Today a leaderboard submission is a one-time, unrelated row. Its authors cannot change. It has
no paper link. Nothing records which cache produced its score. E14 makes a submission a
citable, reproducible artifact:

1. **Editable metadata (E14a).** The owner can add authors and a paper URL after the submit,
   with an edit history.
2. **A cache version per submitted run (E14b).**
   - The gateway records each call of a traced run (full prompt and output).
   - At submit time, the gateway freezes the calls into an immutable, content-addressed
     version, and signs a receipt that the scoreboard verifies.
   - Anyone can replay a public, redistributable version. The owner can replay a private one.
   - A replay miss falls through to the live provider, and the run is marked partial.
   - The owner can publish a version to a public GitHub repo. Only an admin can take it down.
3. **Result clustering.** A new run of the same system on the same board becomes "another
   reported result" under the first claim. The original result ranks.
4. **System names and revisions.** "The url4 minus the benchmark" gets a global name that the
   first submitter owns. A known system keeps its name. The owner can declare a new url4 as the
   next revision. A run can be pinned to a submission, a name, a revision, or a name at a date.

## 2. Bounded contexts and ownership

| Context | Owner component | Owns |
|---|---|---|
| Leaderboard claims, results, names, publishing | `apps/scoreboard` | `Score`, `ReportedResult`, `System`, `SystemRevision`, `ScoreMetadataEvent`, `CacheVersionPublication`; grant signing; the GitHub publisher |
| Call capture, versions, replay | `apps/aigateway` | `CacheCaptureEntry`, `CacheVersion`, `CacheVersionEntry`, `CacheVersionBlob`; receipt signing; the bucket archive (write) |
| Run plumbing | `apps/screamingface-engine` | the freeze proxy route; carrying the replay grant; replay hit and miss counters |
| Client surface and local runtime | `packages/screamingface` | `submit` (freeze then submit), `update_submission`, `evaluate(replay=…)`, `publish_cache_version`; local key wiring |
| Fingerprint | `packages/url4` | the pure `system_fingerprint()` |
| Deploy and local wiring | the WIRING unit (`ans:Q23`) | the `Benchmark.redistributable` admin route; the scoreboard and aigateway charts; the keypair helper; the `screamingface up` flags, keys and archive directory |

The scoreboard and the gateway never call each other. Trust goes through signed tokens
(`contracts.md` DR-2).

## 3. Documents and reading order

1. `erd.md`: the data model. Read it first, because the PRDs refer to its entities.
2. `prd/system-registry.md` (component): names, revisions, fingerprints. 19 scenarios, 20 TDD cases.
3. `prd/cache-version-store.md` (component): capture, freeze, replay lookup, archive. 25 scenarios, 28 TDD cases.
4. `prd/edit-metadata.md` (E14a, can ship first): 22 scenarios, 21 TDD cases.
5. `prd/submit-and-cluster.md`: 22 scenarios, 23 TDD cases.
6. `prd/replay-pinned-run.md`: 22 scenarios, 21 TDD cases (RP-22 is dropped, Q30).
7. `prd/publish-and-takedown.md`: 20 scenarios, 22 TDD cases.
8. `contracts.md`: connections C1–C12, the coded error body, and the decision records DR-1 to DR-4.
9. `test-plan.md`: the risk register, the component split, the not-tested list.

## 4. Interview ledger

The "ticket" rows are the OME-1307 body and Irina's comments. They are tagged `[stated prompt]`.
The `Qn` rows are the user's answers on 2026-09-29. They are tagged `[stated ans:Qn]`. Q19 to Q24
are the user decisions D1 to D7 from the plan review. Q25 is decision D8 from the wave 1 review.
They override older text in this spec set.

### 4.1 From the ticket (Irina, 2026-09-29)

| Id | Question | Answer (verbatim or close) |
|---|---|---|
| I1 | Is a rerun served from the cache a new leaderboard entry? | "Bruno submitting the same url4 will lead to a 'another reported result' clustered under Ana's result, but will not add a new row. […] the claim belongs to Ana." |
| I2 | Must co-authors be registered users? | "Submitter can list anyone, even if not registered […] no confirmation is needed. […] only 1 of the authors are responsible to change the submission." |
| I3 | Should the platform know two submissions are the same recipe? | "The leaderboard should somehow detect whether the existing url4 (minus the benchmark) was already submitted under a name before allowing a new name to be given." |
| I4 | (Estimate comment) | "Likely should pull cached results to a 'pinned' or 'published' repo rather than continuing to use the cache for their storage." |

### 4.2 From the user interview

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | Which parts of E14 do these docs cover? | Editable metadata (E14a), cache version per run (E14b), result clustering, system name plus detection | all four |
| Q2 | Where is a frozen cache version stored? | Public published repo | not the recommended option (frozen slice in S3) |
| Q3 | What content goes into a cache version? | Full prompts and outputs. Private versions are owner-only. | recommended |
| Q4 | Who may rerun with a version? | Anyone for public submissions, the owner for private ones | recommended |
| Q5 | Which public repo hosts published versions? | GitHub repo / releases | not the recommended option (Hugging Face) |
| Q6 | Private-board and gated-benchmark versions? | Private bucket, owner-only | recommended |
| Q7 | What does pin-by-date mean? | Latest version of a name at or before T | recommended |
| Q8 | Who owns a system name? | Global, first submitter | recommended |
| Q9 | When is a version published? | The owner opts in | recommended |
| Q10 | Can a published version be removed? | Admin takedown only | recommended |
| Q11 | In a cluster, which result ranks? | The original result ranks | recommended |
| Q12 | Intake sub-issues OME-1360, OME-1367, OME-1341? | All out of scope | recommended |
| Q13 | A replay call not in the version? | Fall through to the live provider, mark partial | recommended |
| Q14 | Can the owner attach a new url4 as a revision of a name? | Yes, owner-declared | recommended |
| Q15 | A known system arrives with a different name? | Use the existing name, plus a notice | recommended |
| Q16 | Which metadata fields are editable? | Authors plus paper_url | recommended |
| Q17 | (Was DQ-1.) A **new** system asks for a name that **another** system owns? | Reject with `409 system_name_taken` and a suggested name. The resubmit reuses the report and the receipt, so it costs no rerun. | recommended; answered 2026-09-29 after the first review |
| Q18 | (Was DQ-2.) How long does the gateway keep what a late freeze needs? | Store the prompt once per cache key, and keep a thin run index. Keep both **forever**, like the cache answers, so a freeze has no deadline. | answered 2026-09-29, after the user pointed out that cache answers never expire |
| Q19 | (Was X-1, D1.) How does the work land? | All units land on **one branch**, `e14-reproducible-submission-spec`. There is no PR, no Linear sub-issue and no CI merge gate per unit. Each unit is built in its own temporary worktree on the branch `unit/<ID>`, made from the e14 branch HEAD. After each wave, an integrator merges the unit branches into the e14 branch in sequence and runs the gates. Each unit keeps its `docs/work/` ledger. | answered 2026-09-29 at plan review; the wave map is D2 (`test-plan.md` §3) |
| Q20 | (Was X-10, D3.) Does the recipe name change the fingerprint? | No. Option A: `system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))`. A `seed` that the Candidate itself declares stays in the hash (URL4 OD-2 default). With no `candidate` binding, the whole canonical url4 is hashed (URL4 OD-5). Amended by Q25 (c): the function removes `_sf_recipe` only when it is inert, else `ExcludedBindingError` (`422 invalid_url4`). | recommended; answered 2026-09-29 at plan review. See `erd.md` §2.3.2. |
| Q21 | (Was X-2, D4.) The grant life (12 h) is shorter than the job deadline (57,600 s) plus the queue wait. What changes? | Nothing in the code. Keep `exp = iat + 43,200 s`. Document the limit: a replay grant that expires during a run fails that run with the typed error (the RP-14 path). No refresh. | option (c); answered 2026-09-29 at plan review. See A3, `contracts.md` C6. |
| Q22 | (Was X-11, D5.) Which identity does production use? | The Cloudflare identity headers. The scoreboard production mode for E14 is the **existing** auth mode `cloudflare_headers` (`SCOREBOARD_AUTH_MODE`, `SCOREBOARD_ALLOWED_NETWORKS`, the peer check before the header read, `X-User-Email`). Every owner, submitter, reporter, grant `sub` and admin check uses that verified identity. `disabled` is a dev and local fallback only. | answered 2026-09-29 at plan review. See A6. |
| Q23 | (Was X-12, X-13, X-14, D6.) Who owns the deploy and local wiring? | A new unit, **WIRING** (wave 5). It owns the admin route that sets `Benchmark.redistributable`, the scoreboard chart and the aigateway chart (auth mode, keys, bucket credentials, flags, Secret templates), the chart-wiring checks, an Ed25519 keypair helper, and the local runtime (`screamingface up`: flags on, keys made, archive directory set). Secrets stay out of git. | answered 2026-09-29 at plan review. See `test-plan.md` §3. |
| Q24 | (D7.) The engineering defaults X-3 to X-25 from the plan review? | Accepted as the plan defaults: no new shared package (PyJWT EdDSA behind service-local ports; SigV4 copied); raw base64 keys and JSON `{kid: b64}` maps; the replay header rides `GET /?q=`; the C11 `jwt` rule is scoped to `screamingface_engine/auth/`; the counter frame contract; the coded error body; counters stay in process; `archive_sha256` = sha256 of the gzip bytes; C11 enforced by unit tests; `.claude/sdlc.local.md` may change; `httpx.MockTransport` in the SDK; the pin grammar is mirrored; the 32,000-char url4 cap with `422`; the engine `uv.lock` line rides with URL4-fp. Unit-local open decisions take the plan default. | answered 2026-09-29 at plan review. See `contracts.md`. |
| Q25 | (D8, wave 1 review.) Tortoise 1.1.8 overwrites the `source_field` of an FK with `<attr>_id` at init (`tortoise/apps.py:205`). So a custom FK column does not go through the migration state, and a `RunSQL` column rename makes the state and the database different. Also, SQLite checks `RESTRICT` row by row inside a `CASCADE`. And a `_sf_recipe` source that is not inert must not be hidden. What changes? | (a) Every FK column has the Tortoise native name `<attr>_id`. No FK sets a custom `source_field`, and no migration renames a column. `reported_result.head_id` (was `score_id`), `replayed_from_result_id` and `pinned_baseline_result_id` (the FK attributes are `replayed_from_result` and `pinned_baseline_result`), `cache_version_entry.blob_id` (was `blob_sha256`). (b) The two replay FKs use `ON DELETE NO ACTION`, not `RESTRICT`: the delete of a head removes its own in-cluster replays, and a replay in another cluster still blocks the delete of its original. (c) `exclude_bindings` removes a source only when it is inert (text value, explicit weight `0.0`, no `$name` reference); else `ExcludedBindingError`, which the scoreboard maps to `422 invalid_url4`. | decided by the orchestrator 2026-09-29 after the wave 1 review; (c) is merged in `packages/url4`. See `erd.md` §2.2, §2.3.2, §3.4 and plan `00-index.md` D8. |
| Q26 | (Final check RP-X1.) Must a grant call with no HTTP response (a transport failure) count as a version miss? | No. Only a non-2xx response counts as a miss (C12). | answered 2026-09-30 |
| Q27 | (Final check X-SEC-1.) Must `pinned_baseline_result_id` equal `replay.result_id`? | No. Keep the rule as built: the baseline must be on the same board and pass the same replay access rules (C4 "Trust"). | answered 2026-09-30 |
| Q28 | (Final check MRA-1/MRA-2.) A durable admin audit table, or a log line? | A log line (`admin_action`, `admin_change`, C10). | answered 2026-09-30 |
| Q29 | (Final check RP-X2.) Is a coded `503 replay_unsupported` permanent in the SDK? | No. It is transient (the `status >= 500` rule). | answered 2026-09-30 |
| Q30 | Must RP-22 run on a zero-spend fixture made by a paid run? | No. We will not use a paid run as a test. RP-22 is dropped. | answered 2026-09-30 |
| Q31 | The capture bench failed on CI because of disk fsync stalls. How is it fixed? | Write the prompt and capture rows in one transaction (one commit), and run the bench's Postgres with fsync, synchronous_commit and full_page_writes off. The budget stays 5 ms. | answered 2026-09-30 |

## 5. Deferred questions

None. DQ-1 became Q17 and DQ-2 became Q18.

## 6. Global assumptions

| Id | Assumption | Status | What changes if it is wrong |
|---|---|---|---|
| A1 | One trace per candidate run, and the engine forwards `traceparent` to the gateway | [existing] checked: `packages/screamingface/src/screamingface/_engine/transport.py:180-183`, `apps/screamingface-engine/src/screamingface_engine/world/connector.py:1061-1078` | The capture key would need an explicit run id header |
| A2 | The engine calls the gateway without streaming | [assumed] | Streaming calls count as missing (CV-D8). If the engine streams, add stream capture. |
| A3 | The grant life (12 h) is longer than the engine job deadline | [checked] false, accepted (`ans:Q21`, D4). The job deadline is 57,600 s `[existing apps/screamingface-engine/src/screamingface_engine/config.py:148-151]`, and a queued run can wait up to 57,600 s more `[existing apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py:833-858]`. A grant that expires during a run fails that run with `403 replay_grant_invalid` (`reason: expired`), mapped to the typed run failure (RP-14). | If long replays fail often: raise the TTL, or add grant refresh |
| A4 | About 200 submissions per week at 30 users | [assumed] | Storage tripwires in `erd.md` §5 |
| A5 | The scoreboard can take a dependency on `packages/url4` | [proposed] | Otherwise the fingerprint helper needs another home, with a parity test |
| A6 | In production, the scoreboard and the gateway run the auth mode `cloudflare_headers`, and the scoreboard host is routed through the Cloudflare Access / Envoy edge | [stated ans:Q22]. The gateway runs it today. The scoreboard mode exists `[existing apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py]`; WIRING switches `apps/scoreboard/charts/scoreboard/values-prod.yaml` to it. The edge routing is an ops precondition `[existing docs/work/2026-08-03-OME-404-authenticated-leaderboard-submissions.md:94-98]`. | Without a verified identity, E14 is inert: content-hash clustering and no registry, grant `sub = "anonymous"`, and publish and withdraw answer `503`. This is the `disabled` (dev and local) behaviour only. |

## 7. Engineering size (for the epic estimate)

This is an estimate, not a measurement. It uses Irina's scale.

| Piece | Size |
|---|---|
| E14a metadata (MD) | S · 3–5 d |
| url4 fingerprint plus system registry (SR) | M · 6–8 d |
| Gateway capture, freeze, replay, archive (CV) | L · 10–14 d |
| Engine plus SDK plumbing (freeze proxy, grant carry, counters, SDK methods) | S–M · 4–6 d |
| Deploy and local wiring (WIRING: admin route, charts, keys, `screamingface up`) | S · 2–4 d `[proposed]` |
| Submit and cluster (SC) | M · 6–8 d |
| Publish and takedown (PB) | M · 6–8 d |
| **Total** | **37–53 d**. XXXL on the scale, so split it into units and waves (see `test-plan.md` §3). |

This is larger than the triage map's E14 estimate (13–20 d). The interview added clustering,
names with revisions, pin-by-date, and GitHub publishing with a takedown.
