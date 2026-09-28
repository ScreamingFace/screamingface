"""The grading-call scope — which Case's judge call is this, as an ambient tag.

One ContextVar serves two readers (OME-1240): the judge provider reads the Case id
to register the call against that Case's evidence, and the connector's model-call
lifecycle log lines read it to tag a judge round trip with its Case — so the engine
log can answer "what happened to case 7's judge call" by grep alone.
"""

from __future__ import annotations

from screamingface_engine.grading_call_scope import (
    current_grading_case,
    grading_call_log_suffix,
    grading_call_scope,
)


def test_the_scope_is_unset_by_default() -> None:
    assert current_grading_case() is None
    assert grading_call_log_suffix() == ""


def test_the_scope_carries_the_case_and_restores_on_exit() -> None:
    with grading_call_scope(7):
        assert current_grading_case() == 7
        # The suffix leads with a space so log format strings append it verbatim.
        assert grading_call_log_suffix() == " role=judge case=7"
    assert current_grading_case() is None
    assert grading_call_log_suffix() == ""


def test_the_scope_restores_even_when_the_body_raises() -> None:
    try:
        with grading_call_scope(3):
            raise RuntimeError("judge exploded")
    except RuntimeError:
        pass
    assert current_grading_case() is None
