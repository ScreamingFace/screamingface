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
title and range; submitted queries scan retained case fields and candidate names one
case at a time without blocking the notebook widget loop. Preserve the
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
created; full-content queries still read the saved content.
