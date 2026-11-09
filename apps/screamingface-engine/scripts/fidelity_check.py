"""Which Fidelity Records can still be trusted today? (OME-1471)

Run as `just engine fidelity-check [--markdown]`, which is
`uv run --isolated --extra inspect python scripts/fidelity_check.py`.

FEATURE: a Fidelity Record (docs/benchmarks-fidelity/<id>.md) freezes a verdict about one
Benchmark at audit time: "our exam gives the same marks as the paper's", with evidence. The
catalogue keeps moving after that: a grading fix changes the Benchmark's computed fingerprint,
a bump changes the pinned harness link. This script compares each record's two fingerprint
values with today's declaration and says, per Benchmark, fresh / stale / no record / orphan
record. It is a report for a human, not a gate; it opens no socket and calls no model.

Mental model: the record is a dated receipt that names the exam paper it graded (the
fingerprint) and the answer key it compared against (the harness link). The script holds every
receipt up against today's paper and key.

Stages, in execution order (the stage comments below carry the same numbers):

  ① load_records   — read the front matter of every record; refuse malformed ones by name.
  ② declared_today — ask the registry for every Benchmark's id, origin, computed fingerprint and
                     harness_url (the same calls the fingerprint golden test makes, so the two
                     can never disagree about what "the fingerprint" is).
  ③ compare        — one Row per catalogue id (sorted) plus one per orphan record.
  ④ render + exit  — a text or GitHub table and a count line; exit 1 only when a record is
                     malformed or names a parity test file that does not exist.

Worked example. The IFEval record says `fingerprint.benchmark: ada07458a23c55ab`. Someone fixes
a checker in the vendored grading code, which moves the computed fingerprint to 1f3e9c0d2b4a6e8f.
The row reads `ifeval  stale  fingerprint ada07458a23c55ab → 1f3e9c0d2b4a6e8f`: the verdict was
true for an exam that no longer exists, so audit again. Nothing moved → `fresh`. No file →
`no record`. A file for an id the catalogue no longer has → `orphan record`.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ENGINE_ROOT: Path = Path(__file__).resolve().parents[1]
_RECORDS_DIR: Path = _ENGINE_ROOT / "docs" / "benchmarks-fidelity"

VERDICTS: frozenset[str] = frozenset(
    {"comparable-to-paper", "comparable-to-inspect", "not-comparable", "unverified"}
)
#: Verdicts whose front matter must say why (spec §2.1).
_VERDICTS_NEEDING_A_REASON: frozenset[str] = frozenset({"not-comparable", "unverified"})
_REFERENCE_KEYS: tuple[str, ...] = ("paper", "original_harness", "inspect_evals", "inspect_ai")
_FINGERPRINT: re.Pattern[str] = re.compile(r"^[0-9a-f]{16}$")
# WHY: a reference link must land the reader on the exact code or paper version the audit read,
# so its path carries a commit sha or a `v`-tag (`.../tree/v0.20.0`, `.../tree/0c495b2…`,
# `arxiv.org/abs/2311.07911v1`). The same idea as the declaration's harness_url pin rule.
_PINNED_PATH: re.Pattern[str] = re.compile(r"(?:^|/|\d)(?:v\d+(?:\.\d+)*|[0-9a-f]{7,40})(?:/|$)")
#: Upper-case stems (TEMPLATE.md, README.md) sit beside the records and are not records.
_NOT_A_RECORD: re.Pattern[str] = re.compile(r"^[A-Z]")


@dataclass(frozen=True)
class Record:
    """The front matter of one Fidelity Record, already validated (spec §2.1)."""

    benchmark: str
    origin: str
    verdict: str
    verdict_reason: str
    audited: str
    audited_at: str
    fingerprint_benchmark: str
    fingerprint_harness_url: str
    parity_test: str | None  # an Engine-relative path, or None for the literal `none`
    parity_test_reason: str


@dataclass(frozen=True)
class Declared:
    """What the catalogue says about one Benchmark today."""

    benchmark: str
    origin: str
    fingerprint: str
    harness_url: str | None


@dataclass(frozen=True)
class Row:
    """One output line: a catalogue id, or an orphan record's id."""

    benchmark: str
    status: str  # fresh | stale | no record | orphan record
    moved: tuple[str, ...]  # one entry per fingerprint value that moved, old → new
    verdict: str
    audited: str
    parity: str  # yes | none: <reason> | MISSING <path> | "" when there is no record


class _Malformed(Exception):
    """A record the script refuses; the message names the key."""


def _front_matter(text: str) -> dict[str, Any]:
    """The YAML block between the first two `---` lines, as a mapping."""

    if not text.startswith("---\n"):
        raise _Malformed("no front matter block")
    end: int = text.find("\n---", 4)
    if end < 0:
        raise _Malformed("front matter never closes")
    loaded: object = yaml.safe_load(text[4:end])
    if not isinstance(loaded, dict):
        raise _Malformed("front matter is not a mapping")
    return {str(key): value for key, value in loaded.items()}


