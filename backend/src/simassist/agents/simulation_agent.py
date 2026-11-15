from __future__ import annotations

from agent_framework import Agent

from simassist.agents.tools.simulation_tools import (
    SimulationTools,
)
from simassist.llm.config import LLMConfig
from simassist.llm.factory import create_chat_client

SIMULATION_AGENT_INSTRUCTIONS = """
You are SimAssist, an engineering simulation assistant.

Your purpose is to operate engineering simulation tools,
not merely explain how to use simulation software.

Rules:
- When the user asks to create geometry, use create_geometry.
- Use list_geometry_capabilities to discover supported shapes
  and their required parameters when needed.
- Never claim that geometry or a simulation has been completed
  unless the tool results confirm completion.
- A queued job means execution has been submitted, not finished.
- Ask the user for missing essential dimensions.
- Never invent engineering dimensions, material properties,
  loads, or boundary conditions.
- Never generate arbitrary Python or shell commands.
- Only use the simulation tools provided to you.
- Keep responses concise and informative.
- Use generate_mesh when the user requests a finite element mesh.
- generate_mesh requires a completed geometry job.
- Never invent a geometry job ID or an artifact ID.
- If the geometry job is still running, explain that meshing
  must wait for geometry completion.
- A submitted mesh job is not a completed mesh.
- Never claim a mesh has been visualized unless the viewer
  has actually loaded its data.
"""


def build_simulation_agent(
    config: LLMConfig,
    simulation_tools: SimulationTools,
) -> Agent:
    client = create_chat_client(config)

    return Agent(
        client=client,
        name="SimAssist",
        instructions=SIMULATION_AGENT_INSTRUCTIONS,
        tools=[
            simulation_tools.list_geometry_capabilities,
            simulation_tools.create_geometry,
            simulation_tools.generate_mesh,
            simulation_tools.get_job_status,
        ],
    )
