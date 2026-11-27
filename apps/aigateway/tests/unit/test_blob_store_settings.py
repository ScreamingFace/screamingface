"""The file store's two settings: its byte budget and how long one run's files live (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 4).
INVARIANT: the store can always hold the largest file the upload route accepts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aigateway.config import Settings
from aigateway.core.blob_upload import MAX_BLOB_UPLOAD_BYTES, base64_length
from aigateway.core.media_store import ENTRY_OVERHEAD_BYTES, SCOPE_OVERHEAD_BYTES

# The smallest legal store: one largest upload's base64 plus one file's and one run's
# bookkeeping.
SMALLEST_STORE = base64_length(MAX_BLOB_UPLOAD_BYTES) + ENTRY_OVERHEAD_BYTES + SCOPE_OVERHEAD_BYTES


def test_the_defaults_hold_two_largest_files_for_one_run_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIGW_BLOB_STORE_MAX_BYTES", raising=False)
    monkeypatch.delenv("AIGW_BLOB_SCOPE_TTL_SECONDS", raising=False)

    settings = Settings()

    assert settings.blob_store_max_bytes == 40_000_000
    # 16 h run deadline + 1 h, the Engine's run capability lifetime.
    assert settings.blob_scope_ttl_seconds == 58_800


def test_both_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_BLOB_STORE_MAX_BYTES", "64000000")
    monkeypatch.setenv("AIGW_BLOB_SCOPE_TTL_SECONDS", "3600")

    settings = Settings()

    assert settings.blob_store_max_bytes == 64_000_000
    assert settings.blob_scope_ttl_seconds == 3600


def test_a_store_smaller_than_one_largest_file_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIGW_BLOB_STORE_MAX_BYTES", str(SMALLEST_STORE - 1))

    with pytest.raises(ValidationError, match="AIGW_BLOB_STORE_MAX_BYTES"):
        Settings()


def test_a_store_of_exactly_one_largest_file_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_BLOB_STORE_MAX_BYTES", str(SMALLEST_STORE))

    assert Settings().blob_store_max_bytes == SMALLEST_STORE


@pytest.mark.parametrize("name", ["AIGW_BLOB_STORE_MAX_BYTES", "AIGW_BLOB_SCOPE_TTL_SECONDS"])
def test_a_non_positive_value_is_refused(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("size", "encoded"), [(0, 0), (1, 4), (3, 4), (4, 8), (15_000_000, 20_000_000)]
)
def test_base64_length_is_four_characters_per_started_three_bytes(size: int, encoded: int) -> None:
    assert base64_length(size) == encoded
