---
id: OME-748
linear_url: https://linear.app/openmined/issue/OME-748/unblock-the-public-docs-major-group-hold-typescript-at-6
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-748 — unblock the public-docs major group, hold TypeScript at 6

Sub-issue of `OME-733`. Clears #497, the last open Dependabot PR.

## It failed twice, differently

**First** — `npm ci` ERESOLVE: `pinia` 3→4 against `vue-router@5.1.0`'s `peerOptional pinia@^3.0.4`.
Fixed not by us but by **#496** (the *minor* group), which carried `vue-router` to 5.2.0, accepting
`pinia ^3.0.4 || ^4.0.2`. That is `OME-737`'s `-minor`/`-major` split paying off directly — under
the old single-group config, the fix would have been trapped inside the thing it was fixing.

**Second** — `eslint` died: `typescript-eslint does not support TS 7.0`. The group's
`typescript ~6.0.0 → ~7.0.2` bump breaks the config loader inside
`@vue/eslint-config-typescript`.

## Held, and at the right bound

`ignore: typescript >=7` on `/public-docs` — **not `>=6`** as on `aigateway-ui`. The two trees are
capped by different packages for different reasons (`openapi-typescript` peer `^5.x` there;
`typescript-eslint` here), and `public-docs` already sits on ~6.0.0. Copying the sibling entry
would have frozen it a whole major below where it was.

## The other four majors were not innocent

The plan assumed a green eslint would clear them. It didn't — `npm run build` then failed on a
type error lint never reaches:

```
NotebookViewer.vue(50,27): error TS2339: Property 'match' does not exist on type 'string | number'
```

Cause is a **types ownership change**, not a breaking API: markdown-it 15 ships its own typings
(14 had none, so DefinitelyTyped supplied them), and the bundled declaration correctly widens
`TokenAttribute` to `[name: string, value: string | number]`.

Fixed two ways, each defensible alone: dropped the now-redundant — and stale, and *contradicting* —
`@types/markdown-it`, and narrowed the single call site with `typeof href === 'string'` rather than
a cast that would assert what the type deliberately stopped guaranteeing.

## Landed

`lucide-vue-next` 0.577→1.0.0 · `markdown-it` 14→15 · `pinia` 3→4 · `@types/node` 24→26.

## Verified

`npm ci` · `npx oxlint .` · `npx eslint .` · `npm run build` — all exit 0. Config revalidated:
11 entries, every group declares `applies-to`.

Caught entirely by the lane added in `OME-738` (#484). Before it existed, #497 would have merged
into `public-docs` with nothing checking it.

Ledger: `docs/work/2026-08-04-OME-748-public-docs-ts-hold.md`
