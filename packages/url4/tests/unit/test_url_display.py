"""``display_url`` keeps scheme, host, port and path, and never shows a URL's secrets.

FEATURE: image and PDF inputs (epic ``OME-1529``) — push security review.
STORY: as an operator I hand a run a pre-signed ``https://…/a.png?X-Amz-Signature=…`` source;
every message that names it shows scheme, host and path, never its signature.

INVARIANT: query and fragment are replaced by fixed markers, userinfo by ``***``, and the
helper never raises, whatever text it is handed. The tables are the helper tables of #1587's
``test_attachment_url_redaction.py``, moved down with the helper so both branches pin it.
"""

from __future__ import annotations

import pytest

from url4.core.url_display import UNPARSEABLE, display_url

SECRETS = ("SIGSECRET", "CREDSECRET", "TOKSECRET", "FRAGSECRET")
QUERY = "?X-Amz-Signature=SIGSECRET&X-Amz-Credential=CREDSECRET&token=TOKSECRET#FRAGSECRET"
IMG = "https://img.example/photo.png"
SIGNED_IMG = IMG + QUERY


def _leaks(text: str) -> list[str]:
    return [secret for secret in SECRETS if secret in text]


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        (IMG, IMG),
        ("https://h.example:8443/a/b.png", "https://h.example:8443/a/b.png"),
        (SIGNED_IMG, IMG + "?<redacted>#<redacted>"),
        ("https://h.example/a.png?sig=S", "https://h.example/a.png?<redacted>"),
        ("https://h.example/a.png#frag", "https://h.example/a.png#<redacted>"),
        ("https://h.example?token=T", "https://h.example?<redacted>"),
        ("https://user:pw@h.example/a?sig=S", "https://***@h.example/a?<redacted>"),
        ("/files/$name?sig=S", "/files/$name?<redacted>"),
        ("$item.url", "$item.url"),
        ("", ""),
    ],
)
def test_display_url_keeps_scheme_host_port_and_path_only(raw: str, shown: str) -> None:
    assert display_url(raw) == shown


@pytest.mark.parametrize(
    "raw",
    [
        "https://u:SIGSECRET@[::1/x?sig=TOKSECRET",  # unclosed IPv6 bracket: urlsplit raises
        "http://[bad/x?token=TOKSECRET",
        "https://a？b.example/x?sig=SIGSECRET",  # NFKC-normalizes to '?': urlsplit raises
    ],
)
def test_display_url_never_raises_and_falls_back_to_a_fixed_placeholder(raw: str) -> None:
    assert display_url(raw) == UNPARSEABLE
    assert _leaks(display_url(raw)) == []
