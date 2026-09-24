from test_evaluation_progress_panel import candidate, model_span, progress

from screamingface._ui.evaluation_view import _receipt_html


def test_receipt_reserves_summary_before_usage_arrives() -> None:
    item = candidate()
    state = progress(item)
    assert _receipt_html(state) == "<div class='sf-eval__receipt'>0 model calls</div>"

    state.observe(item, model_span(1))
    assert _receipt_html(state) == (
        "<div class='sf-eval__receipt'>1 model call · 1.0k in / 250 out</div>"
    )
