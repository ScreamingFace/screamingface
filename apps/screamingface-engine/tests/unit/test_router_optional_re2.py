"""RE2 is loaded only where a Router regex selector runs (contracts C2, C4; Unit 5.2).

FEATURE: Router Recipe extension. A process that reads a world file through `world.config` (the
SDK runtime CLI does, before it starts an Engine) may run without the Engine's `google-re2`
dependency, so reading a world file, its routing profiles included, and reading or running a
fixed, scoring or llm Router never import RE2. Only a regex selector loads it: the C2 reader
compiles each rule pattern and DECIDE recomputes KEYWORDS (`router_keywords`).

INVARIANT: without RE2 a regex selector is never admitted. ADMIT fails before any read, provider
call or C5 record, and the failure is the missing module, never a refusal of the definition.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from router_block_support import SCOPE, block, run_block, selector_reply, world
from router_support import (
    admit_step,
    choice_definition,
    fixed_definition,
    llm_definition,
    regex_definition,
    router_gateway,
    spec_text,
)
from routing_support import CHAT_PATH, MODELS

from screamingface_engine.benchmarks.picture_admission import run_expression_scope
from screamingface_engine.combine.operators import extract
from screamingface_engine.job_env import RUNNER_CONFIG
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.request_scope import request_scope
from screamingface_engine.world.config import load_config
from screamingface_engine.world.router_keywords import KEYWORDS_WINDOW, keyword_labels
from screamingface_engine.world.router_spec import RegexSelector, RouterSpecError, parse_router_spec
from url4.dag import run as url4_run

_EXTRACT = "screamingface_engine.combine.operators.extract"
_ENDPOINT = "byom_" + "0123456789abcdef" * 2

_WORLD = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/plain"

[[aigateway.models]]
id = "{_ENDPOINT}/general"
web_search = false
public_schema = false

[[aigateway.models]]
id = "{_ENDPOINT}/code"
web_search = false
public_schema = false

[[aigateway.models]]
id = "{_ENDPOINT}/math"
web_search = false
public_schema = false

[[aigateway.models]]
id = "plain"
web_search = false

[routing.profiles.fixed_router_v1]
classifier = "{_ENDPOINT}/model_router_v1"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"

[routing.profiles.fixed_router_v1.branches.general]
model = "{_ENDPOINT}/general"
max_tokens = 1024

[routing.profiles.fixed_router_v1.branches.code]
model = "{_ENDPOINT}/code"
max_tokens = 2048

[routing.profiles.fixed_router_v1.branches.math]
model = "{_ENDPOINT}/math"
max_tokens = 512

[routing.profiles.choice_router_v1]
classifier = "{_ENDPOINT}/model_router_v1"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"
revision_scheme = "router-definition-v1"
instructions = "Pick the expert for the question."

[routing.profiles.choice_router_v1.branches.code]
model = "{_ENDPOINT}/code"
max_tokens = 2048
description = "Programming questions."

[routing.profiles.choice_router_v1.branches.general]
model = "{_ENDPOINT}/general"
max_tokens = 1024
description = "Everything else."
"""

# WHY a fresh interpreter: an Engine test process already imported RE2, so only a new one shows
# what a world-file reader or a non-regex Router imports on its own.
_WITHOUT_RE2 = """
import json
import sys

sys.modules["re2"] = None  # WHY: `import re2` now fails, as in an install without google-re2

from screamingface_engine.job_env import RUNNER_CONFIG
from screamingface_engine.world.config import load_config
from screamingface_engine.world.router_spec import parse_router_spec
import screamingface_engine.world.router_admit
import screamingface_engine.world.router_decide
import screamingface_engine.world.router_join
import screamingface_engine.world.router_steps

inputs = json.load(sys.stdin)
config = load_config({RUNNER_CONFIG: inputs["world"]})
result = {
    "profiles": {name: profile.revision for name, profile in config.routing.items()},
    "revisions": [parse_router_spec(text).revision for text in inputs["specs"]],
    "extract_loaded": inputs["extract"] in sys.modules,
}
try:
    parse_router_spec(inputs["regex"])
except ModuleNotFoundError as missing:
    result["regex"] = missing.name
else:
    result["regex"] = "admitted"
print(json.dumps(result))
"""

_NON_REGEX = {
    "fixed": fixed_definition(),
    "choice": choice_definition(),
    "llm": llm_definition(),
}


