"""Compare actual endpoint work with public top rows and explicit synthetic growth."""
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx
from tortoise import Tortoise
from scoreboard.db import init_db, close_db
from scoreboard.scores.models import Benchmark, Score

OUT = Path(__file__).parent
URL = 'http://127.0.0.1:8773'

async def measure(client, path):
    start = time.perf_counter()
    response = await client.get(path)
    response.raise_for_status()
    return (time.perf_counter()-start)*1000, response.json()

async def main():
    await init_db('postgres://filip@127.0.0.1:55462/catalog_perf')
    seeds = await Score.all()
    assert len(seeds) == 21, 'Start from the captured 21 public top rows'
    results=[]
    async with httpx.AsyncClient(base_url=URL,limits=httpx.Limits(max_connections=100),timeout=60) as client:
        for copies in [0, 99, 900]:
            extra=[]
            for s in seeds:
                for j in range(copies):
                    extra.append(Score(benchmark_id=s.benchmark_id,spec_id=f'perf-{copies}-{j}',
                        score=s.score-.001*(j+1),total_questions=s.total_questions,
                        benchmark_revision=s.benchmark_revision,ran_with_providers=s.ran_with_providers,
                        models=['openai/gpt-4o'],url4_expression=s.url4_expression,
                        run_cost_usd='1.0',run_cost_status='complete'))
            if extra: await Score.bulk_create(extra,batch_size=500)
            total=await Score.all().count()
            # Explicitly synthetic lower-ranked rows: no claim about production depth.
            await Tortoise.get_connection('default').execute_script('ANALYZE scores;')
            _,data=await measure(client,'/v1/benchmarks')
            ids=[b['id'] for b in data['benchmarks'] if b['visibility']!='private']
            samples=[]
            for _ in range(12):
                start=time.perf_counter()
                await measure(client,'/v1/benchmarks')
                boards=await asyncio.gather(*(measure(client,f'/v1/leaderboard/{id}?top=1') for id in ids))
                old=(time.perf_counter()-start)*1000
                new,summary=await measure(client,'/v1/benchmarks/summary')
                expected={b['benchmark']['id']:max([e['score'] for e in b['entries']],default=None) for _,b in boards}
                assert {b['id']:b['best_score'] for b in summary['benchmarks']}==expected
                samples.append({'oldMs':round(old,2),'summaryMs':round(new,2)})
            results.append({'scores':total,'samples':samples,'oldMedianMs':round(statistics.median(s['oldMs'] for s in samples),2),
                            'summaryMedianMs':round(statistics.median(s['summaryMs'] for s in samples),2)})
            print(json.dumps({k:v for k,v in results[-1].items() if k!='samples'}),flush=True)
    await Score.filter(spec_id__startswith='perf-').delete()
    await close_db()
    (OUT/'server-timings.json').write_text(json.dumps(results,indent=2))

asyncio.run(main())
