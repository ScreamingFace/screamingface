# ScreamingFace

ScreamingFace evaluates Candidate Recipes against reproducible research benchmarks.

## Language

**Evaluation**:
The complete process of evaluating one or more Candidates against one Benchmark.
_Avoid_: Run, execution

**Benchmark**:
One independently identified and revisioned Engine-owned evaluation protocol comprising Cases,
Candidate Invocations, Grading, and Aggregation.
_Avoid_: Test, dataset, family

**Benchmark Variant**:
An alternative Benchmark protocol related to a canonical default Benchmark. A Variant has its
own identity and revision even when it shares Cases or Grading material with the default.
_Avoid_: Method, mode, option

**Candidate**:
A complete Recipe submitted to a Benchmark for evaluation. Model, Fusion, and Pipeline are the
public Candidate kinds.
_Avoid_: Ensemble when referring to all Candidate kinds

**Recipe**:
An immutable, network-free description of Candidate-owned answer production. Model, Fusion,
Pipeline, Corrective Loop, and Self-Corrective are the public Recipe values and may compose
recursively.
_Avoid_: Candidate when the Recipe is nested inside another Recipe

**Corrective Loop**:
A Recipe that drafts an answer, asks the Benchmark for Draft Feedback, and revises until the draft
passes or a round limit is reached. A Self-Corrective loop uses one Model as both drafter and reviser.
_Avoid_: Retry, refinement loop

**Complete Recipe**:
A Recipe that accepts one input and produces one final answer. Every constructible public Model,
Fusion, and Pipeline is complete; Fusion therefore always requires a synthesizer.
_Avoid_: Valid Recipe

**Model**:
One atomic model-backed Recipe.
_Avoid_: Solo Fusion

**Fusion**:
An ordered parallel collection of Recipe members followed by one synthesizer Recipe.
_Avoid_: Pipeline, fan-out when referring to the complete synthesized Candidate

**Pipeline**:
An ordered serial Recipe. Its first stage receives the Pipeline input and every later stage
receives only the immediately preceding stage's final answer.
_Avoid_: Cascade, because Pipeline does not imply conditional routing or early exit

**Candidate Result**:
The outcome of evaluating one Candidate against one Benchmark, including its score, Candidate
URL4, Case Results, failures, usage, and available provenance.
_Avoid_: Score when referring to the complete outcome

**Report**:
The ordered, lossless record of every Candidate Result accounted for by one completed Evaluation.
_Avoid_: Result when referring to the complete multi-Candidate record

**Partial Report**:
The recoverable Candidate Results from an Evaluation that ended before every requested Candidate
could be accounted for.
_Avoid_: Report when completeness matters

**Candidate Invocation**:
One request by a Benchmark for a Candidate answer; a Case may require multiple ordered Candidate Invocations.
_Avoid_: Model call, because a Candidate may be a Fusion

**Case**:
One Benchmark item containing an input, its grading material, and optional metadata.
_Avoid_: Row, sample

**Case Result**:
The completed record of one Case for one Candidate: its exact input and output, Case Grade,
failures, and non-secret Benchmark metadata.
_Avoid_: Artifact, row result

**Case Grade**:
The Benchmark-produced score, metrics, and ordered Checks for one Case. A failed Case may have no
Case Grade.
_Avoid_: Result when referring specifically to grading

**Check**:
One named grading requirement inspected within a Case Grade, together with the Evidence used to
evaluate it. A DRACO rubric criterion and an IFEval instruction constraint are both Checks.
_Avoid_: Criterion when speaking across Benchmarks

**Evidence**:
One ordered, attributable observation used by a Check, including its normalized outcome and exact
raw output when one exists. Evidence may be produced by a Judge or a deterministic verifier.
_Avoid_: Verdict when speaking across Benchmarks

**Rubric**:
The Case-owned criteria used to grade a Candidate answer.
_Avoid_: Reference when the grading material is specifically a rubric

**Load**:
The phase that obtains the Benchmark Cases selected for an Evaluation.

**Run**:
The phase in which a Candidate produces an answer for each loaded Case.
_Avoid_: Generation when naming the public lifecycle stage

**Grading**:
The phase that judges a Candidate answer against its Case Rubric and produces a Case grade.
_Avoid_: Judging

**Judge**:
A Model called within Grading to produce evidence or verdicts; it is not an Evaluation phase.
_Avoid_: Judge stage

**Benchmark-owned Model**:
A Model fixed by the Benchmark protocol, such as DRACO's grading Judge. Changing it changes the
Benchmark revision.
_Avoid_: Candidate Model, user-selected Judge

**Candidate-owned Model**:
A Model submitted as part of a Candidate, including a Fusion member or synthesizer. Changing it
changes the Candidate rather than the Benchmark.
_Avoid_: Benchmark dependency, pinned Judge

