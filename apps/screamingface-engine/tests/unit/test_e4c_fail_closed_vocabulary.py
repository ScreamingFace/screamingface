"""E4c adds the failure code ``fail_closed``: a guard ends the Case with an error, never an abstain.

FEATURE: E4c (OME-1291) guards #6, #18 (message half), #29; the PIN rows #3-#5 edit the
exact-set tests (``test_failure_classes.py``, ``test_e4b_catalog_pins.py``,
``test_terminal_error_detail.py``).
STORY: as a researcher, a Case that a guard refused fails with ``fail_closed`` and a fixed message
that names the Gate, so I can count it apart from a scored decline and the input never leaks.
"""

from __future__ import annotations

import random
import string

from screamingface_engine.activity.contract import _FAILURE
from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES
from screamingface_engine.benchmarks.failure_classes import FAIL_CLOSED_CODE, fail_closed
from screamingface_engine.error_text import ENGINE_ERROR_CODES


def test_fail_closed_helper_is_permanent_with_fixed_text_and_declared() -> None:
    failure = fail_closed("gate_3")

    assert failure.code == FAIL_CLOSED_CODE == "fail_closed"
    assert failure.permanent is True
    assert str(failure) == "a guard refused the Case: sf.Gate gate_3 took fail_closed"
    assert "fail_closed" in DECLARED_FAILURE_CODES
    # Engine-authored: an upstream may not send it, and a boundary may echo its fixed text.
    assert "fail_closed" in ENGINE_ERROR_CODES


def test_fail_closed_message_names_the_gate_and_never_the_input() -> None:
    # GU-16: the helper takes only the gate id; no input text can reach the message.
    rng = random.Random(1291)
    for _ in range(20):
        question = "".join(rng.choices(string.ascii_letters + " ", k=30))
        message = str(fail_closed("gate_1"))
        assert question not in message
        assert message.endswith("sf.Gate gate_1 took fail_closed")


def test_activity_failure_set_does_not_gain_fail_closed() -> None:
    # GU-21: the activity set lists model-call failures only; no model call fails with it.
    assert "fail_closed" not in _FAILURE
