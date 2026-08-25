"""Bake the GDPval text-subset assets: the public Cases and the private rubrics.

Run at IMAGE BUILD time, never at run time: a Job's rootfs is read-only apart from ``/tmp`` and
holds no HuggingFace credential, so every benchmark artifact must exist before the Job starts.

    uv run --with datasets --with pdfplumber --with python-docx \
        python -m screamingface_engine.benchmarks.gdpval.prepare --out /opt/benchmarks/gdpval

Emits::

    <out>/cases.json          [{"id": 1..102, "input": <candidate-input envelope>}]
    <out>/rubrics/<id>.json   {"task_id", "items": [{"rubric_id", "criterion", "points"}]}

INVARIANT — ``cases.json`` carries NO rubric. The client receives Case ids and inputs while the
answer key stays in the image.

INVARIANT — Engine Case ids are 1-based positions in ``subset.TEXT_SUBSET_TASK_IDS``, not in the
upstream row order. GDPval rows carry stable ``task_id``s, so the selection is addressed by id
and the build ASSERTS every frozen id is present; a dataset that dropped or renamed one fails the
build rather than silently baking a smaller exam under the same identity.

INVARIANT — container criteria are stripped HERE, so no scoring path can include one. A rubric
left with no positive points after stripping fails the build: its score would divide by zero.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine.benchmarks.gdpval.ingestion import (
    IngestionError,
    Reader,
    docx_reader,
    extract_reference_text,
    pdf_reader,
)
from screamingface_engine.benchmarks.gdpval.pins import DATASET, DATASET_REVISION
from screamingface_engine.benchmarks.gdpval.rubric_filter import strip_format_criteria
from screamingface_engine.benchmarks.gdpval.subset import (
    EXCLUDED_TASK_IDS,
    TEXT_SUBSET_TASK_IDS,
)

# WHY a stable delimiter: the reference block is part of the Case input and therefore part of the
# answer key. Its exact bytes must not drift between builds.
_REFERENCE_HEADER = "--- Reference file: {name} ---"

#: ``(task_id, file_name) -> text``. Injected so the policy is testable without the build-time
#: parsing libraries; ``prepare`` supplies the real one.
ReferenceReader = Callable[[str, str], str]

#: Per-file download budget. A reference is a working document, not a dataset.
_FETCH_TIMEOUT_S = 120
_FETCH_ATTEMPTS = 4
_FETCH_BACKOFF_S = 2.0


class PrepareError(BenchmarkAssetPreparationError):
    """The build refuses to bake these assets. Always says which task and why.

    WHY this base: OME-925 made asset preparation auditable, and
    `BenchmarkAssetPreparationError` is the orchestrator's exit-1 channel for dataset and
    answer-key drift — reported to an operator without a traceback. Frozen-id drift and an
    unreadable reference are exactly that, not programming defects.
    """


def select_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the frozen selection, in frozen order.

    INVARIANT: order comes from ``TEXT_SUBSET_TASK_IDS``, never from the upstream file — Engine
    Case ids are positions in that tuple, so inheriting upstream order would renumber the exam
    whenever HuggingFace reshuffled.
    """

    by_id = {str(row["task_id"]): row for row in rows}
    missing = [task_id for task_id in TEXT_SUBSET_TASK_IDS if task_id not in by_id]
    if missing:
        raise PrepareError(
            f"{len(missing)} frozen task id(s) are absent from {DATASET}@{DATASET_REVISION}, "
            f"first {missing[0]!r} — the dataset moved under the frozen selection; refusing to "
            f"bake a different exam under this identity"
        )
    return [by_id[task_id] for task_id in TEXT_SUBSET_TASK_IDS]


