"""Schedule-time admission, the catalog half: which models a url4 names, and admitting them.

FEATURE: run any OpenRouter model (OME-878). A run's world is built from the admitted overlay
the App snapshots when it SCHEDULES the run, but until now only a `GET /v1/model-parameters`
lookup ever filled that overlay (OME-880). A client that schedules a complete url4 without
probing first — `sf.evaluate("<url4>")` replaying a published leaderboard entry, or a raw HTTP
caller — got a world without its model, and every Case failed with "unknown processor" and zero
gateway calls.

STORY: as a researcher replaying a published FrontierScience url4 for
`openrouter/anthropic/claude-opus-5.5`, I get the published run, not 160 "Answering failed"
Cases, without a manual admission step first.

This module pins the two pieces the scheduling route composes: `_named_dynamic_models` (the
pure walk — `benchmarks/expression_routes.py::local_route_paths` — decoded and gated) and
`ExecutableModelParameterSource.admit_run_models` (the port). The REST wiring is pinned in
`test_schedule_time_admission_rest.py`.

A separate module (append-only gate).
"""

from __future__ import annotations

import logging

import pytest
from schedule_admission_support import PUBLISHED_OPUS_URL4

from screamingface_engine.benchmarks.expression_routes import (
    local_route_paths,
    relative_route_paths,
)
from screamingface_engine.catalog.admission import (
    AdmissionAnswer,
    AdmittedModels,
    RunModelAdmission,
)
from screamingface_engine.catalog.executable import ExecutableModelParameterSource
from screamingface_engine.catalog.local_models import LocalModels
from screamingface_engine.catalog.port import (
    CatalogUnavailable,
    Credential,
    ModelParameterResponse,
)
from screamingface_engine.rest.routes import _named_dynamic_models
from url4.core.parser import build

_OPUS = "openrouter/anthropic/claude-opus-5.5"
_DECLARED = "openrouter/openai/gpt-5.5"
_TARGET = "openrouter/qwen/qwen2.5-7b-instruct"
_CREDENTIAL = Credential.derive({"X-User-Email": "alice@example.com"})
_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
_LOGGER = "screamingface_engine.catalog.executable"


# --- _named_dynamic_models: the walk -------------------------------------------------------------


def test_the_published_replay_url4_names_exactly_its_openrouter_model() -> None:
    # The six /benchmarks/* routes it also names are declared App routes, never admission asks.
    assert _named_dynamic_models(PUBLISHED_OPUS_URL4) == (_OPUS,)


@pytest.mark.parametrize(
    "url4",
    [
        "/anthropic/claude-haiku-4-5('hi')!'go'",  # declared namespace, never admitted
        "/benchmarks/candidate('hi')!'go'",
        "/combine('a', 'b')!'go'",
        "/openrouter/x-ai/grok-4~fast('hi')!'go'",  # '~' decodes to ':', never admissible
        "/openrouter/qwen('hi')!'go'",  # one upstream segment
        "url4://other.example/openrouter/qwen/qwen2.5-7b-instruct('hi')!'go'",  # another node's
        "('just a prompt')!'answer'",
    ],
)
def test_nothing_but_an_admissible_local_route_is_named(url4: str) -> None:
    assert _named_dynamic_models(url4) == ()


def test_a_model_named_only_inside_an_iteration_body_or_intent_is_found() -> None:
    # WHY these are walked by re-parsing: `Iteration.body`/`intent` are template TEXT the
    # executor parses per row, so `nodes.walk` never yields them.
    url4 = "/benchmarks/cases*(/openrouter/a/b($item)!go)!/openrouter/e/f($input)!sum"
    assert _named_dynamic_models(url4) == ("openrouter/a/b", "openrouter/e/f")


