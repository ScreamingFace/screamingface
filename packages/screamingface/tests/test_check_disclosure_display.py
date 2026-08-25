"""The paid-check disclosure picks its carrier: panel when rendering, warning otherwise.

FEATURE: OME-845 — the check-call ceiling used to arrive as a Python warning, which
Jupyter paints as a red stderr banner on every evaluate call. The disclosure is about
money and must never be silent, but it is information, not an alarm.
STORY: as a researcher evaluating a corrective loop in a notebook, I read the ceiling
as a calm pre-flight line inside the evaluation panel; headless callers still get the
Python warning, so the ceiling never disappears with the panel.
"""

from __future__ import annotations

import io
import warnings
from typing import Any, cast

import pytest

from screamingface._evaluation import progress as progress_module
from screamingface._evaluation.model import _compiled_candidate, _compiled_operation
from screamingface._evaluation.progress import _progress_observer
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import _evaluation_fragments
from screamingface.warnings import EvaluationWarning

_DISCLOSURE = "Benchmark 'draco' may make up to 6 paid check calls (6 per case x 1 cases)"


def _runtime_fragments_html(
    state: _EvaluationProgress,
    benchmark: str | None,
    elapsed: float | None,
    check_disclosure: str | None,
) -> str:
    return "".join(_evaluation_fragments(state, benchmark, elapsed, check_disclosure))


def _headless_stream() -> io.StringIO:
    # StringIO.isatty() is False — the "no panel, no terminal" environment.
    return io.StringIO()


def _panel_progress() -> _EvaluationProgress:
    operation = _compiled_operation(
        id="op_model",
        kind="model",
        label="model answer",
        depends_on=(),
    )
    return _EvaluationProgress(
        candidates=(
            _compiled_candidate(
                name="model",
                kind="model",
                models=("provider/model",),
                url4="(@)!'model'",
                operations=(operation,),
            ),
        ),
        case_count=1,
    )


def test_headless_evaluation_still_warns() -> None:
    # INVARIANT: the disclosure is never silent — with no panel to carry it, the
    # Python warning remains the carrier.
    with pytest.warns(EvaluationWarning, match="6 paid check calls"):
        observer = _progress_observer(None, stream=_headless_stream(), check_disclosure=_DISCLOSURE)
    assert observer is None


def test_progress_off_still_warns() -> None:
    # Turning the panel off is a display preference, not consent to hidden spend.
    with pytest.warns(EvaluationWarning, match="6 paid check calls"):
        observer = _progress_observer(
            False, stream=_headless_stream(), check_disclosure=_DISCLOSURE
        )
    assert observer is None


def test_a_rendering_panel_suppresses_the_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    # When the notebook panel is built it carries the disclosure itself; warning too
    # would reintroduce the red banner OME-845 removes.
    taken: dict[str, str | None] = {}

    def fake_notebook_observer(candidates, case_count, benchmark, check_disclosure=None):
        del candidates, case_count, benchmark
        taken["disclosure"] = check_disclosure
        return lambda event: None

    monkeypatch.setattr(progress_module, "_in_notebook", lambda: True)
    monkeypatch.setattr(progress_module, "_notebook_observer", fake_notebook_observer)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        observer = _progress_observer(
            None,
            stream=_headless_stream(),
            candidates=cast(Any, (object(),)),
            case_count=1,
            check_disclosure=_DISCLOSURE,
        )
    assert observer is not None
    assert taken["disclosure"] == _DISCLOSURE


def test_panel_construction_failure_falls_back_to_the_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The degrade path (ipywidgets unavailable, comm failure) must not lose the
    # disclosure along with the panel.
    monkeypatch.setattr(progress_module, "_in_notebook", lambda: True)
    monkeypatch.setattr(progress_module, "_notebook_observer", lambda *a, **k: None)
    with pytest.warns(EvaluationWarning, match="6 paid check calls"):
        observer = _progress_observer(None, stream=_headless_stream(), check_disclosure=_DISCLOSURE)
    assert observer is not None  # text progress still runs; only the carrier changed


def test_no_disclosure_never_warns() -> None:
    # Model/Fusion candidates have no check surface — nothing to disclose, no warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        observer = _progress_observer(None, stream=_headless_stream(), check_disclosure=None)
    assert observer is None


def test_the_panel_renders_the_disclosure_line() -> None:
    html = _runtime_fragments_html(_panel_progress(), "draco", None, "up to 6 paid check <calls>")
    assert "sf-eval__note" in html
    assert "check surface · up to 6 paid check &lt;calls&gt;" in html


def test_the_panel_omits_the_line_without_a_disclosure() -> None:
    html = _runtime_fragments_html(_panel_progress(), "draco", None, None)
    # The class exists in the stylesheet either way; the LINE must not render.
    assert "check surface ·" not in html
    assert "<div class='sf-eval__note'>" not in html
