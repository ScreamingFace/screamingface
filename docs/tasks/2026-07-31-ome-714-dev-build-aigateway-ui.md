---
id: OME-714
linear_url: https://linear.app/openmined/issue/OME-714/add-dev-build-aigateway-uiyml-so-the-console-reaches-the-dev-clusters
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-07-31
closed:
---

# OME-714 — `dev-build-aigateway-ui.yml`: get the console into the dev cluster's registry

`OME-710` produced the console's Dockerfile and chart; `OME-711` publishes them on a release tag.
Neither puts an image where the **dev cluster** can reach it.

#452 (`18cf7379`) wired the three existing dev lanes to push into ACR alongside GHCR, because the
dev cluster pulls from there. That made `aigateway-ui` the only containerised app in the repo with
no dev-build lane.

The gap is not cosmetic: the console is a BFF whose only job is calling `/v1/admin`, so the two
deploy as a **pair**. On a merge to main the gateway would get a fresh `main-<sha>` image and the
console none — meaning a dev cluster could only run a console from a tagged release against a
gateway from `main`. They drift by construction, and the admin API is exactly where that bites,
since **no release tag contains it yet**.

## Decisions

- **Path filter matches the siblings' bare `apps/<name>/**`,** including `charts/`. A chart-only
  edit rebuilds an unchanged image — harmless (the tag is keyed on the commit) and preferable to a
  filter that differs from the other three for reasons nobody will remember.
- **Release lane stays GHCR-only.** #452 touched only dev lanes; aigateway's releases are GHCR-only
  too. Pushing released images to ACR is a platform decision about all four apps.

## Verified

Shape compared programmatically against the three siblings — identical permissions, job and step
count. `verify_chart_wiring.py` grew 23 → 26, all three new checks mutation-tested: renaming the dev
image, colliding the cache scope, and adding a floating `:latest` are each caught. The cache-scope
check spans all four lanes, so it protects the pre-existing ones too.

## Not verified

**The lane has never run** — it triggers on a merge to `main`, and this is on a branch. The GHCR
push, the ACR push and the OIDC federation are unexercised until #451 merges.

Full detail: `docs/work/2026-07-31-OME-714-dev-build-aigateway-ui.md`.
