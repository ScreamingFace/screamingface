# OME-1191 — Ephemeral Client-version provenance

## Agreed scope

Capture the caller-reported ScreamingFace Client version at the Engine run-start
boundary and retain it for the existing run-history lifetime. Missing version
information must not prevent older clients from running. No permanent store or
longer retention period is introduced.

## Existing data lifetimes

- Deployed event streams: `runner/main.py::run_and_reclaim` normally deletes a
  completed run's stream after `job_env.DEFAULT_STREAM_GRACE_S` (60 seconds).
  Explicit teardown may delete it earlier; failed cleanup may leave it until a sweep.
  JetStream max-age is a backstop, not a promise of a day of history.
- Local history: in-memory and bounded by existing frame/run-history limits.
- Result artifacts: separate filesystem TTL or object-store lifecycle policy.
- Operator diagnostic logs: independent pod/collector retention. Existing
  `run_evidence.py` log lines can outlive run streams; they are not a run database.
- Client-held or exported results are separate copies; deleting Engine evidence
  cannot delete data already delivered to a Client.

## Implementation boundary

Read User-Agent on `rest/routes.py::start_run`, after normal request admission
checks. Extract only one unambiguous `screamingface/<version>` product token.
Treat it as untrusted caller-reported software identity, never authentication.
Bounds: inspect at most 512 characters; accept a nonempty version of at
most 128 ASCII characters from letters, digits, dot, plus, underscore and hyphen.
Missing, malformed, ambiguous, unrelated, or oversized headers yield unknown;
do not reject execution or store/log the raw header. Preserve accepted spelling.
This is a diagnostic token, not an enforced package-version compatibility policy.

Carry the optional version explicitly through Engine-local scheduling context,
including queued worker handoff and local mode. Deployed workers run in Kubernetes;
there is no separate Kubernetes scheduling adapter in the current tree. Never put it into
shared world configuration or reuse verified caller identity fields.

Evidence carrier: one existing structured `ai.url4.log` INFO event after the
root Started event, body `Client software version`, with scalar attribute
`screamingface.client.version`.
Publish through the existing sequenced event path so replay and cleanup match
other run evidence. An Engine-local Executor decorator emits the first telemetry step, so lifecycle
sequencing and failure handling remain authoritative. Do not add a shared URL4 schema field or invent a
new event type merely to carry Engine-specific provenance.

## Compatibility and limits

The current Client dispatches `ai.url4.log` and accepts scalar attributes; this
allows this Engine-only change. Actual Started and provenance Log frames were
verified against the merged Client decoder; lifecycle ordering is regression-tested.
This does not provide a typed Report provenance field, permanent retrieval API,
or transactional response-body metadata. Those remain separate OME-416 work.
Do not automatically copy this attribute into longer-lived operator logs or spans;
the existing SpanRelay ignores Log events, and the decorator does not use Python
logging or the run-summary logger.

An operator/caller may inspect this evidence through the existing authorized run
stream while it is available. After reclamation, Engine retrieval is unavailable.
Unknown version is an absence of evidence, never an inferred release version.

## Validation plan

Parser boundaries; installed/source version tokens; unrelated/absent/invalid
headers; no raw-header leakage; no cross-run contamination; rejected starts;
all scheduling modes and queue serialization; event sequencing/replay; old-Client
decoding; normal stream cleanup without extending retention. Run Engine gates.

## Review status

Retention choice, implementation, and draft PR approved on 11 September 2026.
The owner also approved adding only the optional `client_version` parameter to
four existing test doubles; no assertions or test behaviors change.
