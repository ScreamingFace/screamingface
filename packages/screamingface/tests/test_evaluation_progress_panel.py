from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import screamingface as sf
from screamingface._evaluation.model import Candidate, _compiled_candidate, _compiled_operation
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import (
    _compact,
    _duration,
    _money,
    evaluation_panel_html,
)

_START = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def candidate(name: str = "opus", model: str = "provider/opus") -> Candidate:
    operation = _compiled_operation(
        id=f"op_{name}",
        kind="model",
        label=f"{name} answer",
        depends_on=(),
    )
    return _compiled_candidate(
        name=name,
        kind="model",
        models=(model,),
        url4=f"(@)!'{name}'",
        operations=(operation,),
    )


def envelope(sequence: int, *, run_id: str = "run_opus") -> dict[str, Any]:
    return {
        "id": f"{run_id}_{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "timestamp": _START + timedelta(seconds=sequence),
        "source": f"/trace/{run_id}/node/{sequence}",
    }


def model_span(sequence: int, **overrides: Any) -> sf.events.Span:
    values: dict[str, Any] = {
        "name": "chat",
        "operation": "chat",
        "start": _START,
        "end": _START + timedelta(seconds=2),
        "request_model": "provider/opus",
        "input_tokens": 1_000,
        "output_tokens": 250,
    }
    values.update(overrides)
    return sf.events.Span(**envelope(sequence), **values)


def progress(*candidates: Candidate) -> _EvaluationProgress:
    selected = candidates or (candidate(),)
    return _EvaluationProgress(candidates=selected, case_count=2)


def test_model_spans_accumulate_calls_tokens_failures_and_refusals() -> None:
    opus = candidate()
    state = progress(opus)

    state.observe(opus, model_span(1))
    state.observe(opus, model_span(2, status="error", input_tokens=10, output_tokens=0))
    state.observe(opus, model_span(3, refusal="declined"))

    row = state.rows[0]
    assert (row.model_calls, row.failed_calls, row.refusals) == (3, 1, 1)
    assert (row.input_tokens, row.output_tokens) == (2_010, 500)


def test_structural_spans_do_not_count_as_model_work() -> None:
    opus = candidate()
    state = progress(opus)

    state.observe(
        opus,
        sf.events.Span(
            **envelope(1),
            name="TextNode",
            operation="TextNode",
            start=_START,
            end=_START,
        ),
    )

    assert state.rows[0].model_calls == 0


def test_subtree_usage_is_ignored_so_cost_is_not_double_counted() -> None:
    opus = candidate()
    state = progress(opus)
    for sequence, scope, amount in ((1, "self", "0.25"), (2, "subtree", "99")):
        state.observe(
            opus,
            sf.events.Usage(
                **envelope(sequence),
                scope=cast(Any, scope),
                provider="provider",
                model="opus",
                pricing_version="v1",
                usage=sf.Usage(cost_usd=Decimal(amount)),
            ),
        )

    assert state.rows[0].cost_usd == Decimal("0.25")


def test_nested_termination_does_not_change_the_candidate_status() -> None:
    opus = candidate()
    state = progress(opus)
    root = "/trace/run_opus/node/root"
    state.observe(
        opus,
        sf.events.Started(**{**envelope(1), "source": root}, url4=opus.url4),
    )

    state.observe(
        opus,
        sf.events.Terminated(**envelope(2), status="failed"),
    )

    assert state.rows[0].status == "running"

    state.observe(
        opus,
        sf.events.Terminated(**{**envelope(3), "source": root}, status="failed"),
    )

    assert state.rows[0].status == "run_failed"


def test_live_cache_rate_excludes_bypasses() -> None:
    opus = candidate()
    state = progress(opus)
    state.observe(opus, model_span(1, cache_status="hit"))
    state.observe(opus, model_span(2, cache_status="miss"))
    state.observe(opus, model_span(3, cache_status="bypass", cache_reason="stream"))

    assert state.rows[0].cache_totals == (1, 1, 1)
    assert state.rows[0].cache_hit_rate == 0.5
    assert state.cache_bypass_breakdown == (("stream", 1),)


def test_authoritative_cache_summary_replaces_live_counts_and_reasons() -> None:
    opus = candidate()
    state = progress(opus)
    state.observe(opus, model_span(1, cache_status="bypass", cache_reason="stream"))
    state.observe(
        opus,
        sf.events.Log(
            **envelope(2),
            severity_number=9,
            severity_text="INFO",
            body="cache summary",
            attributes={
                "cache.hits": 6,
                "cache.misses": 3,
                "cache.bypasses": 91,
                "cache.bypass.unsupported_control": 74,
                "cache.bypass.opted_out": 17,
            },
        ),
    )

    assert state.rows[0].cache_totals == (6, 3, 91)
    assert state.cache_bypass_breakdown == (
        ("unsupported_control", 74),
        ("opted_out", 17),
    )


def test_cache_evidence_from_candidates_aggregates_without_overwriting() -> None:
    opus = candidate()
    gpt = candidate("gpt", "provider/gpt")
    state = progress(opus, gpt)
    state.observe(opus, model_span(1, cache_status="hit"))
    state.observe(
        gpt,
        sf.events.Span(
            **envelope(1, run_id="run_gpt"),
            name="chat",
            operation="chat",
            start=_START,
            end=_START,
            request_model="provider/gpt",
            cache_status="bypass",
            cache_reason="metadata",
        ),
    )

    assert state.cache_totals == (1, 0, 1)
    assert state.cache_bypass_breakdown == (("metadata", 1),)


def test_unstated_bypass_reason_remains_distinct_from_other() -> None:
    opus = candidate()
    state = progress(opus)
    state.observe(opus, model_span(1, cache_status="bypass"))
    state.observe(opus, model_span(2, cache_status="bypass", cache_reason="other"))

    assert state.cache_bypass_breakdown == (("other", 1), ("unstated", 1))


def test_panel_escapes_candidate_identity_and_global_errors() -> None:
    selected = candidate("<script>", "provider/<model>")
    state = progress(selected)
    state.abort(RuntimeError("bad <payload>"))

    html = evaluation_panel_html(state, "DRACO <private>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "provider/&lt;model&gt;" in html
    assert "bad &lt;payload&gt;" in html
    assert "DRACO &lt;private&gt;" in html


def test_cache_band_renders_truthful_empty_and_bypass_states() -> None:
    opus = candidate()
    state = progress(opus)

    empty = evaluation_panel_html(state)

    assert "no cache activity reported" in empty
    assert "bypassed" not in empty

    state.observe(opus, model_span(1, cache_status="bypass", cache_reason="opted_out"))
    bypassed = evaluation_panel_html(state)

    assert "1 bypassed" in bypassed
    assert "opted_out 1" in bypassed


def test_visible_cache_text_uses_readable_ink_two() -> None:
    html = evaluation_panel_html(progress())
    label = html.split(".sf-eval__cache-k{", 1)[1].split("}", 1)[0]
    body = html.split(".sf-eval__cache-of,", 1)[1].split("}", 1)[0]

    assert "var(--sf-ink-2)" in label
    assert "var(--sf-ink-2)" in body
    assert "--sf-ink-3" not in label
    assert "--sf-ink-3" not in body


def test_live_figure_formatters_cover_large_small_and_long_values() -> None:
    assert _compact(2_000_000) == "2.0M"
    assert _money(Decimal("0.005")) == "$0.0050"
    assert _duration(65) == "1m 05s"
    assert _duration(3_665) == "1h 01m"
