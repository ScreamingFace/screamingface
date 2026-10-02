# PRD: Fusion as a named recipe on the blocks

**Source:** PRD "Named recipes replacing kinds", criterion A4 · ans:Q6 · **Priority:** P1 (the
leaderboard risk "Fusion migration changes outputs")
**Lifecycle:** existing (characterize + delta)
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [block-api](block-api.md).

## 1. Summary and user story

As a researcher with leaderboard entries made with `sf.Fusion(members, synthesizer=sf.Model(…))`,
I want Fusion to be one recipe built from the blocks, so that it is one join among many, while my
existing entries reproduce byte for byte.

## 2. Background and constraints

- "`Fusion(members, synthesizer)` becomes `Fan-out(members)` → `Reduce.compute(concat)` →
  `Model(synthesizer)`. … the output must be byte-identical on the regression set." `[stated prompt]`
- "sf.Fusion becomes a named recipe: Fan-out → Reduce.compute(context) → Model. The 'context' op
  lowers at compile time to today's url4 struct, so url4 bytes and outputs stay identical. Golden
  url4 files and a replay prove it." `[stated ans:Q6]`
- **Deviation from the PRD wording, for product sign-off:** the PRD names `concat`. A text concat
  can never be byte-identical, because today's synthesizer gets a url4 struct `{input, outputs}`, not
  joined text `[existing S/_evaluation/candidate.py:621]`. So the recipe uses a structured compute op
  named `context` `[stated ans:Q6]`. `sf.Concat` stays a separate text join.

### 2.1 Current behavior

- `_fusion` compiles a Fusion `[existing S/_evaluation/candidate.py:310]`. A Model synthesizer
  (`_model_synthesizer`) gets the struct context from `_fusion_context`, the synthesizer prompt or
  `DEFAULT_SYNTHESIS_PROMPT`, binding `synthesis_N`, kind `synthesis`, and a fusion topology in the
  url4 `[existing S/_evaluation/candidate.py:347]` `[existing S/_evaluation/candidate.py:621]`.
- A Pipeline (`_pipeline`) compiles a Model stage as `model_N` with `DEFAULT_ANSWER_PROMPT` and a
  pipeline topology; stage N gets stage N−1's reference `[existing S/_evaluation/candidate.py:511]`.
- A recipe synthesizer marks only its first stage `synthesis=True`
  `[existing ST/data/fusion_recipe_synthesizer.url4:1]`.
- A Reducer synthesizer triggers the `/v1/operators` fetch and the member cap
  `[existing S/_evaluation/runner.py:27]` `[existing S/fusion.py:59]`; a Model synthesizer has
  neither.
- Model-synthesizer bytes are pinned `[existing ST/test_reducer_characterization.py:47]`.

**Delta.** One **pure recipe rewrite**, run before compile `[proposed]`:

```
Pipeline([Fusion(m, Reduce("context", mode="compute")), S, *rest])
    → Pipeline([Fusion(m, S), *rest])      when rest is not empty
    → Fusion(m, S)                          when rest is empty and the Pipeline has no name
```

`S` is a Model or a Recipe (the synthesizer). A named Pipeline with an empty `rest` keeps its name:
`Pipeline([Fusion(m, S)], name=…)` (not byte-identical to a bare Fusion; it was not before either).
`Reduce("context")` is excluded from the operator fetch and from the reducer member cap. Then:

1. `sf.Fusion(members, synthesizer=sf.Model(p))` **is** the named recipe Fan-out →
   `Reduce.compute(context)` → Model; its docs say so. The public constructor does not change.
2. The block form `sf.Pipeline([sf.Fusion(members, synthesizer=sf.Reduce("context",
   mode="compute")), sf.Model(p)])` rewrites to it, so the url4 is byte-identical.
3. `Reduce("context")` anywhere else (last stage, not followed by a Model or Recipe, a `select`
   mode) → `ValueError` before spend.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **FR-1** Given every golden Fusion url4 in the repo, when compiled after the change, then each is
  byte-identical to its golden file. `[stated ans:Q6]`
- **FR-2** Given the block form and the Fusion form, then the two url4 strings are byte-identical.
  `[stated ans:Q6]`
- **FR-3** Given the Fusion regression replay lane (2 Fusion recipes × 5 GSM8K Cases, recorded
  once), when replayed on the new code, then every Case output and every synthesizer request body is
  byte-identical to the recording. `[stated ans:Q6]`

