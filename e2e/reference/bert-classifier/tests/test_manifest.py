import hashlib
import json
import os
import socket
from pathlib import Path

import pytest

from bert_reference import artifacts
from bert_reference.server import prepare_application

PIN = "9f94a3b04de4138225dc013b8cb2d858f99279ea87eb658b184d127e64b699a7"
MANIFEST = Path(__file__).with_name("manifest_fixture.json").read_bytes()
FILES = {
    "config.json": b"{}",
    "model.safetensors": b"head",
    "tokenizer_config.json": b"{}",
    "vocab.txt": b"abc",
}


@pytest.fixture
def root(tmp_path):
    # macOS temp trees can be accessed through /var, which is a symlink.
    directory = tmp_path.resolve() / "artifacts"
    directory.mkdir()
    for name, data in {**FILES, "manifest.json": MANIFEST}.items():
        (directory / name).write_bytes(data)
    return directory


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("artifact verification must not use the network")

    monkeypatch.setattr(socket, "socket", fail)


def never_load(snapshot):
    pytest.fail("an unverified artifact set reached the loader")


def configuration(root, pin=PIN):
    return {
        "SF_BERT_REFERENCE_ARTIFACT_ROOT": str(root),
        "SF_BERT_REFERENCE_MANIFEST_SHA256": pin,
    }


def test_exact_fixture_reaches_loader_as_immutable_bytes(root):
    calls = []

    def load(snapshot):
        calls.append(snapshot)
        # Simulate a path replacement after verification, before this loader consumes the file.
        (root / "vocab.txt").write_bytes(b"new")
        assert dict(snapshot) == FILES
        with pytest.raises(TypeError):
            snapshot["vocab.txt"] = b"new"
        return lambda text, **options: (1, 2), lambda encoding: (0.0, 0.0)

    assert callable(prepare_application(configuration(root), load))
    assert len(calls) == 1


@pytest.mark.parametrize("pin", ["", "A" * 64, "0" * 64, "z" * 64, PIN[:-1]])
def test_refuses_invalid_or_mismatched_external_digest(root, pin):
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root, pin), never_load)


def test_no_in_tree_digest_fallback(root):
    (root / "manifest.sha256").write_text(PIN)
    with pytest.raises(artifacts.ArtifactError):
        prepare_application({"SF_BERT_REFERENCE_ARTIFACT_ROOT": str(root)}, never_load)


def test_digest_covers_final_lf_before_parsing(root, monkeypatch):
    (root / "manifest.json").write_bytes(MANIFEST[:-1])
    monkeypatch.setattr(artifacts, "parse_manifest", lambda data: pytest.fail("parsed early"))
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root), never_load)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b"artifacts.v1", b"artifacts.v2"),
        (b'"Apache-2.0"', b'"apache-2.0"'),
        (b'"schema":', b'"extra": 0, "schema":'),
        (b'"schema":', b'"schema": "old", "schema":'),
        (b'"schema":', b'"wrong":'),
        (b'"size_bytes": 2', b'"size_bytes": true'),
        (b'"size_bytes": 2', b'"size_bytes": 2e0'),
        (b'"size_bytes": 2', b'"size_bytes": -1'),
        (b'"size_bytes": 2', b'"size_bytes": 9223372036854775808'),
        (b'"size_bytes": 2', b'"size_bytes": 7, "size_bytes": 2'),
        (b'"size_bytes": 2', b'"missing": 2'),
        (b'"size_bytes": 2', b'"extra": null, "size_bytes": 2'),
        (b'"44136fa', b'"44136FA'),
        (b'"config.json"', b'"Config.json"'),
        (b'"config.json"', b'"/config.json"'),
        (b'"config.json"', b'"../config.json"'),
        (b'"config.json"', b'"./config.json"'),
        (b'"config.json"', b'"sub/config.json"'),
        (b'"config.json"', rb'"sub\\config.json"'),
        (b'"config.json"', rb'"\u00e9.json"'),
        (b'"config.json"', rb'"manifest.json"'),
    ],
)
def test_refuses_matching_digest_for_malformed_manifest(root, before, after):
    malformed = MANIFEST.replace(before, after, 1)
    assert malformed != MANIFEST
    (root / "manifest.json").write_bytes(malformed)
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root, hashlib.sha256(malformed).hexdigest()), never_load)


