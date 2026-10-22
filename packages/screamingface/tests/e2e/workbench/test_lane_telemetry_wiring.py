"""The lane boots its OTLP receiver before the target and hands the target its URL (§3.6).

Runs the real lane fixtures in a pytester lane with ``start_target`` replaced by a recorder,
so no stack boots. The recorder checks, while the target is "up", that the URL it was given
answers like the receiver (a GET is refused 405, which only a live receiver says).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from workbench import conftest as lane
from workbench.conftest import OUT_ENV, SPANS_FILE
from workbench.targets import LiveTarget

pytest_plugins = ["pytester"]

_ARGS = ("-p", "no:cacheprovider", "--import-mode=importlib")
_CONFTEST = (
    "from workbench.conftest import live_target, otlp_receiver, workbench_out  # noqa: F401\n"
)
_TEST = """
def test_notebook(live_target):
    assert live_target.name == "replay"
"""


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as refused:
        return refused.code


def test_the_target_gets_the_live_receiver_endpoint(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, object]] = []

    @contextmanager
    def start(
        name: str, work_dir: Path, *, otlp_endpoint: str | None = None
    ) -> Iterator[LiveTarget]:
        assert otlp_endpoint is not None
        seen.append({"endpoint": otlp_endpoint, "status": _status(otlp_endpoint)})
        yield LiveTarget(
            name=name,
            engine_url="http://127.0.0.1:1",
            scoreboard_url="",
            sources=(),
            required_hops=(),
        )

    pytester.makepyfile(**{"lane/conftest.py": _CONFTEST, "lane/test_notebooks.py": _TEST})
    out = pytester.path / "evidence"
    monkeypatch.setenv(OUT_ENV, str(out))
    monkeypatch.delenv("SCREAMINGFACE_WORKBENCH_TARGET", raising=False)
    monkeypatch.setattr(lane, "start_target", start)
    pytester.runpytest(*_ARGS).assert_outcomes(passed=1)

    (call,) = seen
    endpoint = str(call["endpoint"])
    assert endpoint.startswith("http://127.0.0.1:") and endpoint.endswith("/v1/traces")
    assert call["status"] == 405, json.dumps(call)
    # The receiver is gone once the session ends: nothing listens on a workbench port after.
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(endpoint, timeout=2)
    assert SPANS_FILE == "spans.jsonl"
