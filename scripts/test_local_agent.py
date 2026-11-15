
import asyncio
import os

from agent_framework import Agent

from simassist.llm.config import LLMConfig
from simassist.llm.factory import create_chat_client


async def main():
    model = os.environ["SIMASSIST_MODEL"]

    config = LLMConfig(
        provider="lm_studio",
        model=model,
    )

    async with create_chat_client(config) as client:
        agent = Agent(
            client=client,
            name="SimAssist",
            instructions=(
                "You are SimAssist, an engineering simulation "
                "assistant. Do not claim to have executed tools "
                "or simulations unless tools actually ran."
            ),
        )

        response = await agent.run(
            "What is the purpose of a finite element mesh? "
            "Answer in one sentence."
        )

        print("Model:", model)
        print("Response:", response.text)


if __name__ == "__main__":
    asyncio.run(main())
