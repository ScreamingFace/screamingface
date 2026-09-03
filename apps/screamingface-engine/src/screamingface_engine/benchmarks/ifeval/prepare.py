"""Download the pinned IFEval dataset and emit its private runtime assets.

Run at IMAGE BUILD time, never at run time: a Job's rootfs is read-only apart from `/tmp`
and it has no network egress, so every benchmark artifact must exist before the Job starts.

    uv run --with datasets python -m screamingface_engine.benchmarks.ifeval.prepare \
        --out /opt/benchmarks/ifeval [--limit 5]

Emits::

    <out>/cases.json              [{"id": …, "input": …}]  — the ONLY thing a client sees
    <out>/instructions/<id>.json  {key, prompt, instruction_id_list, kwargs} — private,
                                  read by `runtime.py` (check) and `aggregate.py`
    <out>/nltk_data/              punkt + punkt_tab tokenizers — offline corpus for the
                                  vendored verifier (never downloaded at run time)

INVARIANT — `cases.json` carries NO instruction ids or kwargs. The client receives case
ids and prompts while the machine-checkable constraints stay in the image, so a Candidate
cannot be tuned against the answer key.

INVARIANT — a case's public id IS the official IFEval ``key`` (unique ints, e.g. 2785),
NOT a sequential index. Every per-case artifact joins directly to the official dataset
and third-party IFEval results; consumers must never assume ids are 1..n or ascending
in case order (the official keys are not sorted). The SELECTION order — what a
``limit`` slice picks — is the row order of ``cases.json``, which is the official
file's row order; ``aggregate.load_case_order`` reads it back.

INVARIANT — rows are VERIFIED against the vendored official dataset
(``vendor/data/input_data.jsonl``) and the official text WINS. The pinned HF snapshot
diverges from the official harness data on exactly one row: key 2785, where the HF
prompt says "at least one placeholder" while its own kwargs (and the official prompt)
require 3. `build` patches that prompt to the official text and FAILS LOUDLY if the
divergence set is ever anything other than {2785} — a new mismatch means the pin or
the official file changed, which is a protocol event, not something to paper over.

Dataset: HF `google/IFEval` (arXiv:2311.07911), 541 rows, single `train` split. Fields:
``key / prompt / instruction_id_list / kwargs`` with kwargs positionally parallel to the
instruction ids.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine.benchmarks.ifeval.definition import (
    ASSET_BUNDLE_ID,
    CASE_COUNT,
    DATASET,
    DATASET_REVISION,
)
from screamingface_engine.benchmarks.registry import DEFAULT_BENCHMARK_ASSETS_ROOT


class PrepareError(BenchmarkAssetPreparationError):
    """The dataset could not be turned into a declared world."""


# The one known HF-vs-official divergence; see the module docstring. Any OTHER key in
# the computed divergence set fails the build.
KNOWN_DIVERGENT_KEYS = frozenset({2785})


def official_rows() -> list[dict[str, Any]]:
    """The vendored official dataset, in its file order — the authority rows are
    verified and patched against."""

    from importlib import resources

    data = resources.files("screamingface_engine.benchmarks.ifeval.vendor").joinpath(
        "data/input_data.jsonl"
    )
    return [json.loads(line) for line in data.read_text("utf-8").splitlines() if line.strip()]


def verify_against_official(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int]]:
    """Return (rows with official-text patches applied, keys patched), or raise on
    unknown drift.

    Comparison is per official ``key`` over the graded surface: prompt,
    instruction_id_list, and null-stripped kwargs. A row whose key the official file
    does not know, a missing/duplicate key, or a divergence outside
    KNOWN_DIVERGENT_KEYS is a loud failure.
    """

    by_key = {row["key"]: row for row in official_rows()}
    seen: set[int] = set()
    patched: list[dict[str, Any]] = []
    divergent: set[int] = set()
    for row in rows:
        key = row.get("key")
        if not isinstance(key, int):
            raise PrepareError(f"row has a non-int official key: {key!r}")
        if key in seen:
            raise PrepareError(f"duplicate official key {key} in the dataset")
        seen.add(key)
        authority = by_key.get(key)
        if authority is None:
            raise PrepareError(f"key {key} is not in the official dataset")
        if row.get("instruction_id_list") != authority["instruction_id_list"] or strip_nulls(
            row.get("kwargs") or []
        ) != strip_nulls(authority["kwargs"]):
            raise PrepareError(
                f"key {key}: instruction ids/kwargs diverge from the official dataset — "
                "the HF pin or the vendored official file changed; audit before rebuilding"
            )
        if row.get("prompt") != authority["prompt"]:
            divergent.add(key)
            row = dict(row) | {"prompt": authority["prompt"]}
        patched.append(row)
    unknown = divergent - KNOWN_DIVERGENT_KEYS
    if unknown:
        raise PrepareError(
            f"prompts diverge from the official dataset on unexpected keys {sorted(unknown)}; "
            f"only {sorted(KNOWN_DIVERGENT_KEYS)} is a known, patched divergence"
        )
    return patched, divergent


def load_rows(limit: int | None = None) -> list[dict[str, Any]]:
    """Download the pinned dataset and return its rows.

    `datasets` is NOT a dependency of screamingface-engine — this module runs at image BUILD time on
    a machine that has it; the Job that serves the artifacts needs only the emitted files.
    """

    try:
        datasets_mod = importlib.import_module("datasets")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc

    loaded = datasets_mod.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = []
    for split in loaded:  # IFEval ships a single `train` split; iterate for uniformity
        for row in loaded[split]:
            rows.append(dict(row))
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def strip_nulls(kwargs_list: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Drop None-valued kwargs keys.

    WHY: a raw `datasets` load pads every kwargs dict with all-None keys for schema
    uniformity; passing a None through ``build_description`` would override a checker's
    real default and crash or, worse, silently change the constraint.
    """

    return [
        {key: value for key, value in kwargs.items() if value is not None} for kwargs in kwargs_list
    ]


