from __future__ import annotations

import sys

import pytest

from screamingface._environment import ipykernel_loaded, running_in_notebook


def test_running_in_notebook_requires_an_active_ipykernel_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NotebookShell:
        __module__ = "ipykernel.zmqshell"

    monkeypatch.setattr("builtins.get_ipython", lambda: NotebookShell(), raising=False)

    assert running_in_notebook() is True


def test_importing_ipykernel_does_not_claim_an_active_notebook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "ipykernel", object())
    monkeypatch.delattr("builtins.get_ipython", raising=False)

    assert ipykernel_loaded() is True
    assert running_in_notebook() is False


def test_running_in_notebook_tolerates_a_broken_host_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_hook() -> object:
        raise RuntimeError("host hook failed")

    monkeypatch.setattr("builtins.get_ipython", broken_hook, raising=False)

    assert running_in_notebook() is False


@pytest.mark.parametrize("host_module", ["google.colab._shell", "dbruntime.display"])
def test_running_in_notebook_recognises_ipykernel_based_hosted_shells(
    monkeypatch: pytest.MonkeyPatch,
    host_module: str,
) -> None:
    class KernelShell:
        pass

    KernelShell.__module__ = "ipykernel.zmqshell"

    class HostedShell(KernelShell):
        pass

    HostedShell.__module__ = host_module
    monkeypatch.setattr("builtins.get_ipython", lambda: HostedShell(), raising=False)

    assert running_in_notebook() is True
