# pyright: reportMissingImports=false
# WHY file-level: this script imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Task 0 of OME-1460: what happens to each Hugging Face-path Benchmark under Task replay.

FEATURE: one Case Preparation path (OME-1460, plan Task 0, P1). Evidence tooling, not
production code: it imports only existing functions and writes nothing into the repo.

Think of it as a dress rehearsal before the move: every Benchmark still prepared from the
Hugging Face path is prepared twice, once the old way and once by calling the eval's own task
function, and the two booklets are compared. Stages, per Benchmark key, in execution order:

    Stage 1 — the old way: load today's pinned rows and prepare today's Cases into a scratch
              directory; note the upstream Sample ids the old way kept.
    Stage 2 — one import-mode replay with the task args and seeds the row implies; compare
              its Cases with today's: identical, order only, or N Cases differ (with the
              first differing pair), and the kept Sample id sets.
    Stage 3 — the full Task-replay import (two runs, the second with the pins forced): the
              verdict is ``imported`` or ``refused: <reason>``.
    Stage 4 — list each Hub repo the replay read and the revision it passed; a repo read
              with no commit is D4's list.

Example line: ``gsm8k  imported  1319 → 1319  ids identical  text identical  hub
openai/gsm8k@cc7b047b…``.

Usage (needs network; xstest needs a Hugging Face token or a cached login)::

    uv run python scripts/sweep_task_replay_fold.py [KEY ...] > sweep.txt

It never runs inspect's ``eval()``: no model, scorer or Judge; nothing is paid for.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screamingface_engine_inspect.fetch_pins import is_commit_sha
from screamingface_engine_inspect.import_replay import (
    ImportReplay,
    TaskReplayImport,
    import_by_task_replay,
    replay_for_import,
)
from screamingface_engine_inspect.importer import ImporterError
from screamingface_engine_inspect.prepare import (
    BENCHMARK_CASES,
    CasesSpec,
    PreparedCase,
    PrepareError,
    _load_rows,
    _pinned_samples,
    prepare_cases,
)

#: Each Hugging Face-path key's inspect task and the task args the row implies (spec R12):
#: few-shot off for gsm8k and winogrande (D2); the subset for xstest and coconot.
TASKS: dict[str, tuple[str, dict[str, Any] | None]] = {
    "gsm8k": ("inspect_evals.gsm8k.gsm8k:gsm8k", {"fewshot": 0}),
    "mmlu": ("inspect_evals.mmlu.mmlu:mmlu_0_shot", None),
    "arc_easy": ("inspect_evals.arc.arc:arc_easy", None),
    "arc_challenge": ("inspect_evals.arc.arc:arc_challenge", None),
    "commonsense_qa": ("inspect_evals.commonsense_qa.commonsense_qa:commonsense_qa", None),
    "paws": ("inspect_evals.paws.paws:paws", None),
    "boolq": ("inspect_evals.boolq.boolq:boolq", None),
    "mmlu_pro": ("inspect_evals.mmlu_pro.mmlu_pro:mmlu_pro", None),
    "winogrande": ("inspect_evals.winogrande.winogrande:winogrande", {"fewshot": 0}),
    "race_h": ("inspect_evals.race_h.race_h:race_h", None),
    "aime24": ("inspect_evals.aime2024.aime2024:aime2024", None),
    "aime25": ("inspect_evals.aime2025.aime2025:aime2025", None),
    "musr": ("inspect_evals.musr.musr:musr", None),
    "wmdp_bio": ("inspect_evals.wmdp.wmdp:wmdp_bio", None),
    "wmdp_chem": ("inspect_evals.wmdp.wmdp:wmdp_chem", None),
    "wmdp_cyber": ("inspect_evals.wmdp.wmdp:wmdp_cyber", None),
    "hellaswag": ("inspect_evals.hellaswag.hellaswag:hellaswag", None),
    "lab_bench_litqa": ("inspect_evals.lab_bench.lab_bench:lab_bench_litqa", None),
    "lab_bench_suppqa": ("inspect_evals.lab_bench.lab_bench:lab_bench_suppqa", None),
    "lab_bench_dbqa": ("inspect_evals.lab_bench.lab_bench:lab_bench_dbqa", None),
    "lab_bench_protocolqa": ("inspect_evals.lab_bench.lab_bench:lab_bench_protocolqa", None),
    "lab_bench_seqqa": ("inspect_evals.lab_bench.lab_bench:lab_bench_seqqa", None),
    "lab_bench_cloning_scenarios": (
        "inspect_evals.lab_bench.lab_bench:lab_bench_cloning_scenarios",
        None,
    ),
    "frontierscience": ("inspect_evals.frontierscience.frontierscience:frontierscience", None),
    "onet_m6": ("inspect_evals.onet.onet:onet_m6", None),
    "pubmedqa": ("inspect_evals.pubmedqa.pubmedqa:pubmedqa", None),
    "xstest_safe": ("inspect_evals.xstest.xstest:xstest", {"subset": "safe"}),
    "xstest_unsafe": ("inspect_evals.xstest.xstest:xstest", {"subset": "unsafe"}),
    "coconot_original": ("inspect_evals.coconot.coconot:coconot", {"subset": "original"}),
    "coconot_contrast": ("inspect_evals.coconot.coconot:coconot", {"subset": "contrast"}),
}

