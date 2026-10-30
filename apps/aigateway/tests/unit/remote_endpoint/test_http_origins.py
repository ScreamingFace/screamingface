"""An approved plain-HTTP origin on an address and port, end to end through the real routes.

# FEATURE: hosted BYOM Unit 1 — a local server such as LM Studio, reached by address or by a Docker
# service name on its own port, is attached and called like any other configured endpoint.
# STORY: as an operator, I approve `http://<host>:<port>` for a lab server; a granted tenant's key
# is probed there and its chats go there, with that key and no other.
# INVARIANT: readiness and dispatch send to exactly the configured origin, port and fixed path,
# with exactly the stored key as the bearer token.
"""

from __future__ import annotations

import pytest

from .conftest import Harness, chat, echo_of, put_key
from .fixtures import ACCOUNT_A, CHAT_PATH, ENDPOINT_A, UPSTREAM_MODEL, document, endpoint

KEY = "sk-lm-studio-local-0001"


@pytest.mark.parametrize(
    "origin",
    ["http://192.168.1.20:1234", "http://lm-studio:1234", "http://[fd00::20]:8080"],
)
def test_an_http_origin_on_its_port_gets_the_probe_and_the_chat(byom: Harness, origin: str) -> None:
    url = origin + CHAT_PATH
    doc = document(endpoint(ENDPOINT_A, origin=origin, accounts=(ACCOUNT_A,)))

    with byom.start(doc) as client:
        attached = put_key(client, ACCOUNT_A, ENDPOINT_A, KEY)
        answered = chat(client, ACCOUNT_A, ENDPOINT_A)

    assert attached.status_code == 200, attached.text
    assert echo_of(answered) == f"{url}|Bearer {KEY}"
    assert [(c.url, c.bearer, c.model, c.probe) for c in byom.upstream.calls] == [
        (url, f"Bearer {KEY}", UPSTREAM_MODEL, True),
        (url, f"Bearer {KEY}", UPSTREAM_MODEL, False),
    ]
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY
