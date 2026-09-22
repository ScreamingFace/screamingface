# Test plan

Testing shows the presence of defects, not their absence. This plan states what is
covered, what is not, and what residual risk remains after it all passes.

## 1. Mission

The decision this testing informs: **may this change reach production without
putting existing ensemble traffic, or any caller's identity, at risk?**

Two properties dominate everything else:

1. No caller ever observes another caller's state.
2. The ensemble path behaves exactly as it does today.

Every other requirement is secondary to those two, and the test order reflects it.

## 2. Risk model

Ranked by likelihood × impact. This ranking is the justification for every choice
below.

| Id | Risk | Likelihood | Impact | Where it is addressed |
|---|---|---|---|---|
| R1 | Cross-caller leak of identity, profile, seed or cache policy via retained handler state | Medium | **Critical** | `prd/01` T1–T4, `prd/03` T1 |
| R2 | Identity impersonation — forged `X-User-Email`, or the node reachable without the App | Medium | **Critical** | `prd/03` T2, T15 |
| R3 | The refactor silently changes ensemble behaviour | Medium | High | `prd/01` T5, T8; conformance suite |
| R4 | A mount is silently shadowed by route precedence | Medium | High | `prd/02` T3, T4 |
| R5 | Memory exhaustion on a tier with no `RLIMIT_AS` | Medium | High | `prd/03` T5, T6; D1 removes fan-out |
| R6 | An operator puts secrets in globally-readable `[holdings]` | **High** | High | `prd/02` T7 + documentation; not fully preventable by tests |
| R7 | The 30 s budget rejects legitimate slow model calls | **High** | Medium | `prd/03` T4; accepted risk under `ans:Q5` |
| R8 | Retry amplification doubles cost on a timeout | Medium | Medium | `prd/03` T8 |
| R9 | A spilled artifact is unreachable by the caller it was created for | **Closed** — OQ-3.2 decided (signed URLs) | Medium | `prd/03` T5 |
| R10 | Two error dialects confuse clients | **High** | Low | Documentation only; OQ-3.1 |
| R11 | App and node disagree on the mount set mid-rollout | Medium | Low | Unknown mounts 404 at the App; `config_digest` |
| R12 | An exec surface reaches production via `[commands]` or a command-backed provider | Low | **Critical** | `prd/02` T1, T2 |

R6 and R7 deserve a note. Neither is fully closable by testing. R6 is an operator
mistake that tests can only make *visible* (a startup log, a documented constraint).
R7 is an accepted product trade-off, not a defect — the test pins the behaviour and
the message, not the wisdom of the number.

## 3. Test levels

Effort follows the pyramid, weighted toward the middle because the risks that matter
here are integration risks, not algorithmic ones.

| Level | Scope | Runs where |
|---|---|---|
| **Unit** | Scope binding, config parsing and rejection, cap ordering, collision-guard logic, route-id encoding | Existing suite |
| **Integration** | ASGI dispatch against a stubbed aigateway: status mapping, forwarder behaviour, route precedence, concurrency isolation | Existing suite, in-process |
| **Conformance** | The full ensemble path against a real NATS JetStream broker | Existing conformance job |
| **Deployment smoke** | Both images boot; the node answers; NetworkPolicy refuses non-App traffic; Helm templates render for external and bundled NATS | CI, extending the existing chart-validation job |

The concurrency isolation tests (R1) belong at the **integration** level, not the
unit level. A unit test of a ContextVar proves the ContextVar works. Only a test that
drives two real concurrent requests through the real handler proves no state is
retained between them.

## 4. Techniques, matched to the problem shape

- **Boundary values** — the numeric caps. Test each at n−1, n, n+1: the 512 KiB
  inline cap, `result_hard_cap_bytes`, the 30 s budget, the in-flight cap.
- **Decision table** — dispatch outcome as a function of (path is a known mount?) ×
  (`q` present?) × (method). This is where url4's fall-through produces the
  confusing `404` that AC11 replaces, and a table makes the gap obvious.
- **State transitions** — node pod lifecycle: starting → world built → ready →
  saturated → draining. Assert readiness at each, particularly that *saturated* is
  not *ready* (R5, gray failure).
- **Pairwise** — the config matrix: section (`data`, `holdings`, `identities`) ×
  provider kind (`value`, `file`, `command`) × declared/absent. Full enumeration is
  small enough here that pairwise is a convenience, not a necessity.
