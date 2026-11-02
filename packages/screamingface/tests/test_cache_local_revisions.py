"""The revisions a pull compares, collected in a process that imported nothing else.

FEATURE: community cache pulled into a local gateway (epic OME-1311), whose rows now include
those of configured endpoints (hosted BYOM, OME-1721).

INVARIANT: the revisions a pull compares name the configured-endpoint adapter at the value the
local gateway's keys embed, so a hosted page keyed under another revision of it is refused
rather than loading rows that never hit.

WHY a fresh process: the adapter registers its revision when its module is imported, so an
import anywhere in this session would hide the omission. Its environment holds only `PATH` and
an empty `HOME`: collecting the revisions needs no setting, key or secret.

WHY it skips without the runtime extra: it runs the gateway's real modules, which the SDK test
job does not install; `test_cache_local.py` covers the pull with them stood in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest

# WHY the import order: the revisions are collected first, as `LocalGateway.prepare` collects
# them; the adapter module is imported only afterwards, to read the value they must hold.
_CHILD = """
import json, sys
from screamingface._cache.local import _local_revisions, missing_runtime_modules

missing = missing_runtime_modules()
if missing:
    print(json.dumps({"missing": list(missing)}))
    raise SystemExit(0)
local = _local_revisions()
started = "aigateway.main" in sys.modules
from aigateway.core.request_cache.sqlite_loader import PageRejected, check_revisions
from aigateway.plugins.remote_endpoint.global_cache import GLOBAL_CACHE_ADAPTER_REVISION

try:
    check_revisions({**local, "remote_endpoint_adapter": "an-older-revision"}, local)
    refused = None
except PageRejected as rejected:
    refused = rejected.reason
print(json.dumps({
    "local": local,
    "expected": GLOBAL_CACHE_ADAPTER_REVISION,
    "refused": refused,
    "started": started,
}))
"""


@pytest.fixture(scope="module")
def fresh(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    home = tmp_path_factory.mktemp("home")
    done = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(home)},
        cwd=home,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-4000:]
    report: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    if "missing" in report:
        pytest.skip(f"needs the screamingface[runtime] extra: {', '.join(report['missing'])}")
    return report


def test_a_pull_compares_the_configured_endpoint_revision(fresh: dict[str, Any]) -> None:
    assert fresh["local"].get("remote_endpoint_adapter") == fresh["expected"]


def test_a_hosted_page_keyed_under_another_endpoint_revision_is_refused(
    fresh: dict[str, Any],
) -> None:
    assert fresh["refused"] == "revision_mismatch"


def test_collecting_the_revisions_starts_no_gateway(fresh: dict[str, Any]) -> None:
    assert fresh["started"] is False
