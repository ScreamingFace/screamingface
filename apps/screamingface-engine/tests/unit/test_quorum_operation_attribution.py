"""Optional shared routes must not fabricate evidence of a member's success."""

import pytest

from screamingface_engine.benchmarks.operation_outputs import attribute_operation_outputs
from screamingface_engine.operation_calls import OperationCall
from url4 import RelExpr, Source, expr, render, src, text


def _model(binding, *, path="/shared") -> Source:
    model = src(
        RelExpr(path=path, context="$input", intent=text("Answer")),
        name=binding,
        weight=0.0,
    )
    assert isinstance(model, Source)
    return model


def _candidate(*, nested, distinct=False):
    first = _model("model_1")
    second = _model("model_2", path="/other" if distinct else "/shared")
    if nested:
        first = src(expr(first, intent=text("$model_1")), name="member_1", required=False)
        second = src(expr(second, intent=text("$model_2")), name="member_2", required=True)
        sources = [
            src(
                expr(first, second, intent=text(""), params={"quorum": 1}),
                name="panel_1",
                weight=0.0,
            )
        ]
    else:
        first = src(first.value, name="model_1", weight=0.0, required=False)
        sources = [first, second]
    return render(expr(*sources, intent=text("FINAL")))


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "composite"])
@pytest.mark.parametrize("call_count", [1, 2, 3])
def test_optional_shared_fingerprint_stays_unknown(nested, call_count):
    # INVARIANT: retry count and identical answers cannot prove which claimant
    # executed. Even as many recorded calls as bindings may belong to one member.
    calls = [OperationCall("/shared", (), "ANSWER", "stop", None)] * call_count
    operations = attribute_operation_outputs(_candidate(nested=nested), calls)
    assert operations is not None
    assert [(op.operation_id, op.output, op.finish_reason) for op in operations] == [
        ("op_model_1", None, None),
        ("op_model_2", None, None),
    ]


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "composite"])
def test_optional_unique_fingerprints_keep_their_answers(nested):
    calls = [
        OperationCall("/shared", (), "FIRST", "stop", None),
        OperationCall("/other", (), "SECOND", "stop", None),
    ]
    operations = attribute_operation_outputs(_candidate(nested=nested, distinct=True), calls)
    assert operations is not None
    assert [(op.output, op.finish_reason) for op in operations] == [
        ("FIRST", "stop"),
        ("SECOND", "stop"),
    ]
