import asyncio, sys
sys.path.insert(0, ".")
from repro import EffectIO
from url4.dag import run
async def one(ann, delay):
    io = EffectIO(delay=delay)
    try:
        r = await asyncio.wait_for(run(f"https://x.test/a;{ann}", io=io), 2.0)
        return f"ok effects={io.effects}"
    except asyncio.TimeoutError:
        return f"HUNG >2s (timeout never fired) effects={io.effects}"
    except BaseException as e:
        return f"{type(e).__name__}({getattr(e,'code','')}) effects={io.effects}"
async def main():
    for ann, d in [("t=-1", 0.0), ("t=nan", 3.0), ("t=inf", 0.0), ("retry=-5;optional", 0.0)]:
        print(f"CASE ;{ann} delay={d} -> {await one(ann, d)}")
asyncio.run(main())
