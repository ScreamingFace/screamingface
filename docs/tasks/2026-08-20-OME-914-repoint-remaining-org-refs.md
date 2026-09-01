---
id: OME-914
linear_url: https://linear.app/openmined/issue/OME-914/repoint-the-remaining-openminedscreamingface-references-in-docs-portal
status: in_progress
type: task
priority: 4
labels: [repo, agentic, autonomous, task]
created: 2026-08-20
closed:
---

# Repoint the remaining OpenMined/screamingface references in docs, portal and public-docs

Follow-up to `OME-910`, which deliberately fixed only the references a GitHub org redirect
cannot cover (published PyPI metadata + the Trusted Publishing comments).

The remaining case variants of `github.com/OpenMined/screamingface` across container and Helm
metadata, `CONTRIBUTING.md`,
`.claude/README.md`, `docs/**`, `public-docs/src/**`, `apps/scoreboard/portal/*.html`,
`apps/screamingface-studio/src-tauri/tauri.conf.json`, and the generated notebook pair
(`packages/screamingface/scripts/build_notebooks.py` + `examples/06_draco.ipynb`) all still
resolve via the redirect, so this is hygiene rather than breakage.

The sweep also repoints public-docs' organization-level GitHub buttons to the ScreamingFace
organization and corrects the current work-item diagram's stale `OM-*` examples to the actual
Linear team prefix, `OME-*`.

**Excluded, deliberately:** the four `CHANGELOG.md` files (correct when written — rewriting
falsifies release history); `OpenMined/sf-installer` in the release workflows (a genuinely
different repo); the sibling repos `OpenMined/screamingface-brand` and
`OpenMined/screamingface-benchmarks`; and the `AIDEV-NOTE (OME-910)` blocks in the two PyPI
release workflows, which name the old org as the stale OIDC value on purpose.

Executed together with `OME-945` on one branch — the two are halves of the same sweep.

- Ledger: `docs/work/2026-08-28-OME-914-org-repoint.md`
- Branch: `OME-914-org-repoint`
