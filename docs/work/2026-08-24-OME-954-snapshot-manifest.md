---
ticket: OME-954
stack: repo
status: in_review
started: 2026-08-24
finished: 2026-08-24
---

# OME-954 — snapshot-cache emits a revision-guard manifest

## Intent

Make `local_k8s_deployment.sh snapshot-cache` write the sidecar manifest the admin upload
(OME-952) verifies: schema tag, generated_at, row_count, sha256 of the archive, and the
DEPLOYED gateway's cache-key revision constants (probed from the cluster's aigateway image,
never the host checkout).

## Outcome

- **Actual files:** `local_k8s_deployment.sh` (tracked for the first time — previously an
  untracked local file), `.gitignore` (snapshot artifacts), this ledger, `docs/plan/2026-08-24-OME-954-snapshot-manifest.md`.
- **Commits:** (see PR)
- **Gates:** `bash -n` clean; LIVE end-to-end verified against the running kind stack:
  snapshot (204,765 rows) + manifest with matching revisions and sha256.
- **Deviations:** **the script's hardcoded OpenRouter API key was removed before its first
  commit** (env-only now, per the script's own SECURITY NOTE). The key value previously sat
  in the untracked file and MUST be rotated — it has existed in plaintext on this machine.
