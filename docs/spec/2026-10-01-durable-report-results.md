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

Report UI retains existing styling and paginates 25 cases, with details and complete
export. Remove search/filter/sort UI. Persistence belongs to collection, not rendering.

## Verification

Sync and async downloads; interrupted download and decode recovery in a new process;
checksum, malformed data, disk failure, and expired remote results; partial evaluation;
case API behavior; byte-identical export; 11 candidates of approximately 200 MB each
with measured peak RSS; notebook pagination without eager case retention.