def rubric_items(row: Mapping[str, Any], case_id: int) -> list[dict[str, Any]]:
    """The scored criteria for one Case, container checks removed and shapes validated."""

    raw = row.get("rubric_json")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise PrepareError(f"case {case_id}: rubric_json is not JSON: {exc}") from exc
    if not isinstance(parsed, list) or not parsed:
        raise PrepareError(f"case {case_id}: rubric_json must be a non-empty array")

    items: list[dict[str, Any]] = []
    for index, item in enumerate(strip_format_criteria(parsed), start=1):
        if not isinstance(item, dict):
            raise PrepareError(f"case {case_id}: rubric item {index} must be an object")
        criterion = item.get("criterion")
        points = item.get("score")
        if not isinstance(criterion, str) or not criterion.strip():
            raise PrepareError(f"case {case_id}: rubric item {index} lacks a criterion")
        if isinstance(points, bool) or not isinstance(points, int):
            # INVARIANT: ints only — the judge must see "[7]", never "[7.0]", or the grader
            # prompt's bytes change for every future run.
            raise PrepareError(
                f"case {case_id}: rubric item {index} score must be an integer, got {points!r}"
            )
        # INVARIANT: rubric_id is the 1-BASED position. `scoring.case_score` indexes points
        # with `enumerate(points, start=1)` and `verdict.binding_key` refuses anything below 1,
        # so a 0-based id here would silently misalign every criterion with its point value.
        items.append({"rubric_id": index, "criterion": criterion, "points": points})

    if not any(item["points"] > 0 for item in items):
        raise PrepareError(
            f"case {case_id}: no positive-points criterion survives the container filter — "
            f"the score's denominator would be zero"
        )
    return items


