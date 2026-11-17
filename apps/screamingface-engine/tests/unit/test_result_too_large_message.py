"""The result_too_large text has one owner:
artifacts.delivery.result_too_large_message (OME-1835)."""

from screamingface_engine.artifacts import result_too_large_message
from screamingface_engine.artifacts.spool import ResultTooLarge


def test_the_message_names_both_byte_counts():
    assert result_too_large_message(70, 64) == "result is 70 bytes, cap is 64 bytes"


def test_the_spool_error_uses_the_shared_message():
    exc = ResultTooLarge(70, 64)
    assert str(exc) == result_too_large_message(70, 64)
    assert (exc.size, exc.allowed) == (70, 64)
