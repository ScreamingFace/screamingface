# Recovery URL and artifact encoding correction — OME-1503

The user authorized fixing both review findings on PR #1269.

Saved Engine origins must be validated before recovery authentication or HTTP requests.
Malformed origins and URL syntax become `result_metadata_invalid` per candidate,
preserving `candidates_failed` and healthy siblings in `partial_report` in both APIs.

Artifact requests negotiate identity encoding. An encoded successful response is
rejected as `result_integrity_mismatch` before its body is consumed or decompressed.
This retains bounded memory even when a server ignores the encoding request. Existing
expiration and HTTP error classification remain intact. Identity responses retain
UTF-8, size and SHA-256 verification before publication.

No public API, metadata schema, dependency or Engine changes.
