"""`url4-cloud serve --local` selects local mode, and nothing else does.

Local mode fuses the control plane with the run mode and tolerates the insecure default JWT
secret, so which argv reaches it is a security boundary, not a convenience. The cases that matter
are the ones where it must NOT be chosen — a bare `url4-cloud` (the image CMD and the chart's
Deployment command) above all.

Self-contained by design: its own fixture rather than one imported from `test_cli.py`, so the
suites stay independently readable and neither has to change when the other grows.
"""

import pytest

from screamingface_engine import cli


@pytest.fixture
def modes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which entrypoint `main` selects, without entering any of them for real."""
    called: list[str] = []
    monkeypatch.setattr(cli, "_serve", lambda: called.append("serve"))
    monkeypatch.setattr(cli, "_serve_local", lambda: called.append("serve-local"))
    monkeypatch.setattr(cli, "_run", lambda: called.append("run"))
    return called


def test_serve_local_selects_local_mode(modes: list[str]) -> None:
    cli.main(["serve", "--local"])
    assert modes == ["serve-local"]


def test_bare_argv_is_never_local(modes: list[str]) -> None:
    """INVARIANT: this is the image's `CMD ["url4-cloud"]`.

    Falling into local mode here would mean a deployed App serving on the publicly-known dev JWT
    secret, with runs executing inside the control-plane process.
    """
    cli.main([])
    assert modes == ["serve"]


def test_plain_serve_is_never_local(modes: list[str]) -> None:
    cli.main(["serve"])
    assert modes == ["serve"]


def test_run_mode_rejects_the_local_flag(modes: list[str]) -> None:
    """`run` has no `--local`: a Job either executes its one expression or it does not."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--local"])

    assert exc.value.code == 2
    assert modes == []


def test_local_resolves_the_real_local_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_serve_local` itself, unshimmed — so its lazy imports are proven to resolve.

    The tests above replace `_serve_local` wholesale, which would keep passing even if it named a
    module or factory that no longer exists. This patches uvicorn instead, so a rename in
    `screamingface_engine.local` fails here rather than at a developer's first `--local` boot.
    """
    import uvicorn

    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app, **kw))

    cli._serve_local()

    from screamingface_engine.local import LOCAL_HOST, create_local_app

    assert captured["app"] == "screamingface_engine.local:create_local_app"
    assert captured["factory"] is True
    # INVARIANT: loopback. Not configurable, and never 0.0.0.0 — see `local.LOCAL_HOST`.
    assert captured["host"] == LOCAL_HOST == "127.0.0.1"
    assert callable(create_local_app)


# --- `--port`: the local server's port, for a supervisor that owns the port plan -----------


@pytest.fixture
def local_ports(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record the port `_serve_local` is handed; `_serve` stays recorded as a bare marker."""
    seen: list[object] = []
    monkeypatch.setattr(cli, "_serve", lambda: seen.append("serve"))
    monkeypatch.setattr(cli, "_serve_local", lambda port=cli._PORT: seen.append(port))
    return seen


def test_local_without_a_port_binds_the_default(local_ports: list[object]) -> None:
    # INVARIANT: a plain `serve --local` keeps binding 9108 — the port `screamingface up` and
    # the SDK's default client discovery expect when nobody asks for another.
    cli.main(["serve", "--local"])
    assert local_ports == [9108]


def test_local_binds_the_requested_port(local_ports: list[object]) -> None:
    # FEATURE (OME-1620): `screamingface up --engine-port N` starts this process as a child and
    # must be able to hand N down, or the stack's port plan and the Engine's bind disagree.
    cli.main(["serve", "--local", "--port", "9111"])
    assert local_ports == [9111]


def test_port_without_local_is_a_usage_error(local_ports: list[object]) -> None:
    """INVARIANT: the deployed `serve` port is hardcoded on purpose — it IS the chart's
    containerPort (see `_serve`). A moved deployed port would put the probes and the Service on
    a port nothing listens on, so the flag is refused rather than honoured there."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--port", "9111"])

    assert exc.value.code == 2
    assert local_ports == []


@pytest.mark.parametrize("value", ["0", "65536", "nine"])
def test_local_rejects_a_port_outside_the_tcp_range(local_ports: list[object], value: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--local", "--port", value])

    assert exc.value.code == 2
    assert local_ports == []


def test_the_real_local_server_binds_the_requested_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_serve_local(port=…)` unshimmed: the port reaches uvicorn, and the host stays loopback."""
    import uvicorn

    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app, **kw))

    cli._serve_local(port=9111)

    assert captured["port"] == 9111
    assert captured["host"] == "127.0.0.1"
