import asyncio

import screamingface as sf


async def main() -> None:
    async with sf.AsyncClient() as client:
        llm = sf.InferenceClient("openrouter/deepseek/deepseek-v4-flash", client=client)

        reply = await llm.chat.completions.create("What is the capital of France?")
        print(reply.text)

        stream = await llm.chat.completions.create(
            "Write one sentence about Paris.", stream=True
        )
        async with stream:
            async for chunk in stream:
                print(chunk.text, end="")
        print()


asyncio.run(main())
