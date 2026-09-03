---
id: OME-910
linear_url: https://linear.app/openmined/issue/OME-910/repoint-the-git-remote-and-release-critical-org-references-after-the
status: In Review
type: Task
priority: High
labels: [repo, agentic, autonomous, task]
created: 2026-08-20
closed:
---

# Repoint the git remote and release-critical org references

The repo was transferred from the `OpenMined` org to `ScreamingFace`. GitHub keeps a redirect,
so most references still resolve — but PyPI Trusted Publishing matches the OIDC `repository`
claim as an exact string and does not follow it, so the `url4` and `screamingface` release
lanes fail at the publish step while verify and build stay green.

Scope is deliberately narrow: `.git/config` (untracked), the published PyPI project URLs in
`packages/url4/pyproject.toml`, and the Trusted Publishing setup comments in the two release
workflows. Docs, portal and public-docs references are `OME-914`; the CHANGELOGs are left
alone because their links were correct when written.

Repointing the PyPI publisher entries is an owner action in the PyPI console and remains open.

Canonical artifacts:

- Ledger: `docs/work/2026-08-20-OME-910-repoint-org-refs.md`
- PR: #663
