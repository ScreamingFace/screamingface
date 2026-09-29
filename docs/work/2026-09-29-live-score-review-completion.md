---
ticket: OME-932
stack: screamingface-engine + screamingface
status: done
started: 2026-09-29
finished: 2026-09-29
---
# Complete live-score review

## Intent
Address every remaining point from Khoa's #1096 review, as requested by the owner.

## Planned changes
Preserve semantic benchmark revisions and old batch endpoints; serve typed early grades at distinct additive routes. Compare old and new protocols with multiple cases and solo/fusion requests. Reduce progress retention without losing native scoring evidence, expose IFEval helpers publicly, reconcile fixture/docs comments, strengthen shared-client isolation and accounting coverage, link the Client component issue.

## Test plan
RED revision and old-expression compatibility regression, all eight boards with solo/fusion and multiple cases, retained-data parity with native scorers, retry/cache/shared-key accounting checks, Client interleaved rows. Cache-only recorded replays and full Engine/Client gates. No paid calls.

## Acceptance
Old ranked scores and old expressions remain valid; no extra grader/model calls; request/result/accounting parity established; every review concern has a concrete resolution. No merge.

## Outcome
Implemented all technical review corrections. Semantic revisions and legacy batch routes remain compatible, while typed results use the additive `/aggregate/graded` route. Progress retains only native scorer facts, including IFEval evidence mode. Public IFEval helpers replace cross-module private access. Finalizer-created missing-case failures now publish completion exactly once in both batch and early-grade paths.

Verification: 32 old/new protocol comparisons across eight built-ins, limits 1/2 and solo/fusion preserve requests and full results; native scorer prefixes match projected inputs. Retry, cache and shared-key accounting tests pass, plus actual HTTP connector cache decoding with observation enabled/disabled. Four recorded cache-only replays preserve final scores and outcomes: IFEval50 0.9184, DRACO-3pass100 0.3593, HealthBench-worst30 157 cases -0.091, GDPval-text25 0.8044. Client interleaved-candidate regression and full gates pass. Final Engine gates pass: lint, format, types, layering and tests/coverage.

Independent correctness review identified the missing finalizer progress and requested stronger real-connector coverage; both addressed and independently rechecked (four additional tests passed, no remaining actionable correctness gaps). Standards review found no architecture violation in this change, but noted an existing historical merge commit contrary to rebase-only guidance; no unsolicited history rewrite performed. Client component ticket creation remains awaiting owner approval; no Linear comments posted.

## Wisdom
Transport evolution need not change an exam's scoring identity: preserve the batch contract and add an explicitly separate typed reduction route. Test the old generated expression against the new serving code. Progress projection must preserve board-native evidence needed by scoring, while discarding diagnostic payloads. Finalization can synthesize terminal cases, so completion publication must cover that boundary too.

## Authoring-guide review correction

Updated the Running scores guidance to match the approved compatibility policy: retain the
batch route, add `/aggregate/graded`, preserve semantic revisions when request/scoring/result
parity is proven, and deploy Engine routes before publishing new expressions. This replaces
the stale instruction to change the benchmark revision for the transport change. Validation:
checked against the approved spec and ran `git diff --check`; documentation only, no runtime
or test changes.
