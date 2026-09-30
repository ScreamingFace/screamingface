"""The same run preserves generic events and derives semantic member accounting."""

import json
from dataclasses import replace
from decimal import Decimal

import httpx
from test_accounting_breakdown import accounting
from test_client_run import _engine, _ReplayTransport
from test_event_values import NOW, event_envelope

import screamingface as sf


class AccountingTransport(_ReplayTransport):
    def run(self, candidate, on_event):
        original = super().run(candidate, on_event)
        assert original.result_body is not None
        assert callable(on_event)
        payload = json.loads(original.result_body)
        payload["cases"][0]["operations"] = [
            dict(
                operation_id=op.id,
                output="Answer",
                finish_reason="stop",
                accounting=accounting().to_dict(),
            )
            for op in candidate.operations
        ]
        self.events = [
            sf.events.Span(
                **event_envelope(), name="call", operation="chat", start=NOW, end=NOW, status="ok"
            ),
            sf.events.Usage(
                **event_envelope(sequence=2),
                scope="self",
                provider="provider",
                model="provider/opus",
                pricing_version="fixture",
                usage=sf.Usage(input_tokens=999, output_tokens=888, cost_usd="9"),
            ),
        ]
        for event in self.events:
            on_event(event)
        return replace(
            original, result_body=json.dumps(payload), root_usage=sf.Usage(cost_usd="0.5")
        )


def test_member_usage_and_live_events_come_from_separate_authorities():
    transport = AccountingTransport()
    events = []
    with sf.Client(http_transport=httpx.MockTransport(_engine), run_transport=transport) as client:
        report = client.evaluate(
            sf.Fusion(
                [sf.Model("provider/opus", name="A"), sf.Model("provider/opus", name="B")],
                synthesizer="provider/opus",
            ),
            benchmark="draco",
            on_event=events.append,
            progress=False,
        )
    assert events == transport.events
    c = report.candidates[0]
    assert c.usage.cost_usd == Decimal("0.5")
    assert [m.usage.cost_usd if m.usage else None for m in c.members] == [
        Decimal("0.1"),
        Decimal("0.1"),
    ]
    assert all(m.duration_ms is None for m in c.members)
    assert c.accounting.by_stage["generation"].usage.input_tokens == 20
    assert c.accounting.by_stage["synthesis"].usage.cost_usd == Decimal("0.1")
    assert (
        json.loads(report.to_json())["candidates"][0]["cases"][0]["operations"][0]["accounting"]
        == accounting().to_dict()
    )