def test_a_model_named_only_inside_a_call_context_is_found() -> None:
    # WHY: a call's context is a source-list the CALLER resolves before dispatch (`OME-535`), so a
    # model there runs in this world even though `RelExpr.context` is raw text.
    url4 = "/anthropic/claude-haiku-4-5(/openrouter/c/d('hi')!'go', 'more')!'x'"
    assert _named_dynamic_models(url4) == ("openrouter/c/d",)


def test_a_model_named_only_inside_a_corrective_member_intent_is_found() -> None:
    url4 = (
        "/ensemble/corrective/v1/member($input)!'(model_1:0.0:/openrouter/q/r($_sf_recipe_input)"
        "!\\'Answer\\')!\\'$model_1\\''"
    )
    assert _named_dynamic_models(url4) == ("openrouter/q/r",)


def test_ids_come_back_deduplicated_and_sorted() -> None:
    url4 = "(/openrouter/z/y('a')!'go', /openrouter/a/b('b')!'go', /openrouter/z/y('c')!'go')!'x'"
    assert _named_dynamic_models(url4) == ("openrouter/a/b", "openrouter/z/y")


@pytest.mark.parametrize("url4", ["", "(((", "('unterminated)!'x'", "!!!"])
def test_an_unparsable_url4_names_nothing_and_never_raises(url4: str) -> None:
    # INVARIANT (best-effort): a url4 the walk cannot read schedules exactly as before; the run
    # then reports its own parse failure on its stream, where the caller is listening.
    assert _named_dynamic_models(url4) == ()


def test_prose_that_looks_like_an_expression_is_ignored() -> None:
    url4 = "('(an aside, (not closed', /openrouter/a/b('hi')!'go')!'x'"
    assert _named_dynamic_models(url4) == ("openrouter/a/b",)


# --- admit_run_models: the port ------------------------------------------------------------------


