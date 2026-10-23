"""Generate the workbench notebooks (e2e workbench spec §3.3).

The notebooks under ``notebooks/`` are BUILD OUTPUT: committed output-free and byte-identical
to what this module renders (``test_build_notebooks`` enforces it). Edit the builder, then run::

    uv run python tests/e2e/workbench/build_notebooks.py          # regenerate
    uv run python tests/e2e/workbench/build_notebooks.py --check  # exit 1 on drift

WHY generated: the replay recipe must be the exact candidate the golden recorded, so it is
rendered from the golden file rather than hand-copied into a notebook where it could drift.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import nbformat

# Run as a script, ``tests/e2e`` is not on sys.path; under pytest it already is.
_E2E_ROOT: Final = Path(__file__).resolve().parents[1]
if str(_E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(_E2E_ROOT))

from harness._gating import GOLDENS_DIR  # noqa: E402
from harness.goldens import GoldenModelSpec, GoldenReport, load_golden  # noqa: E402

from workbench.runner import RESULT_PREFIX, RESULT_TAG  # noqa: E402

NOTEBOOK_DIR: Final = Path(__file__).resolve().parent / "notebooks"

_INDENT: Final = "    "
_WRAP_AT: Final = 72  # string literals longer than this split into implicit concatenation
_KERNELSPEC: Final = {"name": "python3", "display_name": "Python 3", "language": "python"}


# --- golden recipe → Python source ------------------------------------------------------------


def _q(value: str) -> str:
    """``repr`` in ruff-format's preferred double quotes (so the notebook passes format --check)."""
    literal = repr(value)
    if literal.startswith("'") and '"' not in value:
        # repr picks single quotes here only when the value has no quote at all, so the
        # body needs no re-escaping.
        literal = f'"{literal[1:-1]}"'
    return literal


def _value(value: str | int | float | bool) -> str:
    return _q(value) if isinstance(value, str) else repr(value)


def _dict(mapping: Mapping[str, str | int | float | bool]) -> str:
    return "{" + ", ".join(f"{_q(key)}: {_value(val)}" for key, val in mapping.items()) + "}"


def _str(value: str, indent: str) -> str:
    """A deterministic string literal; long ones split on spaces into ``("…" "…")``."""
    if len(_q(value)) <= _WRAP_AT:
        return _q(value)
    chunks: list[str] = []
    for word in re.findall(r"\S*\s*", value):  # words keep their trailing whitespace
        if chunks and len(chunks[-1]) + len(word) <= _WRAP_AT - 4:
            chunks[-1] += word
        elif word:
            chunks.append(word)
    inner = indent + _INDENT
    body = "".join(f"{inner}{_q(chunk)}\n" for chunk in chunks)
    return f"(\n{body}{indent})"


def _call(func: str, args: Sequence[str], indent: str) -> str:
    """``func(\\n    arg,\\n)`` — one argument per line, trailing commas, ruff-format shaped."""
    inner = indent + _INDENT
    body = "".join(f"{inner}{arg},\n" for arg in args)
    return f"{func}(\n{body}{indent})"


def _list(items: Sequence[str], indent: str) -> str:
    inner = indent + _INDENT
    body = "".join(f"{inner}{item},\n" for item in items)
    return f"[\n{body}{indent}]"


def _model(spec: GoldenModelSpec, indent: str) -> str:
    """Mirrors ``harness.goldens.spec_model``: route, then prompt and params only when set."""
    inner = indent + _INDENT
    args = [_q(spec.model)]
    if spec.prompt is not None:
        args.append(f"prompt={_str(spec.prompt, inner)}")
    if spec.params:
        args.append(f"params={_dict(spec.params)}")
    return _call("sf.Model", args, indent)


def _render_loop(golden: GoldenReport) -> str:
    assert golden.judge_spec is not None and golden.max_rounds is not None  # validator-held
    members = _list([_model(spec, _INDENT * 2) for spec in golden.member_specs], _INDENT)
    return _call(
        "sf.CorrectiveLoop",
        [
            members,
            f"judge={_model(golden.judge_spec, _INDENT)}",
            f"max_rounds={golden.max_rounds!r}",
        ],
        "",
    )


def _render_fusion(golden: GoldenReport) -> str:
    members = _list([_q(route) for route in golden.models], _INDENT)
    return _call(
        "sf.Fusion",
        [members, f"name={_q(golden.recipe or '')}", f"synthesizer={_q(golden.synthesizer or '')}"],
        "",
    )


