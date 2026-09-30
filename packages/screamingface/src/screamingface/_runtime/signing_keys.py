"""Local Ed25519 signing keys for `screamingface up` (E14, OME-1307, RP-20).

FEATURE: OME-1307 (E14). A local stack has two signed hand-offs: the gateway signs a receipt that
the scoreboard verifies (C3), and the scoreboard signs a replay grant that the gateway verifies
(C6). `up` makes both keypairs once, keeps them in a private file under the data dir, and hands
each service its half by environment BEFORE the services start.

INVARIANT: the two halves of one group always come from one pair. A signer from one pair and a
verifier from another fail every submit or replay with no clue, so a group that is partly set is
an error, and a group that is fully set is the operator's and is left alone.
AIDEV-NOTE: WIRING (D6) extends this module and the `server.run()` call. It must not add a second
key file or a second key generator. `apply_local_signing_environment(environment, data_dir)` is the
one entry point, and the local E2E calls it too.
AIDEV-NOTE: these are NOT provider credentials, so `credential_blobs` does not apply. Never log or
print key text, and never put it in an error message.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

from nacl.signing import SigningKey

KEY_FILENAME = "signing-keys.json"
_FILE_VERSION = 1

# Env groups (D7 X-4): raw standard base64 keys, JSON `{kid: b64}` public-key maps.
_RECEIPT_NAMES = ("AIGATEWAY_RECEIPT_SIGNING_KEY", "SCOREBOARD_RECEIPT_PUBLIC_KEYS")
_GRANT_NAMES = (
    "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY",
    "SCOREBOARD_REPLAY_GRANT_SIGNING_KID",
    "AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS",
)


@dataclass(frozen=True, slots=True)
class LocalKeyPair:
    # receipt: sha256(public raw).hexdigest()[:16], the kid GW-freeze derives (OD-F2), no prefix.
    # replay_grant: "local-" plus the same digest; the scoreboard takes it from its own setting.
    kid: str
    private_key: str = field(repr=False)  # base64 (standard, padded) of the 32-byte seed
    public_key: str  # base64 of the 32-byte public key


@dataclass(frozen=True, slots=True)
class LocalSigningKeys:
    receipt: LocalKeyPair  # the gateway signs, the scoreboard verifies (C3)
    replay_grant: LocalKeyPair  # the scoreboard signs, the gateway verifies (C6)


def ensure_local_signing_keys(data_dir: Path) -> LocalSigningKeys:
    """The keys of this data dir: read when the file exists, else made once and kept (0600)."""
    path = data_dir / KEY_FILENAME
    if path.exists():
        return _read(path)
    keys = LocalSigningKeys(receipt=_new_pair(""), replay_grant=_new_pair("local-"))
    _write_json_atomic(
        path,
        {
            "version": _FILE_VERSION,
            "receipt": _pair_dict(keys.receipt),
            "replay_grant": _pair_dict(keys.replay_grant),
        },
    )
    return keys


def apply_local_signing_environment(environment: MutableMapping[str, str], data_dir: Path) -> None:
    """Set the signer and verifier variables of each group that is not set at all.

    Per group (and not per variable): none set means set all of them; all set means change
    nothing, the operator wins; some set is a `RuntimeError`. Both groups are checked before
    either is written, so a refused start half-applies nothing.
    """
    receipt_open = _group_is_open(environment, _RECEIPT_NAMES)
    grant_open = _group_is_open(environment, _GRANT_NAMES)
    if not (receipt_open or grant_open):
        return
    keys = ensure_local_signing_keys(data_dir)
    if receipt_open:
        environment[_RECEIPT_NAMES[0]] = keys.receipt.private_key
        environment[_RECEIPT_NAMES[1]] = _public_key_map(keys.receipt)
    if grant_open:
        environment[_GRANT_NAMES[0]] = keys.replay_grant.private_key
        environment[_GRANT_NAMES[1]] = keys.replay_grant.kid
        environment[_GRANT_NAMES[2]] = _public_key_map(keys.replay_grant)


def _group_is_open(environment: MutableMapping[str, str], names: tuple[str, ...]) -> bool:
    present = [name for name in names if name in environment]
    if not present:
        return True
    if len(present) == len(names):
        return False
    raise RuntimeError(f"set all of {', '.join(names)} or none of them")


def _public_key_map(pair: LocalKeyPair) -> str:
    return json.dumps({pair.kid: pair.public_key})


def _new_pair(kid_prefix: str) -> LocalKeyPair:
    signing_key = SigningKey.generate()
    public = bytes(signing_key.verify_key)
    return LocalKeyPair(
        kid=f"{kid_prefix}{hashlib.sha256(public).hexdigest()[:16]}",
        private_key=base64.b64encode(bytes(signing_key)).decode("ascii"),
        public_key=base64.b64encode(public).decode("ascii"),
    )


def _pair_dict(pair: LocalKeyPair) -> dict[str, object]:
    return {"kid": pair.kid, "private_key": pair.private_key, "public_key": pair.public_key}


def _read(path: Path) -> LocalSigningKeys:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != _FILE_VERSION:
            raise ValueError("wrong shape")
        return LocalSigningKeys(
            receipt=_decode_pair(value.get("receipt")),
            replay_grant=_decode_pair(value.get("replay_grant")),
        )
    except (OSError, ValueError) as exc:
        # INVARIANT: the message holds the path and no key text.
        raise RuntimeError(
            f"local signing keys at {path} are unreadable; move the file away to make new keys"
        ) from exc


def _decode_pair(value: object) -> LocalKeyPair:
    if not isinstance(value, dict):
        raise ValueError("wrong shape")
    kid = value.get("kid")
    private_key = value.get("private_key")
    public_key = value.get("public_key")
    if not (isinstance(kid, str) and isinstance(private_key, str) and isinstance(public_key, str)):
        raise ValueError("wrong shape")
    return LocalKeyPair(kid=kid, private_key=private_key, public_key=public_key)


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
