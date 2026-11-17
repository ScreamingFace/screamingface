# pyright: reportMissingImports=false
# WHY file-level: this script imports the crowd-wisdom study package (committee_kit,
# fused_committee) from a path given on the command line; it is not in this repository.
"""Build ``replication.json`` beside this file from the crowd-wisdom study package.

Not part of any test run: it needs the study package (not in this repository) and is kept so the
fixture can be regenerated and checked. Run from the repository root::

    uv run --no-project --with pyarrow python \\
        apps/screamingface-engine/tests/fixtures/futurex_past_study/make_replication_fixture.py \\
        <crowd-wisdom-package> <out.json> <Futurex-Past train parquet at 3c2e3969>

WHY the study's own kit computes ``expected``: the fixture must carry the study's numbers, not
ours, or the replication test would compare our scorer with itself.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any


def _dataset_rows(parquet_path: str, items: list[str]) -> dict[str, dict[str, Any]]:
    """The study items as the 3c2e3969 release holds them: raw key, level, Case position."""

    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = pq.read_table(parquet_path).to_pylist()
    position: dict[str, int] = {f"{r['id']}|{r['end_time']}": n for n, r in enumerate(rows, 1)}
    return {
        item: {
            "ground_truth": rows[position[item] - 1]["ground_truth"],
            "level": rows[position[item] - 1]["level"],
            "position": position[item],
        }
        for item in items
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main(package: Path, out: Path, parquet_path: str) -> None:
    sys.path[:0] = [str(package / "3_results_report"), str(package / "4_fused_committee")]
    import fused_committee
    from committee_kit import corpus, metrics

    data: Path = package / "3_results_report" / "data"
    kit: Any = corpus.load("futurex", str(data))
    gold: dict[str, Any] = {
        row["item_id"]: {
            "level": int(row["level"]),
            "ground_truth": json.loads(row["ground_truth"]),
        }
        for row in _read_csv(data / "futurex_gold.csv")
    }
    raw: dict[str, dict[str, list[str]]] = {}
    for row in _read_csv(data / "futurex_results.csv"):
        model: str = row["model"].split("/")[-1]
        raw.setdefault(model, {})[row["item_id"]] = json.loads(row["answer"] or "[]")
    complete: list[str] = [m for m in kit.models if all(i in kit.answers[m] for i in kit.items)]
    chosen: list[str] = sorted(complete)[:3]
    answers: dict[str, Any] = {m: {i: raw[m][i] for i in kit.items} for m in chosen}
    expected: dict[str, float] = {
        m: metrics.futurex_score(kit.gold, kit.answers[m], kit.items) for m in chosen
    }
    call, _ = fused_committee.stored_reply_call("futurex")
    fused_model: Any = fused_committee.FusedModel("fused-medoids", call=call)
    fused: dict[str, Any] = {
        q["item_id"]: fused_model.answer("futurex", q)["answer"]
        for q in fused_committee.load_questions("futurex")
    }
    answers["fused-medoids"] = {i: fused.get(i) for i in kit.items}
    expected["fused-medoids"] = metrics.futurex_score(kit.gold, fused, kit.items)
    fixture: dict[str, Any] = {
        "dataset_3c2e3969": _dataset_rows(parquet_path, list(kit.items)),
        "source": "crowd-wisdom-package 3_results_report/data + 4_fused_committee replay",
        "gold": {i: gold[i] for i in kit.items},
        "answers": answers,
        "expected": expected,
    }
    text: str = json.dumps(fixture, ensure_ascii=False, indent=1, sort_keys=True)
    out.write_text(text + "\n", encoding="utf-8")  # the end-of-file hook wants a newline
    print(f"{len(complete)} complete models; chosen {chosen}; expected {expected}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
