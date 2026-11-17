# pyright: reportMissingImports=false
# WHY file-level: this script imports the crowd-wisdom study package (committee_kit,
# fused_committee) from a path given on the command line; it is not in this repository.
"""Build ``replication_all_models.json`` beside this file from the crowd-wisdom study package.

``replication.json`` beside it is the first, smaller fixture (three complete models and the fused
committee, scored with ``metrics.futurex_score``), built by this script's first version at commit
c8dadab6c; it is kept unchanged because its tests are.

Not part of any test run: it needs the study package (not in this repository) and is kept so the
fixture can be regenerated and checked. Run from the repository root::

    uv run --no-project --with pyarrow python \\
        apps/screamingface-engine/tests/fixtures/futurex_past_study/make_replication_fixture.py \\
        <crowd-wisdom-package> <out.json> <Futurex-Past train parquet at 3c2e3969>

WHY the study's own kit computes ``expected`` (``rank.score_entry``): the fixture must carry
the study's numbers, not ours, or the replication test would compare our scorer with itself.
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


def _stored_cells(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """model → item → the stored tokens and whether the study excluded the cell (no answer, or
    an uninterpretable box). A cell the study never got (a failed call) is absent."""

    cells: dict[str, dict[str, dict[str, Any]]] = {}
    for row in _read_csv(path):
        model: str = row["model"].split("/")[-1]
        cells.setdefault(model, {})[row["item_id"]] = {
            "tokens": json.loads(row["answer"] or "[]"),
            "excluded": row["excluded"].strip().lower() == "true",
        }
    return cells


def main(package: Path, out: Path, parquet_path: str) -> None:
    sys.path[:0] = [str(package / "3_results_report"), str(package / "4_fused_committee")]
    import fused_committee
    from committee_kit import corpus, rank
    from committee_kit.spec import DEFAULT_AGGREGATION

    data: Path = package / "3_results_report" / "data"
    kit: Any = corpus.load("futurex", str(data))
    gold: dict[str, Any] = {
        row["item_id"]: {
            "level": int(row["level"]),
            "ground_truth": json.loads(row["ground_truth"]),
        }
        for row in _read_csv(data / "futurex_gold.csv")
    }
    answers: dict[str, Any] = _stored_cells(data / "futurex_results.csv")
    # WHY rank.score_entry: it is the study's reporting path (and fused_committee.replay's); it
    # drops a cell nothing usable answered from both sides of the fraction.
    expected: dict[str, float] = {}
    for entry in rank.model_entries(kit, set(kit.models)):
        decisions: Any = rank.decisions_for(entry, kit, DEFAULT_AGGREGATION)
        expected[entry.label] = rank.score_entry(kit, decisions, kit.items)["futurex_score"]
    call, _ = fused_committee.stored_reply_call("futurex")
    fused_model: Any = fused_committee.FusedModel("fused-medoids", call=call)
    questions: list[dict[str, Any]] = fused_committee.load_questions("futurex")
    fused: dict[str, Any] = {
        q["item_id"]: fused_model.answer("futurex", q)["answer"] for q in questions
    }
    # A committee with no majority abstained: the study scores it 0 and keeps it (rank.decide).
    answers["fused-medoids"] = {
        item: {"tokens": fused[item] or [], "excluded": False, "abstained": fused[item] is None}
        for item in kit.items
    }
    expected["fused-medoids"] = fused_committee.replay("fused-medoids")["futurex"]["score"]
    fixture: dict[str, Any] = {
        "dataset_3c2e3969": _dataset_rows(parquet_path, list(kit.items)),
        "source": "crowd-wisdom-package 3_results_report/data + 4_fused_committee replay",
        "prompts": {q["item_id"]: q["prompt"] for q in questions},
        "gold": {i: gold[i] for i in kit.items},
        "answers": answers,
        "expected": expected,
    }
    # WHY compact: all 27 models' cells plus the 100 prompts; indented, the file nears the
    # 500 KB pre-commit cap on added files.
    text: str = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    out.write_text(text + "\n", encoding="utf-8")  # the end-of-file hook wants a newline
    print(f"{len(answers)} entries; expected {expected}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
