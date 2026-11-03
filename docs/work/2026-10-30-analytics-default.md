---
ticket: OME-1768
stack: screamingface
status: in_progress
started: 2026-10-30
finished:
---

# Default analytics in all environments

## Intent

Implement OME-1768 using the choices confirmed by Filip: terminal scripts qualify,
inline Colab notice, and a two-second first-evaluation wait. Filip explicitly
authorized implementation before Irina/Kevin sign-off. On 2 November he authorized
opening the PR and confirmed proceeding, with the Linear decision update handled
by him. This does not claim approval from other reviewers or deployed verification.

## Planned changes

- SDK analytics prompt, local persistence, Colab adapter, tracking and import hook.
- Analytics service conditional enrollment route and browser command.
- SDK/service tests, READMEs, spec and plan.

## Test plan

New tests first: disclosure before ID, prior opt-out, invalid settings, visible output,
first sync/async evaluation, timeout/late-reply races, server cookie checks.
Run SDK and analytics gates and Node script harnesses; no production events.

## Acceptance

New installations enroll in all environments, including headless scripts; disclosure
is best effort. Every explicit opt-out wins; analytics adds at most two seconds
before the first Colab evaluation.
Existing payloads and explicit controls remain compatible.

## Outcome

- Actual files: SDK import, prompt/local/Colab/tracking modules and README;
  service bridge Python/JS and README; new default-enrollment SDK/service/browser
  tests; two existing SDK test files updated for the authorized contract reversal;
  exact test-transition manifest; spec/plan/task mirror and prior-spec amendments.
- Commits: `b0330994b` — feat(analytics): enable SDK analytics after disclosure,
  rebased onto `bc96df570` on 2 November for PR preparation. No merge or
  agent-posted Linear comment.
- Gates: both stack runners ALL GATES GREEN. SDK: lint, format, pyright,
  complete pytest suite with 97% coverage (95% floor), notebook-source check,
  build and distribution checks. Service: lock check, lint, format, pyright,
  complete pytest suite including Node bridge tests, 99% branch-aware coverage
  (95% floor), build. SDK Node browser harness: passed. Mirror-status and
  whitespace checks: passed.
- Verification environment: Python 3.13.5. Gate runner invoked with the installed
  SDK environment's Python (same runner and gates) because PEP-723 dependency
  resolution was network-blocked in the sandbox. SDK socket tests were rerun with
  local socket access after sandbox PermissionErrors; the complete rerun passed.
  DO_NOT_TRACK=1 protected the full SDK run; isolated analytics fixtures explicitly
  clear it and use synthetic/mocked transport. No deployed Colab browser smoke or
  production analytics delivery was performed.
- Deviations: user authorized local implementation before the issue's sign-off.
  The requested default reversal necessarily updates obsolete opt-in tests.
  Both components remain under the existing cross-unit issue for this local draft.
  Failure diagnostics and retries remain tracked separately in OME-1793.

## Review

Conditional enrollment is separate from explicit enable, preserving the user's
ability to reverse a decline intentionally. Existing version-1 choices/IDs remain
compatible. The service route must deploy before the SDK. The first async wait
includes executor queue delay and never repeats once setup completes or is disabled.
In-flight cross-notebook cookie ordering remains an existing limitation, documented
in the spec; no global revocation guarantee is added.

PR: https://github.com/ScreamingFace/screamingface/pull/1633

Filip confirmed proceeding and is posting the decision in Linear himself. The PR
is ready for review; ledger/Linear remain open pending review and landing.
Both full stack gates passed again after the 2 November rebase. No approval from
other reviewers or deployed Colab verification has been represented as received.

## 2 November — headless default-on revision

Filip requested default-on in every environment while respecting every opt-out,
and posted that decision in Linear. The earlier visible-disclosure gate is superseded.
Plan: remove terminal/output availability as an enrollment condition, preserve
DO_NOT_TRACK and explicit disable/decline, update regression tests and docs, run
SDK gates, then update PR #1633. The Linear description was aligned to the new
decision; Filip's comment was left unchanged.

Validation of this revision: ALL SDK GATES GREEN (lint, format, type checking,
full pytest with the 95% coverage floor, notebook checks, build and distribution). The test-first run against
the previous policy failed 12 cases as expected (68 cases total). The new coverage
checks headless subprocess import with redirected/missing/closed stderr, saved
opt-outs, truthy DO_NOT_TRACK values, and suppression of queued/new events when
DO_NOT_TRACK is set after enrollment. Tests mock the analytics sink.

