from __future__ import annotations

import base64
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .mixin import SecretDecryptionError, SecretStoreMixin

_VERSION = "v1"
_PREFIX = f"{_VERSION}:"
_NONCE_BYTES = 12  # 96-bit nonce, the GCM-recommended size

# Recognizes a versioned secret envelope stamped by ANY SF provider — "v1:", a
# future "v2:", or another provider's "kms-v1:" / "aws-kms-v1:" (one or more
# hyphenated tag segments are allowed before the vN: marker). Used to tell an
# envelope this provider cannot decode apart from genuine pre-encryption
# plaintext. Real stored values never match (JSON begins with "{"; token_urlsafe
# secrets contain no ":", nor did the retired profile-id lists).
_SECRET_ENVELOPE_RE = re.compile(r"^(?:[a-z][a-z0-9]*-)*v[0-9]+:")


class LocalSecretStore(SecretStoreMixin):
    """AES-256-GCM envelope encryption with a process-local master key.

    Ciphertext format: ``v1:<nonce-b64>:<ciphertext+tag-b64>``. A fresh random
    96-bit nonce is generated per call (GCM nonce reuse under one key is
    catastrophic; random 96-bit is safe at credential-row volume).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("LocalSecretStore key must be exactly 32 bytes (AES-256)")
        self._aesgcm = AESGCM(key)

    @property
    def version(self) -> str:
        return _VERSION

    async def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        nonce_b64 = base64.b64encode(nonce).decode()
        payload_b64 = base64.b64encode(ciphertext).decode()
        return f"{_PREFIX}{nonce_b64}:{payload_b64}"

    async def decrypt(self, ciphertext: str) -> str:
        if ciphertext.startswith(_PREFIX):
            try:
                _, nonce_b64, payload_b64 = ciphertext.split(":", 2)
                nonce = base64.b64decode(nonce_b64, validate=True)
                payload = base64.b64decode(payload_b64, validate=True)
                return self._aesgcm.decrypt(nonce, payload, None).decode("utf-8")
            except (ValueError, InvalidTag) as exc:
                raise SecretDecryptionError("failed to decrypt v1 secret blob") from exc
        if _SECRET_ENVELOPE_RE.match(ciphertext):
            # A versioned secret envelope written by a different provider/version
            # this store cannot decode (e.g. a future "kms-v1:" blob). Fail loudly
            # rather than hand the opaque ciphertext back as if it were plaintext.
            raise SecretDecryptionError(
                "ciphertext is a non-v1 secret envelope this provider cannot decrypt"
            )
        # Genuine pre-encryption legacy plaintext (SF-221 plan §8): return it
        # unchanged; it is upgraded to ciphertext on its next write.
        #
        # Accepted edge: a legacy plaintext value that itself begins with "v1:"
        # would be treated as a corrupt v1 blob above and raise. This is
        # astronomically unlikely for the values stored here (JSON objects begin
        # with "{"; token_urlsafe secrets contain no ":").
        return ciphertext
