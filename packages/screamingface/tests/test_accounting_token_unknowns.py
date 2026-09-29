"""Retained partial member usage must stay unknown in completed Report totals."""

import json
from dataclasses import replace

import httpx
import pytest
from test_accounting_evaluation import AccountingTransport
from test_client_run import _engine

import screamingface as sf


class PartialTokenTransport(AccountingTransport):
    def __init__(self, input_tokens, output_tokens):
        super().__init__()
        self.usage = sf.Usage(
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd="0.1"
        )

    def run(self, candidate, on_event):
        outcome = super().run(candidate, on_event)
        assert outcome.result_body is not None
        payload = json.loads(outcome.result_body)
        for case in payload["cases"]:
            for operation in case["operations"]:
                operation["accounting"]["usage"] = self.usage.to_dict()
        return replace(
            outcome,
            result_body=json.dumps(payload),
            root_usage=sf.Usage(
                input_tokens=self.usage.input_tokens,
                output_tokens=self.usage.output_tokens,
                cost_usd="0.5",
            ),
        )


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "total", "split"),
    [
        (10, None, "—", "10 / —"),
        (0, None, "—", "0 / —"),
        (None, 10, "—", "— / 10"),
        (None, 0, "—", "— / 0"),
        (None, None, "—", "—"),
        (0, 0, "0", "0 / 0"),
        (10, 4, "14", "10 / 4"),
    ],
)
def test_partial_member_tokens_remain_explicit_after_evaluation(
    input_tokens, output_tokens, total, split
):
    transport = PartialTokenTransport(input_tokens, output_tokens)
    with sf.Client(http_transport=httpx.MockTransport(_engine), run_transport=transport) as client:
        report = client.evaluate(
            sf.Fusion(
                [sf.Model("provider/opus", name="A"), sf.Model("provider/opus", name="B")],
                synthesizer="provider/opus",
            ),
            benchmark="draco",
            on_event=lambda event: None,
            progress=False,
        )
    candidate = report.candidates[0]
    # INVARIANT: the retained usage stays partial; presentation must not manufacture zeroes.
    for member in candidate.members:
        assert member.usage is not None
        assert member.usage.input_tokens == input_tokens
        assert member.usage.output_tokens == output_tokens
    assert candidate.accounting.consistent
    before = report.to_json()
    html = report._repr_html_()
    assert html.count(f"<span class='sf-member__u'>{total}</span>") == 2
    assert f"{split} tokens" in html
    assert report.to_json() == before
