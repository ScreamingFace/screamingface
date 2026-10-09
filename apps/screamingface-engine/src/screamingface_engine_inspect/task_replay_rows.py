"""The generated code of a Task-replay import: its declaration and its BenchmarkSpec row.

FEATURE: Imported Benchmarks (OME-1273, spec R6; the only import path since OME-1460). An
import writes two rows: a ``TaskReplayCasesSpec`` entry in ``prepare.py`` (its Hub commits,
seeds and seal) and the usual ``BenchmarkSpec`` row in ``benchmarks.py``.

Think of it as filing the sealed booklet: the label on the envelope (Case count, Case Digest)
is CAPTURED, so code enforces it; the note clipped to it (the Case Sources) is COPIED, so a
reviewer judges it. Stages of ``write_task_replay_rows``, in execution order:

    Stage 1 — refuse a key either importer already declared.
    Stage 2 — refuse any text that could escape the generated code (injection guard): the
              task and scorer references, the metric names, the license, the Case Sources.
    Stage 3 — render the declaration: Case Sources as comments, the seal and the one fact
              that shapes a Case (kept metadata) as values, the license with its review note.
    Stage 4 — render the BenchmarkSpec row: catalogue prose as TODOs, the first browsable
              Case Source as ``dataset_url``, the scorer lines shared with the Hugging Face rows.
    Stage 5 — insert both rows above their anchors and write each file only if it parses.

Example (agieval_lsat_ar, one Case Source):

    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab…/lsat-ar.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_lsat_ar": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_lsat_ar",
        case_count=230,
        case_digest="…64 hex…",
        ...
"""

from __future__ import annotations

import datetime as _datetime
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screamingface_engine_inspect.case_sources import HUGGING_FACE, CaseSource
from screamingface_engine_inspect.fetch_pins import is_commit_sha
from screamingface_engine_inspect.import_replay import TaskReplayFacts, TaskReplayImport
from screamingface_engine_inspect.importer import (
    _BENCHMARKS_ANCHOR,
    _LICENSE_CHARSET,
    _REFERENCE_CHARSET,
    CLEARED_DATASET_LICENSES,
    ImporterError,
    _is_judged_by,
    _is_literal,
    _python_literal_source,
    _refuse_existing_rows,
    _scorer_lines,
    _with_generated_row,
    _write_verified_python,
)
from screamingface_engine_inspect.prepare import LICENSE_TODO, TaskReplayCasesSpec
from screamingface_engine_inspect.provenance_facts import ProvenanceFacts, provenance_row_lines

#: The anchor generated TaskReplayCasesSpec entries land above, inside TASK_REPLAY_CASES.
_TASK_REPLAY_CASES_ANCHOR: str = (
    "# --- importer: generated TaskReplayCasesSpec rows land above this line ---"
)
#: What a Case Source may hold to land in a generated comment. URLs carry ? = & % (sad's
#: `structs.zip?ref=…`); a quote, a backslash or a newline could escape, and stays refused.
_CASE_SOURCE_CHARSET: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._:/\-?=&%+#~@ ]*\Z")
#: What a Hub repo id may hold to land as a source_pins key (OME-1460).
_HUB_REPO_CHARSET: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._\-/]+\Z")


@dataclass(frozen=True)
class TaskReplayRows:
    """The two generated rows of a Task-replay import: no pins row, no import names."""

    cases: str
    benchmark: str


def render_task_replay_rows(
    key: str,
    imported: TaskReplayImport,
    license: str,
    *,
    card_license: str | None = None,
    provenance: ProvenanceFacts | None = None,
) -> TaskReplayRows:
    """Stages 2 to 4 — render a Task-replay declaration and its BenchmarkSpec row (spec R6).

    Args:
        key: the Benchmark key, e.g. ``agieval_lsat_ar``.
        imported: the sealed import (declaration, Case Sources, facts).
        license: the license value to write; ``LICENSE_TODO`` when the owner must decide.
        card_license: what the Hugging Face card said when it was not a cleared license, so
            the review note can name it (D13); None when there was no card to read.

    Returns:
        The declaration text (for TASK_REPLAY_CASES) and the BenchmarkSpec row text.

    Raises:
        ImporterError: a string that could escape the generated code (injection guard).
    """

    _refuse_injectable_import(imported, license, card_license)
    cases: str = "\n".join(_declaration_lines(key, imported, license, card_license)) + "\n"
    benchmark: str = "\n".join(_benchmark_row_lines(key, imported, license, provenance)) + "\n"
    return TaskReplayRows(cases=cases, benchmark=benchmark)