def _without_re2(world: Path) -> dict[str, Any]:
    inputs = {
        "world": str(world),
        "specs": [spec_text(definition) for definition in _NON_REGEX.values()],
        "regex": spec_text(regex_definition()),
        "extract": _EXTRACT,
    }
    child = subprocess.run(
        [sys.executable, "-c", _WITHOUT_RE2],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert child.returncode == 0, child.stderr[-2000:]
    return json.loads(child.stdout)


def test_a_world_file_and_a_non_regex_router_are_read_without_re2(tmp_path: Path) -> None:
    # INVARIANT: the SDK runtime reads the world file before it starts an Engine, in an
    # install without google-re2; routing profiles and non-regex definitions never load it.
    world = tmp_path / "world.toml"
    world.write_text(_WORLD, encoding="utf-8")

    result = _without_re2(world)

    config = load_config({RUNNER_CONFIG: str(world)})
    assert result["profiles"] == {name: p.revision for name, p in config.routing.items()}
    assert set(result["profiles"]) == {"fixed_router_v1", "choice_router_v1"}
    assert result["revisions"] == [
        parse_router_spec(spec_text(definition)).revision for definition in _NON_REGEX.values()
    ]
    assert result["extract_loaded"] is False
    # INVARIANT: a regex selector still needs RE2; without it the definition is not admitted.
    assert result["regex"] == "re2"


@pytest.fixture
def no_re2(monkeypatch: pytest.MonkeyPatch) -> None:
    """This process without RE2: the next import of `extract` (and so of `re2`) fails."""
    monkeypatch.setitem(sys.modules, "re2", None)
    monkeypatch.delitem(sys.modules, _EXTRACT)


@pytest.mark.usefixtures("no_re2")
def test_admit_of_a_regex_selector_without_re2_fails_before_any_read() -> None:
    gateway = router_gateway()

    with pytest.raises(ModuleNotFoundError) as missing:
        admit_step(gateway, spec_text(regex_definition()))

    assert missing.value.name == "re2"
    assert gateway.calls() == []


@pytest.mark.usefixtures("no_re2")
def test_a_regex_block_without_re2_calls_nothing_and_records_nothing() -> None:
    gateway = router_gateway()
    source = block(regex_definition())

    async def scenario() -> list[OperationCall]:
        async with world(gateway) as node:
            with request_scope(SCOPE), capture_operation_calls() as recorded:
                with run_expression_scope(source), pytest.raises(ModuleNotFoundError):
                    await url4_run(source, io=node)
        return list(recorded)

    recorded = asyncio.run(scenario())

    assert gateway.calls() == []
    assert [call for call in recorded if call.router is not None or call.is_provider] == []


@pytest.mark.usefixtures("no_re2")
@pytest.mark.parametrize("definition", list(_NON_REGEX.values()), ids=list(_NON_REGEX))
def test_a_non_regex_block_runs_without_re2(definition: dict[str, Any]) -> None:
    gateway = router_gateway()
    gateway.script[(CHAT_PATH, MODELS["general"])] = selector_reply("code")

    value, recorded = asyncio.run(run_block(gateway, block(definition)))

    records = [call.router.document() for call in recorded if call.router is not None]
    assert len(records) == 1 and records[0]["status"] == "answered"
    assert value == f"answer from {MODELS[records[0]['selected'][0]['label']]}"


# --- RE2 semantics where it is installed ----------------------------------------------------------


_LABELS = ("general", "code", "math")


def _selector(*patterns: str, multi: bool = False) -> RegexSelector:
    rules = [{"label": label, "pattern": pattern} for label, pattern in zip(_LABELS, patterns)]
    document = {"source": "regex", "rules": rules, "multi": multi}
    return RegexSelector.model_validate_json(json.dumps(document))


def _with_math_rule(pattern: str) -> dict[str, Any]:
    """A regex Router whose `math` rule is ``pattern``; every other part is valid."""
    definition = regex_definition()
    rules = definition["classifier"]["rules"]
    rules[_LABELS.index("math")]["pattern"] = pattern
    assert [rule["label"] for rule in rules] == list(_LABELS)
    return definition


@pytest.mark.parametrize("pattern", ["(?=math)", "(math)\\1", "(?<!x)math"])
def test_a_rule_pattern_re2_cannot_run_is_refused_at_c2(pattern: str) -> None:
    # WHY these: Python's `re` compiles each one, so only RE2 refuses them.
    assert parse_router_spec(spec_text(_with_math_rule("math"))).definition is not None

    with pytest.raises(RouterSpecError, match=r"rules\.2 \(a rule pattern is one RE2 can run\)"):
        parse_router_spec(spec_text(_with_math_rule(pattern)))


@pytest.mark.parametrize(
    ("pattern", "question"),
    [
        pytest.param("math$", "math\n", id="dollar-is-the-end-of-the-text"),
        pytest.param("\\d", "٣", id="digit-class-is-ascii"),
    ],
)
def test_keywords_match_as_re2_does(pattern: str, question: str) -> None:
    # WHY these: Python's `re` matches each pair, RE2 does not.
    assert keyword_labels(_selector(pattern), question) == ()


def test_keywords_read_only_the_first_window_of_the_question() -> None:
    selector = _selector("math")

    assert keyword_labels(selector, "x" * (KEYWORDS_WINDOW - 4) + "math") == ("general",)
    assert keyword_labels(selector, "x" * (KEYWORDS_WINDOW - 3) + "math") == ()


def test_keywords_keep_the_first_rule_in_declared_order_unless_multi() -> None:
    question = "math code general"

    assert keyword_labels(_selector("math", "code"), question) == ("general",)
    assert keyword_labels(_selector("code", "math"), question) == ("general",)
    assert keyword_labels(_selector("x", "math", "code", multi=True), question) == (
        "code",
        "math",
    )


def test_keywords_compile_each_pattern_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT: every Case of a run reads the same rules, so each pattern compiles once.
    selector = _selector("once-a", "once-b", "once-c", multi=True)
    compiled: list[str] = []
    compile_regex = extract.compile_regex

    def counting(args: Any) -> Any:
        compiled.append(args["pattern"])
        return compile_regex(args)

    monkeypatch.setattr(extract, "compile_regex", counting)

    first = keyword_labels(selector, "once-c then once-a")
    again = keyword_labels(selector, "once-c then once-a")

    assert first == again == ("general", "math")
    assert sorted(compiled) == ["once-a", "once-b", "once-c"]
