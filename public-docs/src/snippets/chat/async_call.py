import asyncio

import screamingface as sf


async def main() -> None:
    async with sf.AsyncClient() as client:
        reply = await client.chat.completions.create(
            "What is the capital of France?",
            model="openrouter/deepseek/deepseek-v4-flash",
        )
        print(reply.text)

        stream = await client.chat.completions.create(
            "Write one sentence about Paris.",
            model="openrouter/deepseek/deepseek-v4-flash",
            stream=True,
        )
        async with stream:
            async for chunk in stream:
                print(chunk.text, end="")
        print()


asyncio.run(main())
