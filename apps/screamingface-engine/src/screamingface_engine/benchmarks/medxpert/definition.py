"""MedXpertQA (Text) as one Engine-owned, judge-free Benchmark.

FEATURE: expert-level medical multiple choice — 2,450 questions, one letter each, graded by
string comparison. The first benchmark whose grading spends NO judge tokens.

INVARIANT — the exchange is TWO candidate invocations. Turn 1 reasons freely; turn 2 (the
commit) CONTINUES that chat (OME-1980): the turn-1 prompt as the user, the Candidate's own turn-1
answer as the assistant, then the reply rule and the trigger, so the model completes "…the answer
is ___" and its commitment comes FIRST, which is what makes the official first-match extraction
correct. The harness's layout alone did not hold: with the bare trigger the model still explained
again (OME-2018, Named Deviation 3). Sent as one new user message holding
the reasoning (before OME-1980), the model explained again and its first stray capital was
graded: an external researcher lost 475 of 2,450 Cases.

WHO COMMITS — the one model call that wrote the turn-1 answer (a Fusion's synthesizer, or a
writer after Rank or Filter, without the instruction about its panel); any other recipe runs
whole on the chat (`commit.commit_recipe`).

NAMED DEVIATIONS — (1) the two-turn exchange is imposed at the CANDIDATE BOUNDARY: a Fusion's
members reason once, on turn 1, and never see turn 2; a per-member implementation would run two
turns inside each member. Fusion numbers are therefore not comparable to such an implementation,
and the description says so. (2) Sampling and the system message are the Candidate's own, not
the harness's (temperature 0, seed 0, 2048 or 8192 tokens; "You are a helpful medical
assistant."): today's reasoning models reject temperature 0 or run out of tokens at 2048, and
keeping the system message keeps turn 1 byte-identical across revisions, so reruns replay it from
the cache (owner's call, OME-1980). (3) Turn 2 states its reply rule (OME-2018, owner's call): one
line before the trigger, "Finish the sentence below with the option letter only, and nothing
else." (`prompts.COMMIT_INSTRUCTION`); the harness sends the trigger alone. (4) The reader reads
a letter wrapped in underscores (`__E__`), which the harness's word-boundary rule misses.

References:
    - Paper: https://arxiv.org/abs/2501.18362
    - Dataset: https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA
    - Official harness: https://github.com/TsinghuaC3I/MedXpertQA (eval/)
"""

from __future__ import annotations

from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    FailurePolicy,
    candidate,
    candidate_call,
)
from screamingface_engine.benchmarks.medxpert.prompts import (
    COMMIT_INSTRUCTION,
    COT_PROMPT_TEMPLATE,
    COT_TRIGGER_TEMPLATE,
)
from screamingface_engine.benchmarks.medxpert.revision_inputs import (
    DATASET,
    DATASET_CONFIG,
    DATASET_REVISION,
    DATASET_SPLIT,
    PREPARER_REVISION,
    PROTOCOL_REVISION,
)
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    early_result,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.provenance import FrontierScore, HumanBaseline
from screamingface_engine.benchmarks.selection import CaseSelection
from screamingface_engine.benchmarks.shared_grading.serving import (
    benchmark_routes,
    compute_benchmark_revision,
)
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Url4Node

BENCHMARK_ID = "medxpert"
ASSET_BUNDLE_ID = BENCHMARK_ID
CASE_COUNT = 2450
DATASET_URL = "https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA"
# INVARIANT: grading is retrieval-free — the answer key is a fixed letter, and a model that
# searched would be answering a different question from the one the leaderboard asks.
CANDIDATE_WEB_SEARCH = False
# WHY "withhold" (OME-1642): a Case that never got a valid grade counts 0 over every selected
# Case, the same as an empty ANSWER, which the official empty-prediction verdict grades 0.0
# (`aggregate._scored`). Coverage still shows the graded count beside the score. One constant,
# read by the declaration and by the revision, so the two cannot drift.
FAILURE_POLICY: FailurePolicy = "withhold"


