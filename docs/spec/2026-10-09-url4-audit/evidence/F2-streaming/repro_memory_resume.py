"""Does InMemoryEventStream raise StreamNotFoundError on a resume after delete_stream?"""
import asyncio
from screamingface_engine.adapters.memory import InMemoryEventStream
from url4.streaming.interfaces import StreamNotFoundError
from url4.streaming.protocol import LogData, LogEvent

async def main():
    s = InMemoryEventStream()
    t = "topic-x"
    await s.ensure_stream(t)
    for i in range(3):
        await s.publish(t, LogEvent(id=f"e{i}", source="/trace/x/node/root", subject=t, data=LogData.at("INFO", str(i))))
    await s.delete_stream(t)
    try:
        agen = s.subscribe(t, 2)
        await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        print("resume after reclaim: yielded a frame")
    except StreamNotFoundError:
        print("resume after reclaim: StreamNotFoundError (contract met)")
    except TimeoutError:
        print("resume after reclaim: BLOCKED (no frame, no StreamNotFoundError within 1 s)")
    try:
        agen = InMemoryEventStream().subscribe("never-seen", 2)
        await agen.__anext__()
    except StreamNotFoundError:
        print("resume on a never-seen topic: StreamNotFoundError")
asyncio.run(main())
