"""`create_app` builds the archive reader and refuses half-configured publishing (plan 4.1).

FEATURE: OME-1307 (E14). INVARIANT under test: a partly set configuration fails at startup, naming
the missing variable and never a secret value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scoreboard.adapters.fs_archive_reader import FilesystemArchiveReader
from scoreboard.adapters.s3_archive_reader import S3ArchiveReader
from scoreboard.config import Settings
from scoreboard.main import create_app

_S3: dict[str, Any] = {
    "archive_backend": "s3",
    "archive_s3_endpoint_url": "http://garage.test:3900",
    "archive_s3_bucket": "cv",
    "archive_s3_access_key_id": "AKIATEST",
    "archive_s3_secret_access_key": "the-secret-value",
}


def _app(**values: Any) -> Any:
    return create_app(Settings.model_validate({"database_url": "sqlite://:memory:", **values}))


def test_no_archive_backend_means_no_reader() -> None:
    assert _app().state.archive_reader is None


def test_filesystem_backend_builds_the_filesystem_reader(tmp_path: Path) -> None:
    app = _app(archive_backend="filesystem", archive_fs_root=tmp_path)

    assert isinstance(app.state.archive_reader, FilesystemArchiveReader)


def test_s3_backend_builds_the_s3_reader() -> None:
    assert isinstance(_app(**_S3).state.archive_reader, S3ArchiveReader)


def test_filesystem_backend_without_a_root_is_refused() -> None:
    with pytest.raises(ValueError, match="SCOREBOARD_ARCHIVE_FS_ROOT"):
        _app(archive_backend="filesystem")


@pytest.mark.parametrize(
    ("missing", "variable"),
    [
        ("archive_s3_endpoint_url", "SCOREBOARD_ARCHIVE_S3_ENDPOINT_URL"),
        ("archive_s3_bucket", "SCOREBOARD_ARCHIVE_S3_BUCKET"),
        ("archive_s3_access_key_id", "SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID"),
        ("archive_s3_secret_access_key", "SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY"),
    ],
)
def test_s3_backend_with_a_missing_setting_is_refused_without_the_secret(
    missing: str, variable: str
) -> None:
    values = {key: value for key, value in _S3.items() if key != missing}

    with pytest.raises(ValueError, match=variable) as refused:
        _app(**values)

    assert "the-secret-value" not in str(refused.value)
