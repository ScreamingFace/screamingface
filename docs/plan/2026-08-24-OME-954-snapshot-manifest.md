# OME-954 — snapshot-cache manifest emission (plan)

One unit, one script: after writing the archive, `snapshot-cache` (a) sha256s it, (b) probes
the deployed aigateway image for the two cache-key revision constants (`kubectl run
--command`, one-shot pod, warnings-not-errors on failure), and (c) writes `<name>.manifest.json`
beside the archive. Constants come from the CLUSTER image, never the checkout — the checkout
may be older or newer than what the deployment runs, and the guard only works against the
deployment's truth.

First tracked commit of the script: remove the hardcoded OpenRouter key (env-only) before the
file enters history; gitignore the snapshot artifacts.

Acceptance (spec criterion 12): a manifest whose constants match the deployed gateway,
verified against `GET /v1/admin/cache/info`.