def _render_model(golden: GoldenReport) -> str:
    if len(golden.models) != 1:
        raise ValueError(f"a 'model' golden names exactly one model, got {len(golden.models)}")
    return f"sf.Model({_q(golden.models[0])})"


_RENDERERS: Final[dict[str, Callable[[GoldenReport], str]]] = {
    "corrective_loop": _render_loop,
    "fusion": _render_fusion,
    "model": _render_model,
}


def render_golden_candidate(golden: GoldenReport) -> str:
    """Python source binding ``candidate`` to exactly what ``build_candidate(golden)`` builds.

    Expects ``sf`` (``import screamingface as sf``) in scope. Literals are ``repr``-rendered
    (double-quoted for ruff format), so the output is a pure function of the golden.
    """
    return f"candidate = {_RENDERERS[golden.kind](golden)}\n"


# --- notebook cells ---------------------------------------------------------------------------


def _code(source: str, *tags: str) -> nbformat.NotebookNode:
    cell = nbformat.v4.new_code_cell(source.strip("\n"))
    if tags:
        cell.metadata["tags"] = list(tags)
    return cell


def _markdown(source: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_markdown_cell(source.strip("\n"))


def _require_one_result(cells: list[nbformat.NotebookNode]) -> None:
    """Review finding 6: the runner refuses anything but ONE ``workbench-result`` cell printing
    ONE marker, so a notebook of any other shape must never be built."""
    tagged = [c for c in cells if RESULT_TAG in c.metadata.get("tags", [])]
    if len(tagged) != 1:
        raise ValueError(f"exactly one cell tagged {RESULT_TAG!r} required, found {len(tagged)}")
    markers = sum(c.source.count(RESULT_PREFIX) for c in cells)
    if markers != 1 or tagged[0].source.count(RESULT_PREFIX) != 1:
        raise ValueError(
            f"exactly one {RESULT_PREFIX} marker required, in the {RESULT_TAG!r} cell;"
            f" found {markers} in the notebook"
        )


def _notebook(stem: str, cells: list[nbformat.NotebookNode], meta: dict[str, Any]) -> Any:
    _require_one_result(cells)
    nb = nbformat.v4.new_notebook(cells=cells)
    nb.metadata["kernelspec"] = dict(_KERNELSPEC)
    nb.metadata["workbench"] = meta
    for i, cell in enumerate(nb.cells):
        cell["id"] = f"{stem}-{i:02d}"  # fixed ids: rebuilds are byte-identical
    return nb


_QUICKSTART_TITLE = """
# Quickstart: one evaluation, end to end

Builds one candidate, evaluates it on `BENCHMARK`, and asserts that the client minted a trace
id, the candidate compiled to url4, and the score sits in the hand-set `SCORE_BAND`. The
`workbench-result` cell reports the trace ids right after the evaluation, before any
assertion, so a failing check still leaves them in the evidence. If `client.evaluate()` itself
raises, the SDK error's `trace_id` is reported instead and the error re-raised after the
result cell. The workbench then requires each id to appear in the engine and aigateway logs.

On `replay` the recipe is the golden ifeval recipe (served from the recorded cache, no spend);
on `local` it is the authored open-source fusion below, run with your OpenRouter key.
"""

_QUICKSTART_PARAMETERS = """
ENGINE_URL = "http://127.0.0.1:9108"
SCOREBOARD_URL = "http://127.0.0.1:9106"  # always explicit; replay has none and never calls it
RECIPE = "authored"  # "golden" on replay: the exact recipe the ifeval tape recorded
BENCHMARK = "ifeval"
LIMIT = 1
SCORE_BAND = [0.0, 1.0]  # hand-set sanity band (owner decision 2026-10-16)
EXPECT_CACHED = False
"""

_QUICKSTART_CLIENT = """
import json
import os

import screamingface as sf

if not SCOREBOARD_URL:  # spec §3.1: never fall back to the hosted leaderboard
    raise ValueError("SCOREBOARD_URL must be explicit")
client = sf.Client(engine_url=ENGINE_URL, scoreboard_url=SCOREBOARD_URL)
if os.environ.get("OPENROUTER_API_KEY") and RECIPE == "authored":
    client.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])
"""

_QUICKSTART_AUTHORED = """
else:
    ANSWER = (
        "Answer the request accurately and completely. "
        "Follow every instruction and formatting constraint in the request."
    )
    SYNTH = (
        "Produce the single best answer to the original request by combining the panel "
        "drafts. Preserve every instruction and formatting constraint stated in the "
        "original prompt."
    )
    candidate = sf.Fusion(
        [
            sf.Model("openrouter/deepseek/deepseek-v4-pro", prompt=ANSWER),
            sf.Model("openrouter/qwen/qwen3-coder", prompt=ANSWER),
        ],
        name="best_open_source",
        synthesizer=sf.Model("openrouter/z-ai/glm-5.2", prompt=SYNTH),
    )
candidate
"""

# WHY catch the SDK error here and re-raise it after the result cell (review gap (a)): a run
# minted before the failure carries its id on `sf.ScreamingFaceError.trace_id` (OME-967), and
# the bundle can only correlate the logs of that run if the result cell gets to report it.
# Only the SDK's public error is held back; anything else is a notebook bug and fails here.
_QUICKSTART_EVALUATE = """
report = None
evaluate_error = None
try:
    report = client.evaluate(candidate, benchmark=BENCHMARK, limit=LIMIT, progress=False)
except sf.ScreamingFaceError as exc:
    evaluate_error = exc
    report = getattr(exc, "partial_report", None)  # ExecutionError: the Candidates that ran
"""

# WHY after the result cell: a failing assert must still leave the trace ids in the bundle
# (Review Focus 1), so the workbench can check the chain of the run that misbehaved.
_QUICKSTART_ASSERT = """
if evaluate_error is not None:
    raise evaluate_error
(result,) = list(report.candidates)
assert result.trace_id, "the client minted no trace id (OME-967)"
assert result.url4, "the candidate compiled to no url4"
assert result.score is not None and SCORE_BAND[0] <= result.score <= SCORE_BAND[1], result.score
if EXPECT_CACHED:
    assert result.cache_hits > 0, "expected a warm cache on this target"
report
"""

_QUICKSTART_RESULT = """
ran = list(report.candidates) if report is not None else []
error_trace_id = evaluate_error.trace_id if evaluate_error is not None else None
trace_ids = [c.trace_id for c in ran if c.trace_id] + [error_trace_id]
print(
    "WORKBENCH_RESULT="
    + json.dumps(
        {
            "trace_ids": [t for t in dict.fromkeys(trace_ids) if t],
            "run_ids": [str(c.run_id) for c in ran],
            "candidates": {
                c.name: {
                    "score": c.score,
                    "cache_hits": c.cache_hits,
                    "cache_saved_cost_usd": str(c.cache_saved_cost_usd),
                }
                for c in ran
            },
            "evaluate_error": None
            if evaluate_error is None
            else {"type": type(evaluate_error).__name__, "code": evaluate_error.code},
        }
    )
)
"""


def _quickstart() -> Any:
    golden = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    recipe = (
        'if RECIPE == "golden":\n'
        + textwrap.indent(render_golden_candidate(golden), _INDENT)
        + _QUICKSTART_AUTHORED.strip("\n")
    )
    cells = [
        _markdown(_QUICKSTART_TITLE),
        _code(_QUICKSTART_PARAMETERS, "parameters"),
        _code(_QUICKSTART_CLIENT),
        _code(recipe),
        _code(_QUICKSTART_EVALUATE),
        _code(_QUICKSTART_RESULT, RESULT_TAG),
        _code(_QUICKSTART_ASSERT),
        _code("client.close()"),
    ]
    meta = {"targets": ["replay", "local"], "required_result": ["trace_ids"]}
    return _notebook("quickstart", cells, meta)


_BUILDERS: Final[dict[str, Callable[[], Any]]] = {"quickstart": _quickstart}


def serialize(nb: nbformat.NotebookNode) -> str:
    """The on-disk bytes: ``nbformat.writes`` plus the final newline ``nbformat.write`` adds
    (and the repo's end-of-file-fixer hook demands)."""
    return nbformat.writes(nb) + "\n"


def build() -> dict[str, nbformat.NotebookNode]:
    """Every workbench notebook, keyed by stem, rendered fresh."""
    return {stem: builder() for stem, builder in _BUILDERS.items()}


# --- CLI --------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the workbench notebooks.")
    parser.add_argument("--check", action="store_true", help="exit 1 if a file is stale")
    parser.add_argument("--out", type=Path, default=NOTEBOOK_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    out: Path = args.out
    stale: list[str] = []
    for stem, nb in build().items():
        path = out / f"{stem}.ipynb"
        text = serialize(nb)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(path.name)
        else:
            out.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print(f"stale: {', '.join(stale)}; run build_notebooks.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
