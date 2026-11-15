from __future__ import annotations

from agent_framework import Agent

from simassist.agents.orchestrator import AgentComposition, ToolTelemetry
from simassist.agents.registry import REGISTRY, instructions
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.llm.config import LLMConfig
from simassist.llm.factory import create_chat_client

# Compatibility for integrations that explicitly construct an all-capability agent.
# The chat runtime always passes a request-specific composition instead.
SIMULATION_AGENT_INSTRUCTIONS = "\n\n".join(
    [instructions("core_instructions.md")]
    + [
        instructions(m.instructions_resource)
        for m in REGISTRY.resolve(REGISTRY.modules)
    ]
)


def build_simulation_agent(
    config: LLMConfig,
    simulation_tools: SimulationTools,
    composition: AgentComposition | None = None,
) -> Agent:
    client = create_chat_client(config)
    return Agent(
        client=client,
        name="SimAssist",
        instructions=composition.instructions
        if composition
        else SIMULATION_AGENT_INSTRUCTIONS,
        tools=composition.tools
        if composition
        else simulation_agent_tools(simulation_tools),
        middleware=[ToolTelemetry(composition)] if composition else None,
    )


def simulation_agent_tools(simulation_tools: SimulationTools) -> list:
    """Explicit all-tools compatibility mode; production chat uses selected bundles."""
    return REGISTRY.bind(REGISTRY.resolve(REGISTRY.modules), simulation_tools)
