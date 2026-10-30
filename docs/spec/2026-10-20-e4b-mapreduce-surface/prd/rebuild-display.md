# PRD: rebuild and display (P1)

Spec: [00-overview.md](../00-overview.md).

## 1. url4 → chain (`S/url4.py`)

`Url4.to_python()` (`S/url4.py:92-137`) and `_recipe_from_topology` (`:648-700`) return values of
the new surface. The url4 decode (`S/_evaluation/topology.py`) does not change. In unit 6 the new
rebuild is a private function (`screamingface._surface.rebuild`) that new tests call. It returns
the values and a code string that names the steps through a module alias `sf`; unit 6 tests `exec`
that string in the namespace `{"sf": screamingface._surface}`. At the swap `to_python()` uses it
and the alias is the real `screamingface`.

| Topology | Rebuilt value |
|---|---|
| `model` | `sf.Model(...)` (today) |
| `pipeline` | the stages joined with `>>`; a named Pipeline as `sf.Pipeline([...], name=...)` |
| `fusion` with a reducer synthesizer | `sf.Fanout(members, signals=..., quorum=..., name=...) >> <steps>` |
| `fusion` with a Model or recipe synthesizer | `sf.Fanout(members, ...) >> sf.Synthesize(model, prompt=...)` |
| `pipeline` whose stage `i` is a fusion with a selection and stage `i+1` is a Model or recipe | one block: `sf.Fanout(...) >> <narrow> >> sf.Synthesize(stage i+1)` |
| `self_corrective`, `corrective_loop` | today |

`<steps>` is the inverse of the lowering table ([lowering.md](lowering.md) §2.2):

- A scoring judge splits into `sf.Judge(model, rubric=..., params=...)` and its reader:
  `Rank(by="score:judge")`, `Filter(where=sf.signal("score:judge") ...)`, `ArgMax`/`ArgMin
  ("score:judge")` (from the select `max_score` / `best_holder{order:min}`), or
  `Vote(weights="score:judge")`.
- A spec `narrow` list rebuilds as the narrow steps, in order, before the main step.
- `Pick(by_signal=..., order=)` → `ArgMax`/`ArgMin`. `Pick(field, equals=)` → `First(where=sf.field
  (...) == v)`. A label judge → `JudgePick`. A vote `gate` → `sf.Gate(when=..., then=sf.Vote(...),
  otherwise=..., abstain_if=...)`.
- Signal keys rebuild as strings in `by=` and `weights=` (`by="field:confidence"`), and as
  `sf.signal(...)` in `where=` and `when=`.
- **Erratum E2:** an operator id rebuilds as its rule name through `blocks._REVERSE_RULES`
  (`json_object@1` → `over="json@1"`), because EX-1 accepts rule names only.
- Extract and normalize ids rebuild with their pinned version, as today (`over="last_line@1"`,
  `normalize="text@1"`), which `over=` and `normalize=` accept (surface §9, EX-1). A `ReduceNode`
  spec rebuilds as the step with `over=sf.Extract(...)`.
- An optional Fusion (a quorum panel member) rebuilds as `sf.Pipeline([sf.Fanout(...), <steps>],
  optional=True)`.
- **RB-1** The recompile check stays (`_require_recompiles`, `S/url4.py:447`): the rebuilt chain
  must compile to the same url4 bytes. A hand-edited url4 that the new surface cannot express is
  refused with today's "cannot rebuild" message.
- **RB-2** A url4 with `judge-template@1 returns=scores` is refused ("unsupported judge call", A0).
- The `_REDUCER_CLASSES` and `_BLOCK_FORMS` tables (`S/reducer.py:191`, `S/blocks.py:207`) lose the
  block form (O1). The internal classes keep `_from_spec`.

Erratum U5d/U6a: until the swap, `Url4.to_python()` refuses a url4 with `narrow`. The swap (unit 7, step 7e) switches `to_python()` to the new rebuild and lifts it.

## 2. `repr`

- A chain `repr` uses `>>`: `Fanout(['a', 'b']) >> Judge('j', rubric='...') >> ArgMax('score:judge')`.
  A named or optional Pipeline uses the explicit form: `Pipeline([...], name='x')`.
- Each step `repr` shows only the arguments that differ from the default (today's rule).
- `to_python()` gives code with the `sf.` prefix that runs and compiles to the same url4 (RB-1).

## 3. Cards (`S/_ui/cards.py`)

**Erratum E5:** today `Fusion([chain, ...])._repr_html_()` raises `TypeError` (`cards.py:433` →
`_recipe_kind`), because a closed chain can now be a member. The new card builders handle a chain
member.

| Today | New |
|---|---|
| `fusion_card_html` kicker `fusion` (`:72`), sections `members`, `synthesis` | `block_card_html`: kicker `fanout`; sections `members`, `signals`, `steps` (judge, narrow steps, terminal, each with its category) |
| `pipeline_card_html` kicker `pipeline`, section `stages` | kicker `chain`; section `stages`; a block stage shows as `fanout block` |
| `_synthesizer_fields` label `synthesizer` (`:445-466`) | removed; the terminal shows in `steps` with label `reduce` or `write` |

`model_card_html` does not change.

## 4. Report and Combine section

- The report kind values (`report.py:782-794`: `model`, `fusion`, `pipeline`, ...) stay the same on
  the wire (O7). The display maps the kind `fusion` to the word `fanout`
  (`S/_ui/report_view.py:567`).
- The report validation messages that name the old classes (`report.py:871-895`) say "fanout
  block" in the place of "Fusion".
- The part 4 Combine section (`S/_ui/combine_view.py`):
  - one chip per narrow step: `filter · kept 2 of 3`, `rank top 2 · max` (`top 2 · min` for
    `order="min"`);
  - the member cell of a left-out member: `left out at step {i}: not selected` or `left out at step
    {i}: no signal`;
  - the run summary counts the members left out by the narrow steps, per step.
- The Gate chip and the run-summary gate lines of part 5 keep their text. The docstring of
  `sf.Gate` and the README say that the `otherwise` call runs on every Case (D5).

## 5. Acceptance

- Unit 6: every parity row with no scoring judge round-trips: compile → url4 →
  `_surface.rebuild` → `exec` (namespace above) → compile gives the same bytes.
- Unit 7 (after the `@2` switch): the judge rows round-trip through `to_python()`, and RB-2 (`@1`
  scores refused) holds.
- The cards and the Combine section have golden HTML tests for a block with a judge, a narrow step
  and a reducer.