def write_task_replay_rows(
    key: str,
    imported: TaskReplayImport,
    *,
    engine_src: Path,
    license: str,
    card_license: str | None = None,
    provenance: ProvenanceFacts | None = None,
) -> TaskReplayRows:
    """Stages 1 to 5 — insert a Task-replay import's two rows into prepare.py and benchmarks.py.

    Args:
        key: the Benchmark key; refused when either importer already declared it.
        imported: the sealed import to write.
        engine_src: the directory holding prepare.py and benchmarks.py.
        license: see render_task_replay_rows.
        card_license: see render_task_replay_rows.

    Returns:
        The rows written.

    Raises:
        ImporterError: the key exists, a string could escape, an anchor is missing, or a
            composed file does not parse; nothing is written then.
    """

    prepare_path: Path = engine_src / "prepare.py"
    benchmarks_path: Path = engine_src / "benchmarks.py"
    texts: dict[Path, str] = {
        path: path.read_text(encoding="utf-8") for path in (prepare_path, benchmarks_path)
    }
    # Stage 1
    _refuse_existing_rows(key, texts)
    rows: TaskReplayRows = render_task_replay_rows(
        key, imported, license, card_license=card_license, provenance=provenance
    )
    # Stage 5 — compose both files before writing either.
    new_texts: dict[Path, str] = {
        prepare_path: _with_generated_row(
            texts[prepare_path], _TASK_REPLAY_CASES_ANCHOR, rows.cases, "prepare.py"
        ),
        benchmarks_path: _with_generated_row(
            texts[benchmarks_path], _BENCHMARKS_ANCHOR, rows.benchmark, "benchmarks.py"
        ),
    }
    for path, text in new_texts.items():
        _write_verified_python(path, text)
    return rows


def _refuse_injectable_import(
    imported: TaskReplayImport, license: str, card_license: str | None
) -> None:
    """Stage 2 — refuse any string that could escape the generated rows."""

    declaration: TaskReplayCasesSpec = imported.declaration
    references: list[str | None] = [
        declaration.task,
        imported.facts.scorer,
        *imported.facts.extra_scorers,
        *imported.facts.named_scores,
        *imported.facts.dropped_scorers,
        *imported.facts.dropped_metrics,
        imported.facts.whole_run_metric,
        imported.facts.mean_instead_of,
    ]
    # WHY a looser rule for these: they land only inside comments; only a line break or
    # another control character could end the comment and start code.
    # WHY printable only for the excluded ids: each lands inside a JSON string literal, which
    # escapes every quote, backslash and line break; onet_m6's ids are Thai (OME-1460).
    for text in (*imported.facts.custom_metrics, *(declaration.excluded_sample_ids or ())):
        if not text.isprintable():
            raise ImporterError(
                f"{text!r} cannot be written into generated code — refusing (injection guard)"
            )
    texts: list[tuple[str, re.Pattern[str]]] = [
        *((value, _REFERENCE_CHARSET) for value in references if value is not None),
        *((text, _LICENSE_CHARSET) for text in (license, card_license) if text is not None),
        *(
            (text, _CASE_SOURCE_CHARSET)
            for source in imported.case_sources
            for text in (source.kind, source.location, source.pin)
        ),
    ]
    for text, charset in texts:
        if not charset.match(text):
            raise ImporterError(
                f"{text!r} cannot be written into generated code — refusing (injection guard)"
            )
    for repo_id, commit in declaration.source_pins.items():
        # WHY: a repo id comes from the eval's own call, a commit from the Hub's answer.
        if not _HUB_REPO_CHARSET.match(repo_id) or not is_commit_sha(commit):
            raise ImporterError(
                f"source pin {repo_id!r}: {commit!r} cannot be written into generated code "
                "— refusing (injection guard)"
            )
    if declaration.task_args is not None and not _is_literal(declaration.task_args):
        raise ImporterError(
            f"task args {declaration.task_args!r} are not plain literals — refusing "
            "(injection guard)"
        )