@pytest.mark.parametrize("mode", ["reverse", "duplicate", "empty", "bom"])
def test_refuses_noncanonical_inventory(root, mode):
    document = json.loads(MANIFEST)
    files = document["files"]
    document["files"] = {"reverse": files[::-1], "duplicate": [files[0], *files], "empty": []}.get(
        mode, files
    )
    raw = json.dumps(document).encode()
    if mode == "bom":
        raw = b"\xef\xbb\xbf" + raw
    (root / "manifest.json").write_bytes(raw)
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root, hashlib.sha256(raw).hexdigest()), never_load)


@pytest.mark.parametrize(
    "change", ["missing", "size", "sha256", "hidden", "directory", "fifo", "link", "outside"]
)
def test_refuses_nonmatching_tree(root, change, monkeypatch):
    path = root / "vocab.txt"
    if change in {"missing", "directory", "fifo", "link", "outside"}:
        path.unlink()
    if change == "size":
        path.write_bytes(b"abcd")
    elif change == "sha256":
        path.write_bytes(b"abd")
    elif change == "hidden":
        (root / ".extra").touch()
    elif change == "directory":
        path.mkdir()
    elif change == "fifo":
        os.mkfifo(path)
        original_open = os.open

        def guarded_open(name, *args, **kwargs):
            assert name != "vocab.txt", "attempted to open a known FIFO"
            return original_open(name, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded_open)
    elif change == "link":
        path.symlink_to(root / "config.json")
    elif change == "outside":
        outside = root.parent / "outer.txt"
        outside.write_bytes(b"abc")
        path.symlink_to(outside)
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root), never_load)


def test_refuses_symlink_in_root_chain_or_manifest(root):
    alias = root.parent / "alias"
    alias.symlink_to(root.parent, target_is_directory=True)
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(alias / root.name), never_load)
    (root / "manifest.json").rename(root.parent / "separate.json")
    (root / "manifest.json").symlink_to(root.parent / "separate.json")
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root), never_load)


@pytest.mark.parametrize(
    ("field", "other_identity"),
    [("model", "example/other-model"), ("revision", "0" * 40)],
    ids=["model", "revision"],
)
def test_refuses_wrong_identity_in_complete_pinned_tree(
    root: Path, field: str, other_identity: str
):
    # Keep the file inventory and bytes valid, and pin the changed manifest itself.
    document = json.loads(MANIFEST)
    assert document[field] != other_identity
    document[field] = other_identity
    raw = json.dumps(document).encode()
    (root / "manifest.json").write_bytes(raw)
    with pytest.raises(artifacts.ArtifactError):
        prepare_application(configuration(root, hashlib.sha256(raw).hexdigest()), never_load)


@pytest.mark.parametrize("length", [128, 129])
def test_safe_basename_length_boundary_in_complete_pinned_tree(root: Path, length: int):
    # The replacement sorts last and keeps the original size and content digest.
    basename = "z" * length
    (root / "vocab.txt").rename(root / basename)
    raw = MANIFEST.replace(b'"vocab.txt"', f'"{basename}"'.encode())
    (root / "manifest.json").write_bytes(raw)
    env = configuration(root, hashlib.sha256(raw).hexdigest())
    if length == 129:
        with pytest.raises(artifacts.ArtifactError):
            prepare_application(env, never_load)
    else:
        expected = {name: data for name, data in FILES.items() if name != "vocab.txt"}
        expected[basename] = FILES["vocab.txt"]
        assert artifacts.verify_snapshot(env) == expected
