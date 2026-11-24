"""The error-code scan checks itself on synthetic packages (spec 3.2, gateway code provenance).

FEATURE: Gateway code provenance (`docs/spec/2026-11-23-gateway-code-provenance.md`).
INVARIANT: every shape that can put a code into an error body either resolves to string
literals or is reported as unproven. Each case below must fail; the positive control proves
the resolution rules do not report what they can prove.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from ._gateway_error_code_scan import Producer, Review, failures


def _failures(
    tmp_path: Path,
    files: dict[str, str],
    *,
    codes: tuple[str, ...] = (),
    retired: tuple[str, ...] = (),
    audited: tuple[str, ...] | None = None,
    **tables,
) -> list[str]:
    package = tmp_path / "pkg"
    for name, text in files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(text))
    fixture = {"codes": list(codes), "retired": list(retired)}
    audited = retired if audited is None else audited
    return failures(package, package="pkg", fixture=fixture, retired=audited, **tables)


_UNPROVEN = {
    "dict-literal": "def f(c):\n    return {'code': c}\n",
    "subscript-store": "def f(d, c):\n    d['code'] = c\n",
    "subscript-in-tuple-target": "def f(d, pair):\n    d['code'], d['message'] = pair\n",
    "dict-call": "def f(c):\n    return dict(code=c)\n",
    "update": "def f(d, c):\n    d.update({'code': c})\n",
    "setdefault": "def f(d, c):\n    d.setdefault('code', c)\n",
    # WHY a local bound only to literals is still unproven: the scan is flow-insensitive, so it
    # would also read `outcome = "success"` as a code. Such a site is reviewed with its codes.
    "local-literals": "def f(ok):\n    code = 'a' if ok else 'b'\n    return {'code': code}\n",
    "lambda-parameter": "def f():\n    return lambda c: {'code': c}\n",
    "forwarded-detail": """
        from fastapi import HTTPException

        def f(exc):
            raise HTTPException(400, detail=exc.detail)
        """,
    "forwarded-content": """
        from fastapi.responses import JSONResponse

        def f(entry):
            return JSONResponse(status_code=500, content=entry.response_json["detail"])
        """,
    # WHY: a JSONResponse body is the content itself, so its code is `content["detail"]["code"]`.
    "content-wrapping-a-detail": """
        from fastapi.responses import JSONResponse

        def f(exc):
            return JSONResponse(status_code=500, content={"detail": exc.detail, "meta": {}})
        """,
    "helper-wrapping-a-detail": """
        from fastapi.responses import JSONResponse

        def _merged(detail, meta):
            return {"detail": detail, "meta": meta}

        def f(entry):
            return JSONResponse(status_code=500, content=_merged(entry.detail, {}))
        """,
    "splatted-detail": """
        from fastapi import HTTPException

        def f(exc):
            raise HTTPException(400, detail={**exc.detail, "message": "m"})
        """,
    "aliased-exception": """
        from starlette.exceptions import HTTPException as Raised

        def f(exc):
            raise Raised(400, exc.detail)
        """,
    # WHY: a subclass without its own `__init__` is constructed with HTTPException's arguments.
    "subclass-call": """
        from fastapi import HTTPException

        class Refused(HTTPException):
            pass

        class Deeper(Refused):
            pass

        def f(exc):
            return Deeper(status_code=400, detail=exc.detail)
        """,
    "kwargs-detail": """
        from fastapi import HTTPException

        def f(options):
            raise HTTPException(400, **options)
        """,
}


@pytest.mark.parametrize("source", _UNPROVEN.values(), ids=list(_UNPROVEN))
def test_every_unproven_shape_fails(tmp_path, source) -> None:
    assert _failures(tmp_path, {"m.py": source}) == ["unproven: m.py:f has 1, listed 0"]


def test_a_subclass_init_forwarding_a_parameter_fails_at_its_super_call(tmp_path) -> None:
    source = """
        from fastapi import HTTPException

        class Refused(HTTPException):
            def __init__(self, detail):
                super().__init__(status_code=400, detail=detail)

        def f():
            return Refused({"code": "fine"})
        """
    assert _failures(tmp_path, {"m.py": source}, codes=("fine",)) == [
        "unproven: m.py:Refused.__init__ has 1, listed 0"
    ]


def test_what_the_rules_can_prove_is_collected_and_not_reported(tmp_path) -> None:
    module = """
        from fastapi import HTTPException
        from fastapi.responses import JSONResponse
        from pkg.consts import SHARED
        from .consts import RELATIVE

        LOCAL = "local_constant"
        _DETAIL = {"code": "module_detail"}

        def _helper(flag):
            if flag:
                return {"code": "helper_code"}
            detail = {"code": None, "message": "no code"}
            return detail

        def f(flag):
            if flag:
                raise HTTPException(409, detail=_DETAIL)
            raise HTTPException(400, detail=_helper(flag))

        def g(flag):
            return {"code": LOCAL if flag else SHARED, "other": RELATIVE}

        def h(name):
            raise HTTPException(400, f"plain text about {name}")

        def j():
            return JSONResponse(status_code=404, content={"code": RELATIVE})
        """
    consts = 'SHARED = "imported_constant"\nRELATIVE = "relative_constant"\n'
    written = (
        "helper_code",
        "imported_constant",
        "local_constant",
        "module_detail",
        "relative_constant",
    )
    assert _failures(tmp_path, {"m.py": module, "consts.py": consts}, codes=written) == []


def test_a_new_literal_code_is_not_declared(tmp_path) -> None:
    source = "X = {'code': 'brand_new'}\n"
    assert _failures(tmp_path, {"m.py": source}) == ["not declared: brand_new (m.py:<module>)"]


def test_a_rebound_module_name_is_not_a_constant(tmp_path) -> None:
    source = """
        CODE = "first"

        def rebind(value):
            global CODE
            CODE = value

        def f():
            return {"code": CODE}
        """
    assert _failures(tmp_path, {"m.py": source}) == ["unproven: m.py:f has 1, listed 0"]


def test_a_producer_collects_literals_and_fails_on_a_non_literal(tmp_path) -> None:
    source = """
        def _refuse(status, code, message):
            return {"code": code, "message": message}

        class Refusal(Exception):
            def __init__(self, code, message):
                super().__init__(message)
                self.code = code

        def ok():
            _refuse(400, "declared", "m")
            raise Refusal(code="also_declared", message="m")

        def f(x):
            return _refuse(400, x, "m")
        """
    producers = (Producer("m.py", "_refuse", "code"), Producer("m.py", "Refusal", "code"))
    assert _failures(
        tmp_path,
        {"m.py": source},
        codes=("also_declared", "declared"),
        producers=producers,
    ) == ["unproven: m.py:f has 1, listed 0"]


def test_a_detail_producer_checks_the_detail_at_every_call(tmp_path) -> None:
    source = """
        class TokenError(Exception):
            def __init__(self, status, detail):
                self.detail = detail

        def ok():
            raise TokenError(404, {"code": "not_found"})

        def f(body):
            raise TokenError(502, body)
        """
    producers = (Producer("m.py", "TokenError", "detail", kind="detail"),)
    assert _failures(tmp_path, {"m.py": source}, codes=("not_found",), producers=producers) == [
        "unproven: m.py:f has 1, listed 0"
    ]


def test_a_producer_that_names_nothing_fails(tmp_path) -> None:
    producers = (Producer("m.py", "_gone", "code"),)
    assert _failures(tmp_path, {"m.py": "X = 1\n"}, producers=producers) == [
        "producer not found: m.py:_gone(code)"
    ]


def test_a_reviewed_site_adds_its_codes_and_must_keep_its_count(tmp_path) -> None:
    source = "def f(ok):\n    code = 'a' if ok else 'b'\n    return {'code': code}\n"
    reviewed = {"m.py:f": Review(1, ("a", "b"), "a local bound only to the two literals")}
    assert _failures(tmp_path, {"m.py": source}, codes=("a", "b"), reviewed=reviewed) == []

    stale = {**reviewed, "m.py:gone": Review(1, (), "no longer exists")}
    assert _failures(tmp_path, {"m.py": source}, codes=("a", "b"), reviewed=stale) == [
        "unproven: m.py:gone has 0, listed 1"
    ]


def test_a_reviewed_code_must_be_a_literal_in_its_file(tmp_path) -> None:
    source = "def f(ok):\n    code = 'a' if ok else 'b'\n    return {'code': code}\n"
    reviewed = {"m.py:f": Review(1, ("a", "typo"), "a local bound only to literals")}
    assert _failures(tmp_path, {"m.py": source}, codes=("a", "typo"), reviewed=reviewed) == [
        "reviewed code not a literal in m.py: typo"
    ]


def test_a_not_code_site_is_skipped_only_at_its_listed_count(tmp_path) -> None:
    source = """
        def exchange(code, extra):
            body = {"grant_type": "authorization_code", "code": code}
            return body
        """
    assert _failures(tmp_path, {"m.py": source}, not_codes={"m.py:exchange": 1}) == []

    grown = source.replace("return body", "return {**body, 'echo': {'code': extra}}")
    assert _failures(tmp_path, {"m.py": grown}, not_codes={"m.py:exchange": 1}) == [
        "not-code: m.py:exchange has 2, listed 1"
    ]


def test_a_new_exception_handler_fails_until_reviewed(tmp_path) -> None:
    source = """
        def create(app, handler):
            app.add_exception_handler(Exception, handler)

        def register(app):
            @app.exception_handler(ValueError)
            async def on_value_error(request, exc):
                return None
        """
    assert _failures(tmp_path, {"m.py": source}) == [
        "handler not reviewed: handler",
        "handler not reviewed: on_value_error",
    ]
    reviewed = {"handler", "on_value_error"}
    assert _failures(tmp_path, {"m.py": source}, handlers=reviewed) == []


def test_migrations_are_not_read(tmp_path) -> None:
    source = "def upgrade(ops, forward):\n    ops.RunPython(code=forward)\n"
    assert _failures(tmp_path, {"migrations/0001_x.py": source}) == []


def test_retired_is_exactly_the_audited_set(tmp_path) -> None:
    # INVARIANT: the Engine lifts every retired code, so a value joins `retired` only with its
    # audit; an extra entry fails, and so does an audited code the fixture dropped.
    files = {"m.py": "X = {'code': 'written'}\n"}
    extra = ("byom_secret_deployment_alpha", "old_code")
    assert _failures(tmp_path, files, codes=("written",), retired=extra, audited=("old_code",)) == [
        "retired not audited: byom_secret_deployment_alpha"
    ]
    dropped = ("gone", "old_code")
    assert _failures(
        tmp_path, files, codes=("written",), retired=("old_code",), audited=dropped
    ) == ["audited retired missing: gone"]


@pytest.mark.parametrize(
    ("codes", "retired", "expected"),
    [
        (("written", "gone"), (), "declared but not written: gone"),
        (("written",), ("written",), "in both lists: written"),
        (("written", "a_first"), (), "fixture: codes not sorted"),
        (("written",), ("Not A Code",), "fixture: retired entry not a plain identifier"),
        (("written", "written"), (), "fixture: codes has duplicates"),
    ],
    ids=["stale-entry", "both-lists", "unsorted", "not-identifier", "duplicate"],
)
def test_a_bad_fixture_fails(tmp_path, codes, retired, expected) -> None:
    found = _failures(tmp_path, {"m.py": "X = {'code': 'written'}\n"}, codes=codes, retired=retired)
    assert any(line.startswith(expected) for line in found), found