def compute_revision(
    *,
    dataset_revision: str = DATASET_REVISION,
    cot_template: str = COT_PROMPT_TEMPLATE,
    trigger_template: str = COT_TRIGGER_TEMPLATE,
    failure_policy: FailurePolicy = FAILURE_POLICY,
    protocol_revision: str = PROTOCOL_REVISION,
    commit_instruction: str = COMMIT_INSTRUCTION,
) -> str:
    """Fingerprint this benchmark into the 16 hex characters its routes carry.

    WHY the prompt templates are hashed: this benchmark has no judge, so the prompt is the only
    thing between a model and its score. A changed template is a changed benchmark and must
    re-address every route — otherwise already-recorded submissions would silently become
    incomparable. The failure policy is hashed for the same reason (OME-1642): a ``withhold``
    score is a different number from the same answers, so it gets its own revision. The
    protocol constant stands for the prompt bytes no template holds: what turn 2's input is
    built from (OME-1786).
    """

    return compute_benchmark_revision(
        DATASET,
        DATASET_CONFIG,
        DATASET_SPLIT,
        dataset_revision,
        PREPARER_REVISION,
        protocol_revision,
        EVALUATION_PROTOCOL_REVISION,
        CANDIDATE_RESULT_SCHEMA,
        cot_template,
        trigger_template,
        # WHY conditional (OME-1642): only withhold moves the revision, the same rule as the
        # imported rows' fingerprint pin.
        *(("failure_policy=withhold",) if failure_policy == "withhold" else ()),
        # WHY hashed (OME-2018): turn 2's reply rule is prompt text like the two templates, so
        # rewording it must move the id without anyone remembering to. WHY conditional: the
        # exams before it sent no rule, and an empty one keeps their ids computable.
        *((f"commit_instruction={commit_instruction}",) if commit_instruction else ()),
    )


#: The hash of everything that defines this Benchmark (OME-1610): an alarm, never published.
#: ``tests/unit/inspect/test_benchmark_fingerprints.py`` pins it.
FINGERPRINT = compute_revision()
#: The id this Benchmark publishes, hand-set (OME-1610): what submissions and the leaderboard
#: key on. AIDEV-NOTE: the same rule as a catalogue row's ``published_revision`` — never
#: edited to make a red fingerprint test green; it moves only on a fundamental change, after
#: ``just engine benchmark-bump medxpert`` and with the owner's sign-off
#: (``docs/adding-an-imported-benchmark.md``, "Changing a Benchmark's published revision").
REVISION = "5f6e01e4fa673215"

_ROUTES = benchmark_routes(BENCHMARK_ID, REVISION)
ROUTE_PREFIX = _ROUTES.prefix
CASES_ROUTE = _ROUTES.cases
CHECK_ROUTE = _ROUTES.check
CASE_GRADE_ROUTE = _ROUTES.case_evaluation
AGGREGATE_ROUTE = _ROUTES.aggregate
#: Turns turn 1's result record into the chat turn 2 continues (OME-1786, OME-1980). MedXpertQA's
#: own routes: the shared layout has no such address, because no other hand-built Benchmark has a
#: turn 2.
COMMIT_CHAT_ROUTE = f"{ROUTE_PREFIX}/commit-chat"
#: Reads the Candidate's recipe text and names who answers turn 2 (OME-1980).
COMMIT_RECIPE_ROUTE = f"{ROUTE_PREFIX}/commit-recipe"


