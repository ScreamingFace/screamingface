# Plan — capture a Task-replay Case from the eval's own solvers

- Spec: `docs/spec/2026-09-30-OME-1273-task-replay-import.md` (R2, R9, amended 2026-10-02).
- Ticket: [OME-1273](https://linear.app/openmined/issue/OME-1273/import-the-single-turn-benchmarks-the-importer-still-refuses), plan step 6.
- Ledger: `docs/work/2026-10-02-ome-1273-capture-rendering.md`.
- Component: `apps/screamingface-engine` (`screamingface_engine_inspect`).
- Base: `main`, which has zero Task-replay Benchmarks, so nothing re-seals here. The import
  side (PR #1191) rebases onto this and drops its template facts; the Benchmark PRs re-import.

## TLDR

A **Task-replay Benchmark** fetches its Cases by calling the eval's own task function in a
clean child process. Until now the child read the Task's Samples and rendered each one with
**our writer**, which imitated the two inspect solvers it knew from three template fields on
the declaration. The rule: **the Case must be byte for byte what inspect sends the model.**
sevenllm chains two solvers; the writer rendered the second only, and both replays agreed
because both ran the same writer. The change: the child now runs the Task's real `setup` and
`solver` on each Sample with a **stand-in `generate`** that records the messages and answers
nothing. The transcript is the Case. The declaration loses its template fields. Nothing paid
or model-shaped runs: `eval()`, models, scorers, Judges, sandboxes and tools never do, and a
chain that needs them is refused by name. No existing Benchmark changes.

## Files

| File | Change |
| -- | -- |
| `src/screamingface_engine_inspect/capture.py` | NEW. `captured_case_records(task, spec)`: sandbox refusal, per-Sample `TaskState` built as inspect builds it, `chain(setup, solver)` run with the stand-in, the message-to-text rule, the refusals. |
| `src/screamingface_engine_inspect/prepare.py` | `TaskReplayCasesSpec` drops `prompt_template`, `choice_template`, `system_message`. `case_records` takes `CasesSpec` only. NEW `prepared_case(sample, case_id, input_text, spec)` holds the record shape both paths share. |
| `src/screamingface_engine_inspect/task_replay.py` | the child calls `captured_case_records`; docstring says what runs. |
| `tests/unit/inspect/test_capture.py` | NEW, see Tests. |
| `docs/spec/…OME-1273…` | R2, R6, R9, the Runs table, two Known limitations. |

## The stand-in

```python
class _StandIn:                      # one per Sample
    async def generate(self, state, **_):
        if self.messages is not None: raise CaptureError("case N: the solver called generate twice")
        if state.tools:               raise CaptureError("case N: the solver gave the model K tool(s)")
        self.messages = list(state.messages)                     # the Case
        self.choices = [c.value for c in state.choices] or None  # as shown
        state.output = ModelOutput.from_content("none/stand-in", "")
        state.messages.append(state.output.message)
        return state
```

The empty reply lets post-answer solver work (answer parsing) run as it would on a silent
model, so a chain that asks a second time is seen, not hidden by stopping at the first.

## Message-to-text rule

Accepted: zero or more leading system messages, then exactly one user message, all text.
Joined with one blank line (the existing named deviation: the Candidate has no system role).
Anything else is refused with the Case number and the roles seen.

## Tests (write first)

- the sevenllm shape (`prompt_template` → `multiple_choice`) equals a hand-written literal of
  inspect's SINGLE_ANSWER render; choices and target in the Grading Material
- system message leads the text; template reads Sample metadata; `setup` runs first; a Task
  with no solver serves the raw input; kept metadata rides the record
- refusals: never asks, asks twice, tools, sandbox, multi-turn, reordered choices, raises
- the image-side child (`replayed_cases`) renders the chained shape

## Out

- Few-shot or multi-turn Cases, image content: refused, grown when a package needs them.
- `multiple_choice`'s deprecated shuffle: refused; the task arg that disables it is the fix.
- The Hugging Face path keeps its imitation writer until OME-1460 folds it.
