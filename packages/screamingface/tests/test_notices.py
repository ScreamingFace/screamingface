from __future__ import annotations

import pytest

from screamingface._notices import PARTIAL_SUBMISSION_NOTICE, ClientNotice
from screamingface._ui.notice_view import client_notice_html


def test_client_notice_has_stable_machine_and_human_representations() -> None:
    notice = ClientNotice(
        code="partial_submission",
        severity="warning",
        title="Partial submission",
        body="This score is not directly comparable with a full-run score.",
    )

    assert notice.message == (
        "Partial submission. This score is not directly comparable with a full-run score."
    )


@pytest.mark.parametrize("severity", ["error", "success", "", 1, None])
def test_client_notice_rejects_unknown_severities(severity: object) -> None:
    with pytest.raises((TypeError, ValueError), match="severity"):
        ClientNotice(
            code="partial_submission",
            severity=severity,  # type: ignore[arg-type]
            title="Partial submission",
            body="Comparison caveat.",
        )


@pytest.mark.parametrize("field", ["code", "title", "body"])
def test_client_notice_rejects_empty_identity_or_copy(field: str) -> None:
    values = {
        "code": "partial_submission",
        "severity": "warning",
        "title": "Partial submission",
        "body": "Comparison caveat.",
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        ClientNotice(**values)  # type: ignore[arg-type]


def test_client_notice_normalises_machine_identity_and_display_copy() -> None:
    notice = ClientNotice(
        code=" partial_submission\n",
        severity="warning",
        title=" Partial submission ",
        body=" Comparison caveat.\n",
    )

    assert notice.code == "partial_submission"
    assert notice.title == "Partial submission"
    assert notice.body == "Comparison caveat."


def test_partial_notice_uses_its_own_canonical_persimmon_palette() -> None:
    html = client_notice_html(PARTIAL_SUBMISSION_NOTICE)

    for token in (
        "--sf-notice-ink:#9c4828",
        "--sf-notice-solid:#f1622d",
        "--sf-notice-bg:#fdf4f1",
        "--sf-notice-border:#d7aa9b",
        "--sf-notice-ink:#ffbca5",
        "--sf-notice-solid:#e36f48",
        "--sf-notice-bg:#130e0c",
        "--sf-notice-border:#735248",
    ):
        assert token in html