- **Error guessing**, from this repo's own history:
  - U+2028 and other unicode line separators inside `q`. A prior incident had
    hand-built url4 bodies keying the cache wrongly because of exactly this
    character.
  - A URL at and beyond the practical ~8 KiB edge limit.
  - The tilde-encoded route id, which only appears on this new surface.
  - An empty context `('')` and a context containing an absolute URL, which must
    stay opaque text on a direct hit (D1).

## 5. Entry and exit criteria

| Unit | Entry | Exit |
|---|---|---|
| 1 | Suite green on `main` | Full suite and conformance pass with **no assertion edits**; golden-parity test present; layering fixtures pass |
| 2 | Unit 1 merged | New config sections resolve; `[commands]` and command-backed providers rejected with named errors; collision guard fails startup on a seeded collision |
| 3 | Unit 2 merged; OQ-3.1 and OQ-3.2 decided | All PRD-3 acceptance criteria pass; deployment smoke passes including NetworkPolicy; conformance unchanged |

Unit 3's entry is now satisfied decision-wise: OQ-3.1 and OQ-3.2 were decided by
the owner in a follow-up round (keep both dialects, documented as a unit-3
deliverable; short-lived signed URLs per `contracts.md` C6). Unit 2 merging is
the only remaining entry condition.

## 6. TDD ground rules

- **RED before GREEN, always.** Every test in the PRDs is written to fail first, and
  the failure is observed and understood before implementation. A test that passes
  the moment it is written has proved nothing.
- **A test must be able to fail for the right reason.** Before accepting a green
  test, revert the implementation and confirm it goes red. This is where plans in
  this repo have historically been weakest — assertions that could not distinguish
  the bug from its absence.
- **Unit 1 forbids assertion edits.** A moved test may change its import path. If it
  must change what it asserts, the refactor changed behaviour and the diff is wrong.
- **Coverage is append-only**, per the repo's SDLC card. Add tests; do not weaken or
  delete existing ones to make a gate pass.
- **One behaviour per test**, named for the behaviour rather than the function.

## 7. Test data and environments

- **Stubbed aigateway** for all integration tests. Deterministic, free, and the only
  way to assert on outbound headers.
- **Real NATS** for conformance, as today.
- **No real model calls in CI.** Cost and non-determinism both disqualify them. The
  `answer_seed` path is tested against the stub, not against a live model.
- **`pg_dump` is absent locally**, so the small set of Postgres-dependent tests fails
  on a developer machine and is skipped in the gates. Unrelated to this work, but it
  will be seen while running the suite and should not be mistaken for a regression.

## 8. What is deliberately not tested

Stated plainly, because an unstated gap is an assumed guarantee:

- **Real model latency.** R7's 30 s budget is pinned as a behaviour, but whether 30 s
  is the right number can only be answered by production latency data. The first
  week of `504` rates is the real test.
- **Cloudflare edge behaviour.** The timeout ladder assumes an edge drop near 100 s.
  That is an assumption about infrastructure this suite cannot exercise.
- **Prompt injection.** Inherent to the product and unchanged from the ensemble path.
  Out of scope here, not solved elsewhere.
- **Sustained load and soak.** No capacity test is planned for v1. The in-flight cap
  and pod memory limits are the controls; whether `2 ×` workers is the right cap is a
  production observation.
- **Multi-tenant holdings isolation**, because under D8 there is none to test. The
  test asserts the warning exists, not that isolation works.
- **Rolling-deploy skew** between App and node mount sets. Mitigated by design
  (unknown mounts 404 at the App) rather than by a test.

## 9. Observability as a test aid

Three signals should exist before unit 3 ships, because without them the accepted
risks above are unobservable in production:

1. `504` rate and duration histogram on the sync surface — tells us whether R7's
   30 s is wrong.
2. In-flight gauge and `503` count on the node tier — tells us whether the cap is
   wrong.
3. Request logs carrying `origin=sync|run` alongside the existing `topic` and
   `trace_id` — without this, sync and ensemble traffic are indistinguishable in the
   logs.

## 10. Gaps and assumptions

**Assumed:** that the world build performs no network I/O. `prd/03` AC19 tests this,
but if the assumption proves false, the fix belongs in unit 1 rather than unit 3 and
the estimate grows.

**Assumed:** that cancelling the request task actually cancels the in-flight httpx
call to aigateway. AC6 asserts it; if httpx does not honour it as expected, an
explicit timeout on the client is the fallback.

**Not covered:** whether the two error dialects (OQ-3.1) cause real client breakage.
No existing client consumes the sync surface, so there is nothing to regress — but
also nothing to learn from until one does.

**Next with more time:** a soak test of the node tier at the in-flight cap for an
hour, watching RSS. That is the cheapest way to convert R5 from a reasoned argument
into a measured one.