def _declaration_lines(
    key: str, imported: TaskReplayImport, license: str, card_license: str | None
) -> list[str]:
    """Stage 3 — the TaskReplayCasesSpec entry: sources as comments, the seal as values."""

    declaration: TaskReplayCasesSpec = imported.declaration
    today: str = _datetime.date.today().isoformat()
    lines: list[str] = [
        f"    # {key} — imported by Task replay on {today} from",
        f"    #   {declaration.task}.",
        "    # Case Sources, as recorded at import (review them; the Case Digest pins them):",
        *_case_source_comment_lines(imported.case_sources),
        f'    "{key}": TaskReplayCasesSpec(',
        f'        task="{declaration.task}",',
    ]
    if declaration.task_args:
        lines.append(f"        task_args={_python_literal_source(declaration.task_args)},")
    lines.append(f"        case_count={declaration.case_count},")
    lines.append(f'        case_digest="{declaration.case_digest}",')
    if declaration.case_set_digest is not None:
        # OME-1492: the order-blind seal, so a later broken seal can say "order only".
        lines.append(f'        case_set_digest="{declaration.case_set_digest}",')
    if declaration.keep_sample_metadata:
        # WHY written: the metadata is inside the Case Digest, so the row must say so (D11).
        lines.append("        keep_sample_metadata=True,")
    if not declaration.has_answer_key:
        # WHY written: the empty keys are inside the Case Digest, as the metadata is (R19).
        lines.append("        has_answer_key=False,")
    if declaration.excluded_sample_ids:
        lines.extend(_excluded_id_lines(declaration.excluded_sample_ids))
    lines.extend(_fetch_pin_lines(declaration))
    lines.extend(_license_lines(license, card_license))
    lines.append("    ),")
    return lines


def _fetch_pin_lines(declaration: TaskReplayCasesSpec) -> list[str]:
    """What every build forces onto the eval's fetches (OME-1460): the Hub commits, the
    seeds, and the gate. Written only when set, so a URL-only row reads as before."""

    lines: list[str] = []
    if declaration.source_pins:
        # WHY written: every image build forces these commits; they ride identity (R7).
        lines.append("        source_pins={")
        lines.extend(
            f"            {json.dumps(repo_id)}: {json.dumps(commit)},"
            for repo_id, commit in sorted(declaration.source_pins.items())
        )
        lines.append("        },")
    if declaration.shuffle_seed is not None:
        lines.append(f"        shuffle_seed={declaration.shuffle_seed},")
    if declaration.choice_shuffle_seed is not None:
        lines.append(f"        choice_shuffle_seed={declaration.choice_shuffle_seed},")
    if declaration.needs_hf_token:
        lines.append("        needs_hf_token=True,")
    return lines


def _excluded_id_lines(excluded_ids: tuple[str, ...]) -> list[str]:
    """The Named Deviation (R18): one id per line, under a reason the reviewer still writes."""

    return [
        "        # NAMED DEVIATION — TODO(review): say why upstream's Samples",
        "        # below are left out.",
        "        excluded_sample_ids=(",
        *(
            f"            {json.dumps(sample_id, ensure_ascii=False)},"
            for sample_id in excluded_ids
        ),
        "        ),",
    ]


def _case_source_comment_lines(sources: tuple[CaseSource, ...]) -> list[str]:
    """One Case Source as two comment lines: what was fetched, then what pins it."""

    lines: list[str] = []
    for source in sources:
        what, pin = source.comment_lines()
        lines.extend((f"    #   {what}", f"    #     {pin}"))
    return lines


def _license_lines(license: str, card_license: str | None) -> list[str]:
    """The license value, with a review note whenever the owner still has to decide (D13)."""

    lines: list[str] = []
    if license == LICENSE_TODO:
        reason: str = (
            f"the card says {card_license!r}, not a cleared license"
            if card_license is not None
            else "no dataset card to read"
        )
        lines.append(f"        # TODO(review): {reason}; the owner decides.")
    lines.append(f'        license="{license}",')
    return lines


