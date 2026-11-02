# OME-1768 — disclosure-gated default analytics

Status: local implementation authorized by Filip on 30 October 2026, before
Irina/Kevin sign-off. On 2 November Filip authorized opening a draft PR and chose
to post the Linear confirmation comment himself. No rollout approval is implied.

## Behavior

Use the exact OME-1768 disclosure. At import (after package initialization),
connection setup, and before the first evaluation, attempt disclosure once per
process. A terminal with visible stderr qualifies, including terminal scripts;
local Jupyter uses inline stdout. No input prompt. Missing/closed/redirected
output or a headless new installation stays off. Successful display precedes
identifier creation and persistence. Import creates no analytics event or session.

Local enrollment is conditional under the existing preference lock: only a missing
file can enroll. Accepted/declined settings retain their meaning and identity;
corrupt, unsupported, symlinked or unreadable settings stay off. Explicit enable
continues to allow the user to reverse their own decline. DO_NOT_TRACK and
process disable are checked again before automatic persistence.

Colab starts a nonblocking setup command: retrieve browser preference, show the
same inline notebook notice only for valid unknown state, conditionally enroll,
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
enable or by the newly disclosed default. Do not erase or reinterpret old declines.
This amends the old opt-in-only semantics in the analytics specs; the privacy-posture
review remains outstanding.

Cookie-only storage retains the existing cross-notebook in-flight response ordering
limitation. Conditional enrollment observes decline on the current request, but is
not global atomic revocation of requests already in flight. Local kernel generations
and fresh permission checks protect disable/timeout races within the process.

## Scope boundary

Setup and delivery failures have limited visibility. Missing analytics may remain
hard to distinguish from intentional opt-out. OME-1793 tracks safe failure reasons
in status(); diagnostics, retries, dashboards and failure uploads are out of scope.

## Verification

Test disclosure-before-identity; once-only import/run hooks; redirected and failed
output; existing choices and invalid files; conditional enrollment races; sync/async
first-evaluation readiness; timeout/late responses/disable; absent/accepted/declined
and invalid cookies; browser command routing; unchanged event payloads.
Run both Python stack gates and browser-script tests with synthetic transport only.
Deployed Colab browser acceptance remains a rollout check.
