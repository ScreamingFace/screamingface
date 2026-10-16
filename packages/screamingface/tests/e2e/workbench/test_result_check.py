from __future__ import annotations

from workbench.result_check import check_result

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
OTHER = "00f067aa0ba902b7aaaaaaaaaaaaaaaa"


def test_valid_result_yields_ids_and_no_reasons() -> None:
    assert check_result({"trace_ids": [TID, OTHER]}, ["trace_ids"]) == ([TID, OTHER], [])


def test_no_result_payload_is_a_reason() -> None:
    ids, reasons = check_result(None, ["trace_ids"])
    assert ids == []
    assert any("WORKBENCH_RESULT" in r for r in reasons)


def test_a_declared_key_missing_from_the_result_is_a_reason() -> None:
    ids, reasons = check_result({"trace_ids": [TID]}, ["trace_ids", "run_ids"])
    assert ids == [TID]
    assert reasons == ["result lacks declared key 'run_ids'"]


def test_a_string_payload_is_a_reason_not_iterated_per_character() -> None:
    ids, reasons = check_result({"trace_ids": TID}, ["trace_ids"])
    assert ids == []
    assert len(reasons) == 1 and "must be a list" in reasons[0]


def test_malformed_ids_are_reasons_and_never_reach_the_chain() -> None:
    bad = ["", "xyz", TID.upper(), TID + "0", f" {TID}", 42]
    ids, reasons = check_result({"trace_ids": [TID, *bad]}, ["trace_ids"])
    assert ids == [TID]
    assert len(reasons) == len(bad)
    assert all("malformed trace id" in r for r in reasons)


def test_an_empty_id_list_is_a_reason() -> None:
    assert check_result({"trace_ids": []}, ["trace_ids"]) == (
        [],
        ["no trace id reported by the notebook"],
    )