def _benchmark_row_lines(
    key: str,
    imported: TaskReplayImport,
    license: str,
    provenance: ProvenanceFacts | None = None,
) -> list[str]:
    """Stage 4 — the BenchmarkSpec row: prose as TODOs, the first browsable source as URL."""

    facts: TaskReplayFacts = imported.facts
    dataset_url: str | None = next(
        (url for source in imported.case_sources if (url := source.web_url()) is not None), None
    )
    lines: list[str] = [
        "    BenchmarkSpec(",
        f'        key="{key}",',
        "        # TODO(review): title/description/focus are catalogue prose — the",
        "        # importing agent writes them from the eval's own docs; the human",
        "        # reviewer verifies them against the dataset.",
        '        title="TODO",',
        '        description="TODO",',
        '        focus="TODO",',
    ]
    if dataset_url is None:
        # WHY TODO, not a guess: registration refuses anything but a web URL, so an
        # unreviewed row cannot ship, as with the difficulty tier below.
        lines.append("        # TODO(review): no Case Source has a web page; link the dataset.")
    lines.extend(
        [
            f'        dataset_url="{dataset_url or "TODO"}",',
            "        # TODO(review): assign the catalogue's easy→hard tier (OME-1257) —",
            '        # "easy" | "medium" | "hard". The literal TODO is',
            "        # refused by name at registration, so an unassigned tier cannot ship.",
            '        difficulty="TODO",  # type: ignore[arg-type]',
            "        # Provenance: this scorer is declared by the Task of",
            f"        #   {facts.task_ref}.",
            f"        # License: {license}.",
        ]
    )
    if provenance is not None:
        # Benchmark Provenance (OME-1455): the licence is the one decided above (a cleared
        # value or TODO), not re-read from a card.
        lines.extend(provenance_row_lines(provenance, license, CLEARED_DATASET_LICENSES))
    lines.extend(
        _scorer_lines(
            facts.scorer,
            facts.scorer_kwargs,
            facts.custom_metrics,
            facts.mcq,
            _is_judged_by(facts.scorer, facts.scorer_kwargs),
            extra_scorers=facts.extra_scorers,
            named_scores=facts.named_scores,
            dropped_scorers=facts.dropped_scorers,
            headline_differs=facts.headline_differs,
            dropped_metrics=facts.dropped_metrics,
            whole_run_metric=facts.whole_run_metric,
            mean_instead_of=facts.mean_instead_of,
        )
    )
    lines.append("    ),")
    return lines


@dataclass(frozen=True)
class CardLicense:
    """The license a Task-replay import writes, and what the card said when that is TODO."""

    #: A cleared license read off the card, or LICENSE_TODO for the owner to decide.
    value: str
    #: The card's own license when it was not on the cleared list (D13), else None.
    card_says: str | None


def card_license_of(
    sources: tuple[CaseSource, ...], *, dataset_info: Callable[[str, str | None], Any]
) -> CardLicense:
    """The license the importer can read: the card of the one Hugging Face Case Source.

    WHY one source only: with several, no single card speaks for the Cases (spec R7). WHY a
    cleared license only (D13): medqa's card says ``unknown``; written as the value it would
    pass R7's gate with nobody deciding, so it is written as TODO and named in the note.

    Example: ``hugging-face bigbio/med_qa · pin revision ddef…`` reads the card at ``ddef…``;
    ``Apache-2.0`` → ``apache-2.0``; ``UNKNOWN`` → TODO, the card says ``unknown``.

    Args:
        sources: the Case Sources run 1 recorded.
        dataset_info: ``(repo id, revision) → Hub dataset info`` (HfApi().dataset_info).

    Returns:
        What to write, and the card's own value when the owner must decide instead.
    """

    hugging_face: list[CaseSource] = [source for source in sources if source.kind == HUGGING_FACE]
    card_value: str | None = (
        _card_license_text(hugging_face[0], dataset_info) if len(hugging_face) == 1 else None
    )
    if card_value is None:
        return CardLicense(value=LICENSE_TODO, card_says=None)
    cleared: bool = card_value in CLEARED_DATASET_LICENSES
    return CardLicense(
        value=card_value if cleared else LICENSE_TODO, card_says=None if cleared else card_value
    )


def _card_license_text(
    source: CaseSource, dataset_info: Callable[[str, str | None], Any]
) -> str | None:
    """The card's license at the source's revision, lowercased; None when the card has none.

    A list of licenses is joined.
    """

    revision: str | None = (
        source.pin.removeprefix("revision ") if source.pin.startswith("revision ") else None
    )
    card: Any = getattr(dataset_info(source.hub_repo_id(), revision), "card_data", None) or {}
    value: Any = card.get("license") if hasattr(card, "get") else None
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    return str(value).lower() if value else None


__all__ = [
    "CardLicense",
    "TaskReplayRows",
    "card_license_of",
    "render_task_replay_rows",
    "write_task_replay_rows",
]
