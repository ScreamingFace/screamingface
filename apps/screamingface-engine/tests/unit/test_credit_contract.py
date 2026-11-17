"""Pin the cross-service credit vocabulary to one reviewed wire contract."""

import json
from pathlib import Path
from typing import get_args

from screamingface_engine.connections.credit_models import CreditAmount


def contract():
    root = next(
        p for p in Path(__file__).resolve().parents if (p / ".claude/sdlc.local.md").is_file()
    )
    return json.loads(
        (root / "docs/spec/2026-11-11-provider-credit/credit-contract.json").read_text()
    )


def literals(annotation):
    return {
        value
        for arg in get_args(annotation)
        for value in ([arg] if isinstance(arg, str) else literals(arg))
    }


def test_credit_vocabulary_matches_shared_contract():
    expected = contract()
    assert literals(CreditAmount.model_fields["status"].annotation) == set(expected["states"])
    assert literals(CreditAmount.model_fields["reason"].annotation) == set(expected["reasons"])
