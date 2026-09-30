"""Operator key helper for the E14 signing keys (OME-1307, WIRING, D6, D7 X-4).

FEATURE: OME-1307 (E14) deploy wiring. STORY: as an operator, I make the receipt key (the gateway
signs, the scoreboard verifies) and the replay-grant key (the scoreboard signs, the gateway
verifies) once, put the private half in a Secret, and put the public map into the verifier's chart
values. Run it from a checkout and write OUTSIDE the checkout:

    KEYDIR="$(mktemp -d)"
    uv run --project packages/screamingface python -m screamingface._runtime.keygen \
        --purpose receipt --out "$KEYDIR/receipt.env"

INVARIANT: stdout holds the public parts only. A private key is never printed, never put in an
error message, never written over a file, and never written inside a git work tree.
AIDEV-NOTE: the generator is `signing_keys.generate_key_pair` (SDK-replay owns it). Do not add a
second one here (D7 X-3, SDK-replay section 2.1).
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from screamingface._runtime.signing_keys import (
    KeyPurpose,
    generate_key_pair,
    signer_env,
    verifier_env,
)

PURPOSES: Final[Mapping[str, KeyPurpose]] = {"receipt": "receipt", "replay-grant": "replay_grant"}


def refuse_git_work_tree(path: Path) -> None:
    """`SystemExit` when `path` is inside a git work tree.

    WHY: `*.env` files other than `.env` and `.env.*` are not in `.gitignore`, so a key file
    written into a checkout is one `git add .` away from git. `.git` may be a directory or, in a
    linked worktree, a file.
    """
    parent = path.resolve().parent
    for directory in (parent, *parent.parents):
        if (directory / ".git").exists():
            raise SystemExit(
                f"refusing to write {path}: it is inside a git work tree ({directory}); "
                "write the key file outside any checkout"
            )


def write_env_file(path: Path, env: Mapping[str, str]) -> None:
    """One `NAME=value` line per entry, sorted, mode 0600, and never over an existing file.

    INVARIANT: never overwrites; never writes to stdout; never a key in the message.
    """
    refuse_git_work_tree(path)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(f"refusing to overwrite {path}: the file exists") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        for name in sorted(env):
            stream.write(f"{name}={env[name]}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Make one key pair, write the private half to `--out`, print the public half.

    Prints ONLY `kid=<kid>` and one `NAME=<json>` line per verifier variable.
    """
    parser = argparse.ArgumentParser(
        prog="python -m screamingface._runtime.keygen",
        description="Make an E14 Ed25519 signing key pair for a production deploy.",
    )
    parser.add_argument("--purpose", required=True, choices=sorted(PURPOSES))
    parser.add_argument("--out", required=True, type=Path, help="private env file to create (0600)")
    args = parser.parse_args(argv)
    purpose = PURPOSES[args.purpose]
    pair = generate_key_pair(purpose)
    write_env_file(args.out, signer_env(purpose, pair))
    print(f"kid={pair.kid}", flush=True)
    for name, value in sorted(verifier_env(purpose, pair).items()):
        print(f"{name}={value}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
