# PRD: migration of tests, goldens and docs (P1)

Spec: [00-overview.md](../00-overview.md). Scope numbers come from the 2026-10-20 survey on base
`e4d44281c`.

## 1. Order

The new names collide with today's names (`sf.Judge`, `sf.Gate`, `sf.Rank`, `sf.Filter`,
`sf.Vote` change their signatures), and two of the byte changes (overview §4, items 3 and 4) touch
about 30 test files and the goldens. So:

- Units 2–6 build the new surface in the private package `screamingface._surface`. Only new test
  files import it, and they compare its url4 with today's surface in the same process. No existing
  test changes. Snapshots: unit 1 changes the two v1 schema snapshots and the public surface
  snapshot (`CombineEvidence.__init__` gets `narrow`, `CombineNarrow` is new); units 2–6 change no
  snapshot; unit 7 regenerates the public surface snapshot.
- Unit 7 is **the swap**, in one commit group: export `_surface` as `sf.*`; rename today's classes
  to their `Node` names (O7); switch the judge template to `@2` and the field picks to `by_signal`;
  reword the messages (O13); move the tests and goldens; delete the old names and the tests that
  only check a removed parameter. The owner approves all pinned edits of unit 7 in one list.
- Unit 8 moves the docs.

## 2. Tests (unit 7)

- About 125 of the ~400 SDK test files build recipes with the old names (survey). Engine,
  scoreboard and aigateway tests do not import SDK recipe classes. But these Engine tests hold the
  `@1` scores template text and move at the swap:
  `ET/test_sdk_judge_order_contracts.py:84-86` (asserts `order=min` and "A lower number"),
  `ET/test_sdk_candidate_contracts.py:76`, `ET/test_sdk_filter_judge_contract.py:81`,
  `ET/test_sdk_quorum_contracts.py:138`.
- **MG-1** A codemod script (`packages/screamingface/scripts/migrate_surface.py`, kept in the repo
  for the review and deleted at the end of unit 7) rewrites the mechanical forms:
  - `sf.Fusion(m, synthesizer=R)` → `sf.Fanout(m) >> R'`, and the `Pipeline([sf.Fusion(...),
    W])` selection form → `... >> sf.Synthesize(W)`;
  - `extract=` → `over=` on `Vote`, `Median`, `Mean`, `Filter`;
  - `Pick(by_signal=s, order=o)` → `ArgMax/ArgMin(s)`; `Pick(f, order=o)` → `ArgMax/ArgMin
    ("field:f")`; `Pick(f, equals=v)` → `First(where=sf.field(f) == v)`;
  - `Judge(..., returns="scores")` as a synthesizer or a `by=` / `judge=` → a `sf.Judge` step plus
    its reader; `Judge(..., returns="label")` → `sf.JudgePick`;
  - `Rank(by_field=f)` → `Rank(by="field:f")`; `Rank(by_signal=s)` → `Rank(by=s)`;
  - the old `sf.Gate(observe, cmp, threshold, ...)` and `Vote(gate=)` → the new `sf.Gate`.
- **MG-2** The cases the codemod cannot do are moved by hand: refusal tests of removed parameters
  are deleted (the list goes to the owner); tests of the field pick on non-number values and of the
  `@1` scores template are rewritten for D2 and D3.
- **MG-3** The append-only gate (`.claude/scripts/run_gates.py:382-500`) treats every edit inside a
  test body and every deleted file as a violation. The owner approves the full list once, at the end
  of unit 7. After that approval the orchestrator (the main session, not a subagent) writes the
  approvals into `.claude/test-change-approvals/OME-1653.json`, with the byte-exact blob ids. No
  subagent writes that directory.

## 3. Goldens and fixtures

- `ST/data/fusion_docs/*.url4` (42 files, `ST/test_fusion_doc_goldens.py`) and
  `ST/data/*.url4`: every file whose recipe has no scoring judge and no field pick keeps its bytes
  (parity). The others are compiled again and replaced in unit 7 (pinned files, owner approval).
- Engine fixtures with the `@1` scores template or a field pick
  (`ET/data/combine_contract/judge_vote_candidate.url4`, `judge_order_min_candidate.url4`,
  `filter_judge_candidate.url4`, `quorum_judge_vote_candidate.url4`, `recipe_s10.url4`,
  `recipe_s11_max.url4`, `gate_judge_vote_candidate.url4`, `recipe_s5.url4`,
  `recipe_s5_pick_output.url4`, `recipe_s7.url4`) are compiled again by the SDK and replaced
  (pinned files, owner approval). The unit spec checks the full list with a scan for
  `judge-template@1 returns=scores`, `by_field` and `scores{source:values}` in the fixtures.
- `ST/public_surface_snapshot.json` is regenerated in unit 1 (`CombineNarrow`) and in unit 7 (the
  swap).

## 4. Docs (unit 8)

- `packages/screamingface/README.md`: every recipe section (about 190 recipe lines; sections from
  `:319` to `:1248`) moves to the new surface. The "Combine recipes" section
  (`ST/test_combine_recipes_readme.py`) uses the 13 notebook cases. A new section "How a recipe
  reads" explains map → score → narrow → reduce/write, the chain rules, and the two `Synthesize`
  input forms.
- `packages/screamingface/CHANGELOG.md`: one "Breaking changes" section lists every deleted name and
  parameter, its replacement, and the four byte changes (overview §4).
- Notebooks: the 10 example notebooks in `packages/screamingface/examples/` that build recipes are
  moved and checked by `packages/screamingface/scripts/check_notebooks.py`. The Product Owner
  notebook becomes a new example (`examples/18_map_select_reduce.ipynb`), with the "today" comments
  removed.
- Public docs: the 8 files in `public-docs/src/pages/sf-client/` that use `sf.Fusion` (and any
  other page with a recipe) are moved.
- `docs/` spec, plan and task files of earlier parts are history and stay as they are.

## 5. Acceptance

- After unit 8, `rg "sf\.(Fusion|Pick|Reduce)\b|synthesizer=|\.then\("` over
  `packages/screamingface/tests`, `packages/screamingface/README.md`,
  `packages/screamingface/examples` and `public-docs` finds nothing outside the CHANGELOG. (`src/`
  is out of the check: the internal `FusionNode` keeps its `synthesizer` field, O7.)
- All gates green on the tip, with the append-only check passing on the owner-approved manifest.