def case_input(row: Mapping[str, Any], *, reader: ReferenceReader) -> str:
    """The candidate-input envelope as PLAIN JSON — prompt followed by every reference.

    WHY plain JSON rather than a url4 struct: a value baked into ``cases.json`` is substituted
    into the Candidate call VERBATIM as data, so it must already be what the Runner's envelope
    decoder ``json.loads``es.
    """

    task_id = str(row["task_id"])
    parts = [str(row["prompt"]).strip()]
    for file_name in row.get("reference_files") or []:
        name = str(file_name)
        parts.append(_REFERENCE_HEADER.format(name=name))
        parts.append(reader(task_id, name))
    content = "\n\n".join(parts)
    return json.dumps(
        {"schema": CANDIDATE_INPUT_SCHEMA, "messages": [{"role": "user", "content": content}]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def emit(rows: list[dict[str, Any]], out: Path, *, reader: ReferenceReader) -> int:
    """Write the public cases file and the private rubric assets. Returns the Case count."""

    selected = select_rows(rows)
    rubric_dir = out / "rubrics"
    rubric_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for case_id, row in enumerate(selected, start=1):
        cases.append({"id": case_id, "input": case_input(row, reader=reader)})
        (rubric_dir / f"{case_id}.json").write_text(
            json.dumps(
                {"task_id": str(row["task_id"]), "items": rubric_items(row, case_id)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(cases)


def load_rows() -> list[dict[str, Any]]:
    """Load the pinned dataset revision. Build time only — ``datasets`` is not a dependency."""

    try:
        datasets_mod = importlib.import_module("datasets")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    loaded = datasets_mod.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = []
    for split in loaded:
        rows.extend(dict(row) for row in loaded[split])
    return rows


def reference_urls(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Map every reference file's dataset path to its download URL.

    WHY a map built from ALL rows rather than a per-row lookup: the reader is constructed once
    and closes over this, which keeps ``emit`` and ``case_input`` taking the same two-argument
    reader they are tested against. Dataset paths embed a content hash, so they are unique.
    """

    urls: dict[str, str] = {}
    for row in rows:
        names = row.get("reference_files") or []
        sources = row.get("reference_file_urls") or []
        for name, url in zip(names, sources, strict=False):
            urls[str(name)] = str(url)
    return urls


def _build_reader(cache: Path, urls: Mapping[str, str]) -> ReferenceReader:
    """Download each reference once, then flatten it with the reader for its extension.

    INVARIANT: build time only. The download happens here so a Runner Job — offline, read-only
    rootfs — never needs the network or the original binaries.

    AIDEV-NOTE: the concrete readers are built LAZILY, on first use of each extension. 66 of the
    102 selected tasks carry no reference files at all, and eagerly constructing them would make
    `pdfplumber` and `python-docx` hard requirements of a build that may never open a PDF — and
    would make this function untestable without both installed.
    """

    cache.mkdir(parents=True, exist_ok=True)
    factories = {".pdf": pdf_reader, ".docx": docx_reader, ".doc": docx_reader}
    built: dict[str, Reader] = {}

    def read(task_id: str, file_name: str) -> str:
        suffix = Path(file_name).suffix.casefold()
        factory = factories.get(suffix)
        if factory is None:
            raise IngestionError(
                f"task {task_id}: reference {file_name!r} has no reader for {suffix!r} — the "
                f"selection should contain only prose formats"
            )
        _fetch(task_id, file_name, urls, cache)
        if suffix not in built:
            built[suffix] = factory(cache)
        return extract_reference_text(task_id, file_name, reader=built[suffix])

    return read


def _fetch(task_id: str, file_name: str, urls: Mapping[str, str], cache: Path) -> None:
    """Download one reference into the cache, unless it is already there."""

    destination = cache / file_name
    if destination.is_file() and destination.stat().st_size > 0:
        return
    url = urls.get(file_name)
    if not url:
        raise IngestionError(
            f"task {task_id}: reference {file_name!r} has no download URL in the dataset"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # INVARIANT: the destination path only ever appears COMPLETE. The cache-hit check above is
    # presence plus non-zero size, so a download killed mid-write (Ctrl-C, disk full) would
    # otherwise leave a truncated file that every later run accepts forever — and a truncated
    # PDF that still parses past MIN_VIABLE_CHARS would bake truncated reference text into the
    # answer key. Bytes land in a temp sibling; only a finished download is renamed into place.
    part = destination.with_suffix(destination.suffix + ".part")
    # WHY retry: this fetches 85 files in sequence from a public CDN, and a single reset
    # ("Connection reset by peer") would otherwise abandon a multi-minute build. Bounded, so a
    # genuinely missing file still fails rather than looping.
    last: OSError | None = None
    for attempt in range(_FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_S) as response:
                part.write_bytes(response.read())
        except OSError as exc:
            last = exc
            if attempt + 1 < _FETCH_ATTEMPTS:
                time.sleep(_FETCH_BACKOFF_S * (attempt + 1))
        else:
            os.replace(part, destination)
            return
    part.unlink(missing_ok=True)
    raise IngestionError(
        f"task {task_id}: reference {file_name!r} could not be downloaded after "
        f"{_FETCH_ATTEMPTS} attempts: {last}"
    ) from last


def _default_reference_cache() -> Path:
    """Where downloaded reference binaries live when the caller names no location.

    WHY outside ``out``: ``out`` IS the served asset tree — the Docker build copies
    ``/opt/benchmarks`` wholesale into the Runner image, and the SDK keeps it as the local
    assets dir. The references are already flattened into ``cases.json``, so a cache under
    ``out`` would ship all 85 original PDF/DOCX binaries (tens of MB) for nothing. The dataset
    revision is part of the path so a re-pin can never serve stale binaries from a prior pin.
    """

    return Path(tempfile.gettempdir()) / f"gdpval-references-{DATASET_REVISION[:12]}"


def prepare(out: Path, *, assets_root: Path | None = None) -> dict[str, Any]:
    """Bake the GDPval text-subset assets into ``out``, returning its audit summary."""

    rows = load_rows()
    cache = assets_root or _default_reference_cache()
    try:
        cases = emit(rows, out, reader=_build_reader(cache, reference_urls(rows)))
    except IngestionError as exc:
        # WHY translate: `BenchmarkAssetPreparationError` is the deployment orchestrator's
        # exit-1 channel (OME-925). An IngestionError escaping raw would turn one flaky CDN
        # download into a red image build with a traceback instead of the operator line.
        raise PrepareError(str(exc)) from exc
    return {
        "cases": cases,
        # WHY the exclusions ride the summary: they are a scoring-relevant choice, not an
        # implementation detail. An audit record that showed 102 cases without saying which 7
        # tasks were dropped, and why, would hide the decision it exists to document.
        "excluded_tasks": len(EXCLUDED_TASK_IDS),
        "dataset_revision": DATASET_REVISION,
        "out": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--references", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        summary = prepare(args.out, assets_root=args.references)
    except (PrepareError, IngestionError) as exc:
        print(f"gdpval prepare failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"gdpval: baked {summary['cases']} cases into {args.out} "
        f"({summary['excluded_tasks']} tasks excluded for unusable references)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