Review: no schema, dependency or event-format changes. Only output-related
OSError/ValueError/RuntimeError failures are ignored when attempting the notice,
as required by the best-effort policy; setup failure visibility stays in OME-1793.
Existing preference locks and opt-out rechecks remain intact. Type checking passes
without new suppressions. The service implementation is unchanged by this revision;
its previously passing full gates remain applicable.

Revision commit: `feat(analytics): enable defaults in headless environments`.
Confidence review: ready for code review; deployed Colab smoke remains a rollout check.


## 2 November — review fixes

Intent: close the actionable review findings before updating PR #1633. Filip
explicitly authorized the fixes and strengthening existing assertions.

Planned changes: SDK test bootstrap disables analytics before collection; SDK,
engine, scoreboard, replay and paid-smoke CI lanes set DO_NOT_TRACK. Studio and
failor have no corresponding Python test CI job in this checkout. Protect SDK
setup from unexpected ordinary exceptions with a content-free debug message;
retain interruption/cancellation semantics. Offload local enrollment from async
evaluation; keep the existing bounded Colab setup and late-reply protection.
Strengthen notice/cookie assertions, reconcile docs/README ledger naming with D8,
and clarify that opt-out rechecks are not an atomic promise about in-flight writes.

Test plan: isolated pytest subprocess with no inherited DO_NOT_TRACK, fresh and
previously accepted homes, collection plus evaluation, and a tripwire for real
analytics delivery. Inject unexpected setup errors and interruption; use an event
loop handshake to prove local enrollment runs off the loop. Run full SDK/service
gates and workflow validation. No live analytics, posting comments, merging or
production deployment. Owner approval and deployed Colab smoke remain open.

Acceptance: ordinary tests cannot enroll or send by default, analytics-specific
tests retain mocked opt-in coverage, optional setup cannot replace product failures,
and first local async setup leaves the event loop responsive.

Additional review scope: disable analytics in Studio's sidecar verification script
and failor's manual check/verification scripts and generated notebook. These are
verification entry points, not production runtime defaults. Validate the Python
bootstrap without executing live checks, check shell syntax, and regenerate/parse
the notebook without running its live benchmark cells.


Review-fix verification:
- Red: seven new SDK cases failed on the prior implementation; interruption cases
  already passed. An additional unavailable-executor case failed before its fix.
- Focused SDK checks: 93 cases passed without DO_NOT_TRACK in the parent shell;
  the final 12-case review regression module passes, including executor shutdown.
- Full analytics-service gates and repository gates: ALL GATES GREEN. The repo
  runner needed the installed SDK Python on PATH so child commands could find PyYAML.
- Both full SDK runs passed, including the final run after the executor-shutdown fix.
  Lint, format, type checking, full coverage gate, notebooks, build and distribution
  checks are ALL GREEN.
- All five changed workflow YAML files parse and every job/step inherits the opt-out;
  engine smoke containers receive it explicitly. No engine/scoreboard application
  code was changed, and their full application suites were not rerun locally.
- Manual diagnostic bootstrap checks pass without running a live cluster request;
  Studio verification shell syntax passes. The failor notebook was regenerated,
  parsed, and checked output-free. Its builder exposed an existing lint requirement
  for explicit subprocess check=False; that behavior-preserving fix is included.
- Exact-copy disclosure assertions and structured cookie assertions replace weaker
  substring checks. The test-change manifest pins the authorized fixture/assertion
  changes; no opt-out tests were weakened.

Wisdom review: default-on product policy is unchanged. Broad Exception handling is
limited to optional setup, logs no exception details, and leaves BaseException
interruptions intact. Local async file work runs off the event loop; Colab's existing
bounded setup remains unchanged. No schema, dependency, event fields, retries or
new remote diagnostics. D8 ledger naming is now consistent in docs/README. Privacy
owner confirmation and deployed Colab smoke remain explicit outstanding checks.

Review-fix commit: `fix(analytics): isolate tests and harden optional setup`.
The revision is ready for PR review; no merge or deployment was performed.


## 2 November — final Colab guard and Studio scope

Filip selected all recommended A options: guard the shared Colab setup wait,
retain Studio's inherited default-on behavior with a separate notice/opt-out UI
follow-up, and obtain an explicit owner decision on the current policy/copy.
He retains ownership of posting the review request; prepare text without posting.