### 3.2 Error paths

- **FR-E1** Given `synthesizer=sf.Reduce("context")` as the last stage, then `ValueError` before any
  spend. `[proposed]`
- **FR-E2** Given `sf.Reduce("context", mode="select")`, then `ValueError`. `[implied]`

### 3.3 Derived scenarios (risk-ordered)

- **FR-D1** The regression set `[proposed]` (H×H): (a) every `*.url4` golden that contains a Fusion
  (`ST/data/`, `ST/e2e/`, `ET/data/combine_contract/`); (b) every Fusion example in
  `packages/screamingface/README.md` and `public-docs/`, compiled with today's code and committed as
  new goldens **before** the change; (c) the replay lane FR-3.
- **FR-D2** Recipe synthesizer (H×M): the rewrite with `S` a Pipeline keeps `synthesis=True` on its
  first stage only.
- **FR-D3** Named Pipeline (M×M): `Pipeline([Fusion(m, Reduce("context")), S], name="x")` →
  `Pipeline([Fusion(m, S)], name="x")`, golden.
- **FR-D4** Nested Fusion (M×M): a Fusion as a member of a Fusion keeps its bindings and numbering.
- **FR-D5** Reducer synthesizer `[existing S/fusion.py:59]` (M×M): `sf.Fusion(…, synthesizer=sf.Vote(…))`
  is unchanged.
- **FR-D6** No operator fetch (M×M): compiling the block form does not call `/v1/operators`.
- **FR-D7** Report roles `[existing ST/test_reducer_characterization.py:55]` (M×M): the synthesizer
  operation id stays `op_synthesis_N`.
- **FR-D8** `to_python()` (M×L): a recovered Fusion prints `sf.Fusion(…)`.
- **FR-D9** Recording `[proposed]` (L×M): the replay lane is a paid OpenRouter run under $0.10,
  recorded by the user with `record`, then `bless`, together with EV-12 (U5). It skips until then.

## 4. Non-functional requirements

- Zero change to compiled bytes for existing recipes; no engine change `[stated ans:Q6]`.

## 5. Out of scope

- A text-concat Fusion (`sf.Pipeline([sf.Fusion(…, sf.Concat()), sf.Model(…)])` already works and is
  not byte-identical by design); CorrectiveLoop as a named recipe (needs Branch, E4c).

## 6. Open questions

None. (The `concat` → `context` deviation in §2 needs Irina's sign-off.)

## 7. TDD plan

Characterize first: freeze the regression set as goldens before any refactor.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: new url4 goldens for every README / public-docs Fusion example (new files, pass today) | unit | FR-D1 | — | generate with today's compiler |
| 2 | CHAR: existing Fusion goldens and `test_reducer_characterization.py` stay green | unit | FR-1 | — | passes today |
| 3 | `block_form_rewrites_to_fusion_and_compiles_byte_identical` | unit | FR-2 | H×H | pure rewrite before compile |
| 4 | `rewrite_keeps_rest_of_pipeline` | unit | delta | H×M | — |
| 5 | `recipe_synthesizer_keeps_first_stage_synthesis_flag` | unit | FR-D2 | H×M | — |
| 6 | `named_pipeline_keeps_its_name_after_rewrite` | unit (golden) | FR-D3 | M×M | — |
| 7 | `nested_fusion_keeps_bindings` | unit (golden) | FR-D4 | M×M | — |
| 8 | `reducer_synthesizer_fusion_is_unchanged` | unit | FR-D5 | M×M | existing goldens |
| 9 | `context_block_does_not_fetch_operators` | unit (forbidden transport) | FR-D6 | M×M | exclude from `recipes_need_operators` |
| 10 | `context_misuse_raises_before_spend` | unit | FR-E1, FR-E2 | M×M | — |
| 11 | `synthesizer_operation_ids_unchanged` | unit | FR-D7 | M×M | — |
| 12 | `recovered_fusion_prints_as_fusion` | unit | FR-D8 | M×L | — |
| 13 | `fusion_regression_replay_is_byte_identical` (skips until recorded) | e2e (replay lane) | FR-3 | H×M | reuse `fixtures/reducer_lane.py` record/bless |
| — | FR-D9 is a manual step; row 13 skips until then | — | — | — | — |
