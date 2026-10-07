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

**Benchmark key**:
A Benchmark's short machine name, such as `gsm8k`: one per Benchmark, used to look up its
declarations and to build its Benchmark id (`inspect-gsm8k`). It is not the title people read
(`GSM8K`), and not the inspect eval behind it: one eval can become several Benchmarks, each with
its own key (`mgsm_en`).
_Avoid_: Benchmark name, eval name, key alone

**Grading Material**:
The private part of a Case that the Candidate never sees: the answer key, choices, or Rubric used
in Grading. A Case graded only by a Judge prompt, or by an eval's own scorer that reads only the
reply, may carry no answer key.
_Avoid_: Target, answer, ground truth

**Answer key**:
The correct answers a Benchmark grades against, stored per Case in its Grading Material: e.g.
`42` for "What is 6 times 7?". A Benchmark that compares the answer to it needs no Judge; some
give it to a Judge instead, and some have none: they are graded only by a Judge prompt, or by the
eval's own scorer from the reply alone (cyse4_mitre_frr's refusal check).
_Avoid_: Key alone ("published key", "private key" read as a Benchmark key or a credential),
target, ground truth

**Case Preparation**:
The image-build step that downloads a Benchmark's Cases from its pinned Case Sources and freezes
them, with their Grading Material, into the Benchmark image.
_Avoid_: Bake, snapshot

**Case Source**:
One pinned upstream place Case Preparation fetches Cases from: a Hugging Face dataset revision, a
URL with a commit or sha256, or a file inside the Inspect package.
_Avoid_: Dataset, data file

**Case Digest**:
The sha256 of an Imported Benchmark's prepared Cases, fixed at import and checked at every Case
Preparation. A different digest means different Cases, so none are served.
_Avoid_: Snapshot hash, checksum

**Bundle Provenance**:
The label Case Preparation writes beside a Benchmark's prepared Cases (`provenance.json`): the Case
Sources it read with their pins, any seed it forced, how many Samples it loaded, excluded and
kept, the Inspect versions, and how long it took. It never holds a Case's text. It says how one
image build filled the Benchmark; Benchmark Provenance says where the Benchmark itself comes from.
_Avoid_: Provenance alone, build metadata

**Task replay**:
Calling an eval's own task function in a child process with empty caches, so it fetches its
Cases the way inspect would, then running the Task's own solvers on each Sample up to their
first model call, where a stand-in records the prompt instead (capture). It never calls
inspect's `eval()`: no model, scorer or Judge runs. The importer uses it for every Imported
Benchmark, and Case Preparation uses it again at every image build, checking the Case Digest.
_Avoid_: Running the eval, replaying the evaluation, replay alone

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
extra, `inspect_grade_case`.
Inspect's own words name only inspect's own objects, in the plugin code that calls inspect.
Everywhere else, including our own concepts inside the plugin, use our word:
- inspect Task (`@task`): one eval definition (dataset, solver, scorer) → the eval an Imported
  Benchmark is copied from
- inspect Sample: one question with its target → a Case, but only after Case Preparation keeps
  it; before that step it is still a Sample, and a Sample it drops never becomes a Case
- inspect Dataset (`hf_dataset`, `record_to_sample`): how a Task loads its Samples → the dataset
  that Case Preparation pins
- inspect Target: the correct answer on a Sample → part of the Case's Grading Material
- inspect Solver (`prompt_template`, `multiple_choice`, `system_message`): the steps that build the
  prompt and call the model → the Case input that Case Preparation writes
- inspect Scorer: grades one answer → an Imported Benchmark's Grading
- inspect model role (`model_role="grader"`): a named model slot a Scorer fills → the Benchmark's
  Judge
- inspect ModelAPI: a pluggable model provider → the gateway Judge provider
_Avoid_: inspect or introspect as a verb in our identifiers (say read or check), so an `inspect`
name always means the framework; Sample, Target, Solver and Scorer for our own concepts

**Imported Benchmark**:
A Benchmark generated from an external eval catalogue, whose Cases are exactly the items the
upstream eval would run (apart from any Named Deviation) and whose Grading is the upstream eval's
own grading code. Today the only source is Inspect.
_Avoid_: Board, inspect board

**Named Deviation**:
A declared, reviewable difference between an Imported Benchmark and its upstream eval, such as
dropped questions or a system message delivered as input text. It is written on the Benchmark
and included in its Benchmark Revision.
_Avoid_: Patch, tweak

**Inverted Grade**:
A mark on an Imported Benchmark whose upstream grade counts the behaviour we don't want, such as
a judge's grade for going along with an unsafe prompt. Each Case scores 1 − that grade, so higher
is still better and the Benchmark's score is a refusal rate, not a compliance rate. It is part of
the Benchmark Revision and shown in the Report; it says the score is already flipped, never that
anyone should flip it again.
_Avoid_: Reversed score, lower-is-better Benchmark

**Headline Score**:
The one score of a Benchmark that ranks the Leaderboard, always higher-is-better. For a
single-scorer Benchmark it is the score; for a Benchmark with several Named Scores it is the one
the Benchmark declares, copied into the Case Grade's and Candidate Result's `score`.
_Avoid_: Main score, primary metric

**Named Score**:
One of the several per-Case and per-Candidate numbers a Benchmark reports under its scorer's
name (`f1`, `exact`), shown beside the Headline Score and never ranked. It carries no direction:
the Inverted Grade flip applies to the Headline Score only.
_Avoid_: Sub-score, secondary metric, extra metric

**Benchmark Provenance**:
What says where a Benchmark comes from: its paper with the authors and a citation, the links to
its website, harness, dataset and licence (with any restriction on it) and, for an Imported
Benchmark, the people who ported it into Inspect. Who typed the row into ScreamingFace is not
part of it: git holds that. The harness link is always the original upstream code that produced the paper's
numbers, pinned to a commit or version tag, never ScreamingFace's own translation of it. None of
it is part of the Benchmark Revision: a link or a baseline says nothing about which Cases are
asked or how they are graded.
_Avoid_: Metadata, sources

**Frontier Score**:
The best published AI score on a Benchmark's headline metric, with the model, the source URL and
the as-of date. Typed by a human from a cited source; it is the input to Benchmark Saturation.
_Avoid_: SOTA, top score

**Human Baseline**:
The published human score on a Benchmark's headline metric, with its source. Shown beside the
Frontier Score for context; it plays no part in the saturation verdict.
_Avoid_: Human performance, human score

**Benchmark Saturation**:
The state in which the best published score on a Benchmark sits so close to the maximum that a
further gain cannot show a capability difference. The research definition (Akhtar et al., "When
AI Benchmarks Plateau", arXiv 2602.16763, 2026) requires two things: the top models score
statistically alike, and the top score nears the ceiling. ScreamingFace measures only the second,
as headroom: the maximum score on the headline metric minus the Frontier Score. A Benchmark is
**saturated** when headroom ≤ 0.10, **open** otherwise, and **unknown** when no Frontier Score is
recorded. The Engine derives the verdict; nobody types it. Human-level performance does not make
a Benchmark saturated, and a saturated Benchmark is not a solved problem.
_Avoid_: Solved, beaten, superhuman (that is Frontier Score ≥ Human Baseline, a separate fact)
