from __future__ import annotations

from typing import Any, cast

from tortoise import fields

import scoreboard.scores.models as score_models
from scoreboard.config import Settings
from scoreboard.db import TORTOISE_CONFIG
from scoreboard.main import create_app
from scoreboard.scores.models import (
    BaseBaseline,
    BaseBenchmark,
    BaseIdempotencyKey,
    Baseline,
    BaseScore,
    BaseScoreboardModel,
    Benchmark,
    IdempotencyKey,
    Score,
)
from scoreboard.scores.store import ScoreStore


def test_tortoise_config_registers_score_models_and_migrations() -> None:
    app_config = TORTOISE_CONFIG["apps"]["models"]

    assert "scoreboard.scores.models" in app_config["models"]
    assert app_config["migrations"] == "scoreboard.scores.migrations"


def test_score_model_table_names_and_indexes() -> None:
    assert Benchmark._meta.db_table == "benchmarks"
    assert Score._meta.db_table == "scores"
    assert IdempotencyKey._meta.db_table == "idempotency_keys"
    assert ("benchmark_id", "score") in Score._meta.indexes
    assert ("benchmark_id", "spec_id", "submitted_at") in Score._meta.indexes


def test_score_model_content_hash_field_is_unique_and_nullable() -> None:
    # Mirrors what migration 0003 adds — nullable so it can be added to a table with
    # pre-existing rows without a backfill, unique so the DB itself rejects a
    # duplicate recipe (OME-391 / C28).
    content_hash_field = cast(Any, Score._meta.fields_map["content_hash"])

    assert content_hash_field.unique is True
    assert content_hash_field.null is True
    assert content_hash_field.max_length == 64


def test_score_model_relations_use_expected_delete_rules() -> None:
    benchmark_field = cast(Any, Score._meta.fields_map["benchmark"])
    score_field = cast(Any, IdempotencyKey._meta.fields_map["score"])

    assert benchmark_field.on_delete is fields.OnDelete.RESTRICT
    assert score_field.on_delete is fields.OnDelete.CASCADE


def test_score_model_package_exports_models_and_abstract_bases() -> None:
    expected_exports = {
        "BaseScoreboardModel": BaseScoreboardModel,
        "BaseBenchmark": BaseBenchmark,
        "Benchmark": Benchmark,
        "BaseScore": BaseScore,
        "Score": Score,
        "BaseIdempotencyKey": BaseIdempotencyKey,
        "IdempotencyKey": IdempotencyKey,
    }

    for name, model_class in expected_exports.items():
        assert getattr(score_models, name) is model_class
        assert name in score_models.__all__

    for base_model in (BaseScoreboardModel, BaseBenchmark, BaseScore, BaseIdempotencyKey):
        assert base_model._meta.abstract is True


def test_score_models_live_in_one_model_file_per_concrete_model() -> None:
    assert {
        Benchmark.__module__,
        Score.__module__,
        IdempotencyKey.__module__,
    } == {
        "scoreboard.scores.models.benchmark",
        "scoreboard.scores.models.score",
        "scoreboard.scores.models.idempotency_key",
    }


def test_create_app_wires_score_store_without_db_io() -> None:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))

    assert isinstance(app.state.score_store, ScoreStore)


def test_baseline_model_table_name_and_relation() -> None:
    benchmark_field = cast(Any, Baseline._meta.fields_map["benchmark"])

    assert Baseline._meta.db_table == "baselines"
    assert benchmark_field.on_delete is fields.OnDelete.RESTRICT
    assert ("benchmark", "model_name", "source") in {
        tuple(entry) for entry in Baseline._meta.unique_together
    }


def test_baseline_model_package_exports_and_abstract_base() -> None:
    assert score_models.Baseline is Baseline
    assert score_models.BaseBaseline is BaseBaseline
    assert "Baseline" in score_models.__all__
    assert "BaseBaseline" in score_models.__all__
    assert BaseBaseline._meta.abstract is True


def test_baseline_model_lives_in_its_own_file() -> None:
    assert Baseline.__module__ == "scoreboard.scores.models.baseline"


def test_benchmark_model_carries_a_nullable_revision() -> None:
    # WHY: OME-775 registers the Engine's canonical benchmarks, whose identity includes an
    # immutable revision hash over dataset + protocol. Nullable because the retained legacy
    # demo entries (hle/livetruth) have no Engine revision at all — no backfill (D4).
    revision_field = cast(Any, Benchmark._meta.fields_map["revision"])

    assert revision_field.null is True
    assert revision_field.max_length == 64


def test_score_model_carries_a_nullable_indexed_benchmark_revision() -> None:
    # WHY: the leaderboard partitions ranking on this column (OME-775), so it is indexed.
    # Nullable because OME-322's imported LMArena baselines genuinely never ran at any
    # revision, and every row predating this change has none.
    revision_field = cast(Any, Score._meta.fields_map["benchmark_revision"])

    assert revision_field.null is True
    assert revision_field.max_length == 64
    assert revision_field.index is True


def test_benchmark_model_visibility_defaults_to_public() -> None:
    # WHY a default rather than nullable (OME-894): a benchmark whose visibility is unknown must
    # not be private-by-accident (the challenge becomes unreadable) or public-by-accident (the
    # challenge leaks). `public` preserves today's behaviour for every existing row with no
    # backfill, and only the entry challenge flips.
    visibility_field = cast(Any, Benchmark._meta.fields_map["visibility"])

    assert visibility_field.default == "public"
    assert visibility_field.max_length == 16
    # INVARIANT: nullable on purpose. Tightening it to NOT NULL makes SQLite rebuild and DROP the
    # table, which fails with "FOREIGN KEY constraint failed" on any board holding a score
    # (reproduced in review of PR #719). `default` supplies a value on every write, and readers
    # coerce a legacy NULL to public.
    assert visibility_field.null is True
