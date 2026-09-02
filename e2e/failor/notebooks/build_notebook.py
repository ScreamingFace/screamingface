"""Regenerate `traceability_e2e_k8s.ipynb` (OME-1074).

The notebook is committed, so this builder is the source of truth for its authored cells:
edit here, re-run, commit both.

WHY a builder rather than hand-editing the .ipynb: cells are emitted with `outputs: []` and
`execution_count: None`, so regenerating is always a clean diff no matter how many times the
notebook has been run interactively. This is a live-cluster diagnostic — it is *expected* to
be executed and to accumulate output — and without this, every run would dirty the tree.

    python3 build_notebook.py
"""

import ast
import json
import pathlib
import subprocess

CELLS = []


def md(text):
    CELLS.append(
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": text.strip().splitlines(True),
        }
    )


def code(text):
    CELLS.append(
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": text.strip().splitlines(True),
        }
    )


md("""
# Traceability e2e — live k8s

Validates the tracing ladder against the **deployed** stack, one rung per section.

**Expect failures.** Only rung 1 (`OME-967`) is implemented. Rungs 2–4 are the next changes;
this notebook is the acceptance test you re-run as each lands.

| rung | change | expected today |
|---|---|---|
| 1 | `OME-967` client mints the traceparent | **PASS** (once PR #789 is in your client build) |
| 2 | engine emits it to aigateway | FAIL — not built |
| 3 | `OME-938` `gateway_call_id` on every line | FAIL — not built |
| 4 | aigateway joins the inbound trace | FAIL — not built |

**A run does not execute in the engine pod.** It runs in a per-run Runner Job
(`app.kubernetes.io/name=url4-runner`), and the traceparent reaches it through the Job env.
Grepping the engine Deployment will show nothing and read as a false failure.
""")

md("## 0. Imports")

code("""
import re
import shutil
import subprocess
import threading
import time

TRACEPARENT_RE = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}")
RUNNER_SELECTOR = "app.kubernetes.io/name=url4-runner"  # RUNNER_LABELS, adapters/k8s.py
RESULTS = {}


def record(rung, name, passed, detail=""):
    RESULTS[rung] = (name, passed, detail)
    print(f"[{'PASS' if passed else 'FAIL'}] rung {rung}: {name}")
    if detail:
        print(f"        {detail}")
""")

md("## 1. Configure — edit this cell only")

code("""
# --- edit these -------------------------------------------------------------------
NAMESPACE       = "default"              # where the stack runs
ENGINE_URL      = "http://127.0.0.1:9108"  # deployed engine, or a port-forward
AIGATEWAY_DEPLOY = "deploy/aigateway"     # `kubectl get deploy -n $NAMESPACE` to confirm
BENCHMARK_ID    = "draco"
CANDIDATE       = "openrouter/google/gemini-3-flash-preview"
KUBECTL         = "kubectl"
# ----------------------------------------------------------------------------------
print(f"namespace={NAMESPACE} engine={ENGINE_URL} gateway={AIGATEWAY_DEPLOY}")
""")

md("## 2. Preflight — cluster reachable, pods present")

code("""
def kc(*args, timeout=30):
    return subprocess.run(
        [KUBECTL, "-n", NAMESPACE, *args],
        capture_output=True, text=True, timeout=timeout,
    )

assert shutil.which(KUBECTL), f"{KUBECTL} not on PATH"
pods = kc("get", "pods", "-o", "name")
assert pods.returncode == 0, f"kubectl failed:\\n{pods.stderr}"
print(pods.stdout or "(no pods)")

gw = kc("get", AIGATEWAY_DEPLOY, "-o", "name")
assert gw.returncode == 0, f"aigateway not found as {AIGATEWAY_DEPLOY}:\\n{gw.stderr}"
print("aigateway:", gw.stdout.strip())
""")

md("""
## 3. Start the log tailers **before** the run

Runner Jobs are short-lived and reaped (`orphan_grace_s=120`; Job TTL 1 h today, and the
orphan sweep drops terminal streams to 60 s when the store is full). Miss the window and the
evidence is gone — so start tailing first.
""")

code("""
LOGS = {"gateway": [], "runner": []}
_stop = threading.Event()

def _tail(key, args):
    proc = subprocess.Popen(
        [KUBECTL, "-n", NAMESPACE, "logs", "-f", *args, "--tail=0"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    try:
        for line in proc.stdout:
            LOGS[key].append(line.rstrip())
            if _stop.is_set():
                break
    finally:
        proc.terminate()

threading.Thread(target=_tail, args=("gateway", [AIGATEWAY_DEPLOY]), daemon=True).start()
threading.Thread(
    target=_tail,
    args=("runner", ["-l", RUNNER_SELECTOR, "--all-containers", "--prefix", "--ignore-errors"]),
    daemon=True,
).start()

time.sleep(3)
print("tailing; gateway lines so far:", len(LOGS["gateway"]))
""")

md("""
## 4. Run one evaluation and capture the client's trace id

`trace_id` is public **only on the error hierarchy** (`ScreamingFaceError.trace_id`). On a
successful run the client exposes no trace field on `Report`, so we read it off the event
stream — `sf.Event.traceparent` — which after `OME-967` is the id the client itself minted.
""")

