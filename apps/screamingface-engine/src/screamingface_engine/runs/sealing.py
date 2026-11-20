"""The owner's email, sealed at rest (E5 P2 spec D8, R16).

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose Run the Engine starts after I
have gone, I trust that my email, which the Engine keeps to start it as me, never shows in a
database dump or a logged SQL statement.

AES-256-GCM with a fresh 96-bit nonce per value, as `v1:<nonce>:<ciphertext>` in base64: the
format of aigateway's `LocalSecretStore`. INVARIANT: the Run row holds only what `seal` returns;
only the driver opens it, to start a Candidate.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
_NONCE_BYTES = 12
_PREFIX = "v1:"


class Unreadable(Exception):  # noqa: N818 - a state, as `RunCanceled` is
    """A sealed email this key cannot open: sealed under another key, or damaged."""


def decode_key(encoded: str) -> bytes:
    """The key ``encoded`` as base64; raises ValueError unless it is exactly 32 bytes."""
    try:
        raw = base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the run email key must be base64") from None
    if len(raw) != KEY_BYTES:
        raise ValueError(f"the run email key must decode to exactly {KEY_BYTES} bytes")
    return raw


class EmailSeal:
    """Seals and opens owner emails under one key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(f"the run email key must be exactly {KEY_BYTES} bytes")
        self._aead = AESGCM(key)

    @classmethod
    def for_process(cls) -> EmailSeal:
        """A key made once per process, for an App with no `run_email_key`: local mode, which
        stores no email, and tests. WHY per process and not per store: a test that reopens the
        store over the same database reads what the first one sealed, as a hosted App does after
        a restart with its configured key."""
        return cls(_process_key())

    def seal(self, email: str) -> str:
        # INVARIANT: a fresh nonce per value; GCM with a repeated nonce under one key leaks.
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, email.encode("utf-8"), None)
        return f"{_PREFIX}{_b64(nonce)}:{_b64(sealed)}"

    def open(self, sealed: str) -> str:
        if not sealed.startswith(_PREFIX):
            raise Unreadable("not a v1 sealed value")
        try:
            nonce, body = (base64.b64decode(part, validate=True) for part in sealed[3:].split(":"))
            return self._aead.decrypt(nonce, body, None).decode("utf-8")
        except (ValueError, InvalidTag, UnicodeDecodeError):
            raise Unreadable("sealed under another key, or damaged") from None


_PROCESS_KEY: list[bytes] = []


def _process_key() -> bytes:
    if not _PROCESS_KEY:
        _PROCESS_KEY.append(os.urandom(KEY_BYTES))
    return _PROCESS_KEY[0]


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


__all__ = ["KEY_BYTES", "EmailSeal", "Unreadable", "decode_key"]
