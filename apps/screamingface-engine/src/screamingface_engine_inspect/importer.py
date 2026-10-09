# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The importer: turn one inspect eval into an Imported Benchmark's two generated rows.

FEATURE: Imported Benchmarks. Since OME-1460 there is one path, Task replay: the eval's own
task function is called in a clean child, twice, its Cases are sealed with a Case Digest and
its Hub reads pinned to a commit, and the declaration plus the BenchmarkSpec row land as an
in-place edit to prepare.py / benchmarks.py, so ``git diff`` IS the review artifact. Import
time is the trust window, so a human reviews that diff before anything merges.

Stages, in execution order (``main``):

    Stage 1 — replay: :func:`~screamingface_engine_inspect.import_replay.import_by_task_replay`
              runs the import child (Cases, Case Sources, the built Task's scorer facts read
              by this module's readers), seals the declaration, and replays it once more as
              every build will.
    Stage 2 — the card: the one Hugging Face Case Source's dataset card gives a cleared
              licence, else ``TODO`` for the owner (D13). Network, import side only.
    Stage 3 — write: the declaration and the BenchmarkSpec row are inserted at their
              files' anchor comments (task_replay_rows.py), using this module's renderers.

Run from ``apps/screamingface-engine``::

    uv run python -m screamingface_engine_inspect.importer \
        inspect_evals.commonsense_qa.commonsense_qa:commonsense_qa --key commonsense_qa \
        --shuffle-seed 20260917

STORY: onboarding is AI-first: an agent runs the command, writes the catalogue prose, and
resolves every TODO(review); the human's whole job is verifying the resulting diff. Nobody
transcribes values or writes wiring code.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

# WHY a runtime import is safe here: provenance_facts imports only the stdlib and yaml,
# never this module, so no cycle (OME-1455).
from screamingface_engine_inspect.provenance_facts import read_provenance_facts

if TYPE_CHECKING:
    # WHY type-only: import_replay imports this module, so a runtime import would cycle.
    from screamingface_engine_inspect.import_replay import TaskReplayImport

#: Dataset licenses cleared for the public catalogue. A card naming any other is written as
#: TODO with the card's value in the review note, for the owner to decide (D13).
CLEARED_DATASET_LICENSES: frozenset[str] = frozenset(
    {"mit", "apache-2.0", "cc0-1.0", "cc-by-4.0", "cc-by-sa-4.0", "odc-by"}
)


_BENCHMARKS_ANCHOR = "# --- importer: generated BenchmarkSpec rows land above this line ---"


class ImporterError(Exception):
    """The importer refuses to emit. Always says which fact stopped it."""


# ---------------------------------------------------------------------------
# Stage 1 — read the built Task (its scorer facts)
# ---------------------------------------------------------------------------


def _custom_metrics(task: Any) -> tuple[str, ...]:
    """The eval's own ``metrics=`` by registry name — empty when it uses the scorer's."""

    from inspect_ai._util.registry import registry_info

    metrics: Any = getattr(task, "metrics", None)
    if not metrics:
        return ()
    # WHY the fallback: inspect also takes metric GROUPS (a dict of name → metrics),
    # which carry no registry entry; the review flag only needs a readable name.
    listed: list[Any] = list(metrics) if isinstance(metrics, list) else [metrics]
    names: list[str] = []
    for metric in listed:
        try:
            names.append(str(registry_info(metric).name))
        except Exception:  # noqa: BLE001 — any unregistered shape still gets flagged
            names.append(repr(metric))
    return tuple(names)


#: inspect's reducer when a Task declares epochs but names none (``Epochs`` docstring).
_INSPECT_DEFAULT_REDUCER: str = "mean"


def _refuse_several_epochs(task: Any) -> None:
    """Refuse a Task that asks each Sample more than once, naming its epochs and reducer.

    FEATURE: several Attempts per Case (OME-1458). ``epochs=N`` runs every Sample N times
    and folds the N scores with a reducer (MBPP: 5, ``pass_at_1``); our Benchmark asks
    each Case once, so the import would publish a one-Attempt score as the eval's number.

    INVARIANT: refused whatever the reducer, until the Engine runs several Attempts per
    Case (spec ``docs/spec/2026-10-07-OME-1458-attempts-per-case.md`` D12). One epoch is
    one Attempt, so ``Epochs(1, "mode")`` (lab_bench) imports as before.
    AIDEV-NOTE: the build replaces this refusal with a mapping: any-match reducers
    (``max``, ``at_least_1``, ``pass_at_N``) become ``attempts=N``; every other reducer
    stays refused by name (spec §2.6).
    """

    from inspect_ai.scorer._reducer.registry import reducer_log_names

    epochs: int | None = getattr(task, "epochs", None)
    if epochs is None or epochs <= 1:
        return
    reducers: list[Any] | None = getattr(task, "epochs_reducer", None)
    names: list[str] = (reducer_log_names(reducers) if reducers else None) or [
        _INSPECT_DEFAULT_REDUCER
    ]
    raise ImporterError(
        f"the task declares epochs={epochs} with reducer {', '.join(names)}: a Benchmark "
        "that asks each Case several times is not supported yet (OME-1458), and importing "
        "it would publish a one-Attempt score"
    )


@dataclass(frozen=True)
class ScorerFacts:
    """What the Task declares about its scorers, read off the built Task (OME-1268).

    Mental model: the Task lists its examiners; we keep every examiner we can seat in our
    marking room (one that grades without a judge), seat the first of them at the head of
    the table (the Headline Score), and write down by name any examiner we had to turn away.
    """

    scorer: str
    scorer_kwargs: dict[str, Any]
    scorer_name: str
    extra_scorers: tuple[str, ...] = ()
    named_scores: tuple[str, ...] = ()
    dropped_scorers: tuple[str, ...] = ()
    headline_differs: bool = False
    dropped_metrics: tuple[str, ...] = ()


def _scorer_facts(task: Any, module: Any) -> ScorerFacts:
    """Every scorer the Task declares, kept or dropped by name (OME-1268).

    Stage 1 — list the declared scorers; none is a refusal.
    Stage 2 — one scorer: resolve it exactly as before (a judged one takes the judged row).
    Stage 3 — several: keep each one that grades without a judge, in upstream order; a
              judged one cannot be seated (only a single-scorer row pins a judge), so it is
              written to ``dropped_scorers`` by name. None kept is a refusal.
    Stage 4 — the tripwire: the headline scorer's first declared metric must be a plain mean
              (``accuracy`` / ``mean``), or the row would publish the wrong headline; any
              other metric on a kept scorer is noted as not reproduced.
    """

    from screamingface_engine_inspect.scorer_metrics import (
        extra_metric_names,
        headline_metric_kind,
        headline_metric_name,
    )

    declared: list[Any] = (
        task.scorer if isinstance(task.scorer, list) else [task.scorer] if task.scorer else []
    )
    if not declared:
        raise ImporterError("the task declares no scorer")
    resolved: list[tuple[str, dict[str, Any], str]] = [
        _resolve_scorer(scorer, module) for scorer in declared
    ]
    kept: list[int] = (
        [0]
        if len(declared) == 1
        else [
            index
            for index, (ref, params, _) in enumerate(resolved)
            if not _is_judged_by(ref, params)
        ]
    )
    if not kept:
        dropped_names: list[str] = [name for _, _, name in resolved]
        raise ImporterError(
            f"the task declares {len(declared)} scorers but no conservable scorer: every one "
            f"grades with a judge ({dropped_names}); add the row by hand"
        )
    headline_ref, headline_kwargs, headline_name = resolved[kept[0]]
    headline_scorer: Any = declared[kept[0]]
    # WHY this also catches a Task-level ``metrics=[...]``: inspect copies the Task's metrics
    # onto every scorer when it builds the Task (resolve_scorer_metrics), so xstest's
    # ``Task(metrics=[refusal_rate()])`` reads here as the scorer's headline (OME-1527).
    if headline_metric_kind(headline_scorer) != "mean":
        metric: str | None = headline_metric_name(headline_scorer)
        raise ImporterError(
            f"headline metric {metric or '<none>'} of scorer {headline_name} is not a plain "
            "mean; the Benchmark would publish the wrong headline. A Task-level metrics=[...] "
            "is checked here too, because inspect copies it onto every scorer. Whole-run "
            "metrics other than the mean are coming with OME-1527 (R1); until then add the "
            "row by hand"
        )
    if len(declared) == 1:
        return ScorerFacts(
            scorer=headline_ref,
            scorer_kwargs=headline_kwargs,
            scorer_name=headline_name,
            dropped_metrics=extra_metric_names(headline_scorer),
        )
    _check_kept_scorers(declared, resolved, kept)
    dropped_metrics: list[str] = []
    for index in kept:
        dropped_metrics.extend(extra_metric_names(declared[index]))
    return ScorerFacts(
        scorer=headline_ref,
        scorer_kwargs=headline_kwargs,
        scorer_name=headline_name,
        extra_scorers=tuple(resolved[index][0] for index in kept[1:]),
        named_scores=tuple(resolved[index][2] for index in kept),
        dropped_scorers=tuple(
            resolved[index][2] for index in range(len(declared)) if index not in kept
        ),
        headline_differs=kept[0] != 0,
        dropped_metrics=tuple(dropped_metrics),
    )


def _check_kept_scorers(
    declared: list[Any], resolved: list[tuple[str, dict[str, Any], str]], kept: list[int]
) -> None:
    """Refuse a multi-scorer Task whose kept scorers the row cannot write faithfully.

    WHY here, not at the next benchmarks.py import: the row would be written first and die
    on the registry's own check ("named_scores must be unique"), after the files exist.
    WHY refuse arguments on an extra scorer: it is constructed bare at grading time
    (benchmarks.py keeps kwargs for the headline scorer only), so `match(numeric=True)`
    written as `match()` would pin the wrong configuration into the Revision as faithful —
    "1,889" grades C upstream and I here. Never truncated, never silent.
    """

    from inspect_ai._util.registry import registry_params

    names: list[str] = [resolved[index][2] for index in kept]
    if len(set(names)) != len(names):
        raise ImporterError(
            f"the task declares two conservable scorers with one registry name ({names}); a "
            "Named Score column needs a name of its own — add the row by hand"
        )
    for index in kept[1:]:
        extra_ref, _, extra_name = resolved[index]
        params: dict[str, Any] = dict(registry_params(declared[index]))
        if params:
            raise ImporterError(
                f"extra scorer {extra_name} ({extra_ref}) is created with arguments {params}, "
                "which the Benchmark row cannot carry for a non-headline scorer; add the row "
                "by hand or drop it by name"
            )


def _resolve_scorer(scorer: Any, module: Any) -> tuple[str, dict[str, Any], str]:
    """One scorer as a dotted constructor reference, its literal creation kwargs, and its
    registry name."""

    from inspect_ai._util.registry import registry_info, registry_params

    registry_name: str = registry_info(scorer).name
    package, _, name = registry_name.rpartition("/")
    params: dict[str, Any] = {
        key: value for key, value in registry_params(scorer).items() if _is_literal(value)
    }
    if package == "inspect_ai":
        import inspect_ai.scorer as scorer_module

        if not hasattr(scorer_module, name):
            raise ImporterError(f"scorer {registry_name!r} is not exported by inspect_ai.scorer")
        return f"inspect_ai.scorer:{name}", params, name
    if hasattr(module, name):
        return f"{module.__name__}:{name}", params, name
    raise ImporterError(
        f"cannot resolve scorer {registry_name!r} to an importable constructor — "
        "add the row by hand with the eval's own scorer reference"
    )


def _solver_list(solvers: Any) -> list[Any]:
    """A Task's solver slot as a fresh list: None, one solver, or a list of them."""

    if solvers is None:
        return []
    return list(solvers) if isinstance(solvers, list) else [solvers]


def _is_literal(value: Any) -> bool:
    """True when the value survives a repr round-trip — safe to write into a row."""

    try:
        return ast.literal_eval(repr(value)) == value
    except (ValueError, SyntaxError):
        return False


# ---------------------------------------------------------------------------
# Stage 2 — the Hub card
# ---------------------------------------------------------------------------


def _hub_dataset_info(dataset: str, revision: str | None) -> Any:
    """The Hub's view of the dataset at ``revision`` (HEAD when None) — its
    resolved commit sha plus the card (license)."""

    from huggingface_hub import HfApi

    return HfApi().dataset_info(dataset, revision=revision)


# ---------------------------------------------------------------------------
# Stage 3 — render and write the rows
# ---------------------------------------------------------------------------


def _scorer_lines(
    scorer: str,
    scorer_kwargs: Mapping[str, Any],
    custom_metrics: tuple[str, ...],
    mcq: bool,
    judged: bool,
    *,
    extra_scorers: tuple[str, ...] = (),
    named_scores: tuple[str, ...] = (),
    dropped_scorers: tuple[str, ...] = (),
    headline_differs: bool = False,
    dropped_metrics: tuple[str, ...] = (),
) -> list[str]:
    """The scorer, metric, judge and check-surface lines of a BenchmarkSpec row.

    Written once here, so every Task-replay row declares its scorer the same way. With
    Named Scores (OME-1268) the row also declares the extra scorers, the score names
    (headline first) and any dropped scorer.
    """

    benchmark_lines: list[str] = [f'        scorer="{scorer}",']
    if scorer_kwargs:
        # WHY json.dumps for str values AND names: repr's single quotes fail the
        # emitted file's ruff-format gate; json escaping is as injection-safe as
        # repr's. Names are registry_params keys — identifiers in practice, but
        # a **kwargs-taking scorer could carry arbitrary upstream strings.
        rendered_kwargs: str = ", ".join(
            f"{json.dumps(name)}: {_python_literal_source(value)}"
            for name, value in sorted(scorer_kwargs.items())
        )
        benchmark_lines.append(f"        scorer_kwargs={{{rendered_kwargs}}},")
    benchmark_lines.extend(
        _named_score_lines(
            extra_scorers, named_scores, dropped_scorers, headline_differs, dropped_metrics
        )
    )
    for metric_name in custom_metrics:
        # WHY skip a dropped metric: inspect copies Task-level metrics onto the scorer, so
        # _named_score_lines already wrote its "not reproduced" note; a TODO beside it
        # would ask for the same deviation twice (OME-1527).
        if metric_name.rpartition("/")[2] in dropped_metrics:
            continue
        benchmark_lines.append(
            f"        # TODO(review): the eval reports its own metric {metric_name}, but the"
        )
        benchmark_lines.append(
            "        # benchmark reports the mean per-case score — name that deviation (and how"
        )
        benchmark_lines.append(
            "        # to convert between the two) in the benchmark's description."
        )
    if judged:
        # OME-1240: a judged row must never land silently — the TODO model is
        # refused at assembly by name, so an unreviewed judge cannot ship.
        benchmark_lines.append(
            "        # TODO(review): this scorer grades with an LLM judge. Pin the judge"
        )
        benchmark_lines.append("        # through our gateway: replace the judge-model kwarg with")
        benchmark_lines.append(
            '        # "screamingface/<gateway-model-id>" and declare the SAME id (plus'
        )
        benchmark_lines.append(
            "        # pinned params) here — both join the benchmark's identity."
        )
        benchmark_lines.append("        # If the scorer dispatches on sample metadata, also pass")
        benchmark_lines.append("        # --keep-sample-metadata when importing.")
        benchmark_lines.append('        judge=JudgeSpec(model="TODO"),')
    # Draft Feedback (the Corrective Loop's mid-run check) is never emitted: the field
    # defaults to False on BenchmarkSpec, and turning it on is a per-Benchmark owner decision
    # written by hand with a comment naming it (owner rule 2026-10-07, OME-1513) — never a
    # default, never inferred from the grading family.
    return benchmark_lines


def _named_score_lines(
    extra_scorers: tuple[str, ...],
    named_scores: tuple[str, ...],
    dropped_scorers: tuple[str, ...],
    headline_differs: bool,
    dropped_metrics: tuple[str, ...],
) -> list[str]:
    """The Named Scores declaration of a row (OME-1268): the extra scorers and the score
    names as tuple literals, a dropped scorer as a Named Deviation with its reason, a moved
    headline as a review TODO, and any metric not reproduced as a note."""

    lines: list[str] = []
    if extra_scorers:
        lines.append(f"        extra_scorers={_tuple_literal(extra_scorers)},")
    if named_scores:
        lines.append(f"        named_scores={_tuple_literal(named_scores)},")
    if dropped_scorers:
        lines.append(
            "        # Named Deviation (OME-1268): the Task also declares "
            f"{', '.join(dropped_scorers)}, left out"
        )
        lines.append("        # because it grades with a judge model, and a multi-scorer row pins")
        lines.append("        # no judge. Name the drop and its effect in the description; the")
        lines.append("        # dropped name is part of the Benchmark Revision.")
        lines.append(f"        dropped_scorers={_tuple_literal(dropped_scorers)},")
    if headline_differs and named_scores:
        lines.append(
            f"        # TODO(review): the Headline Score is {named_scores[0]}, not upstream's"
        )
        lines.append("        # first scorer — confirm the description names which column ranks.")
    for metric_name in dropped_metrics:
        lines.append(f"        # The eval also reports {metric_name}; the Benchmark reports each")
        lines.append(
            "        # scorer's mean per-Case score only, so that metric is not reproduced —"
        )
        lines.append("        # name it in the description.")
    return lines


def _tuple_literal(items: tuple[str, ...]) -> str:
    """A tuple literal the generated file's format gate accepts: json-quoted strings, the
    one-element trailing comma kept."""

    body: str = ", ".join(json.dumps(item) for item in items)
    return f"({body},)" if len(items) == 1 else f"({body})"


#: Kwarg names evals use to take their judge model — mirrored by the assembly
#: guard's _JUDGE_MODEL_KWARGS in benchmarks.py; the two lists move together.
_JUDGE_MODEL_KWARG_NAMES = frozenset({"model", "grader_model", "judge_model", "scorer_model"})


def _is_judged_by(scorer: str, scorer_kwargs: Mapping[str, Any]) -> bool:
    """A row is judged when its scorer takes a judge — by builtin NAME or by KWARG.

    WHY the kwarg check: a custom eval-module scorer (frontierscience) carries its
    judge under `model` while matching no `model_graded_*` name; a name-only check
    emitted it as a silently-unjudged row (review finding, 2026-09-24). No check
    surface is emitted for a judged row: assembly refuses the pair until the
    check-cost knob (OME-1116), so the generated row stays green-by-construction.
    """

    if scorer.rpartition(":")[2].startswith("model_graded_"):
        return True
    return any(name in _JUDGE_MODEL_KWARG_NAMES for name in scorer_kwargs)


def _python_literal_source(value: Any) -> str:
    """One scorer kwarg or task-arg value as Python source the emitted file's gates accept.

    WHY recurse instead of json.dumps a container: JSON spells False/None as false/null,
    which ast.parse accepts as NAMES, so the emitted file would parse and then raise
    NameError on import (OME-1273 Review Focus 6). Strings keep json.dumps (double quotes,
    as ruff format writes them); every other scalar keeps repr.

    Example: the task args ``{"shuffle": False, "limit": None}`` render as that same text,
    where json.dumps would write ``{"shuffle": false, "limit": null}``.
    """

    if isinstance(value, dict):
        items: str = ", ".join(
            f"{json.dumps(str(name))}: {_python_literal_source(item)}"
            for name, item in value.items()
        )
        return f"{{{items}}}"
    if isinstance(value, list | tuple):
        # WHY a list for a tuple too: task args cross request.json, which has no tuple.
        return f"[{', '.join(_python_literal_source(item) for item in value)}]"
    return json.dumps(value) if isinstance(value, str) else repr(value)


#: Character sets for text that gets interpolated into GENERATED PYTHON. The Hub
#: controls dataset names and card licenses, so templating them into code is an
#: injection sink (Lane 4): a hostile card could land an executable line in
#: prepare.py. Everything outside these charsets is refused, and the composed files
#: are additionally ast.parse-verified before writing.
_REFERENCE_CHARSET = re.compile(r"^[A-Za-z0-9._:/\- ]*\Z")
_LICENSE_CHARSET = re.compile(r"^[A-Za-z0-9.,+\- ]*\Z")


def _refuse_existing_rows(key: str, texts: Mapping[Path, str]) -> None:
    """Never double a Benchmark: a key already declared in prepare.py or benchmarks.py.

    WHY no constant-stem check any more: it guarded pins.py's ``FOO_BAR_*`` constants, which
    OME-1460 deleted with the Hugging Face path.
    """

    needles: tuple[str, ...] = (f'"{key}": TaskReplayCasesSpec(', f'key="{key}"')
    for path, text in texts.items():
        if any(needle in text for needle in needles):
            raise ImporterError(f"benchmark key {key!r} already exists in {path.name}")


def _with_generated_row(text: str, anchor: str, row_text: str, filename: str) -> str:
    """The whole insertion contract: the generated row lands immediately above the anchor.

    Pure text→text so callers can validate EVERY insertion before writing ANY file.
    """

    lines: list[str] = text.splitlines(keepends=True)
    positions: list[int] = [i for i, line in enumerate(lines) if line.strip() == anchor.strip()]
    if len(positions) != 1:
        raise ImporterError(
            f"{filename}: expected exactly one anchor line {anchor!r}, found {len(positions)} — "
            "the insertion contract is broken; restore the anchor comment"
        )
    lines.insert(positions[0], row_text)
    return "".join(lines)


def _write_verified_python(path: Path, text: str) -> None:
    """The last injection backstop: never write a file that does not parse."""

    try:
        ast.parse(text, filename=path.name)
    except SyntaxError as exc:
        raise ImporterError(
            f"{path.name}: the composed file does not parse ({exc.msg}, line {exc.lineno}) — "
            "refusing to write; the generated row is malformed"
        ) from exc
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TaskReplayImporter(Protocol):
    """The seam main() imports through: the two replays, injectable for tests."""

    def __call__(
        self,
        task_ref: str,
        task_args: Mapping[str, Any] | None,
        *,
        excluded_sample_ids: tuple[str, ...] | None,
        has_answer_key: bool,
        shuffle_seed: int | None,
        choice_shuffle_seed: int | None,
        keep_sample_metadata: bool,
    ) -> TaskReplayImport:
        """Seal the Cases by two replays, as import_replay.import_by_task_replay does."""
        ...


def main(
    argv: list[str] | None = None,
    *,
    dataset_info: Callable[[str, str | None], Any] | None = None,
    import_by_task_replay: TaskReplayImporter | None = None,
    arxiv_fetch: Callable[[str], str] | None = None,
) -> int:
    """Import one inspect eval as an Imported Benchmark, by Task replay (OME-1460, R10).

    There is one path: the eval's own task function is called in a clean child, twice, and
    its Cases are sealed with a Case Digest; the declaration and the BenchmarkSpec row are
    written for the dev to review. ``dataset_info``, ``import_by_task_replay`` and
    ``arxiv_fetch`` (the paper lookup behind Benchmark Provenance, OME-1455) are injectable
    for tests, so none opens a socket.

    Returns:
        0 when the rows are written; 1 when the import is refused (one ERROR line, no write).
    """

    parser = argparse.ArgumentParser(
        prog="python -m screamingface_engine_inspect.importer",
        description="Generate one Imported Benchmark's rows by replaying an inspect task.",
    )
    parser.add_argument("task_ref", help="dotted task reference, e.g. inspect_evals.mod.mod:task")
    parser.add_argument("--key", required=True, help="the benchmark key (catalogue id suffix)")
    parser.add_argument(
        "--task-arg",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="argument forwarded to the task function (repeatable), e.g. fewshot=0",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=None,
        help="the seed forced onto an hf_dataset row shuffle the eval makes without one; "
        "refused when the eval makes none (D7)",
    )
    parser.add_argument(
        "--choice-shuffle-seed",
        type=int,
        default=None,
        help="the seed forced onto a bare shuffle_choices=True; refused when the eval makes "
        "none (D7)",
    )
    parser.add_argument(
        "--engine-src",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="directory holding prepare.py/benchmarks.py (default: this package)",
    )
    _add_task_replay_arguments(parser)
    args = parser.parse_args(argv)

    try:
        _import_by_task_replay_cli(args, dataset_info, import_by_task_replay, arxiv_fetch)
    except ImporterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def _add_task_replay_arguments(parser: argparse.ArgumentParser) -> None:
    """The flags that say what only the importing agent knows."""

    parser.add_argument(
        "--excluded-sample-id",
        action="append",
        default=[],
        metavar="ID",
        help="an upstream Sample id to leave out (repeatable), a Named Deviation whose "
        "reason the row must state, e.g. stages_full:14",
    )
    parser.add_argument(
        "--no-answer-key",
        action="store_true",
        help="the eval's Samples carry no answer key, so an empty one is accepted; the "
        "Benchmark row must then say who grades without it",
    )
    parser.add_argument(
        "--keep-sample-metadata",
        action="store_true",
        help="keep the Sample metadata although the scorer is inspect's own, because a "
        "Judge template reads it (coconot's rubric)",
    )


def _import_by_task_replay_cli(
    args: argparse.Namespace,
    dataset_info: Callable[[str, str | None], Any] | None,
    import_by_task_replay: TaskReplayImporter | None,
    arxiv_fetch: Callable[[str], str] | None = None,
) -> None:
    """The command's one path: two replays, the card license, the two rows (OME-1273/1460).

    Stages: (1) import_by_task_replay seals the Cases (both replays run here; refusals are
    ImporterErrors); (2) the one Hugging Face card, if any, gives a cleared license or TODO
    (D13); (3) the declaration and the BenchmarkSpec row are written; (4) stderr lists each
    Case Source so the importing agent can check them against the eval's loader.
    """

    # WHY lazy: task_replay_rows and import_replay import this module.
    from screamingface_engine_inspect.import_replay import (
        import_by_task_replay as replay_both_times,
    )
    from screamingface_engine_inspect.task_replay_rows import (
        CardLicense,
        card_license_of,
        write_task_replay_rows,
    )

    imported: TaskReplayImport = (import_by_task_replay or replay_both_times)(
        args.task_ref,
        _parse_task_args(args.task_arg),
        excluded_sample_ids=tuple(args.excluded_sample_id) or None,
        has_answer_key=not args.no_answer_key,
        shuffle_seed=args.shuffle_seed,
        choice_shuffle_seed=args.choice_shuffle_seed,
        keep_sample_metadata=args.keep_sample_metadata,
    )
    card: CardLicense = card_license_of(
        imported.case_sources, dataset_info=dataset_info or _hub_dataset_info
    )
    write_task_replay_rows(
        args.key,
        imported,
        engine_src=args.engine_src,
        license=card.value,
        card_license=card.card_says,
        provenance=read_provenance_facts(args.task_ref, fetch=arxiv_fetch),
    )
    sources: str = "\n".join(f"  {source.as_comment()}" for source in imported.case_sources)
    print(
        f"Task-replay rows for {args.key!r} written into {args.engine_src} — "
        f"{imported.declaration.case_count} Cases, Case Digest "
        f"{imported.declaration.case_digest[:12]}…, license {card.value}. Case Sources:\n"
        f"{sources}\n"
        "Onboarding is AI-first: agent, check each Case Source against the eval's loader, "
        "fill the TODO catalogue prose and resolve every TODO(review), then run the gates — "
        "a human decides the license and reviews the diff before merge.",
        file=sys.stderr,
    )


def _parse_task_args(pairs: list[str]) -> dict[str, Any]:
    """``NAME=VALUE`` flags → task kwargs; values parse as literals, else stay strings."""

    parsed: dict[str, Any] = {}
    for pair in pairs:
        name, separator, raw = pair.partition("=")
        if not separator:
            raise ImporterError(f"--task-arg must be NAME=VALUE, got {pair!r}")
        try:
            parsed[name] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            parsed[name] = raw
    return parsed


if __name__ == "__main__":  # pragma: no cover — the module IS the command
    # WHY re-import: under `python -m` this file runs as __main__, a second copy of the
    # module whose ImporterError is a different class from the one task_replay_rows and
    # import_replay raise; main's `except` must name the canonical class (OME-1273).
    from screamingface_engine_inspect.importer import main as _canonical_main

    sys.exit(_canonical_main())