#: How much of a differing Case the report quotes.
_QUOTE_CHARS: int = 160


@dataclass(frozen=True)
class SweepLine:
    """One Benchmark's rehearsal result."""

    key: str
    verdict: str
    today_count: int | None
    replayed_count: int | None
    ids: str
    text: str
    hub: str

    def render(self) -> str:
        """The tab-separated line the ledger quotes."""

        counts: str = f"{self.today_count} → {self.replayed_count}"
        return "\t".join((self.key, self.verdict, counts, self.ids, self.text, self.hub))


def _pairs(prepared: list[PreparedCase]) -> list[tuple[str, str]]:
    """Each Case as (input, target): what a candidate reads and what grades it."""

    return [
        (
            json.dumps(case["case"]["input"], ensure_ascii=False),
            str(case["grading_material"].get("target")),
        )
        for case in prepared
    ]


def text_verdict(today: list[PreparedCase], replayed: list[PreparedCase]) -> str:
    """identical / order only / N Cases differ (first differing pair quoted)."""

    old: list[tuple[str, str]] = _pairs(today)
    new: list[tuple[str, str]] = _pairs(replayed)
    if old == new:
        return "text identical"
    if Counter(old) == Counter(new):
        return "order only"
    only_old: Counter[tuple[str, str]] = Counter(old) - Counter(new)
    only_new: Counter[tuple[str, str]] = Counter(new) - Counter(old)
    first_old: str = next(iter(only_old))[0][:_QUOTE_CHARS] if only_old else "-"
    first_new: str = next(iter(only_new))[0][:_QUOTE_CHARS] if only_new else "-"
    return (
        f"{sum(only_new.values())} Cases differ; first today {first_old!r} "
        f"vs replayed {first_new!r}"
    )


def hub_summary(replay: ImportReplay) -> str:
    """Each Hub repo read, with its revision; an unpinned read is flagged for D4."""

    parts: list[str] = []
    for repo_id, revision in dict(replay.hub_fetches).items():
        mark: str = "" if is_commit_sha(revision) else " (NO COMMIT: D4)"
        parts.append(f"{repo_id}@{(revision or 'HEAD')[:12]}{mark}")
    return ", ".join(parts) or "no Hub fetch"


def sweep_one(key: str, scratch: Path) -> SweepLine:
    """Stages 1 to 4 for one Benchmark key."""

    spec: CasesSpec = BENCHMARK_CASES[key]
    task_ref, task_args = TASKS[key]
    # Stage 1
    out: Path = scratch / key / "today"
    prepare_cases(spec, out)
    today: list[PreparedCase] = _read_prepared(out)
    today_ids: set[str] = {
        str(sample.id) for sample in _pinned_samples(spec, _load_rows(spec), spec.case_count)
    }
    # Stage 2
    options: dict[str, Any] = {
        "excluded_sample_ids": spec.excluded_sample_ids,
        "has_answer_key": spec.has_answer_key,
        "shuffle_seed": spec.shuffle_seed,
        "choice_shuffle_seed": spec.choice_shuffle_seed,
    }
    replay: ImportReplay = replay_for_import(task_ref, task_args, **options)
    replayed_ids: set[str] = {str(sample_id) for sample_id in replay.sample_ids}
    ids: str = (
        "ids identical"
        if today_ids == replayed_ids
        else (f"ids differ (-{len(today_ids - replayed_ids)} +{len(replayed_ids - today_ids)})")
    )
    # Stage 3
    try:
        imported: TaskReplayImport = import_by_task_replay(task_ref, task_args, **options)
        verdict: str = f"imported (digest {imported.declaration.case_digest[:12]}…)"
    except ImporterError as exc:
        verdict = f"refused: {exc}"
    # Stage 4
    return SweepLine(
        key=key,
        verdict=verdict,
        today_count=len(today),
        replayed_count=len(replay.prepared),
        ids=ids,
        text=text_verdict(today, replay.prepared),
        hub=hub_summary(replay),
    )


def _read_prepared(out: Path) -> list[PreparedCase]:
    """Read a prepared directory back as the writer's (case, grading_material) pairs."""

    cases: list[dict[str, Any]] = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    return [
        {
            "case": case,
            "grading_material": json.loads(
                (out / "targets" / f"{case['id']}.json").read_text(encoding="utf-8")
            ),
        }
        for case in cases
    ]


def main(keys: list[str]) -> int:
    """Sweep the given keys (default: every Hugging Face-path key); one line each."""

    missing: list[str] = sorted(set(BENCHMARK_CASES) - set(TASKS))
    if missing and not keys:
        print(f"no task reference for {missing}; add them to TASKS", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="sweep-1460-") as scratch:
        for key in keys or sorted(BENCHMARK_CASES):
            try:
                line: SweepLine = sweep_one(key, Path(scratch))
            except (ImporterError, PrepareError) as exc:
                line = SweepLine(key, f"ERROR: {exc}", None, None, "-", "-", "-")
            print(line.render(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
