# Durable results and bounded report loading

Refs: OME-1422, OME-1448. Approved in the task conversation on 2026-10-01.

## Contract

The SDK automatically retains completed candidate results outside temporary storage.
Record the claim ticket and SDK provenance before fetching. Stream downloads to disk,
verify their size and checksum, and publish complete files atomically. Never fall back
to whole-result RAM buffering when storage fails. Retain results until explicit deletion.
Recovery uses existing Engine authentication, never persisted credentials, and never
starts billable model work. Remote recovery depends on Engine retention; a verified
local copy does not. Expose completed candidates even when siblings are unavailable,
with incomplete evaluation status explicit rather than implied successful completion.

Decode cases incrementally into indexed local storage. Case indexing, identity lookup,
iteration, values, and report.v1 export remain supported. Normal loading, display, and
export have bounded memory; explicit to_dict/to_json/list conversions can materialize.
Keep summary calculations streaming. Preserve prompts, operations, accounting, recipe,
run times, trace, seed, and SDK version. Do not change Engine wire formats.

Report UI reuses the original case rail and detail panes and paginates 25 cases.
The case range, Previous/Next, and export/download control belong inline in the cases
box header, with responsive wrapping and a plain Case results title. No added Case
detail / Full content tabs or filter/sort controls. A search input sits between the
title and range; this search was superseded by the owner's approved case-navigation
layout below. Preserve the
original text previews; complete JSON export retains every field. A single export control changes from Download to disabled/spinning Preparing… to
Download. Duplicate requests are ignored. Failure restores enabled Download with
a brief error; successful states have no separate status text or leftover export button. Persistence belongs to collection, not rendering.

## Verification

Sync and async downloads; interrupted download and decode recovery in a new process;
checksum, malformed data, disk failure, and expired remote results; partial evaluation;
case API behavior; byte-identical export; 11 candidates of approximately 200 MB each
with measured peak RSS; notebook pagination without eager case retention.

Saved reports use sf.reports.list(), get(id), get_async(id), and delete(id).
List has one entry per evaluation (standalone URL4 results use their saved key).
The persisted evaluation ID identifies the group across restarts and copies.
Get returns the whole report; delete explicitly removes that same group.

Pagination remains clickable during a load. Rapid clicks advance the requested
position; rendering runs off the widget event loop and publishes only the latest
requested page. Global accounting attribution/consistency is derived once per
browser into a compact context, then only displayed cases are read for page costs.
Search scans the existing disk JSON index without constructing CaseResult objects,
and candidate-name matches require only positions. No duplicate full-text index is
created; this earlier search UI is superseded by exact case navigation below.

Compact accounting context is persisted as a versioned, checksummed, atomic derived
cache beside the immutable case index. Its identity includes index size/mtime and
all candidate inputs used by accounting. Missing, stale, damaged or unwritable
caches retain the original derived accounting behavior; they never replace raw
accounting evidence or enter exported report.v1. Saved report collection builds
the context; browser rendering reuses it. Index creation also retains validated
numeric-grade counts and compact case failure rows. Existing indices are upgraded
transactionally, with a read-only fallback. Coverage invariants and diagnostic
details remain unchanged.

## Shared case browser (owner-approved follow-up)

Replace text search with a candidate dropdown (default All Candidates) and Go to case number, submitted
on Enter or blur. These use actual retained case identity, not the flattened
candidate–case result number. Indexed identities/positions are read without prompt
decoding. Preserve numeric and string Case IDs and escaped diagnostics. Invalid
input preserves the current page and explains that the case was not found.

All Candidates lists every retained case result across candidates, ordered by first
occurrence of case identity then candidate order, in 25-result pages. Its range is
against the combined result total. A specific candidate lists its cases in the
original order with the same pagination. Go to case selects and reveals the first
matching result in the current selection, using exact case identity rather than row
number; matching candidates sit together in the combined list and may span page
boundaries. Changing candidate preserves that case when available; otherwise starts
at the first available page. There is no implicit one-case comparison mode.
Candidate summary names are native notebook buttons selecting the same shared
browser, with active selection visible. Preserve all figures and original details.
Keep one header, one Download and no per-candidate expanded case panels. Rapid
navigation remains coalesced and clickable. Input/candidate changes are disabled
briefly while a page is loading to keep the navigation model stable.

### Case rail refinement (2026-10-01)

The candidate selector has no visible prefix and defaults to All Candidates. Live rows are 44 px, with a viewport-bounded scrollable rail. Candidate mode shows status, case ID and a short input preview; All Candidates shows status, case ID, candidate name and preview. Go to case selects the detail pane, retains the entered ID, highlights the row and reveals it inside the rail. A brief initial CSS snap is released after insertion so subsequent manual scrolling is unrestricted. Static exports retain their existing labels/layout.

## Export and local runtime durability

Adopts Ionésio's implemented atomic-file and local-runtime artifact improvements from
PR #1211 at 12b8a390bbf7fe83b2d889eccfe55573e83bc1a7. Export retains our finer case-level
streaming, flushes/fsyncs the sibling temporary file before replacement, follows output
symlinks, and preserves existing ordinary permissions. New exports honor the process umask.
On POSIX the parent directory is fsynced after replacement. Failure before replacement
retains the previous export; failure during directory fsync means the new file has already
replaced it, but durability is unconfirmed. `to_json()` uses the same serializer, avoiding
whole-candidate dictionaries, although returning the complete string still takes memory.

`screamingface up` sets both the Engine reader and runner writer to `<data_dir>/artifacts`
by default, creates/restricts that folder to 0700, and respects a nonblank
`URL4_CLOUD_ARTIFACTS_DIR` override. `screamingface status` reports the serving runtime's
artifact path and bytes. This survives temporary-directory cleanup; it does not override
Engine artifact retention/TTL or change hosted storage. SDK-downloaded results remain in
our separate saved-results store. No recovery API or notice planned in #1211 is copied;
our existing `sf.reports` API remains the recovery interface.
