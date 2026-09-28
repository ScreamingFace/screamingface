# OME-416 — Client provenance, first delivery

## Notebook origin

The generator adds `metadata.screamingface.generated_by_version` from the generating checkout's
`packages/screamingface/pyproject.toml` project version. Use Jupyter's custom metadata namespace.
No timestamps or absolute paths. This identifies generation, not the package later executing the
notebook. A package release does not retroactively change an already-generated notebook's stamp.

## Request identity

Set `User-Agent: screamingface/<version>` on Engine HTTP clients, covering sync/async catalogue and
evaluation transport. Reuse `_version.resolve_version()` including `0.0.0+source` fallback.
Per-request capability, trace and other headers still merge normally. No request-body changes.
WebSocket handshake identification and Scoreboard/Access clients are outside this first delivery.

## Remaining work

Current Engine code does not retain Client versions with runs. No published Client-version
metadata field was found. Engine storage and any returned typed provenance require a separate
Engine-owned design/unit; this Client-only PR must not close OME-416.

## Standards

- Jupyter custom metadata: https://nbformat.readthedocs.io/en/5.2.0/format_description.html
- HTTP User-Agent product/version: https://www.rfc-editor.org/rfc/rfc9110.html#section-10.1.5