def _string(data: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> str:
    """One required string key; empty only where the spec allows it."""

    if key not in data:
        raise _Malformed(f"missing key {key}")
    value: object = data[key]
    if value is None and allow_empty:
        return ""
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _Malformed(f"{key} must be a non-empty string")
    return value


def _verdict(data: Mapping[str, Any]) -> tuple[str, str]:
    """The verdict word and its reason; the reason is required for the two doubtful verdicts."""

    verdict: str = _string(data, "verdict")
    if verdict not in VERDICTS:
        raise _Malformed(f"verdict {verdict!r} is not one of {sorted(VERDICTS)}")
    verdict_reason: str = _string(data, "verdict_reason", allow_empty=True)
    if verdict in _VERDICTS_NEEDING_A_REASON and not verdict_reason.strip():
        raise _Malformed(f"verdict_reason is required for verdict {verdict}")
    return verdict, verdict_reason


def _fingerprint(data: Mapping[str, Any]) -> tuple[str, str]:
    """The two values the verdict rested on: the computed fingerprint and the harness link."""

    block: object = data.get("fingerprint")
    if not isinstance(block, dict):
        raise _Malformed("missing key fingerprint")
    benchmark: str = _string(block, "benchmark")
    if not _FINGERPRINT.match(benchmark):
        raise _Malformed("fingerprint.benchmark must be 16 lower-case hex characters")
    return benchmark, _string(block, "harness_url")


def _check_references(data: Mapping[str, Any]) -> None:
    """Every reference link is pinned, so a reader lands on what the audit read."""

    block: object = data.get("references")
    if not isinstance(block, dict):
        raise _Malformed("missing key references")
    for key in _REFERENCE_KEYS:
        url: str = _string(block, key)
        if not url.startswith(("https://", "http://")) or not _PINNED_PATH.search(url):
            raise _Malformed(f"references.{key} must be an http(s) URL pinned to a sha or v-tag")


def _parity_fields(data: Mapping[str, Any]) -> tuple[str | None, str]:
    """The parity test path (None for the literal `none`) and the reason `none` requires."""

    raw: str = _string(data, "parity_test")
    reason: str = _string(data, "parity_test_reason", allow_empty=True)
    parity_test: str | None = None if raw == "none" else raw
    if parity_test is None and not reason.strip():
        raise _Malformed("parity_test_reason is required when parity_test is none")
    return parity_test, reason


def _record(stem: str, data: Mapping[str, Any]) -> Record:
    """Validate one record's front matter; every rule here is a spec §2.1 bullet."""

    benchmark: str = _string(data, "benchmark")
    if benchmark != stem:
        raise _Malformed(f"benchmark {benchmark!r} does not equal the file stem {stem!r}")
    verdict, verdict_reason = _verdict(data)
    fingerprint_benchmark, fingerprint_harness_url = _fingerprint(data)
    _check_references(data)
    parity_test, parity_test_reason = _parity_fields(data)
    return Record(
        benchmark=benchmark,
        origin=_string(data, "origin"),
        verdict=verdict,
        verdict_reason=verdict_reason,
        audited=str(_required(data, "audited")),
        audited_at=str(_required(data, "audited_at")),
        fingerprint_benchmark=fingerprint_benchmark,
        fingerprint_harness_url=fingerprint_harness_url,
        parity_test=parity_test,
        parity_test_reason=parity_test_reason,
    )


def _required(data: Mapping[str, Any], key: str) -> object:
    """A key that must be present; YAML may parse it as a date, so no type is imposed."""

    if key not in data or data[key] is None:
        raise _Malformed(f"missing key {key}")
    return data[key]


def load_records(records_dir: Path, engine_root: Path) -> tuple[dict[str, Record], list[str]]:
    """Stage ① — every record in the folder, and one message per record the script refuses.

    A malformed record is dropped from the returned mapping, so it can never read as fresh;
    `engine_root` is where `parity_test` paths resolve (checked in Stage ③, not here).
    """

    del engine_root  # the signature mirrors main()'s inputs; paths resolve in compare()
    records: dict[str, Record] = {}
    malformed: list[str] = []
    for path in sorted(records_dir.glob("*.md")):
        if _NOT_A_RECORD.match(path.stem):
            continue
        try:
            records[path.stem] = _record(path.stem, _front_matter(path.read_text()))
        except (_Malformed, yaml.YAMLError) as exc:
            malformed.append(f"{path.name}: {exc}")
    return records, malformed


def declared_today() -> dict[str, Declared]:
    """Stage ② — every Benchmark the catalogue registers today, by id.

    WHY the lazy imports: the plugin needs the inspect extra, and the pure stages must load
    without it so their tests run in the extra-less suite. The calls mirror
    tests/unit/inspect/test_benchmark_fingerprints.py's `_fingerprint`, so this script and that
    golden can never disagree about what a Benchmark's fingerprint is.
    """

    from screamingface_engine.benchmarks.medxpert import definition as medxpert
    from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark

    declared: dict[str, Declared] = {
        medxpert.MEDXPERT.id: Declared(
            benchmark=medxpert.MEDXPERT.id,
            origin=medxpert.MEDXPERT.origin,
            fingerprint=medxpert.FINGERPRINT,
            harness_url=medxpert.MEDXPERT.harness_url,
        )
    }
    for spec in BENCHMARKS:
        imported = imported_benchmark(spec.key)
        declared[imported.benchmark.id] = Declared(
            benchmark=imported.benchmark.id,
            origin=imported.benchmark.origin,
            fingerprint=imported.fingerprint,
            harness_url=imported.benchmark.harness_url,
        )
    return declared


def _parity(record: Record, engine_root: Path) -> str:
    if record.parity_test is None:
        return f"none: {record.parity_test_reason}"
    if (engine_root / record.parity_test).is_file():
        return "yes"
    return f"MISSING {record.parity_test}"


def compare(
    records: Mapping[str, Record],
    declared: Mapping[str, Declared],
    *,
    engine_root: Path = _ENGINE_ROOT,
) -> list[Row]:
    """Stage ③ — one Row per catalogue id, sorted, then one per orphan record.

    INVARIANT: a record is `fresh` only when BOTH values it rested on equal today's; a record
    for an id the catalogue no longer has is an `orphan record`, never silently dropped.
    """

    rows: list[Row] = []
    for benchmark in sorted(declared):
        today: Declared = declared[benchmark]
        record: Record | None = records.get(benchmark)
        if record is None:
            rows.append(Row(benchmark, "no record", (), "", "", ""))
            continue
        moved: list[str] = []
        if record.fingerprint_benchmark != today.fingerprint:
            moved.append(f"fingerprint {record.fingerprint_benchmark} → {today.fingerprint}")
        if record.fingerprint_harness_url != (today.harness_url or "none"):
            moved.append(f"harness_url {record.fingerprint_harness_url} → {today.harness_url}")
        status: str = "stale" if moved else "fresh"
        rows.append(
            Row(
                benchmark,
                status,
                tuple(moved),
                record.verdict,
                record.audited,
                _parity(record, engine_root),
            )
        )
    for benchmark in sorted(set(records) - set(declared)):
        record = records[benchmark]
        rows.append(
            Row(
                benchmark,
                "orphan record",
                (),
                record.verdict,
                record.audited,
                _parity(record, engine_root),
            )
        )
    return rows


def render(rows: Sequence[Row], *, markdown: bool) -> str:
    """Stage ④ — the table and the count line, as plain text or a GitHub table."""

    header: tuple[str, ...] = ("benchmark", "status", "moved", "verdict", "audited", "parity test")
    cells: list[tuple[str, ...]] = [
        (row.benchmark, row.status, "; ".join(row.moved), row.verdict, row.audited, row.parity)
        for row in rows
    ]
    counts: str = "  ".join(
        f"{sum(1 for row in rows if row.status == status)} {status}"
        for status in ("fresh", "stale", "no record", "orphan record")
    )
    if markdown:
        lines: list[str] = [
            "| " + " | ".join(header) + " |",
            "|" + "---|" * len(header),
            *("| " + " | ".join(cell) + " |" for cell in cells),
        ]
        return "\n".join(lines) + f"\n\n{counts}\n"
    widths: list[int] = [
        max(len(header[i]), *(len(cell[i]) for cell in cells)) if cells else len(header[i])
        for i in range(len(header))
    ]
    text_lines: list[str] = [
        "  ".join(value.ljust(widths[i]) for i, value in enumerate(line)).rstrip()
        for line in (header, *cells)
    ]
    return "\n".join(text_lines) + f"\n\n{counts}\n"


def main(
    argv: Sequence[str] | None = None, *, declared: Mapping[str, Declared] | None = None
) -> int:
    """Stages ① to ④; `declared` is injectable so the pure path tests without the extra."""

    parser = argparse.ArgumentParser(description="Which Fidelity Records can be trusted today?")
    parser.add_argument("--records", type=Path, default=_RECORDS_DIR)
    parser.add_argument("--engine-root", type=Path, default=_ENGINE_ROOT)
    parser.add_argument("--markdown", action="store_true", help="print a GitHub table")
    args = parser.parse_args(argv)

    records, malformed = load_records(args.records, args.engine_root)
    today: Mapping[str, Declared] = declared if declared is not None else declared_today()
    rows: list[Row] = compare(records, today, engine_root=args.engine_root)
    sys.stdout.write(render(rows, markdown=args.markdown))
    for message in malformed:
        sys.stdout.write(f"MALFORMED {message}\n")
    missing: int = sum(1 for row in rows if row.parity.startswith("MISSING"))
    return 1 if malformed or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