code("""
import screamingface as sf

sf.configure(engine_url=ENGINE_URL)

seen_traceparents = []

def on_event(event):
    tp = getattr(event, "traceparent", None)
    if tp:
        seen_traceparents.append(tp)

TRACE_ID = None
run_error = None
try:
    sf.connect()
    report = sf.evaluate(CANDIDATE, benchmark=BENCHMARK_ID, limit=1, on_event=on_event)
    print("run completed")
except sf.ScreamingFaceError as exc:
    run_error = exc
    # The pre-first-frame classes (capability mint, run start, WS handshake) land here, and
    # after OME-967 they carry an id where they previously carried nothing.
    TRACE_ID = getattr(exc, "trace_id", None)
    print(f"run failed: {type(exc).__name__}: {exc}")
    print("trace_id on the error:", TRACE_ID)

if TRACE_ID is None and seen_traceparents:
    TRACE_ID = TRACEPARENT_RE.search(seen_traceparents[0]).group(1)

print("distinct traceparents seen on events:", len(set(seen_traceparents)))
print("TRACE_ID =", TRACE_ID)
""")

md("## Rung 1 — the client originated a trace id (`OME-967`)")

code("""
ids = {TRACEPARENT_RE.search(tp).group(1) for tp in seen_traceparents if TRACEPARENT_RE.search(tp)}
if TRACE_ID:
    ids.add(TRACE_ID)

record(
    1, "client holds one well-formed trace id",
    bool(TRACE_ID) and len(ids) == 1,
    f"ids={ids or '{}'} — more than one means the run split across traces",
)
""")

md("""
## Rung 2 — the engine emitted it to aigateway

The gateway must have *received* the client's id. Today the engine sends no `traceparent` on
any of its three client paths, so this fails until that change lands.
""")

code("""
time.sleep(5)  # let the tailers drain

gateway_text = "\\n".join(LOGS["gateway"])
hit = TRACE_ID is not None and TRACE_ID in gateway_text

record(
    2, "aigateway saw the client's trace id",
    hit,
    f"{len(LOGS['gateway'])} gateway lines captured; "
    f"{'found' if hit else 'NOT found'} {TRACE_ID}",
)
""")

md("""
## Rung 3 — every aigateway line carries `gateway_call_id` (`OME-938`)

Not a sample — *every* line. A contextvar injector that misses a code path is the failure
mode this rung exists to catch.
""")

code("""
lines = [ln for ln in LOGS["gateway"] if ln.strip()]
missing = [ln for ln in lines if "gateway_call_id" not in ln]

record(
    3, "gateway_call_id on every aigateway log line",
    bool(lines) and not missing,
    f"{len(lines) - len(missing)}/{len(lines)} lines carry it"
    + (f"; first without: {missing[0][:120]}" if missing else ""),
)
""")

md("""
## Rung 4 — one id, greppable across both pods

The payoff. Until this passes, a Linear ticket's `trace_id` points at nothing you can grep.
""")

code("""
runner_text = "\\n".join(LOGS["runner"])
in_runner = TRACE_ID is not None and TRACE_ID in runner_text
in_gateway = TRACE_ID is not None and TRACE_ID in gateway_text

record(
    4, "same trace id in the Runner Job AND aigateway logs",
    in_runner and in_gateway,
    f"runner={'yes' if in_runner else 'no'} ({len(LOGS['runner'])} lines), "
    f"gateway={'yes' if in_gateway else 'no'} ({len(LOGS['gateway'])} lines)",
)
""")

md("## Summary")

code("""
_stop.set()

width = max(len(n) for _, (n, _, _) in RESULTS.items()) if RESULTS else 10
bar = "+------+" + "-" * (width + 2) + "+--------+"
print(bar)
print(f"| rung | {'assertion'.ljust(width)} | result |")
print(bar.replace("-", "="))
for rung in sorted(RESULTS):
    name, passed, _ = RESULTS[rung]
    print(f"| {str(rung).ljust(4)} | {name.ljust(width)} | {'PASS  ' if passed else 'FAIL  '} |")
print(bar)

failed = [r for r, (_, p, _) in RESULTS.items() if not p]
print()
print("all rungs green" if not failed else f"failing rungs: {failed}")
print("TRACE_ID for a manual grep:", TRACE_ID)
""")

md("""
## If a rung fails unexpectedly

- **Rung 1 fails** → your client build predates `OME-967` (PR #789). Check
  `sf.__version__` / reinstall.
- **Rung 2 "0 gateway lines captured"** → the tailer started after the run, or
  `AIGATEWAY_DEPLOY` names the wrong workload. Re-run section 2, then 3.
- **Rung 4 runner=no with lines>0** → you are almost certainly reading the engine Deployment
  rather than the Runner Job. Confirm with
  `kubectl get pods -l app.kubernetes.io/name=url4-runner`.
- **Everything empty** → no DEBUG level exists in any deployed pod today (all three level
  knobs are broken or uncharted), so you only ever see what INFO emits.
""")

nb = {
    "cells": CELLS,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = pathlib.Path(__file__).parent / "traceability_e2e_k8s.ipynb"
out.write_text(json.dumps(nb, indent=1) + "\n")

# WHY ruff runs here: the repo's pre-commit lints and formats `.ipynb` files, so a builder
# whose output is not already ruff-clean would fight the hook — every regeneration reformatted
# on commit, and the next regeneration undoing it. Formatting in the builder makes the two
# agree, and keeps regeneration idempotent.
for argv in (
    ["ruff", "check", "--fix", "--quiet", str(out)],
    ["ruff", "format", "--quiet", str(out)],
):
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(argv[:2])} failed:\n{result.stdout}{result.stderr}"
        )

reloaded = json.loads(out.read_text())
codes = [c for c in reloaded["cells"] if c["cell_type"] == "code"]
for cell in codes:
    ast.parse("".join(cell["source"]))
    assert cell["outputs"] == [], "a cell carries stored outputs"
    assert cell["execution_count"] is None, "a cell carries an execution count"

print(f"wrote {out}")
print(
    f"cells: {len(reloaded['cells'])} ({len(codes)} code) — ruff-clean, parsed, output-free"
)
