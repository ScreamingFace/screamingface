"""The image input matrix's cell logic (image input matrix spec §3.2, plan Task 2). Pure.

One cell is one (path, model, media type) — or, on the Benchmark path, one (model, gold Case).
The notebook calls the stack and hands the outcome here; everything that decides pass or fail
lives in this module, so it is pinned by unit tests without a live target.

INVARIANT: the expectation comes from the gateway's own ``/v1/models`` evidence (the same rows
engine admission and the gateway refusal read), never from a table in the notebook. A model the
listing does not describe is ``unknown`` and its cell is ``skipped`` — unknown is never a pass.

WHY ``wrong`` is judged per path (spec §3.4): a url4 cell sends a fixture whose only content is
the known value, so a wrong answer means the picture did not arrive. A Benchmark Case is a real
question, so one model missing it is scoring noise; only EVERY capable model missing the same
Case says the picture was lost.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

type Path_ = Literal["url4", "benchmark"]
type Expected = Literal["answer", "refuse", "unknown"]
type Observed = Literal["answered", "refused", "wrong", "error", "skipped"]
type Modality = Literal["image", "pdf"]

# The codes a refusal surfaces as: engine admission and the url4 mapping raise ``intent_error``;
# the gateway's 422 backstop is ``unsupported_content_part`` (spec §3.2, either is accepted).
REFUSAL_CODES: Final = frozenset({"intent_error", "unsupported_content_part"})
# The listing words that grant a modality. ``file`` is OpenRouter's raw word for a PDF; the
# gateway maps it to ``pdf``, but accepting both keeps a raw catalogue row from reading as blind.
_GRANTS: Final[Mapping[Modality, frozenset[str]]] = {
    "image": frozenset({"image"}),
    "pdf": frozenset({"pdf", "file"}),
}


@dataclass(frozen=True)
class Cell:
    """One row of ``matrix.json``. ``case`` names the gold Case on the Benchmark path."""

    path: Path_
    model: str
    media_type: str
    expected: Expected
    observed: Observed
    answer: str | None
    code: str | None
    trace_id: str | None
    spend_usd: Decimal | None
    reason: str | None
    case: str | None = None
    # Gateway chat spans under the cell's trace; ``None`` when not counted. WHY: a refusal is
    # recognised by its code, and url4 also raises ``intent_error`` for a malformed expression,
    # so only "no chat call reached the gateway" proves the cell was refused before the model.
    chat_calls: int | None = None


def modality_of(media_type: str) -> Modality:
    """The gateway modality a media type needs: ``image/*`` is image, PDF is pdf."""
    if media_type == "application/pdf":
        return "pdf"
    if media_type.startswith("image/"):
        return "image"
    raise ValueError(f"no input modality for media type {media_type!r}")


def _listed_modalities(models_listing: Mapping[str, object], model: str) -> list[str] | None:
    """The model's listed modalities, or ``None`` when the listing does not describe it.

    The id matches exactly, or, failing that, as the tail of exactly one provider-prefixed id
    (``openrouter/google/x`` for ``google/x``). WHY: the notebook names models the way users
    do; the gateway lists canonical, provider-prefixed ids. Two candidates are ambiguous, and
    ambiguity is unknown, never a guess.
    """
    rows = models_listing.get("data")
    if not isinstance(rows, list):
        return None
    by_id = {row["id"]: row for row in rows if isinstance(row, dict) and "id" in row}
    row = by_id.get(model)
    if row is None:
        tails = [r for i, r in by_id.items() if isinstance(i, str) and i.endswith(f"/{model}")]
        row = tails[0] if len(tails) == 1 else None
    listed = row.get("input_modalities") if row is not None else None
    return [m for m in listed if isinstance(m, str)] if isinstance(listed, list) else None


def expectation(models_listing: Mapping[str, object], model: str, media_type: str) -> Expected:
    """``answer`` when the gateway lists the modality, ``refuse`` when not, else ``unknown``."""
    listed = _listed_modalities(models_listing, model)
    if listed is None:
        return "unknown"
    return "answer" if _GRANTS[modality_of(media_type)] & set(listed) else "refuse"


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def answer_contains(answer: str, expected: str) -> bool:
    """Whether ``answer`` holds ``expected`` as a whole token, case- and whitespace-insensitively.

    The value must stand alone: ``17392`` does not contain ``7392`` and ``HELIOTROPES`` does not
    contain ``HELIOTROPE``, because a model that misread part of a longer token did not read the
    picture. A decimal neighbour (``7392.5``, ``0.7392``) is a different number; a full stop
    ending the sentence is not. Spaced-out digits (``7 3 9 2``) do not match either: only runs
    of whitespace collapse, none are removed.
    """
    needle = re.escape(_normalise(expected))
    before = r"(?<!\w)(?<!\d\.)" if expected[:1].isalnum() else ""
    after = r"(?!\w)(?!\.\d)" if expected[-1:].isalnum() else ""
    return re.search(f"{before}{needle}{after}", _normalise(answer)) is not None


def classify(
    expected: Expected, *, answer: str | None, error_code: str | None, expected_value: str
) -> Observed:
    """What one cell observed. A refusal is recognised by its code, whatever was expected."""
    if expected == "unknown":
        return "skipped"
    if error_code is not None or answer is None:
        return "refused" if error_code in REFUSAL_CODES else "error"
    return "answered" if answer_contains(answer, expected_value) else "wrong"


def _where(cell: Cell) -> str:
    target = cell.case if cell.case is not None else cell.media_type
    return f"{cell.path} {cell.model} {target}"


# (paths, expected, observed set, message template) — first match wins. ``{where}``,
# ``{observed}`` and ``{code}`` are filled per cell. A ``refuse`` cell that reached the model
# (answered OR wrong) means the gateway would have refused it in production: its listing is
# wrong. Benchmark ``wrong`` is absent on purpose: it is judged per Case.
_CELL_RULES: Final = (
    (
        ("url4", "benchmark"),
        "answer",
        frozenset({"refused", "error"}),
        "{where}: expected an answer, got {observed} ({code})",
    ),
    (
        ("url4", "benchmark"),
        "refuse",
        frozenset({"answered", "wrong"}),
        "{where}: expected a refusal, the model {observed} — capability table stale",
    ),
    (
        ("url4", "benchmark"),
        "refuse",
        frozenset({"error"}),
        "{where}: expected a refusal, got a non-refusal error ({code})",
    ),
    (
        ("url4",),
        "answer",
        frozenset({"wrong"}),
        "{where}: wrong answer, the picture was not read",
    ),
)


def _cell_failure(cell: Cell) -> str | None:
    """The cell's own failure, or ``None``."""
    for paths, expected, observed, template in _CELL_RULES:
        if cell.path in paths and cell.expected == expected and cell.observed in observed:
            return template.format(
                where=_where(cell), observed=cell.observed, code=cell.code or "no code"
            )
    return None


def _chat_call_failure(cell: Cell) -> str | None:
    """A ``refused`` cell whose trace still shows a gateway chat call was not refused up front."""
    if cell.observed == "refused" and cell.chat_calls:
        return (
            f"{_where(cell)}: refused ({cell.code or 'no code'}) but {cell.chat_calls} gateway"
            " chat call(s) ran under its trace — not a refusal before the model"
        )
    return None


def _cases_every_model_missed(cells: Sequence[Cell]) -> list[str]:
    """Benchmark Cases on which every model expected to answer answered wrong."""
    by_case: dict[str, list[Cell]] = defaultdict(list)
    for cell in cells:
        if cell.path == "benchmark" and cell.expected == "answer" and cell.case is not None:
            by_case[cell.case].append(cell)
    return [
        f"benchmark {case}: every vision model answered wrong — the picture did not arrive"
        for case, group in by_case.items()
        if all(c.observed == "wrong" for c in group)
    ]


def verdict(cells: Sequence[Cell]) -> list[str]:
    """The matrix's failures, in plain words; an empty list is a pass.

    An empty matrix fails: a run that evaluated no cell proved nothing (unknown is never a pass).
    """
    if not cells:
        return ["matrix: no cell was evaluated — nothing proves the picture arrived"]
    failures = [
        reason
        for cell in cells
        for reason in (_cell_failure(cell), _chat_call_failure(cell))
        if reason is not None
    ]
    return failures + _cases_every_model_missed(cells)
