"""KG-1 .. KG-7 — the operator key helper (E14, OME-1307, WIRING).

FEATURE: OME-1307 (E14). STORY: as an operator, I make the receipt key and the replay-grant key
once, put the private half in a Secret, and put the public map into the verifier's values.
INVARIANT under test: a private key is never printed, never overwritten, and never written inside a
git work tree; the public parts on stdout are the verifier's variables.
The RFC 8032 section 7.1 TEST 1 vector below is a published test vector, not a key of this system.
"""

from __future__ import annotations

import base64
import hashlib
import json
import stat
from pathlib import Path

import pytest
from nacl.signing import SigningKey, VerifyKey

from screamingface._runtime import keygen
from screamingface._runtime.signing_keys import generate_key_pair

RFC8032_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
RFC8032_SEED_B64 = "nWGxne/9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A="
RFC8032_PUBLIC_B64 = "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo="
RFC8032_KID = "21fe31dfa154a261"


def _raw(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _lines(path):
        name, _, value = line.partition("=")
        values[name] = value
    return values


def test_rfc8032_vector_gives_raw_base64_and_the_gw_freeze_kid() -> None:
    pair = generate_key_pair("receipt", seed=RFC8032_SEED)

    assert pair.private_key == RFC8032_SEED_B64
    assert pair.public_key == RFC8032_PUBLIC_B64
    assert pair.kid == RFC8032_KID
    assert len(_raw(pair.private_key)) == 32
    assert len(_raw(pair.public_key)) == 32
    assert "-----BEGIN" not in pair.private_key + pair.public_key


def test_fresh_pair_verifies_and_kid_is_derived() -> None:
    pair = generate_key_pair("replay_grant")

    signed = SigningKey(_raw(pair.private_key)).sign(b"x")
    VerifyKey(_raw(pair.public_key)).verify(b"x", signed.signature)
    assert pair.kid == hashlib.sha256(_raw(pair.public_key)).hexdigest()[:16]
    assert generate_key_pair("replay_grant").kid != pair.kid


def test_receipt_kid_takes_no_prefix_and_a_seed_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="takes no prefix"):
        generate_key_pair("receipt", kid_prefix="x-")
    with pytest.raises(ValueError):
        generate_key_pair("receipt", seed=b"short")

    assert generate_key_pair("replay_grant", kid_prefix="local-").kid.startswith("local-")


def test_cli_writes_a_private_env_file_and_prints_only_public_parts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "r.env"

    assert keygen.main(["--purpose", "receipt", "--out", str(out)]) == 0

    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    (line,) = _lines(out)
    name, _, private = line.partition("=")
    assert name == "AIGATEWAY_RECEIPT_SIGNING_KEY"
    printed = capsys.readouterr().out
    assert private not in printed
    public_line = next(
        x for x in printed.splitlines() if x.startswith("SCOREBOARD_RECEIPT_PUBLIC_KEYS=")
    )
    public_map = json.loads(public_line.partition("=")[2])
    (kid,) = public_map
    assert f"kid={kid}" in printed.splitlines()
    assert base64.b64encode(bytes(SigningKey(_raw(private)).verify_key)).decode() == public_map[kid]


def test_cli_replay_grant_pairs_key_and_kid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "g.env"

    assert keygen.main(["--purpose", "replay-grant", "--out", str(out)]) == 0

    values = _env_values(out)
    assert set(values) == {
        "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY",
        "SCOREBOARD_REPLAY_GRANT_SIGNING_KID",
    }
    kid = values["SCOREBOARD_REPLAY_GRANT_SIGNING_KID"]
    assert not kid.startswith("local-")
    printed = capsys.readouterr().out
    public_line = next(
        x for x in printed.splitlines() if x.startswith("AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS=")
    )
    assert list(json.loads(public_line.partition("=")[2])) == [kid]
    assert values["SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"] not in printed


def test_cli_refuses_to_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.env"
    out.write_bytes(b"OLD=1\n")

    with pytest.raises(SystemExit) as raised:
        keygen.main(["--purpose", "receipt", "--out", str(out)])

    assert str(out) in str(raised.value)
    assert out.read_bytes() == b"OLD=1\n"
    assert "AIGATEWAY_RECEIPT_SIGNING_KEY" not in capsys.readouterr().out


@pytest.mark.parametrize("marker", ["dir", "file"])
def test_cli_refuses_a_path_inside_a_git_work_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], marker: str
) -> None:
    repo = tmp_path / "repo"
    if marker == "dir":
        (repo / ".git").mkdir(parents=True)
    else:
        repo.mkdir()
        # WHY a file: a linked worktree has `.git` as a file, not a directory.
        (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    (repo / "sub").mkdir()
    out = repo / "sub" / "r.env"

    with pytest.raises(SystemExit) as raised:
        keygen.main(["--purpose", "receipt", "--out", str(out)])

    assert str(out) in str(raised.value)
    assert "inside a git work tree" in str(raised.value)
    assert not out.exists()
    assert "AIGATEWAY_RECEIPT_SIGNING_KEY" not in capsys.readouterr().out
