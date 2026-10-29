---
id: OME-1784
linear_url: https://linear.app/openmined/issue/OME-1784/retire-the-quarantined-marker-state-and-the-x-profile-compatibility
status: in_review
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
---

# Retire the quarantined marker state and the X-Profile compatibility path (L4a)

The pair marker has two states, `none` and `migrated`; a stored `quarantined` is a data error.
`SelectorPolicy`, named `X-Profile` selection and `SelectorUnknown` are gone: any present
`X-Profile` value is refused on every route. D18 row 4 and the
`AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` warning are gone, and `migration_note` is neither read nor
written (L4c drops the column). Stacked on OME-1778; merges after it and after the read-only
count of `quarantined` and non-null `migration_note` rows is 0 in dev, stage and prod. Spec
`docs/spec/2026-10-29-ome-1138-closeout.md` §4.2, plan `docs/plan/2026-10-29-ome-1138-closeout.md`
§3 L4a, ledger `docs/work/2026-10-29-retire-quarantine-and-x-profile.md`.

- 2026-10-29: filed, implemented, PR opened.
