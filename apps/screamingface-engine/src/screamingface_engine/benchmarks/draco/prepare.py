"""Download the pinned DRACO dataset and emit its private runtime assets.

Run at IMAGE BUILD time, never at run time: a Job's rootfs is read-only apart
from `/tmp` and it holds no HuggingFace credential, so every benchmark artifact
must exist before the Job starts.

    uv run python -m screamingface_engine.benchmarks.draco.prepare \
        --out /opt/benchmarks/draco --limit 5

Emits::

    <out>/cases.json           [{"id": …, "input": …}]  — the ONLY thing a client ever sees
    <out>/criteria/<id>.json   [{id, requirement, criterion_type}] — private task-builder input
    <out>/rubrics/<id>.json    the weighted rubric      — private, read by `aggregate.py`

INVARIANT: the judge NEVER sees weights. `grading_mode: "official"` (arXiv:2602.11685 §4.2)
judges one criterion at a time, blind to its weight and to its siblings; a judge that can see a
weight can infer how much a criterion is worth and bias toward the expensive ones. The weights
therefore live ONLY in `rubrics/`, which `aggregate.py` reads after the judging is done.

INVARIANT: `cases.json` carries NO rubric. It is the Candidate-facing input, and a rubric column
here would put the grading criteria straight into the prompt the Candidate answers. This is a
protocol boundary, not a secrecy one: `perplexity-ai/draco` is a public dataset and each Case
Result publishes its graded criteria, so nothing here is an undisclosed answer key.

Dataset: `perplexity-ai/draco` (arXiv:2602.11685). Column mapping mirrors
`screamingface-benchmarks/benchmarks_config/draco.yaml`:

    problem → the research prompt   ·   answer → the weighted rubric JSON   ·   domain → metadata
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
from screamingface_engine.benchmarks.draco.definition import (
    ASSET_BUNDLE_ID,
    CASE_COUNT,
    DATASET,
    DATASET_REVISION,
    EXCLUDED_DOMAINS,
    RETRIEVAL_POLICY_ID,
)
from screamingface_engine.benchmarks.draco.scoring import flatten_criteria
from screamingface_engine.benchmarks.registry import DEFAULT_BENCHMARK_ASSETS_ROOT

COLUMN_QUESTION = "problem"
COLUMN_RUBRIC = "answer"
COLUMN_DOMAIN = "domain"

"""The blocklist a DRACO candidate answers under, derived from
`screamingface-benchmarks/benchmarks_config/draco.yaml` and reduced to HOSTS.

DRACO is a deep-research benchmark, so a candidate that retrieves the dataset card, the
reproduction post, or the paper is reading the answer key. That INFLATES the score, which is why
it does not look like a bug.

Upstream's list is page-shaped (`huggingface.co/datasets/perplexity-ai/draco`,
`arxiv.org/abs/2509`). Those values cannot ship: the provider rejects anything longer than a host
with a 400 that fails the entire call, so a page-shaped list does not weaken the guard — it stops
the benchmark. Ours is therefore NOT byte-comparable with the reference harness, and that is a
deliberate divergence rather than a drift.

AIDEV-NOTE: still a floor, not a ceiling — the benchmarks repo calls their list "our best guess"
and OpenRouter never published theirs. Extend it from the audit logs in eval JSONLs (`tool_calls`
in metadata) as real leak sources turn up. The Engine embeds this list in the Benchmark's
``/candidate`` call and hashes it into the Benchmark revision; this file is the matching audit
copy baked into the image. Add HOSTS; anything longer is a 400.
"""


class PrepareError(BenchmarkAssetPreparationError):
    """The dataset could not be turned into a declared world."""


def load_rows(limit: int | None = None) -> list[dict[str, Any]]:
    """Download the dataset and return its rows.

    `datasets` is NOT a dependency of screamingface-engine. This module runs at
    image BUILD time on a machine that has it; the Job that later serves the
    artifacts needs only the emitted files.

    # WHY: `importlib` rather than a plain import; the same pattern `url4.peer.server` uses for
    # its optional uvicorn extra. A static import would make an optional build-time package look
    # like a hard dependency to every reader and to the type checker, for a module that a
    # deployed Job never imports at all.
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
    for split in loaded:  # null split in draco.yaml means "all splits"
        for row in loaded[split]:
            rows.append(dict(row))
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def parse_rubric(raw: Any, case_id: int) -> dict[str, Any]:
    """Decode the `answer` column into the rubric object the grader walks.

    The column is a JSON STRING holding ``{"sections": [{"criteria": [...]}]}``. A rubric that
    flattens to zero criteria is rejected loudly: it would score every answer 0.0 while looking
    like a successful run.
    """
    rubric = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(rubric, dict) or "sections" not in rubric:
        got = list(rubric)[:5] if isinstance(rubric, dict) else type(rubric).__name__
        raise PrepareError(
            f"case {case_id}: rubric has no 'sections' key — got {got}. A flat criteria list "
            "is a different grader (healthbench_rubric), not this one."
        )
    if sum(1 for _ in flatten_criteria(rubric)) == 0:
        raise PrepareError(f"case {case_id}: rubric flattened to 0 criteria")
    return rubric


