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

The scoreboard and the gateway never call each other. Trust goes through signed tokens
(`contracts.md` DR-2).

## 3. Documents and reading order

1. `erd.md`: the data model. Read it first, because the PRDs refer to its entities.
2. `prd/system-registry.md` (component): names, revisions, fingerprints. 19 scenarios, 20 TDD cases.
3. `prd/cache-version-store.md` (component): capture, freeze, replay lookup, archive. 25 scenarios, 28 TDD cases.
4. `prd/edit-metadata.md` (E14a, can ship first): 22 scenarios, 21 TDD cases.
5. `prd/submit-and-cluster.md`: 22 scenarios, 23 TDD cases.
6. `prd/replay-pinned-run.md`: 22 scenarios, 22 TDD cases.
7. `prd/publish-and-takedown.md`: 20 scenarios, 22 TDD cases.
8. `contracts.md`: connections C1–C11 and the decision records DR-1 to DR-4.
9. `test-plan.md`: the risk register, the component split, the not-tested list.

## 4. Interview ledger

The "ticket" rows are the OME-1307 body and Irina's comments. They are tagged `[stated prompt]`.
The `Qn` rows are the user's answers on 2026-09-29. They are tagged `[stated ans:Qn]`.

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

## 5. Deferred questions

None. DQ-1 became Q17 and DQ-2 became Q18.

## 6. Global assumptions

| Id | Assumption | Status | What changes if it is wrong |
|---|---|---|---|
| A1 | One trace per candidate run, and the engine forwards `traceparent` to the gateway | [existing] checked: `packages/screamingface/src/screamingface/_engine/transport.py:180-183`, `apps/screamingface-engine/src/screamingface_engine/world/connector.py:1061-1078` | The capture key would need an explicit run id header |
| A2 | The engine calls the gateway without streaming | [assumed] | Streaming calls count as missing (CV-D8). If the engine streams, add stream capture. |
| A3 | The grant life (12 h) is longer than the engine job deadline | [assumed]. Check `URL4_CLOUD_JOB_DEADLINE_S` during planning. | Raise the TTL, or add grant refresh |
| A4 | About 200 submissions per week at 30 users | [assumed] | Storage tripwires in `erd.md` §5 |
| A5 | The scoreboard can take a dependency on `packages/url4` | [proposed] | Otherwise the fingerprint helper needs another home, with a parity test |

## 7. Engineering size (for the epic estimate)

This is an estimate, not a measurement. It uses Irina's scale.

| Piece | Size |
|---|---|
| E14a metadata (MD) | S · 3–5 d |
| url4 fingerprint plus system registry (SR) | M · 6–8 d |
| Gateway capture, freeze, replay, archive (CV) | L · 10–14 d |
| Engine plus SDK plumbing (freeze proxy, grant carry, counters, SDK methods) | S–M · 4–6 d |
| Submit and cluster (SC) | M · 6–8 d |
| Publish and takedown (PB) | M · 6–8 d |
| **Total** | **35–49 d**. XXXL on the scale, so split it (see `test-plan.md` §3 for the order). |

This is larger than the triage map's E14 estimate (13–20 d). The interview added clustering,
names with revisions, pin-by-date, and GitHub publishing with a takedown.