def _build(selection: int | CaseSelection) -> Node:
    """Build the two-turn MedXpertQA expression.

    Reading outside-in: fetch the Cases, and for each ask the Candidate to reason, then ask the
    SAME Candidate to commit against the bare trigger, then check the committed letter against
    the private key and roll the rows into the aggregate.

    ``selection`` is the run's Cases (OME-1739): a count or explicit ids; the Candidate is
    told the run's size (``selected.count``), never the highest id.
    """

    selected: CaseSelection = CaseSelection.coerce(selection)
    # Turn 1 — free reasoning. The cases file prepares the ready-made CoT prompt.
    # INVARIANT: this node is bound at CASE-EXECUTION scope (via `bindings=` below), never
    # inside the grading scope. The protective iterate rebinds `$item` to the
    # `{candidate_invocation, case_id}` struct, so `$item.cot_prompt` read there resolves
    # empty and the model receives a blank prompt — the OME-1126 live-run failure.
    reasoning = candidate(
        "$item.cot_prompt",
        case_id="$item.id",
        case_index="$index",
        case_count=str(selected.count),
        web_search=CANDIDATE_WEB_SEARCH,
        binding="$candidate",
    )
    # Between the turns — turn 1 resolves to the Candidate's whole result record: its answer
    # text plus the Engine's notes on the call (status, finish reason, and the accounting:
    # tokens, cost, latency, attempts, cache hit or miss). This route keeps the answer text only
    # and writes the chat turn 2 continues: the turn-1 prompt (user), that answer (assistant),
    # the trigger (user), the official harness's four-message layout with our system message.
    # INVARIANT (OME-1786): the record never reaches the prompt. Its accounting differs between
    # a live call and a cache hit, so a record in the prompt changed turn 2's bytes on every
    # rerun: the AI Gateway's request cache missed and the commit was billed again.
    commit_chat = RelExpr(
        path=COMMIT_CHAT_ROUTE,
        context=render(
            struct(
                {
                    "prompt": "$item.cot_prompt",
                    "reasoning": "$reasoning",
                    "trigger": "$item.trigger",
                }
            )
        ),
        intent=Text("$item.id"),
    )
    # Who answers turn 2 (OME-1980): the one model that wrote the turn-1 answer (a Fusion's
    # synthesizer), else the whole Candidate. WHY a route and not this builder: the protocol is
    # built before any Candidate exists; only a step during the run can read its recipe.
    commit_recipe = RelExpr(path=COMMIT_RECIPE_ROUTE, context="$candidate", intent=Text(""))
    # Turn 2 — the commit, continuing the chat; the model finishes the trigger, so the letter
    # leads. WHY `candidate_call` (the bare call) and not `candidate()`: `$commit_chat` and
    # `$commit_recipe` resolve only as DIRECT siblings of the bindings — inside `candidate()`'s
    # wrapper group the reference ships to the model verbatim (OME-1126).
    commit = candidate_call(
        "$commit_chat",
        case_id="$item.id",
        case_index="$index",
        case_count=str(selected.count),
        web_search=CANDIDATE_WEB_SEARCH,
        binding="$commit_recipe",
    )
    checked = expr(
        src(
            RelExpr(
                path=CHECK_ROUTE,
                # D8: the shared candidate envelope has no field for auxiliary text, so the
                # reasoning reaches the report through THIS benchmark's own check envelope.
                context=render(
                    struct({"reasoning": "$reasoning", "commit": "$candidate_invocation"})
                ),
                intent=Text("$item.case_id"),
            ),
            name="record",
            weight=0.0,
        ),
        src(
            RelExpr(
                path=CASE_GRADE_ROUTE,
                context=render(struct({"attempt_1": "$record"})),
                intent=Text("$item.case_id"),
            ),
            name="case_evaluation",
            weight=0.0,
        ),
        intent=Text("$case_evaluation"),
    )
    return build_evaluation_protocol(
        cases_route=CASES_ROUTE,
        case_evaluation=early_result(
            preserve_candidate_outcome(
                # The COMMIT is the candidate outcome — it holds the answer being graded.
                candidate_invocation=commit,
                grading=checked,
                case_id="$item.id",
                # Turn 1 lives here so both the commit chat and the check read the SAME
                # real reasoning (see the INVARIANT on `reasoning` above). The chat and recipe
                # routes follow it as direct siblings, the only place `$reasoning` resolves.
                bindings=(
                    src(reasoning, name="reasoning", weight=0.0),
                    src(commit_chat, name="commit_chat", weight=0.0),
                    src(commit_recipe, name="commit_recipe", weight=0.0),
                ),
            ),
            aggregate_route=AGGREGATE_ROUTE,
            selected_case_count=selected,
        ),
        selected_case_count=selected,
        available_case_count=CASE_COUNT,
        aggregate_route=AGGREGATE_ROUTE + "/graded",
    )


def install_medxpert(node: Url4Node, assets: Path) -> None:
    """Install the MedXpertQA cases, checker and reducers."""

    from screamingface_engine.benchmarks.medxpert.runtime import install

    install(node, assets / ASSET_BUNDLE_ID)


#: FEATURE: answer format on the Benchmark page (OME-1906). What the SCORING parser,
#: `answering.extract_choice_letter`, reads from the turn-2 reply, in the words a submitter
#: sees; every quoted reply is graded through it in
#: tests/unit/test_medxpert_answer_format_scoring_path.py. WHY here and not in the inspect
#: plugin's `answer_formats` package: medxpert is hand-built core code, and core never imports
#: a plugin.
#: AIDEV-NOTE: not `grading.extract_letter` (last letter wins) — that parser is not on the
#: scoring path, and describing it here cost a user ~11 points on a prose commit.
ANSWER_FORMAT: str = (
    "Answer format: after its reasoning, the model gets a second turn asking it to finish "
    "'Therefore, among A through J, the answer is' with one option letter, as the next message "
    "of its own chat. That message tells the model to reply with the option letter only, which "
    "the official harness does not. The grader reads the reply the way the official MedXpertQA "
    "harness does: "
    "if the reply repeats 'the answer is', it keeps only the text between the first and second "
    "time, then takes the first capital option letter standing on its own. So 'D', '(D)', "
    "'**D**', '__D__', 'the answer is D' and 'the answer is D. B would be wrong.' all count as "
    "D, 'the answer is clear: the answer is D' commits to nothing, and a reply with no option "
    "letter, "
    "such as 'not sure', scores 0. "
    "A reply that opens in prose commits its first stray capital: 'A humeral shaft fracture, "
    "so D' counts as A, and a standalone 'I' counts as I. Recipe authors: make the commit "
    "reply the letter alone."
)

