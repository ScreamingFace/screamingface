"""The manual owner's-key check uses hidden prompts and prints observations only."""

import runpy
from pathlib import Path

from aigateway.core.credits import CreditReading, unavailable


def test_owner_verification_never_prints_keys(monkeypatch, capsys):
    import aigateway.plugins.openrouter_provider.credits as adapter

    keys = iter(["private-inference", "private-management"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(keys))

    class FakeProvider:
        async def read(self, inference, management):
            assert inference == "private-inference"
            assert management == "private-management"
            return CreditReading(
                account=unavailable("account_unverified"), key=unavailable("lookup_failed")
            )

    monkeypatch.setattr(adapter, "OpenRouterCredits", FakeProvider)
    root = Path(__file__).resolve().parents[3]
    runpy.run_path(str(root / "scripts" / "verify_openrouter_credits.py"), run_name="__main__")
    output = capsys.readouterr().out
    assert "private-inference" not in output and "private-management" not in output
    assert "account_unverified" in output


def test_owner_verification_refuses_visible_password_fallback(monkeypatch, capsys):
    import warnings
    from getpass import GetPassWarning

    import pytest

    def no_hidden_input(prompt):
        warnings.warn("Password input may be echoed", GetPassWarning)
        pytest.fail("credential entry must stop before the visible fallback")

    monkeypatch.setattr("getpass.getpass", no_hidden_input)
    root = Path(__file__).resolve().parents[3]
    with pytest.raises(SystemExit, match="interactive terminal"):
        runpy.run_path(str(root / "scripts" / "verify_openrouter_credits.py"), run_name="__main__")
    assert capsys.readouterr().out == ""
