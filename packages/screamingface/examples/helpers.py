import os

import httpx


def openrouter_credits(api_key: str | None = None) -> dict:
    """How much money is left on the OpenRouter key powering these runs.

    Reads OPENROUTER_KEY from the environment unless a key is passed —
    the AI Gateway's credential store is encrypted and write-only, so the
    notebook cannot read the connected key back out of it.
    """
    key = api_key or os.environ.get("OPENROUTER_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_KEY in the environment (or pass api_key=...)")
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()["data"]
        remaining = data["total_credits"] - data["total_usage"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"OpenRouter credits lookup failed: {exc}") from exc
    print(
        f"OpenRouter: ${remaining:,.2f} remaining "
        f"(${data['total_usage']:,.2f} of ${data['total_credits']:,.2f} used)"
    )
    return data


def load_candidate_result(
    path: str,
    *,
    candidate: int = 0,
    **overrides,
):
    """Rebuild a submit-ready ``sf.CandidateResult`` from a ``report.export()`` JSON.

    Think of it as reopening a finished exam from its archive: the exported report
    holds everything the Engine graded, and this reconstructs the one object
    ``sf.leaderboards.submit(...)`` accepts — so a saved run can be published later
    without re-running (and re-paying for) the evaluation.

    Stages, in execution order:
      1. read ``candidates[candidate]`` out of the exported document;
      2. rebuild the typed pieces (BenchmarkInfo, Cases with their grades, members,
         operations) — grade *checks/evidence* and token usage are dropped, which the
         submission path never reads;
      3. apply any ``overrides`` (e.g. ``score=``, ``name=``, ``run_id=``) on top;
      4. construct the frozen ``sf.CandidateResult``, which re-validates everything.

    WHY overrides exist: dev/testing knobs. Overriding ``score`` submits a number the
    Engine never produced — useful for exercising the Scoreboard contract locally,
    and a live demonstration that self-reported scores are unverified (OME-821 owns
    fixing that); don't do it against a shared board. Keep ``run_id`` unchanged to
    resubmit idempotently (the same result dedupes to the same row); override it to
    force a new submission.

    Args:
        path: The ``report.export()`` JSON file — an absolute path, or relative to
            the notebook's working directory (``examples/`` under Jupyter).
        candidate: Which entry of the report's ``candidates`` list to rebuild,
            0-based in evaluation order. A single-recipe run has exactly one, so
            the default ``0`` is almost always right; a multi-recipe report needs
            the index of the recipe you mean to publish.
        **overrides: Constructor fields of ``sf.CandidateResult`` to replace after
            loading, keyword-for-keyword (``score=``, ``name=``, ``run_id=``, …).
            ``name`` becomes the board's ``spec_id``, so a new name adds a row
            while the original name competes best-per-spec with earlier rows.
            Unknown field names raise ``TypeError`` from the constructor.

    Returns:
        A frozen ``sf.CandidateResult`` that ``sf.leaderboards.submit(...)`` accepts
        as-is. Its ``score`` is exactly what the file (or your override) says —
        nothing is recomputed from the Case grades.

    AIDEV-NOTE: interim, lossy loader for notebook use. The faithful round-trip API
    is ``sf.Report.load()``, which does not exist yet — build it in the SDK, with
    tests, rather than growing this helper.
    """
    import json
    from datetime import datetime
    from pathlib import Path

    import screamingface as sf

    raw = json.loads(Path(path).read_text())["candidates"][candidate]

    def _ts(text):
        return datetime.fromisoformat(text.replace("Z", "+00:00"))

    def _grade(value):
        if value is None:
            return None
        return sf.CaseGrade(
            method=value["method"],
            score=value["score"],
            metrics=value.get("metrics") or {},
            checks=(),
            # Reports written before Named Scores existed have no key: a single-scorer run.
            scores=value.get("scores") or {},
        )

    def _failure(value):
        return sf.Failure(
            stage=value["stage"],
            code=value["code"],
            message=value["message"],
            retryable=value.get("retryable"),
            operation_id=value.get("operation_id"),
            case_id=value.get("case_id"),
            metadata=value.get("metadata") or {},
        )

    def _case(value):
        # INVARIANT: status/refusal/failures must survive the round trip — a refused
        # Case without its refusal (or a failed Case without its failures) violates
        # the CaseResult outcome contract and the constructor rejects it.
        return sf.CaseResult(
            status=value.get("status"),
            case_id=value["case_id"],
            input=value["input"],
            output=value.get("output"),
            finish_reason=value.get("finish_reason"),
            refusal=value.get("refusal"),
            stop_reason=value.get("stop_reason"),
            rounds_executed=value.get("rounds_executed"),
            grade=_grade(value.get("grade")),
            failures=tuple(_failure(f) for f in value.get("failures") or ()),
            metadata=value.get("metadata") or {},
        )

    def _member(value):
        return sf.MemberResult(
            operation_id=value["operation_id"],
            name=value["name"],
            kind=value["kind"],
            models=tuple(value["models"]),
            failures=(),
            duration_ms=value.get("duration_ms") or 1,
            usage=sf.Usage(),
        )

    fields = {
        "benchmark": sf.BenchmarkInfo(
            id=raw["benchmark"]["id"],
            revision=raw["benchmark"]["revision"],
            case_count=raw["benchmark"]["case_count"],
            # Reports written before the mark existed have no key: an ordinary Benchmark.
            inverted_grade=raw["benchmark"].get("inverted_grade", False),
        ),
        "run_id": raw["run_id"],
        "started_at": _ts(raw["started_at"]),
        "completed_at": _ts(raw["completed_at"]),
        "name": raw["name"],
        "kind": raw["kind"],
        "url4": raw["url4"],
        "models": tuple(raw["models"]),
        "operations": tuple(
            sf.OperationInfo(
                id=o["id"],
                kind=o["kind"],
                label=o["label"],
                depends_on=tuple(o.get("depends_on") or ()),
            )
            for o in raw["operations"]
        ),
        "score": raw["score"],
        "coverage": raw["coverage"],
        "metrics": raw.get("metrics") or {},
        "scores": raw.get("scores") or {},
        "cases": tuple(_case(c) for c in raw["cases"]),
        "members": tuple(_member(m) for m in raw["members"]),
        "failures": (),
        "usage": sf.Usage(),
    }
    fields.update(overrides)
    return sf.CandidateResult(**fields)