def judge_criteria(rubric: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The criteria as the JUDGE sees them — id, requirement, and sign-derived type.

    The official protocol hides the numeric weight but explicitly supplies whether a criterion
    is positive or negative. Deriving that label here preserves both requirements: the judge can
    interpret MET correctly without learning how strongly the criterion affects the score.

    INVARIANT: this projects the scorer's shared ``flatten_criteria`` walk rather than maintaining
    a second traversal. It names the three safe fields explicitly so the attached numeric weight
    can never cross the judge boundary.
    """
    return [
        {
            "id": criterion.get("id"),
            "requirement": criterion.get("requirement", ""),
            "criterion_type": ("negative" if float(criterion.get("weight", 0)) < 0 else "positive"),
        }
        for criterion in flatten_criteria(rubric)
    ]


def build(
    rows: Sequence[dict[str, Any]],
    out: Path,
    *,
    expected_count: int | None = None,
) -> dict[str, Any]:
    """Write the cases and private criterion/rubric files read by DRACO's runtime."""
    if expected_count is not None and len(rows) != expected_count:
        raise PrepareError(
            f"expected {expected_count} DRACO cases, but the pinned dataset produced {len(rows)}"
        )
    rubric_dir = out / "rubrics"
    criteria_dir = out / "criteria"
    rubric_dir.mkdir(parents=True, exist_ok=True)
    criteria_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        case_id = index + 1  # 1-based and stable for a given dataset order
        question = row.get(COLUMN_QUESTION)
        if not question:
            raise PrepareError(f"case {case_id}: empty {COLUMN_QUESTION!r} column")
        rubric = parse_rubric(row.get(COLUMN_RUBRIC), case_id)
        (rubric_dir / f"{case_id}.json").write_text(json.dumps(rubric, indent=1), encoding="utf-8")
        (criteria_dir / f"{case_id}.json").write_text(
            json.dumps(judge_criteria(rubric)), encoding="utf-8"
        )
        cases.append(
            {"id": case_id, "input": question, "domain": row.get(COLUMN_DOMAIN) or "unknown"}
        )

    write_policy(out)
    (out / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return {"cases": len(cases), "out": str(out)}


def write_policy(out: Path) -> Path:
    """Emit the retrieval policy an expression names with `;web_search_policy=`.

    An OBJECT rather than a bare array so the policy can version itself — `id` is what a
    published score cites — and can later carry other retrieval settings without a second route.

    INVARIANT: an EMPTY blocklist is rejected HERE, at build time. The runner deliberately
    accepts an empty policy, because a benchmark may declare unrestricted retrieval as an
    explicit, attributable statement — but for DRACO an empty list means the generator broke, and
    a generation bug belongs to the build rather than to a run that would score high and look
    clean.
    """
    if not EXCLUDED_DOMAINS:
        raise PrepareError("the retrieval policy is empty — a DRACO run needs its blocklist")
    # INVARIANT: bare hosts only, enforced at BUILD time. A path or wildcard is a 400 from the
    # provider on every answering call, which surfaces as a run that terminates SUCCEEDED with a
    # zero score — so the build is the last place it can still be loud. MEASURED 2026-08-02:
    # "Invalid domain 'arxiv.org/abs/2602.11685'".
    malformed = sorted(d for d in EXCLUDED_DOMAINS if any(c in d for c in "/*:"))
    if malformed:
        raise PrepareError(
            f"retrieval policy entries must be bare hosts, got {malformed} — a path or wildcard "
            "is rejected by the provider with a 400 that fails every answering call"
        )
    policy_dir = out / "policy"
    policy_dir.mkdir(parents=True, exist_ok=True)
    path = policy_dir / "retrieval.json"
    path.write_text(
        json.dumps(
            {
                "id": RETRIEVAL_POLICY_ID,
                "excluded_domains": list(EXCLUDED_DOMAINS),
                "note": (
                    "Best-effort proxy for the OpenRouter post's blocklist, which was never "
                    "published. Entries are UNVERIFIED — see prepare.EXCLUDED_DOMAINS."
                ),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return path


def _prepare(out: Path, limit: int | None) -> dict[str, Any]:
    return build(
        load_rows(limit),
        out,
        expected_count=CASE_COUNT if limit is None else limit,
    )


def prepare(out: Path) -> dict[str, Any]:
    """Prepare the complete deployable DRACO asset bundle."""

    return _prepare(out, None)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="draco-prepare", description=__doc__)
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
