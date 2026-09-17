---
id: OME-711
linear_url: https://linear.app/openmined/issue/OME-711/add-release-aigateway-uiyml-publish-the-console-image-and-chart-on
status: in_review
type: task
priority: P3
labels: [repo, autonomous, agentic]
created: 2026-07-30
closed:
---

# OME-711 — `release-aigateway-ui.yml`: publish the console image and chart on `aigateway-ui-v*`

`OME-707` registered `aigateway-ui` with release-please, so merging its release PR bumps
`package.json` and tags `aigateway-ui-v*`. **Nothing listened to that tag.** `OME-710` produced the
Dockerfile and chart it would consume. This closes the loop.

Mirrors `release-aigateway.yml`: `verify` → (`image`, `chart`) → `release`.

## Four real differences from the lane being mirrored

1. **The chart render passes values.** `charts/aigateway-ui` *refuses* to render when
   `networkPolicy.clientPodNames` is empty — a NetworkPolicy ingress rule with no `from:` admits
   every source, on a console that trusts `X-User-Email`. A copy-paste of the aigateway chart step
   fails here and reads as a broken workflow rather than a chart doing its job.
2. **Version from `package.json` via `jq`**, not `pyproject.toml` via `awk`. Structured data
   deserves a parser: a `"version"` key also appears inside dependency entries.
3. **No `sf-installer` mirror.** That repo is the public ScreamingFace installer; this console is
   internal operator tooling behind Cloudflare Access. Listing it there would present an admin
   surface as part of a product install.
4. **Tag filters are disjoint** — `aigateway-v*` does not match `aigateway-ui-v0.1.0`. Confirmed
   with two independent matchers rather than reasoned about.

## Verified

Every locally-runnable step was run against the real artefacts: the version check in both
directions (it fails on a mismatched tag), the exact `helm lint`/`template`/`package` commands, and
the packaged `.tgz` filename the push step assumes. Rendering the *packaged* chart yields
`ghcr.io/openmined/screamingface-aigateway-ui:0.1.0` — exactly what the lane pushes.

`verify_chart_wiring.py` grew to 23 checks; the new one compares the chart's image against the
lane's `env.IMAGE`, because a chart naming an unpublished image is installable and permanently
`ImagePullBackOff` and neither file can notice alone.

## Not verified

**The lane has never run.** It triggers on a tag and no tag has been pushed, so the GHCR pushes, the
multi-arch build under QEMU, and the draft-release step are unexercised until the first release —
which is an owner action (merging the release-please PR).

Full detail: `docs/work/2026-07-30-OME-711-release-aigateway-ui-lane.md`.