def build(
    rows: Sequence[dict[str, Any]],
    out: Path,
    *,
    expected_count: int | None = None,
) -> dict[str, Any]:
    """Write the public cases and private instruction specs read by IFEval's runtime."""

    if expected_count is not None and len(rows) != expected_count:
        raise PrepareError(
            f"expected {expected_count} IFEval cases, but the pinned dataset produced {len(rows)}"
        )
    rows, patched_keys = verify_against_official(rows)
    instructions_dir = out / "instructions"
    instructions_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    for row in rows:
        case_id = row["key"]  # the official IFEval key — see the module invariant
        prompt = row.get("prompt")
        if not prompt:
            raise PrepareError(f"case {case_id}: empty 'prompt' column")
        instruction_ids = row.get("instruction_id_list")
        kwargs_list = row.get("kwargs")
        if not isinstance(instruction_ids, list) or not instruction_ids:
            raise PrepareError(f"case {case_id}: empty instruction_id_list")
        if not isinstance(kwargs_list, list) or len(kwargs_list) != len(instruction_ids):
            raise PrepareError(
                f"case {case_id}: kwargs must be positionally parallel to instruction_id_list"
            )
        spec = {
            "key": case_id,
            "prompt": prompt,
            "instruction_id_list": instruction_ids,
            "kwargs": strip_nulls(kwargs_list),
        }
        (instructions_dir / f"{case_id}.json").write_text(json.dumps(spec), encoding="utf-8")
        cases.append({"id": case_id, "input": prompt})

    (out / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return {"cases": len(cases), "patched_keys": sorted(patched_keys), "out": str(out)}


def prepare_nltk(out: Path) -> dict[str, Any]:
    """Download the tokenizer corpus the vendored verifier reads, into the assets dir.

    Build-time network use is deliberate — the run-time Job reads this directory via
    ``grading.configure_nltk`` and never downloads.
    """

    import nltk

    from screamingface_engine.benchmarks.ifeval.grading import configure_nltk

    target = out / "nltk_data"
    target.mkdir(parents=True, exist_ok=True)
    # WHY: nltk>=3.10's downloader rejects any target not registered in nltk.data.path
    # ("Security Violation: Unauthorized path"), so the directory is authorized first —
    # the same registration the run-time reader uses.
    configure_nltk(target)
    for resource in ("punkt", "punkt_tab"):
        if not nltk.download(resource, quiet=True, download_dir=str(target)):
            raise PrepareError(f"could not download the nltk resource {resource!r}")
    return {"nltk_data": str(target)}


def _prepare(out: Path, limit: int | None) -> dict[str, Any]:
    summary = build(
        load_rows(limit),
        out,
        expected_count=CASE_COUNT if limit is None else limit,
    )
    return summary | prepare_nltk(out)


def prepare(out: Path) -> dict[str, Any]:
    """Prepare the complete deployable IFEval asset bundle, including NLTK data."""

    return _prepare(out, None)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ifeval-prepare", description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_BENCHMARK_ASSETS_ROOT / ASSET_BUNDLE_ID,
    )
    parser.add_argument("--limit", type=int, default=None, help="cap the case count (probes)")
    args = parser.parse_args(argv)

    try:
        summary = _prepare(args.out, args.limit)
    except PrepareError as exc:
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
