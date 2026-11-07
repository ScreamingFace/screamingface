"""Seed a disposable local DB from public responses, never production credentials."""
import asyncio
import gzip
import json
import os
from pathlib import Path

from tortoise import Tortoise
from scoreboard.db import init_db, close_db
from scoreboard.scores.models import Benchmark, Score, Baseline


async def main():
    url = os.environ['CATALOG_PERF_DB']
    assert '@127.0.0.1:55462/catalog_perf' in url, 'Disposable local DB only'
    await init_db(url)
    await Tortoise.generate_schemas()
    data = json.loads(gzip.decompress(Path(__file__).with_name('live.json.gz').read_bytes()))['bodies']
    boards = data['/v1/benchmarks']['benchmarks']
    for b in boards:
        await Benchmark.create(**{k: v for k, v in b.items() if k in {
            'id', 'display_name', 'description', 'focus', 'revision', 'case_count',
            'visibility', 'dataset_url', 'provenance', 'saturation'}})
    count = 0
    for key, board in data.items():
        if not key.startswith('/v1/leaderboard/'):
            continue
        b = board['benchmark']
        for row in board['entries']:
            # Only fields visible through the anonymous public endpoint. All IDs are new.
            await Score.create(benchmark_id=b['id'], spec_id=row['spec_id'], score=row['score'],
                               benchmark_revision=row.get('benchmark_revision'),
                               total_questions=row['total_questions'],
                               ran_with_providers=row.get('ran_with_providers') or [],
                               url4_expression=row.get('url4_expression') or 'url4://public-fixture',
                               run_cost_usd=row.get('run_cost_usd'),
                               submitted_by=row.get('submitted_by'), authors=row.get('authors'),
                               verified_by_screamingface=row.get('verified_by_screamingface', True))
            count += 1
        for row in board.get('baselines', []):
            await Baseline.create(benchmark_id=b['id'], model_name=row['model_name'],
                                  score=row['score'], source=row['source'])
    print(json.dumps({'benchmarks': len(boards), 'scores': count}))
    await close_db()

asyncio.run(main())
