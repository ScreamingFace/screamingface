from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(__file__).with_name("preview_access.sh")


def executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body))
    path.chmod(0o755)


def test_helper_logs_in_and_installs_valid_kubeconfig(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "cloudflare-login"
    curl_config = tmp_path / "curl-config"
    kubeconfig = tmp_path / "preview.kubeconfig"

    executable(
        fake_bin / "cloudflared",
        """\
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        marker = Path(os.environ["FAKE_CLOUDFLARE_LOGIN"])
        if sys.argv[1:3] == ["access", "token"]:
            if not marker.exists():
                raise SystemExit(1)
            print("cloudflare-token")
        elif sys.argv[1:3] == ["access", "login"]:
            marker.touch()
        else:
            raise SystemExit(2)
        """,
    )
    executable(
        fake_bin / "gh",
        """\
        #!/usr/bin/env python3
        import sys

        if sys.argv[1:] != ["auth", "token"]:
            raise SystemExit(2)
        print("github-token")
        """,
    )
    executable(
        fake_bin / "curl",
        """\
        #!/usr/bin/env python3
        import os
        import re
        import sys
        from pathlib import Path

        config = sys.stdin.read()
        Path(os.environ["FAKE_CURL_CONFIG"]).write_text(config)
        output = re.search(r'^output = "([^"]+)"$', config, re.MULTILINE)
        if output is None:
            raise SystemExit(2)
        Path(output.group(1)).write_text(
            "apiVersion: v1\\nkind: Config\\ncurrent-context: preview\\n"
        )
        """,
    )
    executable(
        fake_bin / "kubectl",
        """\
        #!/usr/bin/env python3
        import sys

        if sys.argv[1:3] != ["config", "view"]:
            raise SystemExit(2)
        """,
    )

    environment = {
        **os.environ,
        "FAKE_CLOUDFLARE_LOGIN": str(marker),
        "FAKE_CURL_CONFIG": str(curl_config),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PREVIEW_KUBECONFIG": str(kubeconfig),
    }
    result = subprocess.run(
        ["bash", str(HELPER), "707"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(kubeconfig)
    assert "Complete the Cloudflare login" in result.stderr
    assert "Preview access is ready for namespace sf-preview-pr-707." in result.stderr
    assert "Cluster-wide commands are blocked." in result.stderr
    assert marker.exists()
    assert kubeconfig.stat().st_mode & 0o777 == 0o600
    request = curl_config.read_text()
    assert 'header = "cf-access-token: cloudflare-token"' in request
    assert 'header = "X-Preview-Access-Token: cloudflare-token"' in request
    assert 'header = "X-GitHub-Token: github-token"' in request
    assert (
        'url = "https://kube-pr-707.preview.dev.screamingface.ai/kubeconfig"' in request
    )


def test_helper_requires_a_pull_request_number() -> None:
    result = subprocess.run(
        ["bash", str(HELPER)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Usage: preview_access.sh PULL_REQUEST_NUMBER" in result.stderr