class _ParamSource:
    def __init__(self, responses: list[ModelParameterResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.fetched: list[str] = []
        self.traceparents: list[str | None] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.fetched.append(model)
        self.traceparents.append(traceparent)
        if self._responses:
            return self._responses.pop(0)
        return ModelParameterResponse(status=200, content=b"{}")


class _FailingParamSource(_ParamSource):
    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.fetched.append(model)
        raise CatalogUnavailable("aigateway unreachable")


class _Admitter:
    def __init__(self, answer: AdmissionAnswer) -> None:
        self.answer = answer
        self.calls: list[str] = []
        self.credentials: list[Credential] = []

    async def admit_model(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> AdmissionAnswer:
        self.calls.append(model)
        self.credentials.append(credential)
        return self.answer


def _source(
    answer: AdmissionAnswer,
    *,
    params: _ParamSource | None = None,
    admitted: AdmittedModels | None = None,
    local: LocalModels | None = None,
) -> tuple[ExecutableModelParameterSource, _ParamSource, _Admitter, AdmittedModels, list[bool]]:
    params = params if params is not None else _ParamSource()
    admitted = admitted if admitted is not None else AdmittedModels()
    admitter = _Admitter(answer)
    invalidations: list[bool] = []
    source = ExecutableModelParameterSource(
        params,
        frozenset({_DECLARED}),
        admitted=admitted,
        local=local,
        admission_source=admitter,
        on_admitted=lambda: invalidations.append(True),
    )
    return source, params, admitter, admitted, invalidations


def test_the_executable_parameter_source_is_the_run_admission_port() -> None:
    source, *_ = _source(AdmissionAnswer(outcome="admitted"))
    assert isinstance(source, RunModelAdmission)


@pytest.mark.asyncio
async def test_a_granted_model_joins_the_overlay_before_the_call_returns() -> None:
    source, params, admitter, admitted, invalidations = _source(AdmissionAnswer(outcome="admitted"))

    await source.admit_run_models(_CREDENTIAL, [_TARGET], traceparent=_TRACEPARENT)

    assert admitted.ids == (_TARGET,)
    assert invalidations == [True]
    assert admitter.calls == [_TARGET]
    assert admitter.credentials == [_CREDENTIAL]
    # OME-1134: each upstream call is this request's own, so each carries its traceparent.
    assert params.fetched == [_TARGET]
    assert params.traceparents == [_TRACEPARENT]


@pytest.mark.asyncio
async def test_a_declared_or_local_model_costs_no_upstream_call() -> None:
    local = LocalModels(prefixes=("ollama",))
    source, params, admitter, admitted, _ = _source(
        AdmissionAnswer(outcome="admitted"), local=local
    )

    await source.admit_run_models(_CREDENTIAL, [_DECLARED, "ollama/llama3"])

    assert params.fetched == []
    assert admitter.calls == []
    assert admitted.ids == ()


@pytest.mark.asyncio
async def test_a_non_admissible_id_costs_no_upstream_call() -> None:
    source, params, admitter, _admitted, _ = _source(AdmissionAnswer(outcome="admitted"))

    await source.admit_run_models(_CREDENTIAL, ["anthropic/claude-haiku-4-5", "openrouter/x~y"])

    assert params.fetched == []
    assert admitter.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        AdmissionAnswer(outcome="refused", code="model_not_on_openrouter", message="no"),
        AdmissionAnswer(outcome="unsupported"),
    ],
    ids=["refused", "unsupported"],
)
async def test_a_gateway_that_says_no_never_raises_and_leaves_the_overlay_alone(
    answer: AdmissionAnswer, caplog: pytest.LogCaptureFixture
) -> None:
    # WHY no raise: the run is still scheduled and fails ON ITS STREAM, where the caller is
    # listening — a control-plane exception before the caller subscribes would hide the reason.
    source, _params, admitter, admitted, invalidations = _source(answer)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await source.admit_run_models(_CREDENTIAL, [_TARGET])

    assert admitter.calls == [_TARGET]
    assert admitted.ids == ()
    assert invalidations == []
    (record,) = [r for r in caplog.records if r.name == _LOGGER]
    assert _TARGET in record.getMessage()


@pytest.mark.asyncio
async def test_an_unreachable_gateway_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    admitted = AdmittedModels()
    admitted.add(_TARGET)
    source, params, _admitter, _admitted, _ = _source(
        AdmissionAnswer(outcome="admitted"), params=_FailingParamSource(), admitted=admitted
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await source.admit_run_models(_CREDENTIAL, [_TARGET])

    assert params.fetched == [_TARGET]
    (record,) = [r for r in caplog.records if r.name == _LOGGER]
    assert _TARGET in record.getMessage()
    # The credential's identity never reaches the log line.
    assert "alice@example.com" not in record.getMessage()


@pytest.mark.asyncio
async def test_a_stale_overlay_member_is_healed_by_readmission() -> None:
    # STORY: the gateway restarted and forgot its admission; the Engine's overlay still lists the
    # model. The schedule-time ask reuses the F1 heal, so the run is not scheduled into a world
    # whose gateway will refuse every call.
    admitted = AdmittedModels()
    admitted.add(_TARGET)
    params = _ParamSource([ModelParameterResponse(status=404, content=b'{"detail":"Not Found"}')])
    source, params, admitter, admitted, invalidations = _source(
        AdmissionAnswer(outcome="admitted"), params=params, admitted=admitted
    )

    await source.admit_run_models(_CREDENTIAL, [_TARGET])

    assert params.fetched == [_TARGET, _TARGET]
    assert admitter.calls == [_TARGET]
    assert admitted.ids == (_TARGET,)
    assert invalidations == [True]


@pytest.mark.asyncio
async def test_every_named_model_is_asked_for_even_after_one_fails() -> None:
    other = "openrouter/z/y"
    source, params, admitter, admitted, _ = _source(
        AdmissionAnswer(outcome="refused", code="nope", message="no")
    )

    await source.admit_run_models(_CREDENTIAL, [_TARGET, other])

    assert admitter.calls == [_TARGET, other]
    assert params.fetched == []
    assert admitted.ids == ()


# --- _named_dynamic_models: call contexts and iteration tails ------------------------------------


@pytest.mark.parametrize(
    ("url4", "expected"),
    [
        # A trailing comma is an empty source slot url4 drops before it lowers the context.
        ("/anthropic/claude-haiku-4-5(/openrouter/a/b('x')!'go', )!'x'", ("openrouter/a/b",)),
        # A holdings context ("@") travels verbatim to the receiving route, never resolved here.
        ("/anthropic/claude-haiku-4-5(@/notes, /openrouter/a/b('x')!'go')!'x'", ()),
        # Prose in a call's parens ships verbatim and names no route.
        ("/anthropic/claude-haiku-4-5(run: 1, it is prose)!'x'", ()),
        # A cross-row reducer `(src*(body)!peri)!reducer` is template text too.
        (
            "(/benchmarks/cases*(/openrouter/a/b($item)!go)!peri)!/openrouter/r/s($input)!sum",
            ("openrouter/a/b", "openrouter/r/s"),
        ),
    ],
    ids=["trailing-comma", "holdings", "prose", "reducer"],
)
def test_call_contexts_and_iteration_tails_follow_the_lowering_rules(
    url4: str, expected: tuple[str, ...]
) -> None:
    assert _named_dynamic_models(url4) == expected


def test_a_pathologically_nested_url4_names_nothing_and_never_raises() -> None:
    # The url4 is the caller's: a nesting depth past the parser's stack must read as unreadable,
    # never as a 500 on the scheduling route.
    url4 = "(" * 2000 + "/openrouter/a/b('x')!'go'" + ")!'x'" * 2000
    assert _named_dynamic_models(url4) == ()


# --- local_route_paths: the shared walker (review follow-ups) -----------------------------------


def test_a_bare_data_reference_to_a_model_route_is_named() -> None:
    # A `(/path)` data reference resolves against this node's routes exactly like a call does,
    # and `registry.py` already validated it — the admission walk now shares that rule.
    assert local_route_paths("(/openrouter/a/b)!'x'") == frozenset({"/openrouter/a/b"})
    assert _named_dynamic_models("(/openrouter/a/b)!'x'") == ("openrouter/a/b",)


def test_an_iteration_body_survives_an_intent_that_does_not_parse() -> None:
    # WHY: two adjacent literals are not one intent, so `build` rejects the intent — and, joined
    # as `({body})!{intent}`, the body with it. Each template is read separately, so the body's
    # model is still admitted.
    url4 = "/benchmarks/cases*(/openrouter/a/b($item)!go)!'x' 'y'"
    assert _named_dynamic_models(url4) == ("openrouter/a/b",)


def test_an_iteration_body_that_is_a_source_list_is_read_as_the_executor_runs_it() -> None:
    # The executor runs each row as `({body})!{intent}`, so a comma source list is a legal body
    # even though it does not parse as written.
    url4 = "/benchmarks/cases*(/openrouter/a/b($item)!go, /openrouter/c/d($item)!go)!pick"
    assert _named_dynamic_models(url4) == ("openrouter/a/b", "openrouter/c/d")


def test_validation_does_not_read_text_literals_or_rewrap_an_iteration_body() -> None:
    # INVARIANT: `registry.py` validates each template as written (`as_executed=False`); only
    # admission widens the descent. Sharing the walker must not tighten benchmark installation.
    root = build(
        "(/benchmarks/cases*(/x/a($item)!go, /x/b($item)!go)!/x/c($input)!sum, "
        "'(/x/d(\\'q\\')!go)!\\'y\\'')!'x'"
    )
    assert relative_route_paths(root, as_executed=False) == {"/benchmarks/cases", "/x/c"}
    assert relative_route_paths(root, as_executed=True) == {
        "/benchmarks/cases",
        "/x/a",
        "/x/b",
        "/x/c",
        "/x/d",
    }