MEDXPERT = Benchmark(
    id=BENCHMARK_ID,
    title="MedXpertQA",
    description=(
        "2,450 expert-level medical multiple-choice questions (MedXpertQA Text). The model "
        "reasons step by step, then commits to one lettered choice; grading is an exact match "
        "against the published key, so no judge tokens are spent. Benchmark score = plain "
        "accuracy over every case run, reported beside the fraction actually answered — a case "
        "the model leaves unanswered, or that fails, counts as wrong. "
        "The two-turn exchange is applied at the candidate boundary: the commit continues the "
        "model's own chat, the official harness's message layout. When one model writes the "
        "answer from the members' replies (a fusion's synthesizer model, or a writer after a "
        "selection step), the members reason once and that model alone commits; any other "
        "recipe commits whole. Fusion numbers are not comparable to a per-member "
        "implementation. Sampling (temperature, seed, token cap) and the system message are the "
        "candidate's own, not the harness's temperature 0, seed 0, 2,048-token cap and "
        "medical-assistant system message. The commit message also states the reply format, "
        "which the harness leaves unsaid. " + ANSWER_FORMAT
    ),
    revision=REVISION,
    case_count=CASE_COUNT,
    build=_build,
    install=install_medxpert,
    focus="Expert medical multiple choice",
    dataset_url=DATASET_URL,
    declaration=BenchmarkDeclaration(
        # See FAILURE_POLICY (OME-1642).
        failure_policy=FAILURE_POLICY,
        # WHY "multi_turn": the benchmark invokes the Candidate twice per Case — reason, then
        # commit. Declared because it adds an invocation and changes what a Fusion entrant is
        # asked to do (its synthesizer alone commits, OME-1980).
        interaction="multi_turn",
        # Expert-level medical questions frontier models still visibly fail (OME-1257).
        difficulty="hard",
    ),
    # AIDEV-NOTE: no check_surface — deliberately. The declaration is a promise the SDK trusts
    # BEFORE spend: with one present, a corrective-loop run passes the pre-spend gate, burns paid
    # candidate turns, then dies on a route `runtime.install` never serves. With none, the SDK
    # refuses the loop up front (check_surface_missing). Declare it only together with the
    # handler — `grading.extract_letter`/`grade` are the parsers it should use.
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2501.18362",
    authors="Zuo et al., 2025",
    citation=(
        "@misc{zuo2025medxpertqabenchmarkingexpertlevelmedical,\n"
        "      title={MedXpertQA: Benchmarking Expert-Level Medical Reasoning and Und"
        "erstanding}, \n"
        "      author={Yuxin Zuo and Shang Qu and Yifei Li and Zhangren Chen and Xuek"
        "ai Zhu and Ermo Hua and Kaiyan Zhang and Ning Ding and Bowen Zhou},\n"
        "      year={2025},\n"
        "      eprint={2501.18362},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.AI},\n"
        "      url={https://arxiv.org/abs/2501.18362}, \n"
        "}"
    ),
    harness_url=(
        "https://github.com/TsinghuaC3I/MedXpertQA/tree/5f1db162d0d2b03d62da2d4fe086076a36105e18/eval"
    ),
    license="MIT",
    license_note="TsinghuaC3I/MedXpertQA dataset card.",
    content_warning="Expert medical questions, including graphic clinical detail.",
    # Human baseline: "Expert (Pre-Licensed)", Text overall, paper Table 4 — an estimate from
    # exam-taker score distributions, not a sitting of this set
    human_baseline=HumanBaseline(score=0.426, source_url="https://arxiv.org/abs/2501.18362"),
    # Frontier score: MedXpertQA Text accuracy (10-option MCQ, 2,450 questions), Comparison r….
    frontier_score=FrontierScore(
        score=0.715,
        model="Gemini 3.1 Pro",
        source_url="https://benchlm.ai/benchmarks/medxpertqatext",
        as_of="2026-04",
    ),
    notebook="11_medxpert",
)

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASES_ROUTE",
    "CASE_COUNT",
    "CASE_GRADE_ROUTE",
    "CHECK_ROUTE",
    "COMMIT_CHAT_ROUTE",
    "COMMIT_RECIPE_ROUTE",
    "MEDXPERT",
    "REVISION",
    "compute_revision",
    "install_medxpert",
]
