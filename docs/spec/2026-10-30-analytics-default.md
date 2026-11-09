# OME-1768 — default analytics in all environments

Status: local implementation authorized by Filip on 30 October 2026, before
Irina/Kevin sign-off. On 2 November Filip confirmed proceeding with the implementation
and PR and chose to post the decision in Linear himself. Deployed Colab verification
remains a rollout check. Later on 2 November, Filip replaced the disclosure gate
with default-on in all environments, including headless scripts, while respecting
every explicit opt-out. The Linear description and his comment record this decision.

Approval update, 3 November: Filip confirmed that Irina approved in today's sync.
This records his confirmation; no Kevin co-sign has been recorded here.

## Behavior

Use the exact OME-1768 disclosure. At import (after package initialization),
connection setup, and before the first evaluation, attempt disclosure once per
process. Python uses stderr, including redirected logs; local Jupyter uses inline
stdout. No input prompt. Headless execution and missing/closed/redirected output
do not prevent enrollment. Attempt the notice before identity creation, but treat
display errors as best-effort failures. Import creates no analytics event or session.

Local enrollment is conditional under the existing preference lock: only a missing
file can enroll. Accepted/declined settings retain their meaning and identity;
corrupt, unsupported, symlinked or unreadable settings stay off. Explicit enable
continues to allow the user to reverse their own decline. DO_NOT_TRACK and
process disable are checked again before automatic persistence.

Colab starts a nonblocking setup command: retrieve browser preference, show the
same best-effort inline notebook notice only for valid unknown state, conditionally enroll,
then obtain the browser ID. A new service command/route enrolls only an absent
preference; it preserves a saved decline and rejects malformed/stale cookies.
Old SDKs keep their explicit opt-in flow; a new SDK against an old service stays
off if enrollment is unavailable. Deploy the additive service route first.

The first evaluation may wait at most two seconds for pending setup (including
queue delay). The async path must not block the event loop. Timeout invalidates
that pending generation: late replies cannot enable kernel tracking. No replay
of operations started before enrollment, no new recovery loop.

## Contract

No new event fields or events. Version 1 remains the compatible preference/wire
format; accepted/consent_granted means analytics is permitted, either by explicit
enable or by the default-on policy. Do not erase or reinterpret old declines.
This amends the old opt-in-only semantics in the analytics specs; the privacy-posture
review now includes Irina's sync approval as confirmed by Filip; Kevin's co-sign
has not been recorded.

Explicit decline also sets a separate non-identifying opt-out cookie at /bridge.
It takes precedence over consent/identity cookies and is cleared only by explicit
accept. Automatic enrollment and identity refresh never change it, so their late
responses cannot reverse a completed decline across notebooks or service replicas.
Unrecognized opt-out values remain untracked. Upgrade every service replica before
SDK rollout; old replicas do not enforce this flag. Cookies may expire or be evicted.
Requests dispatched before decline can still complete, and concurrent explicit
accept/decline responses remain ordered by browser application. Local kernel
generations protect disable/timeout races within the process.

The notice/setup guard is process-local: after a fork, reset it with the lock so
the child's fresh Colab bridge can initialize. Inherited opt-outs still take precedence.

Existing-ID reads do not rewrite the ID cookie, and automatic enrollment never
writes or deletes it. Their late replies therefore cannot restore a discarded ID
or delete an ID created after explicit reaccept. IDs expire at the configured age
from creation (180 days by default), rather than renewing on reads; consent still
renews. A later ID request under accepted consent can create a replacement.
This is not cross-frame serialization of first-time ID creation: concurrent
requests that both mint fresh IDs can still apply in browser response order,
including across a reaccept. They cannot restore an already-used old ID through
an existing-ID read. Explicit-action response ordering also remains unchanged.

## Scope boundary

Setup and delivery failures have limited visibility. Missing analytics may remain
hard to distinguish from intentional opt-out. OME-1793 tracks safe failure reasons
in status(); diagnostics, retries, dashboards and failure uploads are out of scope.

## Verification

Test notice-attempt-before-identity; once-only import/run hooks; headless, redirected
and failed output enrollment; every opt-out and invalid files; conditional enrollment races; sync/async
first-evaluation readiness; timeout/late responses/disable; absent/accepted/declined
and invalid cookies; browser command routing; unchanged event payloads.
Run both Python stack gates and browser-script tests with synthetic transport only.
Deployed Colab browser acceptance remains a rollout check.


## Review hardening — 2 November

Ordinary SDK test collection and test CI must set DO_NOT_TRACK before importing
the SDK. Analytics tests may explicitly remove it only with isolated preferences
and synthetic transport. Unexpected ordinary setup exceptions must not prevent
import or evaluation; debug messages contain no exception details. Interruptions
and cancellation still propagate. Local enrollment in async evaluation runs in a
worker thread; Colab retains its two-second wait and generation invalidation.

The local preference lock serializes persisted choices. A process-only disable
or DO_NOT_TRACK change after the final permission check can still race with an
already-started preference write; dispatch checks suppress subsequent tracking.
This is not a promise to undo in-flight persistence or network requests.


## Colab wait errors and Studio scope — 2 November

Unexpected ordinary exceptions while waiting for Colab setup must let both sync
and async evaluations continue untracked. Invalidate pending setup so late replies
cannot enable kernel tracking; log only a generic debug message. Interruptions and
cancellation propagate. The two-second cap and explicit opt-outs remain unchanged.

Studio inherits the same SDK default when its sidecar bundles this SDK version.
A fresh eligible installation may enroll at sidecar startup; the notice goes to
runtime logs, not a dedicated Studio UI. Startup/import emits no event. Studio
shares the SDK preference file (independent of runtime --data-dir), so existing
saved declines and DO_NOT_TRACK retain precedence. The lack of a dedicated visible notice and
controls is acknowledged; no Studio UI follow-up is planned for now. Successful
notice display is not an enrollment prerequisite. Irina's sync approval was
confirmed by Filip on 3 November; Kevin's co-sign has not been recorded.
