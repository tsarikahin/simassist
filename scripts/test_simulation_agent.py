
import asyncio
import os
from uuid import UUID

from simassist.agents.simulation_agent import (
    build_simulation_agent,
)
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import (
    SimulationTools,
)
from simassist.api.dependencies import get_job_repository
from simassist.jobs.manager import JobManager
from simassist.llm.config import LLMConfig


PROJECT_ID = UUID(
    "11111111-1111-4111-8111-111111111111"
)


async def main():
    config = LLMConfig(
        provider="lm_studio",
        model=os.getenv(
            "SIMASSIST_MODEL",
            "spark-x2.6-4b",
        ),
        endpoint=os.getenv(
            "SIMASSIST_LLM_ENDPOINT",
            "http://127.0.0.1:1235/v1",
        ),
    )

    manager = JobManager(
        repository=get_job_repository()
    )

    geometry_tools = GeometryTools(
        job_manager=manager,
        project_id=PROJECT_ID,
    )

    simulation_tools = SimulationTools(
        geometry=geometry_tools,
    )

    agent = build_simulation_agent(
        config=config,
        simulation_tools=simulation_tools,
    )

    prompt = (
        "Create a cylinder named Agent Test Cylinder "
        "with radius 10 mm and height 50 mm. "
        "Actually call the geometry creation tool."
    )

    print("Model:", config.model)
    print("User:", prompt)

    try:
        response = await agent.run(prompt)

        print("\nAgent response:")
        print(response.text)

        print("\nSubmitted jobs:")
        print(simulation_tools.submitted_job_ids)

        if not simulation_tools.submitted_job_ids:
            raise RuntimeError(
                "The model did not successfully submit "
                "a geometry job."
            )

        for job_id in simulation_tools.submitted_job_ids:
            job = manager.get(UUID(job_id))

            print(
                f"Verified in SQLite: "
                f"{job.id} -> {job.status.value}"
            )

    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
