"""Which key the BYOK connection panel blames when OpenRouter rejects a credential.

STORY: as a BYOK user whose execution key was revoked, the panel tells me my key was
rejected, not a management key I may never have set up (review of PR #1942).

WHY: when the execution key's `/key` call returns 401/403, the Gateway marks BOTH amounts
`credential_rejected` and never tries the management key. Only an account amount rejected
next to a key allowance that still reads comes from the management key.

Assertions read each note element's exact text from parsed HTML, never a substring.
"""

from __future__ import annotations

from test_credit_repr import _available, _byok, _parse, _unavailable

from screamingface._ui.credit_view import credit_html


def test_rejected_execution_key_reads_key_rejected_on_both_boxes() -> None:
    rejected = _unavailable("credential_rejected")

    panel = _parse(credit_html(_byok(rejected, rejected), hosted=False))

    assert panel.texts("sf-credits__note") == ["Key rejected", "Key rejected"]


def test_rejected_management_key_still_names_the_management_key() -> None:
    panel = _parse(
        credit_html(_byok(_unavailable("credential_rejected"), _available("80")), hosted=False)
    )

    # The account box comes first; the readable key allowance renders an empty note.
    assert panel.texts("sf-credits__note")[0] == "Management key rejected"