Planned files: SDK prompt and focused Colab regression tests; spec/plan and SDK/
Studio runtime documentation; Linear Studio follow-up and its task mirror. Tests
must prove sync/async evaluations survive unexpected wait failures, pending setup
is invalidated before a late response can enable tracking, and cancellation/
interruptions propagate. Run full SDK gates. No new events, retries, Studio UI,
merge, deployment or claim of owner approval.


Final-guard validation: the new tests first failed five ordinary-error cases while
three interruption/cancellation cases passed. All 63 focused Colab/review tests now
pass. Full SDK gates are ALL GREEN: lint, format, type checking, full tests with
the coverage floor, notebook checks, build and distribution. The mirror-status
check and whitespace checks pass.
The service implementation is unchanged and retains the prior passing gates.

Studio follow-up OME-1805 was created in Backlog under OME-1308, with shared SDK
preferences and no new event instrumentation or enrollment gate. No UI code was
added. An owner-review request covering the current policy/copy, persistent IDs,
Colab cookies and inherited Studio enrollment was prepared for Filip, not posted.

Review: errors use the existing pending-generation invalidation, not a retry or
new consent state. Sync/async error paths log only a generic debug message and
preserve BaseException interruptions. Scope stays limited to optional setup and
explicit documentation; policy approval and deployed Colab smoke remain open.

Final-guard commit: `fix(analytics): guard Colab setup waits`. Ready for PR review;
no merge, deployment or owner approval is represented as completed.


## 2 November — remove Studio follow-up

Filip requested removing the follow-up and retaining only an awareness note in
PR #1633, with no follow-up planned for now. The Linear connector has no delete
operation, so OME-1805 was canceled, unassigned and unlinked from OME-1768. This
supersedes the earlier follow-up plan; no Studio UI work started. Remove its task
mirror and active links from docs, and update the PR description. Documentation
only: verify mirror consistency and whitespace; prior code gates remain valid.

Mirror-status and whitespace checks passed. No runtime or test code changed.

## 3 November — Dmitry's response-ordering and fork review

Filip requested fixing Dmitry's PR review findings. Reproduce late automatic
enrollment and identity-refresh responses arriving after a completed decline,
using two independent service instances and a shared synthetic cookie jar.
Add a separate non-identifying opt-out cookie: explicit decline sets it, only
explicit accept clears it, and automatic/background responses never touch it.
All service permission checks must honor it. Deploy all service replicas before
the SDK; mixed old/new replicas cannot provide the new ordering guarantee.

Reset the process-local notice/setup guard together with its lock after a fork.
Test first-child evaluation in sync/async Colab paths and preserved browser,
environment and process opt-outs. No new identity, events, retries or server store.
Run RED regressions, both Python stack gates and the browser harness, then update
the existing PR. Acceptance: late automatic responses cannot reverse a stored
decline; forked Colab setup runs once per process and respects opt-outs.

Linear was checked again: owner policy/copy sign-off and deployed Colab smoke
remain outstanding. No new ticket, review comment, merge or deployment is planned.

Validation: RED reproduced six service failures (including both reversed-response
cases) and six fork/setup failures; four inherited opt-out cases already passed.
After the fixes, all 40 focused service and 61 focused Colab tests pass. Full
analytics and SDK gates are ALL GREEN, including coverage, notebook checks and
build/distribution checks. Service coverage is 99%, with complete coverage of the
changed bridge module. The 12-test SDK browser harness and repository gates pass.
No existing tests were edited or weakened.

The first SDK append-only check used the newly advanced origin/main and counted
unrelated upstream test additions as deletions. Verified those paths were added
on main, then reran all gates against the actual PR merge base
bc96df570b17b5db17726b6c169f7780d334b138. The new response-delay helper also needed
an explicit optional-path type annotation; type checking passes after that fix.

Review: the opt-out marker is a constant preference, not another identity, and
works across independent replicas without server state or browser-script locks.
Automatic enrollment is separate from explicit acceptance so it cannot erase
the marker. Invalid marker values stay untracked. Existing cookie lifetime and
security attributes remain; explicit accept can still restore permission.
Requests already dispatched and concurrent explicit choices retain their stated
limitations. Both fixes are ready for review; owner approval and live Colab
acceptance remain unverified. No merge, deployment, new ticket or comment posted.
