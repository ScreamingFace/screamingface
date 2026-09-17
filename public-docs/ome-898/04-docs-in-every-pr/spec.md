---
title: "Documentation as part of every PR: the mechanism"
ticket: OME-898 (child 4, not yet filed)
status: draft
date: 2026-09-16
---

# Documentation as part of every PR

The ticket: "whenever a PR is made, documentation is also part of it (automatically
generated)." The mechanism below is this session's reading of that line, not a quote from
Linear.

`public-docs/` is a folder in this repo, not a separate one. `deploy-public-docs.yml` builds
it and rsyncs the result to the docs VM on every push to `main`. A gate can require a
`public-docs/` change in the same PR as a code change.

`public-docs/` has no test lane today. It was removed deliberately in `78331eb8` (`OME-405`,
2026-07-22) because nothing was using it. A minimal, purpose-built test is fine to add here.
`check_notebooks.py` already does the same kind of check elsewhere in this repo, a marker
list asserting the notebooks demonstrate specific public API surface, so this is not a new
technique for the codebase.

This needs its own workflow file, not a job added to `public-docs-tests.yml`. That workflow
triggers only on `paths: public-docs/**`, so a PR that changes only the Python side, with no
`public-docs/` touch at all, would never run it, meaning the exact failure this check exists
to catch would never be checked. `docs-sync-check.yml` triggers on either side of the pair
instead: `packages/screamingface/src/screamingface/**` or
`public-docs/src/pages/sf-client/api/**`.

## The mechanism has three layers

Each catches what the one before it misses.

**1. In-loop drafting, on every change.** The `writing-docs` skill drafts or updates the
relevant `public-docs/` page while the change is being made, before a PR exists. Needs child
01 published somewhere installable, and a routing rule in `.claude/` (child 03) that invokes
it on a public-surface change. No CI work. Nothing enforces it on its own; a step with no
PR-time check is a step people skip under deadline, which is what layer 2 is for.

**2. A minimal CI check, at PR time.** If the PR touches public surface, it must also touch
`public-docs/**`. Checks presence, not quality. A PR without the change fails and names what
triggered it. Live at `packages/screamingface/scripts/check_docs_sync.py`, tested against
real history; see below.

*Public surface, defined:* a name in `packages/screamingface/src/screamingface/__init__.py`'s
`__all__` (58 entries) is public surface, and so is a change to the file it is imported from.
That file is derived by parsing `__init__.py`'s own `from X import Y` statements, not by a
directory-naming convention. Two of its real sources, `_default_client.py` and
`_ui/connections.py`, sit under an underscore-prefixed path despite backing six genuinely
public names (`configure`, `close`, `connect`, `disconnect`, `evaluate`, `ConnectionPanel`);
a convention-based check would silently miss all six.

A name counts as changed two ways, checked independently: it is new in `__all__` on this
branch (so promoting an existing, otherwise-untouched function to public by editing only
`__init__.py`'s import and export lines still counts), or its backing file changed. A name
*removed* from `__all__` also requires its page to change, since the page needs updating or
removing to match; it is not exempt just because nothing new needs writing.

*The page-to-code map: `symbol-page-map.md`, not the nav file directly.*
`sfClientReferenceNavigation` groups the 15 API reference pages by class family, not by exact
`__all__` name; its "Candidates" group alone spans five separate exports. `symbol-page-map.md`
makes the mapping explicit, one entry per name, and is what `check_docs_sync.py` reads. 55 of
58 names have a page; `__version__`, `OperationAccounting`, and `OperationCache` do not, and
are a named, accepted gap rather than a check failure waiting to happen.

*Known limitation: file granularity, not symbol granularity.* The check knows a *file*
changed, not which class or function inside it did. Tested against a real commit
(`dd51ea81`, "retain operation accounting"): its actual change was scoped to two names, but
because ten other public names are imported from the same file (`report.py`), the check
would have required touching three pages, two of which document nothing that commit
actually changed. This is the accepted cost of "presence, not quality" at this scope; a
per-symbol check would need to diff the AST inside each file, not just its path.

*Scope for this version:* `public-docs/src/pages/sf-client/api/**` only. Overview, the
tutorials, and the guides are not required to change, since a new class does not
automatically mean a guide needs rewriting, and no equivalent map exists for those pages
yet. A `public-docs/**` change with no `__all__` or backing-file change never fails the
check.

**3. A follow-up PR, for anything that still merges without one.** An admin override, a
hotfix, an accepted exception. Opens automatically against `public-docs/` afterward, using
child 01's skill again to draft the content, run after merge instead of before. If layer 2
is a hard gate, this rarely fires.

Needs a bot identity with write access. Docs are one merge behind by construction; on a site
that deploys straight from `main`, that is a real window where the deployed docs are wrong.