**Fusion Synthesizer**:
The Candidate-owned complete Recipe configured for a Fusion's synthesizer role. A Fusion
invocation passes its input and parallel member answers to it to produce one final answer.
It is part of the complete Candidate Recipe and remains distinct from a Benchmark-owned grading
Judge.
_Avoid_: Fusion member, grading Judge

**Cost Estimate**:
A versioned, conservative pre-spend projection of an Evaluation's USD cost. Dynamic control flow
may require a range or maximum rather than one exact amount.
_Avoid_: Quote, guaranteed cost

**Evaluation Budget**:
The optional maximum USD cost authorized for one complete Evaluation, including every Candidate,
Benchmark-owned Model call, and retry. It is enforced by the Engine before model dispatch.
_Avoid_: Per-Candidate budget, token limit

**Unpriced Evaluation**:
An Evaluation containing at least one required model call for which the Engine cannot provide a
versioned USD price. It may execute without an Evaluation Budget, but its Report cannot claim a
complete USD cost.
_Avoid_: Free Evaluation

**Provider Connection**:
An Engine-managed association that authorizes a researcher to use one model provider. It is
distinct from authenticating the researcher to a hosted Engine.
_Avoid_: Engine login, caller authentication

**Caller Authentication**:
The process by which a researcher proves one identity to configured ScreamingFace services.
Different service origins may require separate credentials for that same identity.
_Avoid_: Provider Connection, provider authentication

**Scoreboard**:
The deployed system that accepts and stores public Scores and produces Leaderboards.
_Avoid_: Leaderboard when referring to the system or service

**Leaderboard**:
The ranked view of comparable entries for one Benchmark.
_Avoid_: Scoreboard, board

**Leaderboard Score**:
One persisted Scoreboard record containing a Candidate's measured score, identity, provenance,
verification state, and Candidate URL4.
_Avoid_: Leaderboard Submission

**Score Submission**:
The request to create a Leaderboard Score from one evaluated Candidate Result.
_Avoid_: Leaderboard Score when referring specifically to the write request

**Leaderboard Entry**:
The ranked projection of a Leaderboard Score shown on a Leaderboard.
_Avoid_: Score Submission

**Aggregation**:
The phase that combines Case grades into a Candidate’s Benchmark metrics.
_Avoid_: Reduction

**Draft Feedback**:
A Benchmark's mid-run answer to "is this draft good enough yet?", offered only by Benchmarks whose
feedback cannot leak the answer. Corrective Loops use it; it never produces a Case Grade.
_Avoid_: Check, check surface

**Benchmark Revision**:
The content hash that identifies one exact Benchmark: its Cases, prompts, Grading, and
Benchmark-owned Models. Changing any of them yields a new revision.
_Avoid_: Version

**Grading Material**:
The private part of a Case that the Candidate never sees: the answer key, choices, or Rubric used
in Grading. A Case graded only by a Judge prompt may carry no answer key.
_Avoid_: Target, answer, ground truth

**Case Preparation**:
The image-build step that downloads a Benchmark's Cases at a pinned dataset revision and freezes
them, with their Grading Material, into the Benchmark image.
_Avoid_: Bake, snapshot

**Coverage**:
The share of a Benchmark's Cases that received a valid Case Grade, reported beside the score.
_Avoid_: Completion rate

**Failure Policy**:
A Benchmark's declared rule for how a Case without a valid Case Grade affects its score: counted
as a failure, or excluded and reported through Coverage.
_Avoid_: Error handling

**Inspect**:
The external evaluation framework (`inspect_ai`, with its eval catalogue `inspect_evals`) that
Imported Benchmarks come from. A name that starts with `inspect` means it touches that framework:
the `screamingface_engine_inspect` plugin, `inspect-<key>` Benchmark ids, the `inspect` install
extra, `InspectTaskFacts`, `read_inspect_task`, `inspect_grade_case`. Inspect's own words stay only
where code talks to inspect: an inspect Task is the eval definition we import, an inspect Sample
becomes a Case, and an inspect Scorer becomes an Imported Benchmark's Grading.
_Avoid_: inspect or introspect as a verb in our identifiers (say read or check), so an `inspect`
name always means the framework; Sample when meaning a Case

**Imported Benchmark**:
A Benchmark copied from inspect_evals whose Cases are exactly the questions inspect itself would
run, apart from any Named Deviation.
_Avoid_: Board, inspect board

**Named Deviation**:
A declared, reviewable difference between an Imported Benchmark and its upstream eval, such as
dropped questions or a system message delivered as input text. It is written on the Benchmark
and included in its Benchmark Revision.
_Avoid_: Patch, tweak
